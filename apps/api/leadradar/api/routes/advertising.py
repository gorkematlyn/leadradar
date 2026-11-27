from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.api.deps import current_user
from leadradar.api.routes.companies import get_company
from leadradar.core.activity import record_activity
from leadradar.core.security import encrypt_secret
from leadradar.db.models import (
    Advertisement,
    Advertiser,
    AdvertisingProvider,
    AdvertisingResearchRun,
    User,
)
from leadradar.db.session import get_db
from leadradar.modules.advertising.providers import REGISTRY
from leadradar.modules.advertising.service import (
    build_query,
    confirm_advertiser,
    record_manual,
    start_research,
)

router = APIRouter(tags=["advertising"])


@router.get("/ad-providers")
def providers(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    out = []
    for p in db.scalars(select(AdvertisingProvider).order_by(AdvertisingProvider.sort_order)):
        cls = REGISTRY.get(p.key)
        out.append({"key": p.key, "name": p.name, "enabled": p.enabled, "automation_status": p.automation_status,
                    "automation_supported": bool(cls and cls.automated), "credentials_configured": bool(p.credentials_enc),
                    "note_en": p.automation_note_en, "note_tr": p.automation_note_tr,
                    "official_source_url": p.official_source_url,
                    "manual_search_url_template": p.manual_search_url_template, "config": p.config,
                    "rate_limit_per_minute": p.rate_limit_per_minute, "recheck_days": p.recheck_days})
    return out


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = None  # write-only; never returned
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=60)
    recheck_days: int | None = Field(default=None, ge=1, le=365)
    official_source_url: str | None = Field(default=None, max_length=500)
    manual_search_url_template: str | None = Field(default=None, max_length=1000)


def _valid_url(value: str) -> str:
    from urllib.parse import urlsplit

    v = value.strip()
    parts = urlsplit(v.replace("{", "").replace("}", ""))
    if parts.scheme != "https" or not parts.netloc or any(c in v for c in " <>\"\n"):
        raise HTTPException(400, "invalid_url")
    import string

    try:
        fields = {f for _, f, _, _ in string.Formatter().parse(v) if f is not None}
    except ValueError as exc:
        raise HTTPException(400, "invalid_url") from exc
    if fields - {"query", "domain", "country"}:
        raise HTTPException(400, "invalid_placeholder")
    return v


