"""Idempotent seeding.

* Inserts missing rows; updates seeded rows only while ``admin_customized`` is false.
* Never deletes administrator data and never creates companies.
* Safe to run on every deployment (guarded by a PostgreSQL advisory lock).
"""

from __future__ import annotations

import json
import logging
from importlib import resources

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from leadradar.core.app_settings import DEFS
from leadradar.db.models import (
    AdvertisingProvider,
    ApplicationSetting,
    AuditRule,
    Country,
    CrmStatus,
    Industry,
    IndustryRule,
    Region,
    ReportTemplate,
    RetentionPolicy,
    ReviewQuestion,
    ReviewTemplate,
    ScoringProfile,
    ScoringRule,
    ServiceRule,
    TrackingTechnology,
)
from leadradar.seeds import defaults as D

log = logging.getLogger(__name__)


def _upsert(db: Session, model, pk: dict, values: dict, *, respect_custom: bool = True):  # type: ignore[no-untyped-def]
    row = db.get(model, tuple(pk.values()) if len(pk) > 1 else next(iter(pk.values())))
    if row is None:
        row = model(**pk, **values)
        db.add(row)
        return row, True
    if respect_custom and getattr(row, "admin_customized", False):
        return row, False
    for k, v in values.items():
        setattr(row, k, v)
    return row, False


def seed_regions_countries(db: Session) -> None:
    for code, en, tr, order in D.REGIONS:
        _upsert(db, Region, {"code": code}, {"name_en": en, "name_tr": tr, "sort_order": order}, respect_custom=False)
    db.flush()
    data = json.loads(resources.files("leadradar.seeds").joinpath("data/countries.json").read_text("utf-8"))
    initial = {"TR", "NL", "DE", "GB", "US"}
    for c in data:
        row = db.get(Country, c["iso2"])
        if row is None:
            db.add(Country(
                iso2=c["iso2"], iso3=c["iso3"], name_en=c["name_en"], name_tr=c["name_tr"], region_code=c["region"],
                flag_asset=c["flag"], enabled=c["iso2"] in initial, is_priority=c["iso2"] in initial,
            ))
        elif not row.admin_customized:
            row.name_en, row.name_tr, row.region_code, row.flag_asset = c["name_en"], c["name_tr"], c["region"], c["flag"]


def seed_review_templates(db: Session) -> ReviewTemplate:
    tpl = db.scalar(select(ReviewTemplate).where(ReviewTemplate.key == "default"))
    if tpl is None:
        tpl = ReviewTemplate(key="default", name_en="Default review", name_tr="Varsayılan inceleme", is_default=True)
        db.add(tpl)
        db.flush()
    existing = {q.key: q for q in db.scalars(select(ReviewQuestion).where(ReviewQuestion.template_id == tpl.id))}
    for i, (key, en, tr, yes_sig, no_sig) in enumerate(D.REVIEW_QUESTIONS):
        if key not in existing:
            db.add(ReviewQuestion(template_id=tpl.id, key=key, text_en=en, text_tr=tr, yes_signal=yes_sig,
                                  no_signal=no_sig, sort_order=i))
    return tpl


def seed_scoring(db: Session) -> dict[str, ScoringProfile]:
    profiles: dict[str, ScoringProfile] = {}
    for key, en, tr, is_default, focus, overrides in D.PROFILES:
        prof = db.scalar(select(ScoringProfile).where(ScoringProfile.key == key))
        if prof is None:
            prof = ScoringProfile(
                key=key, name_en=en, name_tr=tr, is_default=is_default, category_limits=dict(D.CATEGORY_LIMITS),
                thresholds=dict(D.THRESHOLDS), confidence_weights=dict(D.CONFIDENCE_WEIGHTS), service_focus=focus,
            )
            db.add(prof)
            db.flush()
        profiles[key] = prof
        existing = {r.key: r for r in db.scalars(select(ScoringRule).where(ScoringRule.profile_id == prof.id))}
        for rule in D.SCORING_RULES:
            values = dict(rule)
            if rule["key"] in overrides:
                values["points"] = overrides[rule["key"]]
            row = existing.get(rule["key"])
            if row is None:
                db.add(ScoringRule(profile_id=prof.id, **values))
            elif not row.admin_customized:
                changed = any(getattr(row, k) != v for k, v in values.items())
                if changed:
                    for k, v in values.items():
                        setattr(row, k, v)
                    row.version += 1
    existing_svc = {r.key: r for r in db.scalars(select(ServiceRule))}
    for rule in D.SERVICE_RULES:
        row = existing_svc.get(rule["key"])
        if row is None:
            db.add(ServiceRule(**rule))
        elif not row.admin_customized and any(getattr(row, k) != v for k, v in rule.items()):
            for k, v in rule.items():
                setattr(row, k, v)
            row.version += 1
    return profiles


