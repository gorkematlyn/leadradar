from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from leadradar.api.deps import current_user
from leadradar.core.activity import record_activity
from leadradar.db.models import (
    ChangeEvent,
    Company,
    CompanyChange,
    CompanySource,
    CompanyTag,
    Country,
    CrmActivity,
    CrmStatus,
    DuplicateCandidate,
    ImportRun,
    Industry,
    LeadScore,
    MergeHistory,
    ScoreOverride,
    ServiceScore,
    SocialProfile,
    Tag,
    User,
)
from leadradar.db.session import get_db
from leadradar.jobs import queue
from leadradar.modules.crm.companies import RecordInput, apply_website, merge_companies, upsert_record
from leadradar.modules.crm.filters import SORTS, CompanyFilter, apply_filter
from leadradar.modules.crm.normalize import normalize_name, normalize_phone, normalize_url
from leadradar.modules.crm.suppression import active_entries, suppress_company

router = APIRouter(prefix="/companies", tags=["companies"])


def now() -> datetime:
    return datetime.now(UTC)


def get_company(db: Session, company_id: uuid.UUID) -> Company:
    c = db.get(Company, company_id)
    if c is None or c.deleted_at is not None:
        raise HTTPException(404, "not_found")
    return c


def _industries(db: Session) -> dict[uuid.UUID, Industry]:
    return {i.id: i for i in db.scalars(select(Industry))}


def row_view(c: Company, industries: dict[uuid.UUID, Industry]) -> dict[str, Any]:
    ind = industries.get(c.primary_industry_id) if c.primary_industry_id else None
    top_services = sorted(((k, v) for k, v in (c.service_scores or {}).items() if v.get("score", 0) >= 30),
                          key=lambda kv: -kv[1]["score"])[:3]
    return {
        "id": str(c.id), "name": c.name, "website": c.website_url, "domain": c.canonical_domain,
        "country": c.country_iso2, "city": c.city, "industry": ind.key if ind else None,
        "industry_confidence": c.industry_confidence, "lead_score": c.effective_lead_score,
        "preliminary_score": c.preliminary_lead_score, "final_score": c.final_lead_score,
        "classification": c.score_classification, "confidence": c.confidence_score, "website_status": c.website_status,
        "advertising_platforms": c.advertising_platforms or [],
        "services": [{"key": k, "score": v["score"], "provisional": v.get("provisional", False)} for k, v in top_services],
        "tags": [{"id": str(t.id), "name_en": t.name_en, "name_tr": t.name_tr, "color": t.color} for t in c.tags],
        "crm_status": c.crm_status, "analysis_status": c.analysis_status, "last_audit_at": c.last_audit_at,
        "do_not_contact": c.do_not_contact, "archived": c.archived, "watchlisted": c.watchlisted,
        "follow_up_at": c.follow_up_at,
    }


@router.get("/facets")
def facets(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    """Values that actually occur in the company list, with counts, so filters only offer
    options that can return results."""
    from leadradar.db.models import CompanyTag, Country, Tag

    live = (Company.merged_into_id.is_(None), Company.deleted_at.is_(None))

    def counts(col) -> list[dict]:  # type: ignore[no-untyped-def]
        return [{"value": v, "count": n} for v, n in db.execute(
            select(col, func.count()).where(*live, col.isnot(None)).group_by(col).order_by(func.count().desc())).all()]

    industries = {i.id: i.key for i in db.scalars(select(Industry))}
    regions = dict(db.execute(select(Country.iso2, Country.region_code)).all())
    country_counts = counts(Company.country_iso2)
    region_counts: dict[str, int] = {}
    for x in country_counts:
        r = regions.get(x["value"])
        if r:
            region_counts[r] = region_counts.get(r, 0) + x["count"]
    tag_counts = db.execute(select(CompanyTag.tag_id, func.count()).join(Company, Company.id == CompanyTag.company_id)
                            .where(*live).group_by(CompanyTag.tag_id)).all()
    tag_ids = {t.id for t in db.scalars(select(Tag))}
    platforms: dict[str, int] = {}
    for arr, n in db.execute(select(Company.advertising_platforms, func.count()).where(*live)
                             .group_by(Company.advertising_platforms)).all():
        for p in arr or []:
            platforms[p] = platforms.get(p, 0) + n
    return {
        "countries": country_counts,
        "regions": [{"value": k, "count": v} for k, v in region_counts.items()],
        "industries": [{"value": industries[x["value"]], "count": x["count"]} for x in counts(Company.primary_industry_id)
                       if x["value"] in industries],
        "crm_status": counts(Company.crm_status),
        "website_status": counts(Company.website_status),
        "analysis_status": counts(Company.analysis_status),
        "classifications": counts(Company.score_classification),
        "tags": [{"value": str(t), "count": n} for t, n in tag_counts if t in tag_ids],
        "ad_platforms": [{"value": k, "count": v} for k, v in platforms.items()],
    }


class ListIn(BaseModel):
    filter: CompanyFilter = Field(default_factory=CompanyFilter)
    sort: str = "score"
    direction: Literal["asc", "desc"] = "desc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


@router.post("/query")
def list_companies(body: ListIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    base = apply_filter(select(Company), body.filter)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    col = SORTS.get(body.sort, Company.effective_lead_score)
    order = col.desc().nulls_last() if body.direction == "desc" else col.asc().nulls_last()
    rows = db.scalars(base.order_by(order, Company.id).offset((body.page - 1) * body.page_size).limit(body.page_size)).all()
    inds = _industries(db)
    return {"total": total, "page": body.page, "page_size": body.page_size, "items": [row_view(c, inds) for c in rows]}


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    website: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    industry: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=160)
    region: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None, max_length=400)
    postal_code: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    legal_name: str | None = Field(default=None, max_length=300)
    socials: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=20_000)
    quick_audit: bool = False


