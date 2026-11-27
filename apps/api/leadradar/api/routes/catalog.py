from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from leadradar.api.deps import current_user
from leadradar.core.activity import record_activity
from leadradar.db.models import (
    Company,
    Country,
    ImportRun,
    Industry,
    IndustryRule,
    Job,
    Region,
    ReviewTemplate,
    SavedGeoSelection,
    ScoringProfile,
    User,
)
from leadradar.db.session import get_db
from leadradar.jobs import queue
from leadradar.modules.discovery.matching import compile_rules
from leadradar.modules.discovery.status import (
    country_action,
    country_progress,
    display_status,
    on_job_cancelled,
)

router = APIRouter(tags=["catalog"])


@router.get("/regions")
def regions(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"code": r.code, "name_en": r.name_en, "name_tr": r.name_tr}
            for r in db.scalars(select(Region).order_by(Region.sort_order))]


@router.get("/countries")
def countries(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    counts = dict(db.execute(select(Company.country_iso2, func.count()).where(Company.merged_into_id.is_(None))
                             .group_by(Company.country_iso2)).all())
    progress = country_progress(db)
    return [{"iso2": c.iso2, "iso3": c.iso3, "name_en": c.name_en, "name_tr": c.name_tr, "region": c.region_code,
             "flag": c.flag_asset, "enabled": c.enabled, "is_priority": c.is_priority,
             "import_status": display_status(c, progress.get(c.iso2)), "progress": progress.get(c.iso2),
             "last_import_at": c.last_import_at, "last_source_timestamp": c.last_source_timestamp,
             "geofabrik_ids": c.geofabrik_ids, "companies": counts.get(c.iso2, 0)}
            for c in db.scalars(select(Country).order_by(Country.name_en))]


@router.get("/discovery/progress")
def discovery_progress(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    """Import batches per country (latest batch), for progress bars on Discovery and Overview."""
    progress = country_progress(db)
    if not progress:
        return []
    out = []
    for c in db.scalars(select(Country).where(Country.iso2.in_(list(progress)))):
        p = progress[c.iso2]
        out.append({"iso2": c.iso2, "name_en": c.name_en, "name_tr": c.name_tr, "region": c.region_code,
                    "flag": c.flag_asset, **p, "status": display_status(c, p)})
    return out


class CountryAction(BaseModel):
    action: Literal["cancel", "pause", "resume"]


@router.post("/discovery/countries/{iso2}/action")
def discovery_country_action(iso2: str, body: CountryAction, db: Session = Depends(get_db),
                             user: User = Depends(current_user)) -> dict:
    if db.get(Country, iso2.upper()) is None:
        raise HTTPException(404, "not_found")
    affected = country_action(db, iso2, body.action)
    record_activity(db, "data", f"import_{body.action}", user_id=user.id, entity_type="country",
                    entity_id=iso2.upper(), details={"jobs": affected})
    return {"affected": affected}


class CountryPatch(BaseModel):
    enabled: bool | None = None
    is_priority: bool | None = None
    geofabrik_ids: list[str] | None = Field(default=None, max_length=100)


@router.patch("/countries/{iso2}")
def patch_country(iso2: str, body: CountryPatch, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    c = db.get(Country, iso2.upper())
    if c is None:
        raise HTTPException(404, "not_found")
    if body.enabled is not None:
        c.enabled = body.enabled
        if not body.enabled:
            # Stop future imports; existing companies are kept.
            for job in db.scalars(select(Job).where(Job.type.in_(["geofabrik_country_import", "geofabrik_extract_import"]),
                                                    Job.status.in_(["queued", "paused"]))):
                if (job.payload or {}).get("country") == c.iso2:
                    queue.cancel(db, job)
                    on_job_cancelled(db, job)
            c.import_status = "disabled"
        elif c.import_status == "disabled":
            c.import_status = "never" if c.last_import_at is None else "completed"
    if body.is_priority is not None:
        c.is_priority = body.is_priority
    if body.geofabrik_ids is not None:
        c.geofabrik_ids = [x.strip() for x in body.geofabrik_ids if x.strip()] or None
    c.admin_customized = True
    record_activity(db, "settings", "country_updated", user_id=user.id, entity_type="country", entity_id=c.iso2,
                    details=body.model_dump(exclude_unset=True))
    return {"ok": True}


class BulkCountries(BaseModel):
    iso2: list[str] = Field(max_length=300)
    enabled: bool


@router.post("/countries/bulk")
def bulk_countries(body: BulkCountries, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    for code in body.iso2:
        patch_country(code, CountryPatch(enabled=body.enabled), db, user)
    return {"updated": len(body.iso2)}


class ImportIn(BaseModel):
    countries: list[str] = Field(min_length=1, max_length=50)
    industries: list[str] | None = None
    force: bool = False


@router.post("/discovery/imports")
def start_imports(body: ImportIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    jobs = []
    for iso in body.countries:
        c = db.get(Country, iso.upper())
        if c is None or not c.enabled:
            raise HTTPException(400, f"country_disabled:{iso}")
        j = queue.enqueue(db, "geofabrik_country_import", f"Import {c.name_en}",
                          {"country": c.iso2, "industries": body.industries, "force": body.force},
                          idempotency_key=f"geofabrik_country:{c.iso2}", created_by=user.id)
        c.import_status = "queued"
        jobs.append(str(j.id))
    return {"jobs": jobs}


@router.delete("/discovery/imports")
def clear_import_runs(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Delete the import history. Runs that are still queued or running are kept."""
    active_jobs = select(Job.id).where(Job.status.in_(["queued", "running", "paused"]))
    res = db.execute(delete(ImportRun).where(ImportRun.status.notin_(["queued", "running"]))
                     .where(or_(ImportRun.job_id.is_(None), ImportRun.job_id.notin_(active_jobs))))
    # Runs left "queued" by an earlier version after their job was cancelled are stale as well.
    stale = db.execute(delete(ImportRun).where(ImportRun.status.in_(["queued", "running"]),
                                               or_(ImportRun.job_id.is_(None), ImportRun.job_id.notin_(active_jobs))))
    deleted = (res.rowcount or 0) + (stale.rowcount or 0)
    record_activity(db, "data", "import_history_cleared", user_id=user.id, details={"deleted": deleted})
    return {"deleted": deleted}


@router.get("/discovery/imports")
def import_runs(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    rows = db.scalars(select(ImportRun).order_by(ImportRun.created_at.desc()).limit(200))
    return [{"id": str(r.id), "source": r.source, "country": r.country_iso2, "extract_id": r.extract_id,
             "status": r.status, "file_size": r.file_size, "source_timestamp": r.source_timestamp, "stats": r.stats,
             "error": r.error, "job_id": str(r.job_id) if r.job_id else None, "started_at": r.started_at,
             "finished_at": r.finished_at, "created_at": r.created_at} for r in rows]


# --- Industries ----------------------------------------------------------------------------

def industry_view(i: Industry) -> dict[str, Any]:
    return {"id": str(i.id), "key": i.key, "name_en": i.name_en, "name_tr": i.name_tr,
            "description_en": i.description_en, "description_tr": i.description_tr, "enabled": i.enabled,
            "priority": i.priority, "is_priority": i.is_priority, "relevant_services": i.relevant_services,
            "relevant_features": i.relevant_features, "applicable_audit_rules": i.applicable_audit_rules,
            "review_template_id": str(i.review_template_id) if i.review_template_id else None,
            "scoring_profile_id": str(i.scoring_profile_id) if i.scoring_profile_id else None,
            "rules": [{"id": str(r.id), "key": r.key, "description": r.description, "conditions": r.conditions,
                       "classification": r.classification, "enabled": r.enabled} for r in i.rules]}


@router.get("/industries")
def industries(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [industry_view(i) for i in db.scalars(select(Industry).order_by(Industry.priority.desc(), Industry.name_en))]


class IndustryIn(BaseModel):
    key: str | None = Field(default=None, pattern=r"^[a-z0-9_]{2,64}$")
    name_en: str | None = Field(default=None, max_length=120)
    name_tr: str | None = Field(default=None, max_length=120)
    description_en: str | None = Field(default=None, max_length=2000)
    description_tr: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    is_priority: bool | None = None
    relevant_services: list[str] | None = None
    relevant_features: list[str] | None = None
    applicable_audit_rules: list[str] | None = None
    review_template_id: uuid.UUID | None = None
    scoring_profile_id: uuid.UUID | None = None


def _apply_industry(db: Session, ind: Industry, body: IndustryIn) -> None:
    from leadradar.seeds.defaults import SERVICES

    data = body.model_dump(exclude_unset=True)
    data.pop("key", None)
    if "relevant_services" in data and set(data["relevant_services"] or []) - set(SERVICES):
        raise HTTPException(400, "invalid_service")
    if data.get("review_template_id") and db.get(ReviewTemplate, data["review_template_id"]) is None:
        raise HTTPException(400, "invalid_review_template")
    if data.get("scoring_profile_id") and db.get(ScoringProfile, data["scoring_profile_id"]) is None:
        raise HTTPException(400, "invalid_profile")
    for k, v in data.items():
        setattr(ind, k, v)
    ind.admin_customized = True


@router.post("/industries")
def create_industry(body: IndustryIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    if not body.key or not body.name_en or not body.name_tr:
        raise HTTPException(400, "key_and_names_required")
    if db.scalar(select(Industry.id).where(Industry.key == body.key)):
        raise HTTPException(409, "exists")
    default_tpl = db.scalar(select(ReviewTemplate).where(ReviewTemplate.is_default.is_(True)))
    ind = Industry(key=body.key, name_en=body.name_en, name_tr=body.name_tr, review_template_id=default_tpl.id if default_tpl else None)
    db.add(ind)
    _apply_industry(db, ind, body)
    db.flush()
    record_activity(db, "settings", "industry_created", user_id=user.id, entity_type="industry", entity_id=ind.key)
    return industry_view(ind)


@router.patch("/industries/{industry_id}")
def patch_industry(industry_id: uuid.UUID, body: IndustryIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    ind = db.get(Industry, industry_id)
    if ind is None:
        raise HTTPException(404, "not_found")
    _apply_industry(db, ind, body)
    record_activity(db, "settings", "industry_updated", user_id=user.id, entity_type="industry", entity_id=ind.key)
    db.flush()
    return industry_view(ind)


class RuleIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    description: str = Field(default="", max_length=500)
    conditions: dict
    classification: Literal["confident", "review"] = "confident"
    enabled: bool = True


def _validate_conditions(cond: dict) -> None:
    if set(cond) - {"all", "any", "exclude"}:
        raise HTTPException(400, "invalid_conditions")
    for group in cond.values():
        if not isinstance(group, list) or len(group) > 20:
            raise HTTPException(400, "invalid_conditions")
        for c in group:
            if not isinstance(c, dict) or not isinstance(c.get("key"), str) or c.get("op", "eq") not in ("eq", "in", "exists", "regex"):
                raise HTTPException(400, "invalid_conditions")
            if c.get("op") == "regex" and len(str(c.get("value", ""))) > 200:
                raise HTTPException(400, "regex_too_long")
    try:
        compile_rules([{"industry_key": "x", "rule_key": "x", "conditions": cond}])
    except Exception as exc:
        raise HTTPException(400, "invalid_conditions") from exc
    if not cond.get("all") and not cond.get("any"):
        raise HTTPException(400, "conditions_required")


@router.post("/industries/{industry_id}/rules")
def add_rule(industry_id: uuid.UUID, body: RuleIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    ind = db.get(Industry, industry_id)
    if ind is None:
        raise HTTPException(404, "not_found")
    _validate_conditions(body.conditions)
    if db.scalar(select(IndustryRule.id).where(IndustryRule.industry_id == ind.id, IndustryRule.key == body.key)):
        raise HTTPException(409, "exists")
    r = IndustryRule(industry_id=ind.id, **body.model_dump())
    db.add(r)
    ind.admin_customized = True
    db.flush()
    return {"id": str(r.id)}


@router.patch("/industries/{industry_id}/rules/{rule_id}")
def patch_rule(industry_id: uuid.UUID, rule_id: uuid.UUID, body: RuleIn, db: Session = Depends(get_db),
               _: User = Depends(current_user)) -> dict:
    r = db.get(IndustryRule, rule_id)
    if r is None or r.industry_id != industry_id:
        raise HTTPException(404, "not_found")
    _validate_conditions(body.conditions)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    ind = db.get(Industry, industry_id)
    ind.admin_customized = True  # type: ignore[union-attr]
    return {"ok": True}


@router.delete("/industries/{industry_id}/rules/{rule_id}")
def delete_rule(industry_id: uuid.UUID, rule_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.get(IndustryRule, rule_id)
    if r is None or r.industry_id != industry_id:
        raise HTTPException(404, "not_found")
    db.delete(r)
    db.get(Industry, industry_id).admin_customized = True  # type: ignore[union-attr]
    return {"ok": True}


class TestTagsIn(BaseModel):
    tags: dict[str, str]


@router.post("/industries/test-match")
def test_match(body: TestTagsIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    from leadradar.modules.discovery.handlers import load_rules
    from leadradar.modules.discovery.matching import match_industries

    return [m.__dict__ for m in match_industries(load_rules(db), body.tags)]


# --- Saved geographic selections ------------------------------------------------------------

class GeoIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)


@router.get("/geo-selections")
def geo_list(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"id": str(g.id), "name": g.name, "regions": g.regions, "countries": g.countries,
             "industries": g.industries, "cities": g.cities}
            for g in db.scalars(select(SavedGeoSelection).order_by(SavedGeoSelection.name))]


@router.post("/geo-selections")
def geo_create(body: GeoIn, overwrite: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    """Names are unique (case-insensitive). An existing name is replaced only with ``overwrite=true``."""
    name = body.name.strip()
    existing = db.scalar(select(SavedGeoSelection).where(func.lower(SavedGeoSelection.name) == name.lower()))
    if existing is not None:
        if not overwrite:
            raise HTTPException(409, "exists")
        for k, v in body.model_dump().items():
            setattr(existing, k, v)
        existing.name = name
        return {"id": str(existing.id), "overwritten": True}
    g = SavedGeoSelection(**{**body.model_dump(), "name": name})
    db.add(g)
    db.flush()
    return {"id": str(g.id), "overwritten": False}


@router.put("/geo-selections/{gid}")
def geo_update(gid: uuid.UUID, body: GeoIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    g = db.get(SavedGeoSelection, gid)
    if g is None:
        raise HTTPException(404, "not_found")
    name = body.name.strip()
    clash = db.scalar(select(SavedGeoSelection.id).where(func.lower(SavedGeoSelection.name) == name.lower(),
                                                         SavedGeoSelection.id != gid))
    if clash:
        raise HTTPException(409, "exists")
    for k, v in body.model_dump().items():
        setattr(g, k, v)
    g.name = name
    return {"id": str(g.id)}


@router.delete("/geo-selections/{gid}")
def geo_delete(gid: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    g = db.get(SavedGeoSelection, gid)
    if g:
        db.delete(g)
    return {"ok": True}