def seed_industries(db: Session, review_tpl: ReviewTemplate, profiles: dict[str, ScoringProfile]) -> None:
    profile_for = {"ecommerce_brands": "ecommerce", "digital_agencies": "website_design"}
    for ind in D.INDUSTRIES:
        row = db.scalar(select(Industry).where(Industry.key == ind["key"]))
        values = {
            "name_en": ind["name_en"], "name_tr": ind["name_tr"], "description_en": ind["description_en"],
            "description_tr": ind["description_tr"], "priority": ind["priority"],
            "relevant_services": ind["services"], "relevant_features": ind["features"],
        }
        if row is None:
            row = Industry(key=ind["key"], enabled=True, is_priority=ind["priority"] >= 7,
                           review_template_id=review_tpl.id,
                           scoring_profile_id=profiles[profile_for.get(ind["key"], "general")].id, **values)
            db.add(row)
            db.flush()
        elif not row.admin_customized:
            for k, v in values.items():
                setattr(row, k, v)
        else:
            continue
        existing = {r.key: r for r in db.scalars(select(IndustryRule).where(IndustryRule.industry_id == row.id))}
        for rule in ind["rules"]:
            if rule["key"] not in existing:
                db.add(IndustryRule(industry_id=row.id, key=rule["key"], conditions=rule["conditions"],
                                    classification=rule["classification"], description=rule["key"].replace("_", " ")))


def seed_misc(db: Session) -> None:
    for key, en, tr, order, terminal, pipeline in D.CRM_STATUSES:
        _upsert(db, CrmStatus, {"key": key},
                {"name_en": en, "name_tr": tr, "sort_order": order, "is_terminal": terminal, "show_in_pipeline": pipeline},
                respect_custom=False)
    for rule in D.AUDIT_RULES:
        values = dict(rule)
        key = values.pop("key")
        row = db.get(AuditRule, key)
        if row is None:
            db.add(AuditRule(key=key, **values))
        elif not row.admin_customized and any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            row.version += 1
    for tech in D.TRACKING_TECHNOLOGIES:
        values = dict(tech)
        key = values.pop("key")
        _upsert(db, TrackingTechnology, {"key": key}, values)
    for p in D.ADVERTISING_PROVIDERS:
        row = db.get(AdvertisingProvider, p["key"])
        values = {"name": p["name"], "official_source_url": p["official_source_url"],
                  "manual_search_url_template": p["manual_search_url_template"], "automation_note_en": p["note_en"],
                  "automation_note_tr": p["note_tr"], "sort_order": p["sort_order"]}
        if row is None:
            db.add(AdvertisingProvider(key=p["key"], automation_status=p["automation_status"], **values))
        else:
            for k, v in values.items():
                if row.admin_customized and k in ("official_source_url", "manual_search_url_template"):
                    continue  # keep URLs edited by the administrator
                setattr(row, k, v)
            if p["automation_status"] == "unsupported":
                row.automation_status = "unsupported"
    for key, en, tr, is_default, sections in D.REPORT_TEMPLATES:
        if db.scalar(select(ReportTemplate).where(ReportTemplate.key == key)) is None:
            db.add(ReportTemplate(key=key, name_en=en, name_tr=tr, is_default=is_default, default_sections=sections))
    for key, en, tr, days in D.RETENTION_POLICIES:
        _upsert(db, RetentionPolicy, {"key": key}, {"name_en": en, "name_tr": tr, "retention_days": days})
    for d in DEFS:
        if d.secret or d.default is None:
            continue
        if db.get(ApplicationSetting, d.key) is None:
            db.add(ApplicationSetting(key=d.key, value=d.default, is_secret=False, admin_customized=False))


def run_seed(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('leadradar.seed'))"))
    seed_regions_countries(db)
    db.flush()
    tpl = seed_review_templates(db)
    profiles = seed_scoring(db)
    db.flush()
    seed_industries(db, tpl, profiles)
    seed_misc(db)
    db.flush()
    log.info("seed complete")