@router.post("")
def create_company(body: CompanyIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    if body.website and normalize_url(body.website) is None:
        raise HTTPException(400, "invalid_website")
    rec = RecordInput(source="manual", source_key=str(uuid.uuid4()), name=body.name.strip(),
                      country_iso2=body.country.upper() if body.country else None,
                      industry_keys=[body.industry] if body.industry else [], classification="confident",
                      website=body.website, city=body.city, region=body.region, address=body.address,
                      postal_code=body.postal_code, email=body.email, phone=body.phone, legal_name=body.legal_name,
                      socials=body.socials)
    out = upsert_record(db, rec, active_entries(db))
    if body.notes:
        out.company.notes = body.notes
    record_activity(db, "data", "company_created", user_id=user.id, entity_type="company", entity_id=out.company.id)
    job_id = None
    if body.quick_audit and out.company.website_url:
        from leadradar.modules.website_audit.service import create_audit

        _, job = create_audit(db, out.company, "quick", user_id=user.id, priority=10)
        job_id = str(job.id)
    return {"id": str(out.company.id), "action": out.action, "job_id": job_id}


class QuickAuditIn(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    name: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    industry: str | None = None
    mode: Literal["quick", "full"] = "full"


@router.post("/quick-audit")
def quick_audit(body: QuickAuditIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Create (or reuse) a company from a URL and start an audit immediately."""
    from leadradar.modules.netsafe.policy import BlockedDestination, validate_url
    from leadradar.modules.website_audit.service import create_audit

    n = normalize_url(body.url)
    if n is None:
        raise HTTPException(400, "invalid_website")
    try:
        validate_url(n.url)
    except BlockedDestination as exc:
        raise HTTPException(400, "blocked_destination") from exc
    existing = None
    if not n.is_shared_platform:
        existing = db.scalar(select(Company).where(Company.canonical_domain == n.canonical_domain,
                                                   Company.merged_into_id.is_(None), Company.deleted_at.is_(None)).limit(1))
    if existing is None:
        name = body.name or n.registrable_domain.split(".")[0].replace("-", " ").title()
        rec = RecordInput(source="quick_audit", source_key=n.property_key, name=name,
                          country_iso2=body.country.upper() if body.country else None,
                          industry_keys=[body.industry] if body.industry else [], website=n.url)
        existing = upsert_record(db, rec, active_entries(db)).company
    audit, job = create_audit(db, existing, body.mode, user_id=user.id, priority=5, force=True)
    return {"company_id": str(existing.id), "audit_id": str(audit.id), "job_id": str(job.id)}


@router.get("/{company_id}")
def company_detail(company_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    inds = _industries(db)
    out = row_view(c, inds)
    country = db.get(Country, c.country_iso2) if c.country_iso2 else None
    override = db.scalar(select(ScoreOverride).where(ScoreOverride.company_id == c.id, ScoreOverride.active.is_(True))
                         .order_by(ScoreOverride.created_at.desc()))
    latest_score = db.scalar(select(LeadScore).where(LeadScore.company_id == c.id).order_by(LeadScore.calculated_at.desc()).limit(1))
    services = []
    if latest_score:
        services = [{"service": s.service, "score": s.score, "provisional": s.provisional, "rules": s.rules}
                    for s in db.scalars(select(ServiceScore).where(ServiceScore.lead_score_id == latest_score.id)
                                        .order_by(ServiceScore.score.desc()))]
    out.update({
        "legal_name": c.legal_name, "region": c.region, "address": c.address, "postal_code": c.postal_code,
        "latitude": c.latitude, "longitude": c.longitude, "email": c.email, "email_verified": c.email_verified,
        "phone": c.phone, "notes": c.notes, "discovered_at": c.discovered_at, "last_verified_at": c.last_verified_at,
        "is_chain": c.is_chain, "permanently_closed": c.permanently_closed, "rejected": c.rejected,
        "additional_industries": [inds[i].key for i in (c.additional_industry_ids or []) if i in inds],
        "field_sources": c.field_sources, "country_name": {"en": country.name_en, "tr": country.name_tr} if country else None,
        "service_scores_detail": services,
        "score": {"id": str(latest_score.id), "stage": latest_score.stage, "score": latest_score.score,
                  "classification": latest_score.classification, "confidence": latest_score.confidence,
                  "breakdown": latest_score.breakdown, "calculated_at": latest_score.calculated_at,
                  "profile_version": latest_score.profile_version} if latest_score else None,
        "override": {"score": override.override_score, "original": override.original_score, "reason": override.reason,
                     "created_at": override.created_at, "user_id": str(override.user_id) if override.user_id else None}
        if override else None,
        "sources": [{"source": s.source, "source_key": s.source_key, "source_url": s.source_url,
                     "source_timestamp": s.source_timestamp, "last_seen_at": s.last_seen_at}
                    for s in db.scalars(select(CompanySource).where(CompanySource.company_id == c.id))],
        "social_profiles": [{"id": str(s.id), "platform": s.platform, "handle": s.handle, "url": s.url,
                             "verified": s.verified, "source": s.source} for s in c.social_profiles],
    })
    return out


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    legal_name: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=2000)
    country: str | None = Field(default=None, max_length=2)
    industry: str | None = None
    industry_confidence: Literal["confident", "review"] | None = None
    city: str | None = Field(default=None, max_length=160)
    region: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None, max_length=400)
    postal_code: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    email_verified: bool | None = None
    phone: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=20_000)
    crm_status: str | None = None
    follow_up_at: datetime | None = None
    is_chain: bool | None = None
    permanently_closed: bool | None = None
    rejected: bool | None = None
    watchlisted: bool | None = None
    archived: bool | None = None
    website_status: Literal["unverified", "verified", "not_found", "verified_absent"] | None = None


@router.patch("/{company_id}")
def patch_company(company_id: uuid.UUID, body: CompanyPatch, db: Session = Depends(get_db),
                  user: User = Depends(current_user)) -> dict:
    from leadradar.modules.crm.companies import _set_field

    c = get_company(db, company_id)
    data = body.model_dump(exclude_unset=True)
    for fld in ("name", "legal_name", "city", "region", "address", "postal_code", "email"):
        if fld in data and data[fld] is not None:
            _set_field(db, c, fld, data[fld].strip() or None, "manual", user_id=user.id, force=True)
    if "name" in data and data["name"]:
        c.normalized_name = normalize_name(c.name)
    if "country" in data and data["country"]:
        if db.get(Country, data["country"].upper()) is None:
            raise HTTPException(400, "invalid_country")
        _set_field(db, c, "country_iso2", data["country"].upper(), "manual", user_id=user.id, force=True)
    if "phone" in data:
        if data["phone"]:
            _set_field(db, c, "phone", data["phone"], "manual", user_id=user.id, force=True)
            c.phone_normalized = normalize_phone(data["phone"], c.country_iso2)
    status_before = c.website_status
    if "website" in data and data["website"] == "":
        # Clearing the address: the company has no known website.
        c.website_url, c.canonical_domain, c.website_property_id = None, None, None
        c.website_status = "not_found"
    if "website" in data and data["website"]:
        if normalize_url(data["website"]) is None:
            raise HTTPException(400, "invalid_website")
        apply_website(db, c, data["website"], "manual", force=True, user_id=user.id)
    if "industry" in data and data["industry"]:
        ind = db.scalar(select(Industry).where(Industry.key == data["industry"]))
        if ind is None:
            raise HTTPException(400, "invalid_industry")
        c.primary_industry_id = ind.id
        c.industry_confidence = "confident"
        fs = dict(c.field_sources or {})
        fs["primary_industry_id"] = {"source": "manual", "at": now().isoformat(), "confirmed": True}
        c.field_sources = fs
    if data.get("industry_confidence"):
        c.industry_confidence = data["industry_confidence"]
    if "crm_status" in data and data["crm_status"]:
        set_status(db, c, data["crm_status"], user.id)
    for fld in ("email_verified", "is_chain", "permanently_closed", "rejected", "watchlisted", "archived"):
        if fld in data and data[fld] is not None:
            setattr(c, fld, data[fld])
    if data.get("website_status"):
        # Manual correction of the website status (e.g. a wrongly detected or missing site).
        c.website_status = data["website_status"]
        fs = dict(c.field_sources or {})
        fs["website_status"] = {"source": "manual", "at": now().isoformat(), "confirmed": True}
        c.field_sources = fs
    if c.website_status != status_before and "verified_absent" in (c.website_status, status_before):
        from leadradar.modules.scoring.service import score_company

        db.flush()
        score_company(db, c)  # "no website" is a scoring signal
    if "notes" in data:
        c.notes = data["notes"]
    if "follow_up_at" in data:
        c.follow_up_at = data["follow_up_at"]
        if data["follow_up_at"]:
            db.add(CrmActivity(company_id=c.id, kind="follow_up", title="Follow-up scheduled", due_at=data["follow_up_at"],
                               occurred_at=now(), user_id=user.id))
    db.flush()
    return {"ok": True}


def set_status(db: Session, c: Company, status: str, user_id: uuid.UUID | None) -> None:
    if db.get(CrmStatus, status) is None:
        raise HTTPException(400, "invalid_status")
    if c.do_not_contact and status not in ("do_not_contact", "archived"):
        raise HTTPException(409, "company_suppressed")
    if status == "do_not_contact":
        suppress_company(db, c, "Set via CRM status", user_id)
        return
    old = c.crm_status
    if old == status:
        return
    c.crm_status = status
    if status == "archived":
        c.archived = True
    db.add(CrmActivity(company_id=c.id, kind="status_change", title=f"{old} → {status}",
                       data={"from": old, "to": status}, occurred_at=now(), user_id=user_id))


class BulkIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=5000)
    filter: CompanyFilter | None = None
    action: Literal["add_tags", "remove_tags", "set_status", "audit_quick", "audit_full", "research_ads", "archive",
                    "unarchive", "watch", "unwatch", "do_not_contact", "recalculate", "delete"]
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    status: str | None = None
    platforms: list[str] | None = None
    reason: str | None = Field(default=None, max_length=400)


def _bulk_targets(db: Session, body: BulkIn) -> list[Company]:
    if body.ids:
        return list(db.scalars(select(Company).where(Company.id.in_(body.ids), Company.deleted_at.is_(None))))
    if body.filter is not None:
        return list(db.scalars(apply_filter(select(Company), body.filter).limit(5000)))
    raise HTTPException(400, "no_targets")


@router.post("/bulk")
def bulk(body: BulkIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    targets = _bulk_targets(db, body)
    jobs = 0
    if body.action in ("add_tags", "remove_tags"):
        tags = list(db.scalars(select(Tag.id).where(Tag.id.in_(body.tag_ids))))
        for c in targets:
            for t in tags:
                exists = db.get(CompanyTag, (c.id, t))
                if body.action == "add_tags" and exists is None:
                    db.add(CompanyTag(company_id=c.id, tag_id=t))
                elif body.action == "remove_tags" and exists is not None:
                    db.delete(exists)
    elif body.action == "set_status":
        for c in targets:
            if not c.do_not_contact:
                set_status(db, c, body.status or "", user.id)
    elif body.action in ("audit_quick", "audit_full"):
        from leadradar.modules.website_audit.service import create_audit

        if len(targets) > 500:
            raise HTTPException(400, "too_many_targets")
        for c in targets:
            if c.website_url:
                create_audit(db, c, "quick" if body.action == "audit_quick" else "full", user_id=user.id, priority=60)
                jobs += 1
    elif body.action == "research_ads":
        from leadradar.modules.advertising.service import start_research

        if len(targets) > 200:
            raise HTTPException(400, "too_many_targets")
        for c in targets:
            jobs += len(start_research(db, c, body.platforms, user.id))
    elif body.action in ("archive", "unarchive"):
        for c in targets:
            c.archived = body.action == "archive"
    elif body.action in ("watch", "unwatch"):
        for c in targets:
            c.watchlisted = body.action == "watch"
    elif body.action == "do_not_contact":
        for c in targets:
            suppress_company(db, c, body.reason, user.id)
    elif body.action == "delete":
        from leadradar.modules.crm.trash import move_to_trash

        move_to_trash(db, targets, user.id)
    elif body.action == "recalculate":
        queue.enqueue(db, "recalculate_scores", f"Recalculate {len(targets)} scores",
                      {"company_ids": [str(c.id) for c in targets]}, created_by=user.id)
        jobs = 1
    record_activity(db, "data", f"bulk_{body.action}", user_id=user.id, details={"count": len(targets)})
    return {"affected": len(targets), "jobs": jobs}


class TagsIn(BaseModel):
    tag_ids: list[uuid.UUID] = Field(max_length=100)


@router.put("/{company_id}/tags")
def set_tags(company_id: uuid.UUID, body: TagsIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    db.execute(delete(CompanyTag).where(CompanyTag.company_id == c.id))
    for t in db.scalars(select(Tag.id).where(Tag.id.in_(body.tag_ids))):
        db.add(CompanyTag(company_id=c.id, tag_id=t))
    db.flush()
    db.refresh(c)
    return {"tags": [{"id": str(t.id), "name_en": t.name_en, "name_tr": t.name_tr, "color": t.color} for t in c.tags]}


class ActivityIn(BaseModel):
    kind: Literal["note", "call", "email", "meeting", "proposal", "follow_up", "won", "lost"]
    title: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, max_length=20_000)
    occurred_at: datetime | None = None
    due_at: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)


@router.get("/{company_id}/activities")
def activities(company_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    rows = db.scalars(select(CrmActivity).where(CrmActivity.company_id == company_id)
                      .order_by(CrmActivity.occurred_at.desc()).limit(300))
    return [{"id": str(a.id), "kind": a.kind, "title": a.title, "body": a.body, "data": a.data,
             "occurred_at": a.occurred_at, "due_at": a.due_at, "completed": a.completed} for a in rows]


@router.post("/{company_id}/activities")
def add_activity(company_id: uuid.UUID, body: ActivityIn, db: Session = Depends(get_db),
                 user: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    if len(str(body.data)) > 5000:
        raise HTTPException(400, "too_large")
    a = CrmActivity(company_id=c.id, kind=body.kind, title=body.title, body=body.body, data=body.data,
                    occurred_at=body.occurred_at or now(), due_at=body.due_at, user_id=user.id)
    db.add(a)
    # Automatic status moves only apply while the administrator still has these statuses.
    def auto(status: str) -> None:
        if db.get(CrmStatus, status) is not None and not c.do_not_contact:
            set_status(db, c, status, user.id)

    if body.kind == "won":
        auto("won")
    elif body.kind == "lost":
        auto("lost")
    elif body.kind == "proposal" and c.crm_status in ("new", "qualified", "shortlisted", "contacted", "replied", "meeting"):
        auto("proposal_sent")
    elif body.kind == "meeting" and c.crm_status in ("new", "qualified", "shortlisted", "contacted", "replied"):
        auto("meeting")
    if body.due_at:
        c.follow_up_at = body.due_at
    db.flush()
    return {"id": str(a.id)}


@router.patch("/{company_id}/activities/{activity_id}")
def complete_activity(company_id: uuid.UUID, activity_id: uuid.UUID, db: Session = Depends(get_db),
                      _: User = Depends(current_user)) -> dict:
    a = db.get(CrmActivity, activity_id)
    if a is None or a.company_id != company_id:
        raise HTTPException(404, "not_found")
    a.completed = not a.completed
    return {"completed": a.completed}


@router.get("/{company_id}/history")
def history(company_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    changes = db.scalars(select(CompanyChange).where(CompanyChange.company_id == company_id)
                         .order_by(CompanyChange.created_at.desc()).limit(300))
    events = db.scalars(select(ChangeEvent).where(ChangeEvent.company_id == company_id)
                        .order_by(ChangeEvent.detected_at.desc()).limit(300))
    scores = db.scalars(select(LeadScore).where(LeadScore.company_id == company_id)
                        .order_by(LeadScore.calculated_at.desc()).limit(50))
    merges = db.scalars(select(MergeHistory).where(MergeHistory.target_company_id == company_id))
    return {
        "field_changes": [{"field": x.field, "old": x.old_value, "new": x.new_value, "source": x.source,
                           "at": x.created_at} for x in changes],
        "change_events": [{"id": str(e.id), "category": e.category, "field": e.field, "before": e.before,
                           "after": e.after, "significance": e.significance, "at": e.detected_at,
                           "acknowledged": e.acknowledged} for e in events],
        "scores": [{"id": str(s.id), "stage": s.stage, "score": s.score, "confidence": s.confidence,
                    "classification": s.classification, "at": s.calculated_at, "profile_version": s.profile_version}
                   for s in scores],
        "merges": [{"merged_company_id": str(m.merged_company_id), "name": m.merged_snapshot.get("name"),
                    "at": m.created_at} for m in merges],
    }


class OverrideIn(BaseModel):
    score: int = Field(ge=0, le=100)
    reason: str = Field(min_length=3, max_length=2000)


@router.post("/{company_id}/score-override")
def override_score(company_id: uuid.UUID, body: OverrideIn, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> dict:
    from leadradar.modules.scoring.service import classify_override, load_profile

    c = get_company(db, company_id)
    for o in db.scalars(select(ScoreOverride).where(ScoreOverride.company_id == c.id, ScoreOverride.active.is_(True))):
        o.active = False
    original = c.final_lead_score if c.final_lead_score is not None else c.preliminary_lead_score
    db.add(ScoreOverride(company_id=c.id, original_score=original, override_score=body.score, reason=body.reason,
                         user_id=user.id, created_at=now()))
    c.effective_lead_score = body.score
    c.score_classification = classify_override(body.score, load_profile(db), c.do_not_contact)
    record_activity(db, "data", "score_override", user_id=user.id, entity_type="company", entity_id=c.id,
                    details={"original": original, "override": body.score})
    return {"ok": True}


@router.delete("/{company_id}/score-override")
def clear_override(company_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    from leadradar.modules.scoring.service import score_company

    c = get_company(db, company_id)
    for o in db.scalars(select(ScoreOverride).where(ScoreOverride.company_id == c.id, ScoreOverride.active.is_(True))):
        o.active = False
    db.flush()
    score_company(db, c)
    return {"ok": True}


class RecalcIn(BaseModel):
    profile_key: str | None = None


@router.post("/{company_id}/recalculate")
def recalculate(company_id: uuid.UUID, body: RecalcIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    from leadradar.modules.scoring.service import load_profile, score_company

    c = get_company(db, company_id)
    profile = load_profile(db, key=body.profile_key) if body.profile_key else None
    res = score_company(db, c, profile=profile)
    return {"score": res["score"], "classification": res["classification"], "confidence": res["confidence"]}


@router.post("/{company_id}/preview-score")
def preview_score(company_id: uuid.UUID, body: RecalcIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    """Score with another profile without persisting (profile comparison)."""
    from leadradar.modules.scoring.service import load_profile, score_company

    c = get_company(db, company_id)
    return score_company(db, c, profile=load_profile(db, key=body.profile_key), persist=False)


class VerifyWebsiteIn(BaseModel):
    absent: bool


@router.post("/{company_id}/verify-website")
def verify_website(company_id: uuid.UUID, body: VerifyWebsiteIn, db: Session = Depends(get_db),
                   user: User = Depends(current_user)) -> dict:
    from leadradar.modules.scoring.service import score_company
    from leadradar.modules.website_audit.service import verify_no_website

    c = get_company(db, company_id)
    verify_no_website(db, c, user.id, body.absent)
    score_company(db, c)
    return {"website_status": c.website_status}


class DncIn(BaseModel):
    reason: str | None = Field(default=None, max_length=400)


@router.post("/{company_id}/do-not-contact")
def do_not_contact(company_id: uuid.UUID, body: DncIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    entries = suppress_company(db, c, body.reason, user.id)
    db.add(CrmActivity(company_id=c.id, kind="status_change", title="Do Not Contact", body=body.reason,
                       occurred_at=now(), user_id=user.id))
    record_activity(db, "data", "do_not_contact", user_id=user.id, entity_type="company", entity_id=c.id)
    return {"entries": len(entries)}


class MergeIn(BaseModel):
    source_id: uuid.UUID


@router.post("/{company_id}/merge")
def merge(company_id: uuid.UUID, body: MergeIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    target = get_company(db, company_id)
    source = get_company(db, body.source_id)
    if source.merged_into_id:
        raise HTTPException(409, "already_merged")
    try:
        merge_companies(db, target, source, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record_activity(db, "data", "company_merged", user_id=user.id, entity_type="company", entity_id=target.id,
                    details={"source": str(source.id)})
    return {"ok": True}


@router.get("/duplicates/pending")
def duplicates(db: Session = Depends(get_db), _: User = Depends(current_user), limit: int = Query(100, le=500)) -> list[dict]:
    rows = db.scalars(select(DuplicateCandidate).where(DuplicateCandidate.status == "pending")
                      .order_by(DuplicateCandidate.score.desc()).limit(limit)).all()
    ids = {r.company_a_id for r in rows} | {r.company_b_id for r in rows}
    comps = {c.id: c for c in db.scalars(select(Company).where(Company.id.in_(ids), Company.deleted_at.is_(None)))}
    out = []
    for r in rows:
        a, b = comps.get(r.company_a_id), comps.get(r.company_b_id)
        if not a or not b or a.merged_into_id or b.merged_into_id:
            continue
        view = lambda c: {"id": str(c.id), "name": c.name, "city": c.city, "address": c.address,  # noqa: E731
                          "website": c.website_url, "phone": c.phone, "country": c.country_iso2}
        out.append({"id": str(r.id), "score": r.score, "reasons": r.reasons, "a": view(a), "b": view(b)})
    return out


@router.post("/duplicates/{dup_id}/dismiss")
def dismiss_duplicate(dup_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    d = db.get(DuplicateCandidate, dup_id)
    if d is None:
        raise HTTPException(404, "not_found")
    d.status = "dismissed"
    return {"ok": True}


class SocialIn(BaseModel):
    url: str = Field(max_length=500)
    verified: bool = True


@router.post("/{company_id}/social-profiles")
def add_social(company_id: uuid.UUID, body: SocialIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    from leadradar.modules.crm.normalize import detect_social

    c = get_company(db, company_id)
    det = detect_social(body.url)
    if not det:
        raise HTTPException(400, "unsupported_social_url")
    sp = SocialProfile(company_id=c.id, platform=det[0], handle=det[1], url=normalize_url(body.url).url,  # type: ignore[union-attr]
                       source="manual", verified=body.verified)
    db.add(sp)
    db.flush()
    return {"id": str(sp.id)}


@router.delete("/{company_id}/social-profiles/{profile_id}")
def delete_social(company_id: uuid.UUID, profile_id: uuid.UUID, db: Session = Depends(get_db),
                  _: User = Depends(current_user)) -> dict:
    sp = db.get(SocialProfile, profile_id)
    if sp is None or sp.company_id != company_id:
        raise HTTPException(404, "not_found")
    db.delete(sp)
    return {"ok": True}


@router.delete("/{company_id}")
def delete_company(company_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Moves the company to the trash (restorable for 30 days). Suppression entries survive."""
    from leadradar.modules.crm.trash import move_to_trash

    move_to_trash(db, [get_company(db, company_id)], user.id)
    return {"ok": True}


@router.get("/trash/items")
def trash_items(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    from leadradar.modules.crm.trash import TRASH_DAYS

    rows = db.scalars(select(Company).where(Company.deleted_at.isnot(None)).order_by(Company.deleted_at.desc()).limit(2000)).all()
    t = now()
    items = []
    for c in rows:
        purge_at = c.deleted_at + timedelta(days=TRASH_DAYS)  # type: ignore[operator]
        items.append({"id": str(c.id), "name": c.name, "country": c.country_iso2, "city": c.city, "domain": c.canonical_domain,
                      "deleted_at": c.deleted_at, "purge_at": purge_at,
                      "days_left": int(max(0, -(-(purge_at - t).total_seconds() // 86400)))})
    return {"days": TRASH_DAYS, "items": items}


class TrashIn(BaseModel):
    ids: list[uuid.UUID] | None = Field(default=None, max_length=5000)  # None with purge = empty the whole trash


@router.post("/trash/restore")
def trash_restore(body: TrashIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    from leadradar.modules.crm.trash import restore

    return {"restored": restore(db, body.ids or [], user.id)}


@router.post("/trash/purge")
def trash_purge(body: TrashIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Permanent deletion of trashed companies (with audits, reports and CRM history)."""
    from leadradar.modules.crm.trash import purge

    return {"deleted": purge(db, body.ids, user.id)}


# --- Export & import -----------------------------------------------------------------------

EXPORT_FIELDS = ["name", "website", "country", "city", "industry", "lead_score", "confidence", "crm_status",
                 "analysis_status", "website_status", "advertising_platforms", "email", "phone"]


@router.post("/export")
def export_csv(body: ListIn, purpose: Literal["contact", "analysis"] = Query("contact"), db: Session = Depends(get_db),
               user: User = Depends(current_user)) -> StreamingResponse:
    f = body.filter.model_copy()
    if purpose == "contact":
        f.dnc = "exclude"  # suppressed records never appear in contact-oriented exports
    q = apply_filter(select(Company), f).limit(50_000)
    inds = _industries(db)
    buf = io.StringIO()
    w = csv.writer(buf)
    fields = EXPORT_FIELDS if purpose == "contact" else [x for x in EXPORT_FIELDS if x not in ("email", "phone")]
    w.writerow(fields)
    count = 0
    for c in db.scalars(q):
        if purpose == "contact" and c.do_not_contact:
            continue
        ind = inds.get(c.primary_industry_id) if c.primary_industry_id else None
        vals = {"name": c.name, "website": c.website_url, "country": c.country_iso2, "city": c.city,
                "industry": ind.key if ind else "", "lead_score": c.effective_lead_score, "confidence": c.confidence_score,
                "crm_status": c.crm_status, "analysis_status": c.analysis_status, "website_status": c.website_status,
                "advertising_platforms": ";".join(c.advertising_platforms or []), "email": c.email, "phone": c.phone}
        # Neutralize spreadsheet formula injection.
        w.writerow([_csv_safe(vals[k]) for k in fields])
        count += 1
    record_activity(db, "data", "export", user_id=user.id, details={"purpose": purpose, "rows": count})
    db.commit()
    buf.seek(0)
    name = f"leadradar-companies-{now().date()}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _csv_safe(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return "" if v is None else v


MAX_CSV_BYTES = 10 * 1024 * 1024


@router.post("/import/preview")
async def import_preview(file: UploadFile, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, "file_too_large")
    text = _decode(raw)
    dialect_delim = ";" if text[:2000].count(";") > text[:2000].count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=dialect_delim)
    rows = [r for _, r in zip(range(6), reader, strict=False)]
    return {"delimiter": dialect_delim, "columns": rows[0] if rows else [], "sample": rows[1:]}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "unreadable_file")


@router.post("/import")
async def import_csv(file: UploadFile, mapping: str = Query(..., max_length=4000), delimiter: str = Query(","),
                     default_country: str | None = Query(None, max_length=2), default_industry: str | None = Query(None),
                     db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    import json

    from leadradar.modules.discovery.handlers import CSV_FIELDS

    raw = await file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        raise HTTPException(413, "file_too_large")
    try:
        m = json.loads(mapping)
    except ValueError as exc:
        raise HTTPException(400, "invalid_mapping") from exc
    if not isinstance(m, dict) or "name" not in m or set(m) - CSV_FIELDS:
        raise HTTPException(400, "invalid_mapping")
    if delimiter not in (",", ";", "\t", "|"):
        raise HTTPException(400, "invalid_delimiter")
    run = ImportRun(source="csv", status="queued", stats={"filename": (file.filename or "")[:200]})
    db.add(run)
    db.flush()
    job = queue.enqueue(db, "csv_import", f"CSV import: {(file.filename or 'upload')[:100]}",
                        {"content": _decode(raw), "mapping": m, "delimiter": delimiter, "import_run_id": str(run.id),
                         "default_country": default_country, "default_industry": default_industry}, created_by=user.id)
    run.job_id = job.id
    return {"job_id": str(job.id), "import_run_id": str(run.id)}


@router.get("/meta/cities")
def cities(country: str | None = None, q: str | None = None, db: Session = Depends(get_db),
           _: User = Depends(current_user)) -> list[str]:
    stmt = select(Company.city).where(Company.city.isnot(None)).group_by(Company.city).order_by(func.count().desc()).limit(50)
    if country:
        stmt = stmt.where(Company.country_iso2 == country.upper())
    if q:
        stmt = stmt.where(or_(func.lower(Company.city).like(f"{q.lower()}%")))
    return [c for c in db.scalars(stmt) if c]
