"""Company creation, source upserts, duplicate detection and merging."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from leadradar.db.models import (
    Advertiser,
    AdvertisingResearchRun,
    ChangeEvent,
    Company,
    CompanyChange,
    CompanySnapshot,
    CompanySource,
    CompanyTag,
    Contact,
    CrmActivity,
    DuplicateCandidate,
    Evidence,
    Industry,
    LeadScore,
    MergeHistory,
    Report,
    ScoreOverride,
    SocialProfile,
    WebsiteAudit,
    WebsiteProperty,
)
from leadradar.modules.crm.normalize import (
    detect_social,
    haversine_m,
    name_similarity,
    normalize_name,
    normalize_phone,
    normalize_url,
)
from leadradar.modules.crm.suppression import is_suppressed

SOURCE_RELIABILITY = {"manual": 100, "quick_audit": 80, "csv": 60, "osm": 50, "apify": 40}
TRACKED_FIELDS = ("name", "legal_name", "website_url", "email", "phone", "address", "city", "region", "postal_code",
                  "latitude", "longitude", "country_iso2")


def now() -> datetime:
    return datetime.now(UTC)


@dataclass
class RecordInput:
    source: str
    source_key: str
    name: str
    country_iso2: str | None = None
    industry_keys: list[str] = field(default_factory=list)
    classification: str = "confident"
    source_url: str | None = None
    legal_name: str | None = None
    region: str | None = None
    city: str | None = None
    address: str | None = None
    postal_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    socials: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    source_timestamp: datetime | None = None
    is_chain: bool | None = None
    closed: bool = False
    import_run_id: uuid.UUID | None = None


@dataclass
class UpsertOutcome:
    company: Company
    action: str  # created, updated, matched, unchanged
    duplicate_candidates: int = 0


def _clean_email(v: str | None) -> str | None:
    if not v:
        return None
    v = v.strip().split(";")[0].strip().lower()
    if v.startswith("mailto:"):
        v = v[7:]
    return v if "@" in v and "." in v.split("@")[-1] and len(v) <= 320 else None


def ensure_property(db: Session, url: str | None) -> WebsiteProperty | None:
    n = normalize_url(url or "")
    if n is None:
        return None
    prop = db.scalar(select(WebsiteProperty).where(WebsiteProperty.property_key == n.property_key))
    if prop is None:
        prop = WebsiteProperty(property_key=n.property_key, canonical_domain=n.canonical_domain, start_url=n.url,
                               is_shared_platform=n.is_shared_platform)
        db.add(prop)
        db.flush()
    return prop


def _set_field(db: Session, company: Company, fld: str, value: Any, source: str, *, user_id=None,  # type: ignore[no-untyped-def]
               force: bool = False, record_change: bool = True) -> bool:
    if value is None or value == "":
        return False
    meta = (company.field_sources or {}).get(fld) or {}
    current = getattr(company, fld)
    if current == value:
        return False
    if not force and current not in (None, ""):
        if meta.get("confirmed"):
            return False  # never overwrite administrator-confirmed values
        if SOURCE_RELIABILITY.get(source, 0) < SOURCE_RELIABILITY.get(meta.get("source", ""), 0):
            return False
    setattr(company, fld, value)
    fs = dict(company.field_sources or {})
    fs[fld] = {"source": source, "at": now().isoformat(), "confirmed": source == "manual"}
    company.field_sources = fs
    if record_change and current not in (None, ""):
        db.add(CompanyChange(company_id=company.id, field=fld, old_value=current, new_value=value, source=source,
                             user_id=user_id, created_at=now()))
    return True


def apply_website(db: Session, company: Company, url: str | None, source: str, *, force: bool = False,
                  user_id=None) -> None:  # type: ignore[no-untyped-def]
    n = normalize_url(url or "")
    if n is None:
        return
    if _set_field(db, company, "website_url", n.url, source, force=force, user_id=user_id):
        company.canonical_domain = None if n.is_shared_platform else n.canonical_domain
        prop = ensure_property(db, n.url)
        company.website_property_id = prop.id if prop else None
        if company.website_status in ("not_found", "verified_absent", "unverified"):
            company.website_status = "unverified"


def _industry_ids(db: Session, keys: list[str]) -> list[uuid.UUID]:
    if not keys:
        return []
    rows = dict(db.execute(select(Industry.key, Industry.id).where(Industry.key.in_(keys))).all())
    return [rows[k] for k in keys if k in rows]


def find_matches(db: Session, rec: RecordInput, domain: str | None, phone: str | None) -> tuple[Company | None, list[tuple[Company, float, list[str]]]]:
    """Return (high-confidence match, potential duplicates)."""
    conds = []
    if domain:
        conds.append(Company.canonical_domain == domain)
    if phone:
        conds.append(Company.phone_normalized == phone)
    norm = normalize_name(rec.name)
    if rec.latitude is not None and rec.longitude is not None:
        d = 0.003  # ~300 m bounding box
        conds.append(and_(Company.latitude.between(rec.latitude - d, rec.latitude + d),
                          Company.longitude.between(rec.longitude - d * 1.5, rec.longitude + d * 1.5)))
    elif norm and rec.city:
        conds.append(and_(Company.normalized_name == norm, Company.city.ilike(rec.city)))
    if not conds:
        return None, []
    cands = db.scalars(select(Company).where(or_(*conds), Company.merged_into_id.is_(None)).limit(50)).all()
    best: Company | None = None
    potentials: list[tuple[Company, float, list[str]]] = []
    for c in cands:
        reasons: list[str] = []
        dist = None
        if None not in (rec.latitude, rec.longitude, c.latitude, c.longitude):
            dist = haversine_m(rec.latitude, rec.longitude, c.latitude, c.longitude)  # type: ignore[arg-type]
        sim = name_similarity(rec.name, c.name)
        same_domain = bool(domain and c.canonical_domain == domain)
        same_phone = bool(phone and c.phone_normalized == phone)
        if same_domain:
            reasons.append("same_domain")
        if same_phone:
            reasons.append("same_phone")
        if sim >= 0.6:
            reasons.append(f"name_similarity_{sim:.2f}")
        if dist is not None:
            reasons.append(f"distance_{int(dist)}m")
        near = dist is not None and dist <= 150
        unknown_loc = dist is None
        # High-confidence automatic match.
        if (same_domain and (near or (unknown_loc and sim >= 0.6))) or (same_phone and (near or sim >= 0.6)) or (
            sim >= 0.9 and dist is not None and dist <= 40
        ):
            if best is None:
                best = c
            continue
        score = 0.0
        if same_domain:
            score += 0.4  # same domain, different location: possibly a branch
        if same_phone:
            score += 0.3
        score += 0.4 * sim
        if dist is not None and dist <= 100:
            score += 0.2
        if score >= 0.5:
            potentials.append((c, round(min(score, 1.0), 2), reasons))
    return best, potentials


def upsert_record(db: Session, rec: RecordInput, suppression: dict[str, set[str]] | None = None) -> UpsertOutcome:
    t = now()
    src = db.scalar(select(CompanySource).where(CompanySource.source == rec.source,
                                                CompanySource.source_key == rec.source_key))
    domain_n = normalize_url(rec.website or "")
    domain = domain_n.canonical_domain if domain_n and not domain_n.is_shared_platform else None
    phone = normalize_phone(rec.phone, rec.country_iso2)
    email = _clean_email(rec.email)
    potentials: list[tuple[Company, float, list[str]]] = []
    company: Company | None = None
    action = "updated"
    if src is not None:
        company = db.get(Company, src.company_id)
        while company is not None and company.merged_into_id:
            company = db.get(Company, company.merged_into_id)
    if company is None:
        company, potentials = find_matches(db, rec, domain, phone)
        action = "matched" if company else "created"
    if company is None:
        company = Company(id=uuid.uuid4(), name=rec.name[:300], normalized_name=normalize_name(rec.name)[:300],
                          discovered_at=t, crm_status="new", analysis_status="not_analyzed",
                          website_status="unverified" if rec.website else "not_found", field_sources={})
        db.add(company)
        db.flush()
    changed = False
    for fld, val in (("name", rec.name[:300]), ("legal_name", rec.legal_name), ("country_iso2", rec.country_iso2),
                     ("region", rec.region), ("city", rec.city), ("address", rec.address),
                     ("postal_code", rec.postal_code), ("latitude", rec.latitude), ("longitude", rec.longitude),
                     ("email", email)):
        changed |= _set_field(db, company, fld, val, rec.source, record_change=action != "created")
    if phone and _set_field(db, company, "phone", (rec.phone or "")[:64], rec.source, record_change=action != "created"):
        company.phone_normalized = phone
        changed = True
    if rec.website:
        apply_website(db, company, rec.website, rec.source)
    if not company.website_url and company.website_status == "unverified":
        company.website_status = "not_found"  # the source gave no usable website address
    company.normalized_name = normalize_name(company.name)[:300]
    ind_ids = _industry_ids(db, rec.industry_keys)
    if ind_ids:
        if company.primary_industry_id is None:
            company.primary_industry_id = ind_ids[0]
            company.industry_confidence = rec.classification
        elif company.industry_confidence == "review" and rec.classification == "confident" and not (
            company.field_sources or {}).get("primary_industry_id", {}).get("confirmed"):
            company.primary_industry_id = ind_ids[0]
            company.industry_confidence = "confident"
        extra = [i for i in ind_ids if i != company.primary_industry_id and i not in (company.additional_industry_ids or [])]
        if extra:
            company.additional_industry_ids = list(company.additional_industry_ids or []) + extra
    if rec.is_chain is not None and company.is_chain is None:
        company.is_chain = rec.is_chain
    if rec.closed:
        company.permanently_closed = True
    for s in rec.socials:
        det = detect_social(s)
        if det:
            platform, handle = det
            exists = db.scalar(select(SocialProfile.id).where(SocialProfile.company_id == company.id,
                                                              SocialProfile.platform == platform,
                                                              SocialProfile.handle == handle))
            if not exists:
                db.add(SocialProfile(company_id=company.id, platform=platform, handle=handle,
                                     url=normalize_url(s).url if normalize_url(s) else s, source=rec.source))  # type: ignore[union-attr]
    if src is None:
        src = CompanySource(company_id=company.id, source=rec.source, source_key=rec.source_key)
        db.add(src)
    src.company_id = company.id
    src.source_url = rec.source_url
    src.raw = rec.raw
    src.source_timestamp = rec.source_timestamp
    src.import_run_id = rec.import_run_id
    src.last_seen_at = t
    company.last_verified_at = t if rec.source == "manual" else company.last_verified_at
    if suppression is not None and not company.do_not_contact and is_suppressed(
        suppression, company_id=str(company.id), domain=company.canonical_domain, email=company.email,
        phone=company.phone_normalized, source_keys=[f"{rec.source}:{rec.source_key}"],
    ):
        company.do_not_contact = True
        company.crm_status = "do_not_contact"
    db.flush()
    created_dups = 0
    for other, score, reasons in potentials:
        if other.id == company.id:
            continue
        a, b = sorted([company.id, other.id], key=str)
        if not db.scalar(select(DuplicateCandidate.id).where(DuplicateCandidate.company_a_id == a,
                                                             DuplicateCandidate.company_b_id == b)):
            db.add(DuplicateCandidate(company_a_id=a, company_b_id=b, score=score, reasons=reasons))
            created_dups += 1
    if created_dups:
        db.flush()
    if action == "updated" and not changed:
        action = "unchanged"
    return UpsertOutcome(company, action, created_dups)


def merge_companies(db: Session, target: Company, source: Company, user_id: uuid.UUID | None) -> None:
    """Merge ``source`` into ``target`` preserving CRM records, audits and history."""
    if target.id == source.id:
        raise ValueError("cannot merge a company into itself")
    snapshot = {c.name: _jsonable(getattr(source, c.key)) for c in Company.__table__.columns}
    for fld in TRACKED_FIELDS:
        if getattr(target, fld) in (None, "") and getattr(source, fld) not in (None, ""):
            setattr(target, fld, getattr(source, fld))
    if not target.canonical_domain and source.canonical_domain:
        target.canonical_domain = source.canonical_domain
        target.website_property_id = source.website_property_id
    if not target.phone_normalized:
        target.phone_normalized = source.phone_normalized
    target.do_not_contact = target.do_not_contact or source.do_not_contact
    target.notes = "\n\n".join(x for x in (target.notes, source.notes) if x) or None
    moves = [CompanySource, Contact, CrmActivity, WebsiteAudit, Evidence, LeadScore, ScoreOverride, Report,
             AdvertisingResearchRun, ChangeEvent, CompanySnapshot, CompanyChange]
    for model in moves:
        db.execute(update(model).where(model.company_id == source.id).values(company_id=target.id))
    db.execute(update(Advertiser).where(Advertiser.company_id == source.id).values(company_id=target.id))
    for sp in db.scalars(select(SocialProfile).where(SocialProfile.company_id == source.id)).all():
        dup = db.scalar(select(SocialProfile.id).where(SocialProfile.company_id == target.id,
                                                       SocialProfile.platform == sp.platform,
                                                       SocialProfile.handle == sp.handle))
        if dup:
            db.delete(sp)
        else:
            sp.company_id = target.id
    target_tags = set(db.scalars(select(CompanyTag.tag_id).where(CompanyTag.company_id == target.id)))
    for ct in db.scalars(select(CompanyTag).where(CompanyTag.company_id == source.id)).all():
        if ct.tag_id not in target_tags:
            db.add(CompanyTag(company_id=target.id, tag_id=ct.tag_id))
        db.delete(ct)
    db.execute(update(DuplicateCandidate).where(
        or_(and_(DuplicateCandidate.company_a_id == source.id, DuplicateCandidate.company_b_id == target.id),
            and_(DuplicateCandidate.company_a_id == target.id, DuplicateCandidate.company_b_id == source.id))
    ).values(status="merged"))
    source.merged_into_id = target.id
    source.archived = True
    db.add(MergeHistory(target_company_id=target.id, merged_company_id=source.id, merged_snapshot=snapshot,
                        user_id=user_id, created_at=now()))
    db.add(CrmActivity(company_id=target.id, kind="note", title="Merged company", body=f"Merged record {source.name}",
                       data={"merged_company_id": str(source.id)}, occurred_at=now(), user_id=user_id))
    db.flush()


def _jsonable(v: Any) -> Any:
    if isinstance(v, (uuid.UUID, datetime)):
        return str(v)
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v
