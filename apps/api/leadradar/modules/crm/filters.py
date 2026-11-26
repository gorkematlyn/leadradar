"""Server-side company filtering shared by the Companies table, saved filters, exports and bulk actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, exists, func, or_, select

from leadradar.db.models import (
    Company,
    CompanyTag,
    Country,
    Industry,
    TrackingDetection,
    WebsiteAudit,
)


class CompanyFilter(BaseModel):
    q: str | None = Field(default=None, max_length=200)
    countries: list[str] = Field(default_factory=list, max_length=300)
    regions: list[str] = Field(default_factory=list, max_length=10)
    cities: list[str] = Field(default_factory=list, max_length=100)
    industries: list[str] = Field(default_factory=list, max_length=100)
    score_min: int | None = Field(default=None, ge=0, le=100)
    score_max: int | None = Field(default=None, ge=0, le=100)
    confidence_min: int | None = Field(default=None, ge=0, le=100)
    confidence_max: int | None = Field(default=None, ge=0, le=100)
    classifications: list[str] = Field(default_factory=list, max_length=10)
    ad_platforms: list[str] = Field(default_factory=list, max_length=10)
    ad_mode: Literal["any", "all"] = "any"
    website_status: list[str] = Field(default_factory=list, max_length=10)
    tracking_detected: list[str] = Field(default_factory=list, max_length=30)
    tracking_not_detected: list[str] = Field(default_factory=list, max_length=30)
    services: list[str] = Field(default_factory=list, max_length=20)
    service_min: int = Field(default=30, ge=0, le=100)
    crm_status: list[str] = Field(default_factory=list, max_length=20)
    analysis_status: list[str] = Field(default_factory=list, max_length=10)
    tags_any: list[str] = Field(default_factory=list, max_length=50)
    tags_all: list[str] = Field(default_factory=list, max_length=50)
    tags_exclude: list[str] = Field(default_factory=list, max_length=50)
    audit_from: datetime | None = None
    audit_to: datetime | None = None
    dnc: Literal["exclude", "include", "only"] = "exclude"
    archived: Literal["exclude", "include", "only"] = "exclude"
    watchlisted: bool | None = None
    industry_confidence: Literal["confident", "review"] | None = None
    has_website: bool | None = None


SORTS: dict[str, Any] = {
    "name": Company.normalized_name, "score": Company.effective_lead_score, "confidence": Company.confidence_score,
    "last_audit": Company.last_audit_at, "created": Company.created_at, "country": Company.country_iso2,
    "city": Company.city, "crm_status": Company.crm_status, "analysis_status": Company.analysis_status,
    "updated": Company.updated_at,
}


def _tag_ids_subq(names: list[str]):  # type: ignore[no-untyped-def]
    from leadradar.db.models import Tag

    return select(Tag.id).where(func.lower(Tag.name).in_([n.lower() for n in names]))


def apply_filter(q: Select, f: CompanyFilter) -> Select:
    conds = [Company.merged_into_id.is_(None)]
    if f.q:
        term = f"%{f.q.strip().lower()}%"
        conds.append(or_(func.lower(Company.name).like(term), Company.canonical_domain.like(term),
                         func.lower(Company.city).like(term), Company.phone_normalized.like(term)))
    if f.countries:
        conds.append(Company.country_iso2.in_([c.upper() for c in f.countries]))
    if f.regions:
        conds.append(Company.country_iso2.in_(select(Country.iso2).where(Country.region_code.in_(f.regions))))
    if f.cities:
        conds.append(func.lower(Company.city).in_([c.lower() for c in f.cities]))
    if f.industries:
        ids = select(Industry.id).where(Industry.key.in_(f.industries))
        conds.append(or_(Company.primary_industry_id.in_(ids),
                         Company.additional_industry_ids.overlap(select(func.array_agg(Industry.id)).where(
                             Industry.key.in_(f.industries)).scalar_subquery())))
    if f.score_min is not None:
        conds.append(Company.effective_lead_score >= f.score_min)
    if f.score_max is not None:
        conds.append(Company.effective_lead_score <= f.score_max)
    if f.confidence_min is not None:
        conds.append(Company.confidence_score >= f.confidence_min)
    if f.confidence_max is not None:
        conds.append(Company.confidence_score <= f.confidence_max)
    if f.classifications:
        conds.append(Company.score_classification.in_(f.classifications))
    if f.ad_platforms:
        conds.append(Company.advertising_platforms.contains(f.ad_platforms) if f.ad_mode == "all"
                     else Company.advertising_platforms.overlap(f.ad_platforms))
    if f.website_status:
        conds.append(Company.website_status.in_(f.website_status))
    for tech in f.tracking_detected:
        conds.append(exists().where(and_(TrackingDetection.audit_id == WebsiteAudit.id,
                                         WebsiteAudit.company_id == Company.id,
                                         TrackingDetection.technology == tech, TrackingDetection.status == "detected")))
    for tech in f.tracking_not_detected:
        conds.append(exists().where(and_(TrackingDetection.audit_id == WebsiteAudit.id,
                                         WebsiteAudit.company_id == Company.id, TrackingDetection.technology == tech,
                                         TrackingDetection.status == "not_detected")))
        conds.append(~exists().where(and_(TrackingDetection.audit_id == WebsiteAudit.id,
                                          WebsiteAudit.company_id == Company.id, TrackingDetection.technology == tech,
                                          TrackingDetection.status == "detected")))
    for svc in f.services:
        conds.append(func.coalesce(Company.service_scores[svc]["score"].as_integer(), 0) >= f.service_min)
    if f.crm_status:
        conds.append(Company.crm_status.in_(f.crm_status))
    if f.analysis_status:
        conds.append(Company.analysis_status.in_(f.analysis_status))
    if f.tags_any:
        conds.append(exists().where(and_(CompanyTag.company_id == Company.id, CompanyTag.tag_id.in_(_tag_ids_subq(f.tags_any)))))
    for name in f.tags_all:
        conds.append(exists().where(and_(CompanyTag.company_id == Company.id, CompanyTag.tag_id.in_(_tag_ids_subq([name])))))
    if f.tags_exclude:
        conds.append(~exists().where(and_(CompanyTag.company_id == Company.id,
                                          CompanyTag.tag_id.in_(_tag_ids_subq(f.tags_exclude)))))
    if f.audit_from:
        conds.append(Company.last_audit_at >= f.audit_from)
    if f.audit_to:
        conds.append(Company.last_audit_at <= f.audit_to)
    if f.dnc == "exclude":
        conds.append(Company.do_not_contact.is_(False))
    elif f.dnc == "only":
        conds.append(Company.do_not_contact.is_(True))
    if f.archived == "exclude":
        conds.append(Company.archived.is_(False))
    elif f.archived == "only":
        conds.append(Company.archived.is_(True))
    if f.watchlisted is not None:
        conds.append(Company.watchlisted.is_(f.watchlisted))
    if f.industry_confidence:
        conds.append(Company.industry_confidence == f.industry_confidence)
    if f.has_website is not None:
        conds.append(Company.website_url.isnot(None) if f.has_website else Company.website_url.is_(None))
    return q.where(and_(*conds))
