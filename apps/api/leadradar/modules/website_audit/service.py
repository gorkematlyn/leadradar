"""Audit lifecycle: creation, job handlers, administrator review and finalization."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.db.models import (
    AuditFinding,
    Company,
    CrmActivity,
    Evidence,
    EvidenceBlob,
    Job,
    ReviewQuestion,
    ReviewResponse,
    WebsiteAudit,
)
from leadradar.db.session import session_scope
from leadradar.jobs import queue
from leadradar.jobs.runtime import FAILURE_HOOKS, HandlerResult, JobContext, handler

ANSWERS = {"yes", "no", "unknown", "not_applicable"}


def now() -> datetime:
    return datetime.now(UTC)


def create_audit(db: Session, company: Company, mode: str = "full", *, user_id: uuid.UUID | None = None,
                 force: bool = False, start_url: str | None = None, priority: int | None = None) -> tuple[WebsiteAudit, Job]:
    if mode not in ("full", "quick"):
        raise ValueError("mode must be full or quick")
    active = db.scalar(select(WebsiteAudit).where(WebsiteAudit.company_id == company.id,
                                                  WebsiteAudit.status.in_(["queued", "running"])))
    if active is not None and active.job_id:
        job = db.get(Job, active.job_id)
        if job is not None and job.status in ("queued", "running"):
            return active, job
    audit = WebsiteAudit(company_id=company.id, mode=mode, status="queued", start_url=start_url or company.website_url,
                         property_id=company.website_property_id, context={"force": force})
    db.add(audit)
    db.flush()
    key = f"property:{company.website_property_id}" if company.website_property_id else f"company:{company.id}"
    job = queue.enqueue(db, "website_audit" if mode == "full" else "quick_audit",
                        f"{'Website audit' if mode == 'full' else 'Quick audit'}: {company.name}",
                        {"audit_id": str(audit.id)}, idempotency_key=f"audit:{company.id}", concurrency_key=key,
                        company_id=company.id, created_by=user_id, priority=priority)
    audit.job_id = job.id
    company.analysis_status = "queued"
    db.flush()
    return audit, job


def _run(ctx: JobContext) -> HandlerResult:
    from leadradar.modules.website_audit.engine import execute_audit

    audit_id = uuid.UUID(ctx.payload["audit_id"])

    def progress(stage: str) -> None:
        ctx.progress(stage)
        ctx.raise_if_cancelled()

    out = execute_audit(audit_id, progress)
    return HandlerResult(out, waiting_review=out.get("status") == "action_required")


@handler("website_audit")
def handle_full(ctx: JobContext) -> HandlerResult:
    return _run(ctx)


@handler("quick_audit")
def handle_quick(ctx: JobContext) -> HandlerResult:
    return _run(ctx)


def _audit_failed(ctx: JobContext, outcome: str) -> None:
    with session_scope() as db:
        audit = db.get(WebsiteAudit, uuid.UUID(ctx.payload["audit_id"]))
        if audit is None:
            return
        audit.status = "cancelled" if outcome == "cancelled" else "failed"
        company = db.get(Company, audit.company_id)
        if company is not None:
            company.analysis_status = audit.status


FAILURE_HOOKS["website_audit"] = _audit_failed
FAILURE_HOOKS["quick_audit"] = _audit_failed


def review_questions_for(db: Session, company: Company) -> list[ReviewQuestion]:
    from leadradar.db.models import Industry, ReviewTemplate

    tpl_id = None
    if company.primary_industry_id:
        ind = db.get(Industry, company.primary_industry_id)
        tpl_id = ind.review_template_id if ind else None
    if tpl_id is None:
        tpl = db.scalar(select(ReviewTemplate).where(ReviewTemplate.is_default.is_(True)))
        tpl_id = tpl.id if tpl else None
    if tpl_id is None:
        return []
    return list(db.scalars(select(ReviewQuestion).where(ReviewQuestion.template_id == tpl_id,
                                                        ReviewQuestion.enabled.is_(True))
                           .order_by(ReviewQuestion.sort_order)))


def submit_review(db: Session, audit: WebsiteAudit, answers: list[dict[str, Any]], *, user_id: uuid.UUID | None,
                  finding_validations: dict[int, bool | None] | None = None, approve_evidence: list[uuid.UUID] | None = None,
                  finalize: bool = True) -> dict[str, Any]:
    if audit.status not in ("action_required", "completed"):
        raise ValueError("audit is not awaiting review")
    company = db.get(Company, audit.company_id)
    assert company is not None
    valid_keys = {q.key for q in review_questions_for(db, company)}
    for a in answers:
        key, answer = a["question_key"], a["answer"]
        if key not in valid_keys or answer not in ANSWERS:
            raise ValueError(f"invalid answer for {key}")
        row = db.scalar(select(ReviewResponse).where(ReviewResponse.audit_id == audit.id,
                                                     ReviewResponse.question_key == key))
        if row is None:
            row = ReviewResponse(audit_id=audit.id, question_key=key, answer=answer)
            db.add(row)
        row.answer = answer
        row.note = (a.get("note") or None)
        row.user_id = user_id
    for fid, valid in (finding_validations or {}).items():
        f = db.get(AuditFinding, int(fid))
        if f is not None and f.audit_id == audit.id:
            f.admin_validated = valid
    for eid in approve_evidence or []:
        ev = db.get(Evidence, eid)
        if ev is not None and ev.audit_id == audit.id:
            ev.approved_for_reports = True
            if ev.blob_id:
                blob = db.get(EvidenceBlob, ev.blob_id)
                if blob:
                    blob.pinned = True
    db.flush()
    result: dict[str, Any] = {"saved": True}
    if finalize:
        audit.status = "completed"
        audit.completed_at = now()
        audit.reviewed_by = user_id
        company.analysis_status = "completed"
        if audit.job_id:
            job = db.get(Job, audit.job_id)
            if job is not None and job.status == "waiting_review":
                job.status = "completed"
                job.finished_at = now()
        db.flush()
        from leadradar.modules.scoring.service import score_company

        result["score"] = score_company(db, company, stage="final", audit=audit)
        db.add(CrmActivity(company_id=company.id, kind="note", title="Audit review completed",
                           data={"audit_id": str(audit.id), "score": result["score"]["score"]},
                           occurred_at=now(), user_id=user_id))
    return result


def verify_no_website(db: Session, company: Company, user_id: uuid.UUID | None, absent: bool) -> None:
    """Manual website verification (the only way a company becomes 'verified_absent')."""
    company.website_status = "verified_absent" if absent else ("verified" if company.website_url else "unverified")
    fs = dict(company.field_sources or {})
    fs["website_status"] = {"source": "manual", "at": now().isoformat(), "confirmed": True}
    company.field_sources = fs
    company.last_verified_at = now()
    db.add(CrmActivity(company_id=company.id, kind="note", title="Website verification",
                       body="Verified: no website" if absent else "Verified: website exists", occurred_at=now(),
                       user_id=user_id))
    db.flush()
