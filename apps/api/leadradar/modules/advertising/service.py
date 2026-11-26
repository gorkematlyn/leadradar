"""Advertising research workflow: queue, execute, store, confirm matches, manual entries."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadradar.core.security import decrypt_json
from leadradar.db.models import (
    Advertisement,
    Advertiser,
    AdvertisingProvider,
    AdvertisingResearchRun,
    Company,
    SocialProfile,
)
from leadradar.db.session import session_scope
from leadradar.jobs import queue
from leadradar.jobs.runtime import HandlerResult, JobContext, PermanentJobError, handler
from leadradar.modules.advertising.providers import REGISTRY
from leadradar.modules.advertising.providers.base import (
    FOUND,
    MATCH_REQUIRED,
    NO_RESULTS,
    RATE_LIMITED,
    STATES,
    UNSUPPORTED,
    CompanyQuery,
    ProviderResult,
)


def now() -> datetime:
    return datetime.now(UTC)


def _sanitize(text: str | None) -> str | None:
    if not text:
        return text
    return re.sub(r"(access_token|token|key)=[^&\s]+", r"\1=[redacted]", text)[:1000]


def build_query(db: Session, company: Company) -> CompanyQuery:
    socials: dict[str, list[str]] = {}
    for sp in db.scalars(select(SocialProfile).where(SocialProfile.company_id == company.id)):
        socials.setdefault(sp.platform, []).append(sp.handle)
    known = list(db.scalars(select(Advertiser.platform_advertiser_id).where(
        Advertiser.company_id == company.id, Advertiser.match_status == "confirmed")))
    return CompanyQuery(str(company.id), company.name, company.canonical_domain, company.website_url,
                        company.country_iso2, socials, known)


def provider_instance(db: Session, key: str):  # type: ignore[no-untyped-def]
    row = db.get(AdvertisingProvider, key)
    if row is None:
        raise PermanentJobError(f"unknown provider {key}")
    cls = REGISTRY[key]
    return row, cls(dict(row.config or {}), decrypt_json(row.credentials_enc), row.manual_search_url_template)


def start_research(db: Session, company: Company, platforms: list[str] | None, user_id: uuid.UUID | None) -> list[AdvertisingResearchRun]:
    rows = db.scalars(select(AdvertisingProvider).where(AdvertisingProvider.enabled.is_(True))
                      .order_by(AdvertisingProvider.sort_order)).all()
    selected = [r for r in rows if not platforms or r.key in platforms]
    runs = []
    for prov in selected:
        run = AdvertisingResearchRun(company_id=company.id, platform=prov.key, status="not_checked",
                                     method="automated", user_id=user_id)
        db.add(run)
        db.flush()
        job = queue.enqueue(db, "ad_research", f"Ad research ({prov.name}): {company.name}",
                            {"run_id": str(run.id)}, idempotency_key=f"ad_research:{company.id}:{prov.key}",
                            company_id=company.id, created_by=user_id)
        run.job_id = job.id
        runs.append(run)
    return runs


@handler("ad_research")
def handle_research(ctx: JobContext) -> HandlerResult:
    run_id = uuid.UUID(ctx.payload["run_id"])
    with session_scope() as db:
        run = db.get(AdvertisingResearchRun, run_id)
        if run is None:
            raise PermanentJobError("research run missing")
        company = db.get(Company, run.company_id)
        if company is None:
            raise PermanentJobError("company missing")
        prov_row, provider = provider_instance(db, run.platform)
        recent = db.scalar(select(func.count()).select_from(AdvertisingResearchRun).where(
            AdvertisingResearchRun.platform == run.platform, AdvertisingResearchRun.method == "automated",
            AdvertisingResearchRun.researched_at >= now() - timedelta(minutes=1)))
        if provider.automated and provider.is_configured() and (recent or 0) >= prov_row.rate_limit_per_minute:
            run.status = RATE_LIMITED
            queue.enqueue(db, "ad_research", f"Ad research retry ({prov_row.name})", {"run_id": str(run.id)},
                          run_at=now() + timedelta(seconds=75), company_id=company.id)
            return HandlerResult({"status": RATE_LIMITED, "rescheduled": True})
        query = build_query(db, company)
    ctx.progress("research")
    try:
        result = provider.research(query)
    except Exception as exc:
        result = ProviderResult("error", error=str(exc)[:300], source_url=provider.manual_url(query))
    with session_scope() as db:
        run = db.get(AdvertisingResearchRun, run_id)
        store_result(db, run, result)  # type: ignore[arg-type]
        company = db.get(Company, run.company_id)  # type: ignore[union-attr]
        refresh_company_platforms(db, company)  # type: ignore[arg-type]
        from leadradar.modules.scoring.service import score_company

        score_company(db, company)  # type: ignore[arg-type]
    return HandlerResult({"status": result.status, "advertisers": len(result.advertisers), "ads": len(result.ads)})


def store_result(db: Session, run: AdvertisingResearchRun, result: ProviderResult) -> None:
    run.status = result.status if result.status in STATES else "error"
    run.source_url = result.source_url
    run.search_scope = result.search_scope
    run.notes = result.notes
    run.error = _sanitize(result.error)
    run.researched_at = now()
    run.result_count = len(result.ads)
    adv_ids: dict[str, Advertiser] = {}
    for fa in result.advertisers:
        adv = db.scalar(select(Advertiser).where(Advertiser.platform == run.platform,
                                                 Advertiser.platform_advertiser_id == fa.platform_advertiser_id))
        if adv is None:
            adv = Advertiser(platform=run.platform, platform_advertiser_id=fa.platform_advertiser_id, name=fa.name[:300],
                             match_confidence=fa.match_confidence, source_url=fa.source_url)
            db.add(adv)
        if adv.match_status != "rejected" and (adv.company_id is None or adv.company_id == run.company_id):
            adv.company_id = run.company_id
            adv.match_confidence = max(adv.match_confidence, fa.match_confidence)
            if result.status == FOUND and fa is result.advertisers[0] and adv.match_status == "pending":
                adv.match_status = "confirmed"  # unambiguous: unique domain-verified advertiser
        db.flush()
        adv_ids[fa.platform_advertiser_id] = adv
    for ad in result.ads:
        adv = adv_ids.get(ad.advertiser_id)
        row = db.scalar(select(Advertisement).where(Advertisement.platform == run.platform,
                                                    Advertisement.platform_ad_id == ad.platform_ad_id))
        if row is None:
            row = Advertisement(platform=run.platform, platform_ad_id=ad.platform_ad_id, first_observed_at=now())
            db.add(row)
        row.advertiser_id = adv.id if adv else None
        row.research_run_id = run.id
        row.ad_format, row.ad_text, row.landing_page_url = ad.ad_format, ad.ad_text, ad.landing_page_url
        row.status, row.source_start_date, row.source_end_date = ad.status, ad.start_date, ad.end_date
        row.geographic_scope, row.source_url, row.last_observed_at = ad.geographic_scope, ad.source_url, now()
    confirmed_active = False
    if result.status in (FOUND, MATCH_REQUIRED):
        confirmed = {a.platform_advertiser_id for a in adv_ids.values() if a.match_status == "confirmed"}
        confirmed_active = any(ad.status == "active" and ad.advertiser_id in confirmed for ad in result.ads)
        if result.status == MATCH_REQUIRED and confirmed:
            run.status = FOUND
    run.active_ads_verified = confirmed_active
    db.flush()


def confirm_advertiser(db: Session, adv: Advertiser, company: Company, confirm: bool, user_id: uuid.UUID | None) -> None:
    adv.match_status = "confirmed" if confirm else "rejected"
    adv.company_id = company.id if confirm else adv.company_id
    adv.confirmed_by = user_id
    db.flush()
    # Re-evaluate latest run for this platform without new external research.
    run = db.scalar(select(AdvertisingResearchRun).where(AdvertisingResearchRun.company_id == company.id,
                                                         AdvertisingResearchRun.platform == adv.platform)
                    .order_by(AdvertisingResearchRun.created_at.desc()).limit(1))
    if run is not None:
        active = db.scalar(select(Advertisement.id).join(Advertiser, Advertiser.id == Advertisement.advertiser_id).where(
            Advertiser.company_id == company.id, Advertiser.platform == adv.platform,
            Advertiser.match_status == "confirmed", Advertisement.status == "active").limit(1))
        run.active_ads_verified = bool(active)
        if confirm and run.status == MATCH_REQUIRED:
            run.status = FOUND
        if not confirm and not db.scalar(select(Advertiser.id).where(
                Advertiser.company_id == company.id, Advertiser.platform == adv.platform,
                Advertiser.match_status != "rejected").limit(1)):
            run.status = NO_RESULTS
    refresh_company_platforms(db, company)


def record_manual(db: Session, company: Company, platform: str, data: dict[str, Any], user_id: uuid.UUID | None) -> AdvertisingResearchRun:
    """Administrator-verified manual research result from the official source."""
    status = data["status"]
    if status not in {FOUND, NO_RESULTS, UNSUPPORTED, "blocked", "not_checked"}:
        raise ValueError("invalid status for manual research")
    run = AdvertisingResearchRun(company_id=company.id, platform=platform, status=status, method="manual",
                                 source_url=data.get("source_url"), notes=data.get("notes"),
                                 active_ads_verified=bool(data.get("active_ads_verified")) and status == FOUND,
                                 researched_at=now(), user_id=user_id,
                                 search_scope={"manual": True, "terms": data.get("search_terms") or []})
    db.add(run)
    db.flush()
    if status == FOUND and data.get("advertiser_name"):
        pid = (data.get("advertiser_id") or f"manual:{company.id}:{platform}")[:200]
        adv = db.scalar(select(Advertiser).where(Advertiser.platform == platform, Advertiser.platform_advertiser_id == pid))
        if adv is None:
            adv = Advertiser(platform=platform, platform_advertiser_id=pid, name=data["advertiser_name"][:300])
            db.add(adv)
        adv.company_id, adv.match_status, adv.match_confidence = company.id, "confirmed", 1.0
        adv.confirmed_by, adv.source_url = user_id, data.get("source_url")
        db.flush()
        for i, ad in enumerate(data.get("ads") or []):
            db.add(Advertisement(
                platform=platform, platform_ad_id=(ad.get("ad_id") or f"manual:{run.id}:{i}")[:200], advertiser_id=adv.id,
                research_run_id=run.id, ad_format=ad.get("format"), ad_text=(ad.get("text") or "")[:2000] or None,
                landing_page_url=ad.get("landing_page_url"), status=ad.get("status") or "unknown",
                source_start_date=_d(ad.get("start_date")), source_end_date=_d(ad.get("end_date")),
                first_observed_at=now(), last_observed_at=now(), source_url=ad.get("source_url"),
            ))
    refresh_company_platforms(db, company)
    return run


def _d(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def refresh_company_platforms(db: Session, company: Company) -> None:
    runs = db.scalars(select(AdvertisingResearchRun).where(AdvertisingResearchRun.company_id == company.id)
                      .order_by(AdvertisingResearchRun.created_at.desc())).all()
    latest: dict[str, AdvertisingResearchRun] = {}
    for r in runs:
        latest.setdefault(r.platform, r)
    company.advertising_platforms = sorted(p for p, r in latest.items() if r.status == FOUND and r.active_ads_verified)
    db.flush()
