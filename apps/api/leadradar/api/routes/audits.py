from __future__ import annotations

import uuid
from typing import Literal

import nh3
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from leadradar.api.deps import current_user
from leadradar.api.routes.companies import get_company
from leadradar.db.models import (
    AuditFinding,
    AuditRule,
    Company,
    Evidence,
    EvidenceBlob,
    Industry,
    ReviewResponse,
    TrackingDetection,
    User,
    WebsiteAudit,
)
from leadradar.db.session import get_db
from leadradar.modules.website_audit.service import create_audit, review_questions_for, submit_review

router = APIRouter(tags=["audits"])


class StartAuditIn(BaseModel):
    mode: Literal["quick", "full"] = "full"
    force: bool = False


@router.post("/companies/{company_id}/audits")
def start_audit(company_id: uuid.UUID, body: StartAuditIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    c = get_company(db, company_id)
    if not c.website_url:
        raise HTTPException(400, "no_website")
    audit, job = create_audit(db, c, body.mode, user_id=user.id, force=body.force, priority=20)
    return {"audit_id": str(audit.id), "job_id": str(job.id)}


@router.post("/companies/{company_id}/run-all")
def run_all(company_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    from leadradar.modules.advertising.service import start_research

    c = get_company(db, company_id)
    out: dict = {}
    if c.website_url:
        audit, job = create_audit(db, c, "full", user_id=user.id, priority=20)
        out["audit_id"], out["job_id"] = str(audit.id), str(job.id)
    out["ad_runs"] = len(start_research(db, c, None, user.id))
    return out


@router.get("/companies/{company_id}/audits")
def list_audits(company_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    rows = db.scalars(select(WebsiteAudit).where(WebsiteAudit.company_id == company_id)
                      .order_by(WebsiteAudit.created_at.desc()).limit(50))
    return [_audit_summary(a) for a in rows]


def _audit_summary(a: WebsiteAudit) -> dict:
    return {"id": str(a.id), "mode": a.mode, "status": a.status, "start_url": a.start_url, "final_url": a.final_url,
            "created_at": a.created_at, "automated_completed_at": a.automated_completed_at,
            "completed_at": a.completed_at, "reused_from": str(a.reused_from_audit_id) if a.reused_from_audit_id else None,
            "error": a.error, "job_id": str(a.job_id) if a.job_id else None}


@router.get("/audits/{audit_id}")
def audit_detail(audit_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    a = db.get(WebsiteAudit, audit_id)
    if a is None:
        raise HTTPException(404, "not_found")
    company = db.get(Company, a.company_id)
    rules = {r.key: r for r in db.scalars(select(AuditRule))}
    findings = db.scalars(select(AuditFinding).where(AuditFinding.audit_id == a.id).order_by(AuditFinding.rule_key)).all()
    ev_counts = dict(db.execute(select(Evidence.finding_id, func.count()).where(Evidence.audit_id == a.id)
                                .group_by(Evidence.finding_id)).all())
    industry = db.get(Industry, company.primary_industry_id) if company and company.primary_industry_id else None
    out = _audit_summary(a)
    out.update({
        "company": {"id": str(company.id), "name": company.name, "website": company.website_url,
                    "industry": industry.key if industry else None} if company else None,
        "pages_audited": a.pages_audited, "metrics": a.metrics, "context": a.context, "technologies": a.technologies,
        "rule_versions": a.rule_versions,
        "findings": [{
            "id": f.id, "rule_key": f.rule_key, "result": f.result, "page_url": f.page_url, "value": f.value,
            "confidence": f.confidence, "params": f.message_params, "admin_validated": f.admin_validated,
            "rule_version": f.rule_version, "evidence_count": ev_counts.get(f.id, 0),
            "category": rules[f.rule_key].category if f.rule_key in rules else None,
            "severity": rules[f.rule_key].severity if f.rule_key in rules else None,
            "title_en": rules[f.rule_key].title_en if f.rule_key in rules else f.rule_key,
            "title_tr": rules[f.rule_key].title_tr if f.rule_key in rules else f.rule_key,
            "description_en": rules[f.rule_key].description_en if f.rule_key in rules else "",
            "description_tr": rules[f.rule_key].description_tr if f.rule_key in rules else "",
            "recommendation_en": rules[f.rule_key].recommendation_en if f.rule_key in rules else "",
            "recommendation_tr": rules[f.rule_key].recommendation_tr if f.rule_key in rules else "",
            "heuristic": rules[f.rule_key].category == "visual" if f.rule_key in rules else False,
        } for f in findings],
        "tracking": [{"technology": t.technology, "status": t.status, "consent_state": t.consent_state,
                      "methods": t.methods, "evidence_urls": t.evidence_urls, "identifiers": t.identifiers_redacted,
                      "confidence": t.confidence, "limitations": t.limitations, "page_url": t.page_url,
                      "detected_at": t.detected_at}
                     for t in db.scalars(select(TrackingDetection).where(TrackingDetection.audit_id == a.id)
                                         .order_by(TrackingDetection.technology, TrackingDetection.consent_state))],
        "screenshots": [{"id": str(e.id), "label": e.label, "viewport": e.viewport, "blob_id": str(e.blob_id),
                         "approved_for_reports": e.approved_for_reports, "width": e.data.get("width")}
                        for e in db.scalars(select(Evidence).where(Evidence.audit_id == a.id, Evidence.kind == "screenshot"))],
        "responses": {r.question_key: {"answer": r.answer, "note": r.note}
                      for r in db.scalars(select(ReviewResponse).where(ReviewResponse.audit_id == a.id))},
        "questions": [{"key": q.key, "text_en": q.text_en, "text_tr": q.text_tr}
                      for q in (review_questions_for(db, company) if company else [])],
    })
    return out


@router.get("/evidence")
def evidence_list(company_id: uuid.UUID, audit_id: uuid.UUID | None = None, finding_id: int | None = None,
                  db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    q = select(Evidence).where(Evidence.company_id == company_id)
    if audit_id:
        q = q.where(Evidence.audit_id == audit_id)
    if finding_id is not None:
        q = q.where(Evidence.finding_id == finding_id)
    out = []
    for e in db.scalars(q.order_by(Evidence.created_at.desc()).limit(500)):
        data = dict(e.data or {})
        if "html" in data and isinstance(data["html"], str):
            # External HTML is shown as sanitized text-like markup only; scripts/handlers are stripped.
            data["html"] = nh3.clean(data["html"], tags=set(), attributes={})[:2000]
        out.append({"id": str(e.id), "kind": e.kind, "label": e.label, "source_url": e.source_url,
                    "selector": e.selector, "data": data, "blob_id": str(e.blob_id) if e.blob_id else None,
                    "detection_method": e.detection_method, "rule_version": e.rule_version,
                    "confidence": e.confidence, "limitations": e.limitations, "viewport": e.viewport,
                    "audit_id": str(e.audit_id) if e.audit_id else None, "finding_id": e.finding_id,
                    "approved_for_reports": e.approved_for_reports, "created_at": e.created_at})
    return out


@router.get("/blobs/{blob_id}")
def blob(blob_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> Response:
    b = db.get(EvidenceBlob, blob_id)
    if b is None:
        raise HTTPException(404, "not_found")
    if not b.content_type.startswith(("image/", "application/pdf")):
        raise HTTPException(415, "unsupported")
    return Response(b.data, media_type=b.content_type,
                    headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": "inline",
                             "X-Content-Type-Options": "nosniff"})


class ApproveEvidenceIn(BaseModel):
    approved: bool


@router.post("/evidence/{evidence_id}/approve")
def approve_evidence(evidence_id: uuid.UUID, body: ApproveEvidenceIn, db: Session = Depends(get_db),
                     _: User = Depends(current_user)) -> dict:
    e = db.get(Evidence, evidence_id)
    if e is None:
        raise HTTPException(404, "not_found")
    e.approved_for_reports = body.approved
    if e.blob_id and body.approved:
        b = db.get(EvidenceBlob, e.blob_id)
        if b:
            b.pinned = True
    return {"ok": True}


@router.get("/review-queue")
def review_queue(db: Session = Depends(get_db), _: User = Depends(current_user), limit: int = Query(100, le=500)) -> list[dict]:
    rows = db.execute(select(WebsiteAudit, Company).join(Company, Company.id == WebsiteAudit.company_id)
                      .where(WebsiteAudit.status == "action_required", Company.deleted_at.is_(None))
                      .order_by(WebsiteAudit.automated_completed_at.asc().nulls_last()).limit(limit)).all()
    return [{"audit_id": str(a.id), "company_id": str(c.id), "company": c.name, "website": c.website_url,
             "country": c.country_iso2, "preliminary_score": c.preliminary_lead_score, "confidence": c.confidence_score,
             "automated_completed_at": a.automated_completed_at, "mode": a.mode, "error": a.error} for a, c in rows]


class AnswerIn(BaseModel):
    question_key: str = Field(max_length=64)
    answer: Literal["yes", "no", "unknown", "not_applicable"]
    note: str | None = Field(default=None, max_length=4000)


class ReviewIn(BaseModel):
    answers: list[AnswerIn] = Field(default_factory=list, max_length=50)
    finding_validations: dict[int, bool | None] = Field(default_factory=dict)
    approve_evidence: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    finalize: bool = True


@router.post("/audits/{audit_id}/review")
def review(audit_id: uuid.UUID, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    a = db.get(WebsiteAudit, audit_id)
    if a is None:
        raise HTTPException(404, "not_found")
    try:
        return submit_review(db, a, [x.model_dump() for x in body.answers], user_id=user.id,
                             finding_validations=body.finding_validations, approve_evidence=body.approve_evidence,
                             finalize=body.finalize)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/audit-rules")
def audit_rules(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"key": r.key, "category": r.category, "severity": r.severity, "title_en": r.title_en, "title_tr": r.title_tr,
             "description_en": r.description_en, "description_tr": r.description_tr, "enabled": r.enabled,
             "applicable_industries": r.applicable_industries, "service_categories": r.service_categories,
             "emits_signals": r.emits_signals, "recommendation_en": r.recommendation_en,
             "recommendation_tr": r.recommendation_tr, "requires_browser": r.requires_browser,
             "public_safe": r.public_safe, "version": r.version, "evidence_requirements": r.evidence_requirements}
            for r in db.scalars(select(AuditRule).order_by(AuditRule.category, AuditRule.key))]


class AuditRulePatch(BaseModel):
    enabled: bool | None = None
    severity: Literal["info", "low", "medium", "high", "critical"] | None = None
    applicable_industries: list[str] | None = None
    recommendation_en: str | None = Field(default=None, max_length=2000)
    recommendation_tr: str | None = Field(default=None, max_length=2000)
    public_safe: bool | None = None


@router.patch("/audit-rules/{key}")
def patch_audit_rule(key: str, body: AuditRulePatch, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.get(AuditRule, key)
    if r is None:
        raise HTTPException(404, "not_found")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    r.version += 1
    r.admin_customized = True
    return {"ok": True, "version": r.version}
