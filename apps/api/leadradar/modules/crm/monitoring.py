"""Change detection for watchlisted companies.

Snapshots are normalized (content fingerprint ignores digits, ids, whitespace and cookie
text; numeric metrics use configurable thresholds) to avoid false alerts from dynamic
timestamps, rotating ads, cookie banners and measurement noise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.core.app_settings import get_setting
from leadradar.db.models import (
    ChangeEvent,
    Company,
    CompanySnapshot,
    CompanySource,
    TrackingDetection,
    WebsiteAudit,
)
from leadradar.db.session import session_scope
from leadradar.jobs.runtime import HandlerResult, JobContext, PermanentJobError, handler
from leadradar.modules.crm.notifications import notify


def build_snapshot(db: Session, company: Company) -> dict[str, Any]:
    audit = db.scalar(select(WebsiteAudit).where(WebsiteAudit.company_id == company.id,
                                                 WebsiteAudit.status.in_(["completed", "action_required"]))
                      .order_by(WebsiteAudit.created_at.desc()).limit(1))
    tracking: list[str] = []
    perf = None
    reachable = None
    fingerprint = None
    if audit is not None:
        tracking = sorted({t.technology for t in db.scalars(select(TrackingDetection).where(
            TrackingDetection.audit_id == audit.id, TrackingDetection.status == "detected"))})
        perf = ((audit.metrics or {}).get("lighthouse") or {}).get("scores", {}).get("performance")
        http = (audit.metrics or {}).get("http") or {}
        reachable = http.get("status") is not None and 200 <= int(http.get("status") or 0) < 400
        fingerprint = audit.content_fingerprint
    src = db.scalar(select(CompanySource).where(CompanySource.company_id == company.id)
                    .order_by(CompanySource.updated_at.desc()).limit(1))
    return {
        "website_url": company.website_url, "reachable": reachable, "content_fingerprint": fingerprint,
        "performance": perf, "tracking": tracking, "advertising": sorted(company.advertising_platforms or []),
        "lead_score": company.effective_lead_score, "confidence": company.confidence_score,
        "services": sorted(k for k, v in (company.service_scores or {}).items() if v.get("score", 0) >= 30),
        "source": {"name": company.name, "phone": company.phone, "address": company.address,
                   "source_ts": src.source_timestamp.isoformat() if src and src.source_timestamp else None},
    }


def diff_snapshots(before: dict[str, Any], after: dict[str, Any], score_threshold: int, perf_threshold: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(category: str, field: str, b: Any, a: Any, significance: str = "minor") -> None:
        events.append({"category": category, "field": field, "before": b, "after": a, "significance": significance})

    if before.get("website_url") != after.get("website_url"):
        add("website", "website_url", before.get("website_url"), after.get("website_url"), "major")
    if before.get("reachable") is not None and after.get("reachable") is not None and before["reachable"] != after["reachable"]:
        add("website", "availability", before["reachable"], after["reachable"], "major")
    if before.get("content_fingerprint") and after.get("content_fingerprint") and \
            before["content_fingerprint"] != after["content_fingerprint"]:
        add("website", "content", None, None, "minor")
    bp, ap = before.get("performance"), after.get("performance")
    if isinstance(bp, (int, float)) and isinstance(ap, (int, float)) and abs(ap - bp) >= perf_threshold:
        add("performance", "lighthouse_performance", bp, ap, "minor")
    for key, cat in (("tracking", "tracking"), ("advertising", "advertising"), ("services", "opportunities")):
        b, a = set(before.get(key) or []), set(after.get(key) or [])
        if b != a:
            add(cat, key, sorted(b), sorted(a), "major" if key == "advertising" and a - b else "minor")
    for key in ("lead_score", "confidence"):
        b, a = before.get(key), after.get(key)
        if isinstance(b, int) and isinstance(a, int) and abs(a - b) >= score_threshold:
            add("score", key, b, a, "major" if key == "lead_score" else "minor")
    bs, as_ = before.get("source") or {}, after.get("source") or {}
    for k in ("name", "phone", "address"):
        if bs.get(k) != as_.get(k) and bs.get(k) is not None:
            add("source", k, bs.get(k), as_.get(k))
    return events


def record_snapshot(db: Session, company: Company) -> list[ChangeEvent]:
    snap = build_snapshot(db, company)
    prev = db.scalar(select(CompanySnapshot).where(CompanySnapshot.company_id == company.id)
                     .order_by(CompanySnapshot.taken_at.desc()).limit(1))
    now = datetime.now(UTC)
    db.add(CompanySnapshot(company_id=company.id, data=snap, taken_at=now))
    created: list[ChangeEvent] = []
    if prev is not None:
        for e in diff_snapshots(prev.data, snap, int(get_setting(db, "monitoring.score_change_threshold")),
                                int(get_setting(db, "monitoring.performance_change_threshold"))):
            ev = ChangeEvent(company_id=company.id, detected_at=now, **e)
            db.add(ev)
            created.append(ev)
        if any(e.significance == "major" for e in created):
            notify(db, "change_detected", "notifications.changeDetected", {"company": company.name,
                   "count": len(created)}, link=f"/companies/{company.id}?tab=changes",
                   dedupe_key=f"change:{company.id}:{now.date()}")
    db.flush()
    return created


@handler("monitor_company")
def handle_monitor(ctx: JobContext) -> HandlerResult:
    from leadradar.modules.website_audit.engine import execute_audit

    cid = uuid.UUID(ctx.payload["company_id"])
    with session_scope() as db:
        company = db.get(Company, cid)
        if company is None:
            raise PermanentJobError("company missing")
        if not company.website_url:
            record_snapshot(db, company)
            return HandlerResult({"audited": False})
        audit = WebsiteAudit(company_id=cid, mode="quick", status="queued", start_url=company.website_url,
                             property_id=company.website_property_id, context={"force": True, "monitoring": True})
        db.add(audit)
        db.flush()
        audit_id = audit.id
    execute_audit(audit_id, lambda s: ctx.progress(s))
    with session_scope() as db:
        company = db.get(Company, cid)
        events = record_snapshot(db, company)  # type: ignore[arg-type]
    return HandlerResult({"changes": len(events)})