@router.patch("/ad-providers/{key}")
def patch_provider(key: str, body: ProviderPatch, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    p = db.get(AdvertisingProvider, key)
    if p is None:
        raise HTTPException(404, "not_found")
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.config is not None:
        if len(str(body.config)) > 2000:
            raise HTTPException(400, "too_large")
        p.config = body.config
    if body.credentials is not None:
        cls = REGISTRY.get(key)
        if not (cls and cls.automated):
            raise HTTPException(400, "automation_unsupported")
        p.credentials_enc = encrypt_secret(body.credentials) if any(body.credentials.values()) else None
        p.automation_status = "automated" if p.credentials_enc else "manual"
    if body.rate_limit_per_minute is not None:
        p.rate_limit_per_minute = body.rate_limit_per_minute
    if body.recheck_days is not None:
        p.recheck_days = body.recheck_days
    if body.official_source_url is not None:
        p.official_source_url = _valid_url(body.official_source_url)
        p.admin_customized = True
    if body.manual_search_url_template is not None:
        p.manual_search_url_template = _valid_url(body.manual_search_url_template) if body.manual_search_url_template.strip() else None
        p.admin_customized = True
    record_activity(db, "settings", "ad_provider_updated", user_id=user.id, entity_type="ad_provider", entity_id=key,
                    details={"credentials_changed": body.credentials is not None})
    return {"ok": True}


class ResearchIn(BaseModel):
    platforms: list[str] | None = None


@router.post("/companies/{company_id}/ad-research")
def research(company_id: uuid.UUID, body: ResearchIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    runs = start_research(db, c, body.platforms, user.id)
    return {"runs": [str(r.id) for r in runs]}


@router.get("/companies/{company_id}/advertising")
def company_ads(company_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    q = build_query(db, c)
    provs = db.scalars(select(AdvertisingProvider).order_by(AdvertisingProvider.sort_order)).all()
    runs = db.scalars(select(AdvertisingResearchRun).where(AdvertisingResearchRun.company_id == c.id)
                      .order_by(AdvertisingResearchRun.created_at.desc()).limit(100)).all()
    advertisers = db.scalars(select(Advertiser).where(Advertiser.company_id == c.id)).all()
    adv_ids = [a.id for a in advertisers]
    ads = db.scalars(select(Advertisement).where(Advertisement.advertiser_id.in_(adv_ids))
                     .order_by(Advertisement.last_observed_at.desc()).limit(300)).all() if adv_ids else []
    platforms = []
    for p in provs:
        inst = REGISTRY[p.key](dict(p.config or {}), {}, p.manual_search_url_template)
        latest = next((r for r in runs if r.platform == p.key), None)
        platforms.append({
            "key": p.key, "name": p.name, "enabled": p.enabled, "automation_status": p.automation_status,
            "manual_url": inst.manual_url(q), "note_en": p.automation_note_en, "note_tr": p.automation_note_tr,
            "latest": {"id": str(latest.id), "status": latest.status, "method": latest.method,
                       "researched_at": latest.researched_at, "active_ads_verified": latest.active_ads_verified,
                       "result_count": latest.result_count, "notes": latest.notes, "error": latest.error,
                       "source_url": latest.source_url, "search_scope": latest.search_scope} if latest else None,
        })
    return {
        "platforms": platforms,
        "runs": [{"id": str(r.id), "platform": r.platform, "status": r.status, "method": r.method,
                  "researched_at": r.researched_at, "created_at": r.created_at, "notes": r.notes} for r in runs],
        "advertisers": [{"id": str(a.id), "platform": a.platform, "name": a.name, "match_status": a.match_status,
                         "match_confidence": a.match_confidence, "source_url": a.source_url,
                         "platform_advertiser_id": a.platform_advertiser_id} for a in advertisers],
        "ads": [{"id": str(x.id), "platform": x.platform, "advertiser_id": str(x.advertiser_id) if x.advertiser_id else None,
                 "format": x.ad_format, "text": x.ad_text, "landing_page_url": x.landing_page_url, "status": x.status,
                 "start_date": x.source_start_date, "end_date": x.source_end_date, "first_observed_at": x.first_observed_at,
                 "last_observed_at": x.last_observed_at, "source_url": x.source_url, "geographic_scope": x.geographic_scope,
                 "approved_for_reports": x.approved_for_reports} for x in ads],
    }


class ConfirmIn(BaseModel):
    confirm: bool


@router.post("/companies/{company_id}/advertisers/{advertiser_id}/confirm")
def confirm(company_id: uuid.UUID, advertiser_id: uuid.UUID, body: ConfirmIn, db: Session = Depends(get_db),
            user: User = Depends(current_user)) -> dict:
    from leadradar.modules.scoring.service import score_company

    c = get_company(db, company_id)
    adv = db.get(Advertiser, advertiser_id)
    if adv is None or adv.company_id not in (None, c.id):
        raise HTTPException(404, "not_found")
    confirm_advertiser(db, adv, c, body.confirm, user.id)
    score_company(db, c)
    return {"ok": True}


class ManualAdIn(BaseModel):
    ad_id: str | None = Field(default=None, max_length=200)
    format: str | None = Field(default=None, max_length=48)
    text: str | None = Field(default=None, max_length=2000)
    landing_page_url: str | None = Field(default=None, max_length=2000)
    status: Literal["active", "inactive", "unknown"] = "unknown"
    start_date: str | None = None
    end_date: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)


class ManualIn(BaseModel):
    platform: str
    status: Literal["found", "no_results", "blocked", "not_checked", "unsupported"]
    active_ads_verified: bool = False
    advertiser_name: str | None = Field(default=None, max_length=300)
    advertiser_id: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)
    search_terms: list[str] = Field(default_factory=list, max_length=10)
    ads: list[ManualAdIn] = Field(default_factory=list, max_length=50)


@router.post("/companies/{company_id}/ad-research/manual")
def manual(company_id: uuid.UUID, body: ManualIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    from leadradar.modules.scoring.service import score_company

    c = get_company(db, company_id)
    if db.get(AdvertisingProvider, body.platform) is None:
        raise HTTPException(400, "invalid_platform")
    try:
        run = record_manual(db, c, body.platform, {**body.model_dump(), "ads": [a.model_dump() for a in body.ads]}, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    score_company(db, c)
    return {"id": str(run.id)}


class AdApproveIn(BaseModel):
    approved: bool


@router.post("/ads/{ad_id}/approve")
def approve_ad(ad_id: uuid.UUID, body: AdApproveIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    ad = db.get(Advertisement, ad_id)
    if ad is None:
        raise HTTPException(404, "not_found")
    ad.approved_for_reports = body.approved
    return {"ok": True}
