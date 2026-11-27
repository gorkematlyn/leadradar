from __future__ import annotations

import shutil
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.orm import Session, aliased

from leadradar.api.deps import current_user
from leadradar.core.activity import record_activity
from leadradar.core.app_settings import DEF_BY_KEY, get_setting, public_settings_view, set_setting
from leadradar.core.config import get_settings
from leadradar.db.models import (
    ActivityLog,
    ApifyActorConfig,
    CampaignRun,
    Company,
    CrmActivity,
    CrmStatus,
    ImportRun,
    Job,
    JobAttempt,
    JobLog,
    Notification,
    ProviderUsage,
    RetentionPolicy,
    ReviewQuestion,
    ReviewTemplate,
    SavedCampaign,
    SavedFilter,
    ScoringProfile,
    ScoringRule,
    ServiceRule,
    SuppressionEntry,
    Tag,
    User,
    WebsiteAudit,
    WorkerHeartbeat,
)
from leadradar.db.session import get_db
from leadradar.jobs import queue
from leadradar.modules.crm.filters import CompanyFilter

router = APIRouter(tags=["system"])


def now() -> datetime:
    return datetime.now(UTC)


# --- Dashboard ------------------------------------------------------------------------------

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    base = select(func.count()).select_from(Company).where(Company.merged_into_id.is_(None), Company.archived.is_(False),
                                                          Company.deleted_at.is_(None))
    total = db.scalar(base)
    qualified = db.scalar(base.where(Company.crm_status.in_(["qualified", "shortlisted", "contacted", "replied",
                                                             "meeting", "proposal_sent"])))
    high = db.scalar(base.where(Company.score_classification == "high_priority", Company.do_not_contact.is_(False)))
    review = db.scalar(select(func.count()).select_from(WebsiteAudit).join(Company, Company.id == WebsiteAudit.company_id)
                       .where(WebsiteAudit.status == "action_required", Company.deleted_at.is_(None)))
    completed = db.scalar(select(func.count()).select_from(WebsiteAudit).where(WebsiteAudit.status == "completed"))
    running = db.scalar(select(func.count()).select_from(Job).where(Job.status == "running"))
    queued = db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued"))
    since = now() - timedelta(days=1)
    cleared = get_setting(db, "ui.warnings_cleared_at")
    if cleared:
        try:
            since = max(since, datetime.fromisoformat(str(cleared)))
        except ValueError:
            pass
    failed_24h = db.scalar(select(func.count()).select_from(Job).where(Job.status.in_(["failed", "dead"]),
                                                                        Job.finished_at >= since))
    top = db.scalars(select(Company).where(Company.merged_into_id.is_(None), Company.archived.is_(False), Company.deleted_at.is_(None),
                                           Company.do_not_contact.is_(False), Company.effective_lead_score.isnot(None))
                     .order_by(Company.effective_lead_score.desc(), Company.confidence_score.desc().nulls_last()).limit(8)).all()
    recent = db.execute(select(CrmActivity, Company.name).join(Company, Company.id == CrmActivity.company_id)
                        .order_by(CrmActivity.occurred_at.desc()).limit(10)).all()
    warnings = [{"id": str(n.id), "kind": n.kind, "message_key": n.message_key, "params": n.params,
                 "severity": n.severity, "link": n.link, "created_at": n.created_at}
                for n in db.scalars(select(Notification).where(Notification.severity.in_(["warning", "error"]),
                                                               Notification.read_at.is_(None))
                                    .order_by(Notification.created_at.desc()).limit(5))]
    return {
        "metrics": {"total_companies": total, "qualified_leads": qualified, "high_priority": high,
                    "requires_review": review, "completed_audits": completed, "running_jobs": running,
                    "queued_jobs": queued, "failed_jobs_24h": failed_24h},
        "top_opportunities": [{"id": str(c.id), "name": c.name, "score": c.effective_lead_score,
                               "confidence": c.confidence_score, "country": c.country_iso2,
                               "classification": c.score_classification} for c in top],
        "recent_activity": [{"company": name, "company_id": str(a.company_id), "kind": a.kind, "title": a.title,
                             "occurred_at": a.occurred_at} for a, name in recent],
        "warnings": warnings,
    }


@router.post("/dashboard/warnings/clear")
def clear_warnings(db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Dismiss the Overview warnings: warning/error notifications are marked read and the
    failed-jobs counter restarts from now. Nothing is deleted."""
    db.execute(update(Notification).where(Notification.severity.in_(["warning", "error"]), Notification.read_at.is_(None),
                                          or_(Notification.user_id.is_(None), Notification.user_id == user.id))
               .values(read_at=now()))
    set_setting(db, "ui.warnings_cleared_at", now().isoformat(), admin=False)
    return {"ok": True}


# --- Jobs ---------------------------------------------------------------------------------------

FINISHED = ("completed", "failed", "dead", "cancelled")
IMPORT_TYPES = ("geofabrik_country_import", "geofabrik_extract_import")


def resolve_job_notifications(db: Session, job_ids: list[uuid.UUID]) -> None:
    """A failure notification disappears once its job is retried, cancelled or deleted."""
    if not job_ids:
        return
    keys = [f"{prefix}:{jid}" for jid in job_ids for prefix in ("job_failed", "import_failed")]
    db.execute(delete(Notification).where(Notification.dedupe_key.in_(keys)))


def _sync_import_countries(db: Session, jobs_: list[Job]) -> None:
    from leadradar.modules.discovery.status import sync_country_status

    for c in {str((j.payload or {}).get("country", "")).upper() for j in jobs_ if j.type in IMPORT_TYPES}:
        if c:
            sync_country_status(db, c)

def job_view(j: Job) -> dict:
    return {"id": str(j.id), "type": j.type, "name": j.name, "queue": j.queue, "status": j.status,
            "priority": j.priority, "stage": j.stage, "processed": j.processed_count, "total": j.total_count,
            "attempts": j.attempts, "max_attempts": j.max_attempts, "error": j.error, "created_at": j.created_at,
            "started_at": j.started_at, "finished_at": j.finished_at, "heartbeat_at": j.heartbeat_at,
            "run_at": j.run_at, "locked_by": j.locked_by, "cancel_requested": j.cancel_requested,
            "company_id": str(j.company_id) if j.company_id else None, "parent_id": str(j.parent_id) if j.parent_id else None,
            "resource_class": j.resource_class}


@router.get("/jobs")
def jobs(status: list[str] = Query(default=[]), type: str | None = None, page: int = Query(1, ge=1),
         page_size: int = Query(50, le=200), db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    q = select(Job)
    if status:
        q = q.where(Job.status.in_(status))
    if type:
        q = q.where(Job.type == type)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    order = [(Job.status == "running").desc(), Job.created_at.desc()]
    rows = db.scalars(q.order_by(*order).offset((page - 1) * page_size).limit(page_size)).all()
    counts = dict(db.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    return {"total": total, "page": page, "page_size": page_size, "counts": counts, "items": [job_view(j) for j in rows]}


class JobDeleteIn(BaseModel):
    statuses: list[Literal["completed", "failed", "dead", "cancelled"]] = Field(default_factory=lambda: list(FINISHED))
    ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)


@router.post("/jobs/delete")
def delete_jobs(body: JobDeleteIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Delete finished job records (with their logs). Queued, running, paused and
    waiting-for-review jobs are never deleted."""
    # A finished job whose sub-jobs are still running is kept: e.g. a country import's
    # planning job, which progress tracking and per-country controls rely on.
    child = aliased(Job)
    has_active_children = select(child.id).where(child.parent_id == Job.id,
                                                 child.status.in_(["queued", "running", "paused"])).exists()
    q = select(Job).where(Job.status.in_(body.statuses or list(FINISHED)), ~has_active_children)
    if body.ids:
        q = q.where(Job.id.in_(body.ids))
    rows = db.scalars(q).all()
    ids = [j.id for j in rows]
    resolve_job_notifications(db, ids)
    for i in range(0, len(ids), 500):
        db.execute(delete(Job).where(Job.id.in_(ids[i:i + 500])))
    db.flush()
    _sync_import_countries(db, list(rows))
    record_activity(db, "data", "jobs_deleted", user_id=user.id, details={"count": len(ids), "statuses": body.statuses})
    return {"deleted": len(ids)}


@router.get("/jobs/{job_id}")
def job_detail(job_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "not_found")
    out = job_view(j)
    out["payload"] = {k: v for k, v in (j.payload or {}).items() if k != "content"}
    out["result"] = j.result
    out["checkpoint"] = j.checkpoint
    out["logs"] = [{"level": log.level, "message": log.message, "data": log.data, "at": log.created_at}
                   for log in db.scalars(select(JobLog).where(JobLog.job_id == j.id).order_by(JobLog.created_at.desc()).limit(200))]
    out["attempts_detail"] = [{"attempt": a.attempt, "worker": a.worker, "started_at": a.started_at,
                               "finished_at": a.finished_at, "outcome": a.outcome, "error": a.error}
                              for a in db.scalars(select(JobAttempt).where(JobAttempt.job_id == j.id).order_by(JobAttempt.attempt))]
    out["children"] = [job_view(c) for c in db.scalars(select(Job).where(Job.parent_id == j.id).order_by(Job.created_at))]
    return out


class JobAction(BaseModel):
    action: Literal["cancel", "retry", "pause", "resume"]


@router.post("/jobs/{job_id}/action")
def job_action(job_id: uuid.UUID, body: JobAction, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    j = db.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "not_found")
    from leadradar.modules.discovery.status import on_job_cancelled, on_job_retried

    touched = [j]
    getattr(queue, body.action)(db, j)
    if body.action == "cancel":
        on_job_cancelled(db, j)
        for child in db.scalars(select(Job).where(Job.parent_id == j.id, Job.status.in_(["queued", "paused", "running"]))):
            queue.cancel(db, child)
            on_job_cancelled(db, child)
            touched.append(child)
    elif body.action == "retry":
        on_job_retried(db, j)
    if body.action in ("cancel", "retry"):
        resolve_job_notifications(db, [x.id for x in touched])
    _sync_import_countries(db, touched)
    queue.add_log(db, j.id, "info", f"{body.action} requested by administrator")
    record_activity(db, "data", f"job_{body.action}", user_id=user.id, entity_type="job", entity_id=j.id)
    return job_view(j)


# --- Notifications --------------------------------------------------------------------------

@router.get("/notifications")
def notifications(unread_only: bool = False, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    q = select(Notification).where(or_(Notification.user_id.is_(None), Notification.user_id == user.id))
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = db.scalars(q.order_by(Notification.created_at.desc()).limit(100)).all()
    unread = db.scalar(select(func.count()).select_from(Notification).where(
        or_(Notification.user_id.is_(None), Notification.user_id == user.id), Notification.read_at.is_(None)))
    return {"unread": unread, "items": [{"id": str(n.id), "kind": n.kind, "severity": n.severity,
                                         "message_key": n.message_key, "params": n.params, "link": n.link,
                                         "read": n.read_at is not None, "created_at": n.created_at} for n in rows]}


class ReadIn(BaseModel):
    ids: list[uuid.UUID] | None = None
    read: bool = True


class NotificationDeleteIn(BaseModel):
    ids: list[uuid.UUID] | None = None  # None = all


@router.post("/notifications/delete")
def delete_notifications(body: NotificationDeleteIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    q = delete(Notification).where(or_(Notification.user_id.is_(None), Notification.user_id == user.id))
    if body.ids:
        q = q.where(Notification.id.in_(body.ids))
    res = db.execute(q)
    return {"deleted": res.rowcount or 0}


@router.post("/notifications/read")
def mark_read(body: ReadIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    q = update(Notification).where(or_(Notification.user_id.is_(None), Notification.user_id == user.id))
    if body.ids:
        q = q.where(Notification.id.in_(body.ids))
    db.execute(q.values(read_at=now() if body.read else None))
    return {"ok": True}


# --- Settings -------------------------------------------------------------------------------------

@router.get("/settings")
def get_app_settings(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    return public_settings_view(db)


class SettingsIn(BaseModel):
    values: dict[str, Any]


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    changed = []
    for key, value in body.values.items():
        d = DEF_BY_KEY.get(key)
        if d is None or d.group == "internal":
            raise HTTPException(400, f"unknown_setting:{key}")
        try:
            set_setting(db, key, value)
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, f"invalid_value:{key}:{exc}") from exc
        changed.append(key)
    record_activity(db, "settings", "settings_updated", user_id=user.id, details={"keys": changed})
    return public_settings_view(db)


@router.get("/retention-policies")
def retention(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"key": p.key, "name_en": p.name_en, "name_tr": p.name_tr, "retention_days": p.retention_days,
             "enabled": p.enabled} for p in db.scalars(select(RetentionPolicy).order_by(RetentionPolicy.key))]


class RetentionIn(BaseModel):
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    enabled: bool | None = None


@router.patch("/retention-policies/{key}")
def patch_retention(key: str, body: RetentionIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    p = db.get(RetentionPolicy, key)
    if p is None:
        raise HTTPException(404, "not_found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(p, k, v)
    p.admin_customized = True
    record_activity(db, "settings", "retention_updated", user_id=user.id, entity_id=key, details=data)
    return {"ok": True}


@router.post("/maintenance/retention")
def run_retention(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    j = queue.enqueue(db, "retention_cleanup", "Retention cleanup (manual)", {}, idempotency_key="retention_cleanup")
    return {"job_id": str(j.id)}


# --- Health ---------------------------------------------------------------------------------------

@router.get("/health/system")
def system_health(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    vm = psutil.virtual_memory()
    try:
        disk = shutil.disk_usage(get_settings().worker_tmp_dir)
    except FileNotFoundError:
        disk = shutil.disk_usage("/")
    db_size = db.scalar(text("SELECT pg_database_size(current_database())"))
    tables = db.execute(text(
        "SELECT relname, pg_total_relation_size(relid) FROM pg_catalog.pg_statio_user_tables "
        "ORDER BY pg_total_relation_size(relid) DESC LIMIT 8")).all()
    workers = db.scalars(select(WorkerHeartbeat).where(WorkerHeartbeat.last_seen_at >= now() - timedelta(minutes=5))).all()
    last_import = db.scalar(select(func.max(ImportRun.finished_at)).where(ImportRun.status == "completed"))
    last_audit = db.scalar(select(func.max(WebsiteAudit.automated_completed_at)))
    errors = db.scalars(select(Job).where(Job.status.in_(["failed", "dead"])).order_by(Job.finished_at.desc().nulls_last()).limit(10)).all()
    return {
        "note": "API container view; worker containers report memory in their heartbeat.",
        "cpu_percent": psutil.cpu_percent(interval=0.1), "cpu_count": psutil.cpu_count(),
        "memory": {"total": vm.total, "used": vm.used, "percent": vm.percent},
        "disk": {"total": disk.total, "free": disk.free, "used": disk.used},
        "database": {"available": True, "size_bytes": db_size, "largest_tables": [{"table": t, "bytes": b} for t, b in tables]},
        "workers": [{"id": w.worker_id.split(":")[0] + ":" + w.worker_id.split(":")[-1], "queues": w.queues,
                     "last_seen_at": w.last_seen_at, "running_jobs": w.running_jobs, "stats": w.stats} for w in workers],
        "pending_jobs": db.scalar(select(func.count()).select_from(Job).where(Job.status == "queued")),
        "recent_errors": [{"id": str(j.id), "name": j.name, "error": (j.error or "")[:300], "at": j.finished_at} for j in errors],
        "last_successful_import": last_import, "last_successful_audit": last_audit,
    }


# --- Tags ------------------------------------------------------------------------------------------

class TagIn(BaseModel):
    name_en: str = Field(min_length=1, max_length=64)
    name_tr: str = Field(min_length=1, max_length=64)
    description_en: str | None = Field(default=None, max_length=300)
    description_tr: str | None = Field(default=None, max_length=300)
    color: Literal["neutral", "lime", "blue", "amber", "red", "violet", "teal"] = "neutral"


def tag_view(t: Tag, count: int | None = None) -> dict:
    out = {"id": str(t.id), "name_en": t.name_en, "name_tr": t.name_tr, "description_en": t.description_en,
           "description_tr": t.description_tr, "color": t.color}
    if count is not None:
        out["count"] = count
    return out


def _check_tag_names(db: Session, body: TagIn, exclude: uuid.UUID | None = None) -> None:
    for col, value in ((Tag.name_en, body.name_en), (Tag.name_tr, body.name_tr)):
        q = select(Tag.id).where(func.lower(col) == value.strip().lower())
        if exclude:
            q = q.where(Tag.id != exclude)
        if db.scalar(q):
            raise HTTPException(409, "exists")


@router.get("/tags")
def tags(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    from leadradar.db.models import CompanyTag

    counts = dict(db.execute(select(CompanyTag.tag_id, func.count()).group_by(CompanyTag.tag_id)).all())
    return [tag_view(t, counts.get(t.id, 0)) for t in db.scalars(select(Tag).order_by(Tag.name_en))]


@router.post("/tags")
def create_tag(body: TagIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    _check_tag_names(db, body)
    t = Tag(name_en=body.name_en.strip(), name_tr=body.name_tr.strip(), description_en=body.description_en or None,
            description_tr=body.description_tr or None, color=body.color)
    db.add(t)
    db.flush()
    return {"id": str(t.id)}


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: uuid.UUID, body: TagIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    t = db.get(Tag, tag_id)
    if t is None:
        raise HTTPException(404, "not_found")
    _check_tag_names(db, body, exclude=t.id)
    t.name_en, t.name_tr = body.name_en.strip(), body.name_tr.strip()
    t.description_en, t.description_tr, t.color = body.description_en or None, body.description_tr or None, body.color
    return {"ok": True}


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    t = db.get(Tag, tag_id)
    if t:
        db.delete(t)
    return {"ok": True}


# --- Saved filters --------------------------------------------------------------------------------

class SavedFilterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    filters: CompanyFilter
    is_pinned: bool = False


@router.get("/saved-filters")
def saved_filters(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"id": str(f.id), "name": f.name, "description": f.description, "filters": f.filters, "is_pinned": f.is_pinned,
             "updated_at": f.updated_at} for f in db.scalars(select(SavedFilter).order_by(SavedFilter.is_pinned.desc(), SavedFilter.name))]


@router.post("/saved-filters")
def create_saved_filter(body: SavedFilterIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    f = SavedFilter(name=body.name, description=body.description, filters=body.filters.model_dump(mode="json"),
                    is_pinned=body.is_pinned, user_id=user.id)
    db.add(f)
    db.flush()
    return {"id": str(f.id)}


@router.put("/saved-filters/{fid}")
def update_saved_filter(fid: uuid.UUID, body: SavedFilterIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    f = db.get(SavedFilter, fid)
    if f is None:
        raise HTTPException(404, "not_found")
    f.name, f.description, f.filters, f.is_pinned = body.name, body.description, body.filters.model_dump(mode="json"), body.is_pinned
    return {"ok": True}


@router.delete("/saved-filters/{fid}")
def delete_saved_filter(fid: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    f = db.get(SavedFilter, fid)
    if f:
        db.delete(f)
    return {"ok": True}


# --- Saved campaigns ----------------------------------------------------------------------------

class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    discovery_sources: list[Literal["geofabrik", "csv", "apify", "manual"]] = Field(default_factory=lambda: ["geofabrik"])
    actions: dict[str, Any] = Field(default_factory=dict)
    audit_rules: list[str] = Field(default_factory=list)
    scoring_profile_id: uuid.UUID | None = None
    record_limit: int = Field(default=50, ge=1, le=500)
    schedule_interval_hours: int | None = Field(default=None, ge=6, le=24 * 90)
    enabled: bool = True


def campaign_view(db: Session, c: SavedCampaign) -> dict:
    runs = db.scalars(select(CampaignRun).where(CampaignRun.campaign_id == c.id).order_by(CampaignRun.created_at.desc()).limit(10))
    return {"id": str(c.id), "name": c.name, "regions": c.regions, "countries": c.countries, "industries": c.industries,
            "cities": c.cities, "discovery_sources": c.discovery_sources, "actions": c.actions, "audit_rules": c.audit_rules,
            "scoring_profile_id": str(c.scoring_profile_id) if c.scoring_profile_id else None,
            "record_limit": c.record_limit, "schedule_interval_hours": c.schedule_interval_hours, "enabled": c.enabled,
            "last_run_at": c.last_run_at, "next_run_at": c.next_run_at,
            "runs": [{"id": str(r.id), "status": r.status, "trigger": r.trigger, "stats": r.stats, "created_at": r.created_at,
                      "finished_at": r.finished_at} for r in runs]}


def _clean_actions(a: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if a.get("import"):
        out["import"] = True
    if a.get("audit") in ("quick", "full"):
        out["audit"] = a["audit"]
    if a.get("ads"):
        out["ads"] = True
        if isinstance(a.get("ad_platforms"), list):
            out["ad_platforms"] = [str(x) for x in a["ad_platforms"]][:10]
    return out


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [campaign_view(db, c) for c in db.scalars(select(SavedCampaign).order_by(SavedCampaign.name))]


@router.post("/campaigns")
def create_campaign(body: CampaignIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    data = body.model_dump()
    data["actions"] = _clean_actions(data["actions"])
    c = SavedCampaign(**data)
    if c.schedule_interval_hours:
        c.next_run_at = now() + timedelta(hours=c.schedule_interval_hours)
    db.add(c)
    db.flush()
    return campaign_view(db, c)


@router.put("/campaigns/{cid}")
def update_campaign(cid: uuid.UUID, body: CampaignIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    c = db.get(SavedCampaign, cid)
    if c is None:
        raise HTTPException(404, "not_found")
    data = body.model_dump()
    data["actions"] = _clean_actions(data["actions"])
    for k, v in data.items():
        setattr(c, k, v)
    c.next_run_at = now() + timedelta(hours=c.schedule_interval_hours) if c.schedule_interval_hours else None
    return campaign_view(db, c)


@router.post("/campaigns/{cid}/run")
def run_campaign(cid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    c = db.get(SavedCampaign, cid)
    if c is None:
        raise HTTPException(404, "not_found")
    # The idempotency key prevents overlapping duplicate runs.
    j = queue.enqueue(db, "campaign_run", f"Campaign: {c.name}", {"campaign_id": str(c.id), "trigger": "manual"},
                      idempotency_key=f"campaign:{c.id}", created_by=user.id)
    return {"job_id": str(j.id)}


@router.delete("/campaigns/{cid}")
def delete_campaign(cid: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    c = db.get(SavedCampaign, cid)
    if c:
        db.delete(c)
    return {"ok": True}


# --- Suppression (Do Not Contact) -------------------------------------------------------------

class SuppressionIn(BaseModel):
    kind: Literal["company", "domain", "email", "phone", "source"]
    value: str = Field(min_length=1, max_length=400)
    reason: str | None = Field(default=None, max_length=400)


@router.get("/suppression")
def suppression(include_removed: bool = False, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    q = select(SuppressionEntry).order_by(SuppressionEntry.created_at.desc()).limit(2000)
    if not include_removed:
        q = q.where(SuppressionEntry.removed_at.is_(None))
    return [{"id": str(e.id), "kind": e.kind, "value": e.value, "reason": e.reason,
             "company_id": str(e.company_id) if e.company_id else None, "created_at": e.created_at,
             "removed_at": e.removed_at, "removal_reason": e.removal_reason} for e in db.scalars(q)]


@router.post("/suppression")
def add_suppression(body: SuppressionIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    from leadradar.modules.crm.suppression import add_entry

    e = add_entry(db, body.kind, body.value, body.reason, user.id)
    record_activity(db, "data", "suppression_added", user_id=user.id, entity_type="suppression", entity_id=e.id)
    return {"id": str(e.id)}


class RemoveSuppressionIn(BaseModel):
    reason: str = Field(min_length=3, max_length=400)


@router.post("/suppression/{eid}/remove")
def remove_suppression(eid: uuid.UUID, body: RemoveSuppressionIn, db: Session = Depends(get_db),
                       user: User = Depends(current_user)) -> dict:
    from leadradar.modules.crm.suppression import remove_entry

    e = db.get(SuppressionEntry, eid)
    if e is None or e.removed_at:
        raise HTTPException(404, "not_found")
    remove_entry(db, e, body.reason, user.id)
    record_activity(db, "data", "suppression_removed", user_id=user.id, entity_type="suppression", entity_id=e.id,
                    details={"reason": body.reason})
    return {"ok": True}


# --- Usage & costs --------------------------------------------------------------------------------

@router.get("/usage")
def usage(db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    from leadradar.modules.advertising.apify import spent

    rows = db.scalars(select(ProviderUsage).order_by(ProviderUsage.occurred_at.desc()).limit(300)).all()
    month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_provider = db.execute(select(ProviderUsage.provider,
                                    func.coalesce(func.sum(ProviderUsage.estimated_cost_usd), 0),
                                    func.coalesce(func.sum(ProviderUsage.actual_cost_usd), 0), func.count())
                             .where(ProviderUsage.occurred_at >= month_start).group_by(ProviderUsage.provider)).all()
    return {
        "note": "API and infrastructure costs only. Advertising spend of researched companies is never shown.",
        "apify": {"spent_24h": float(spent(db, now() - timedelta(days=1))), "spent_month": float(spent(db, month_start))},
        "month_by_provider": [{"provider": p, "estimated_usd": float(e), "confirmed_usd": float(a), "entries": n}
                              for p, e, a, n in by_provider],
        "items": [{"id": str(u.id), "provider": u.provider, "kind": u.kind, "description": u.description,
                   "reference": u.reference, "estimated_usd": float(u.estimated_cost_usd) if u.estimated_cost_usd is not None else None,
                   "actual_usd": float(u.actual_cost_usd) if u.actual_cost_usd is not None else None,
                   "confirmed": u.cost_confirmed, "status": u.status, "units": u.units, "occurred_at": u.occurred_at}
                  for u in rows],
    }


class ExpenseIn(BaseModel):
    provider: str = Field(min_length=1, max_length=48)
    description: str = Field(min_length=1, max_length=300)
    amount_usd: Decimal = Field(ge=0, le=1_000_000)
    occurred_at: datetime | None = None


@router.post("/usage/expenses")
def add_expense(body: ExpenseIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    u = ProviderUsage(provider=body.provider, kind="manual_expense", description=body.description,
                      actual_cost_usd=body.amount_usd, cost_confirmed=True, status="recorded",
                      occurred_at=body.occurred_at or now(), user_id=user.id)
    db.add(u)
    db.flush()
    return {"id": str(u.id)}


@router.delete("/usage/{uid}")
def delete_usage(uid: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    u = db.get(ProviderUsage, uid)
    if u is None or u.kind != "manual_expense":
        raise HTTPException(404, "not_found")
    db.delete(u)
    return {"ok": True}


class ApifyActorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    actor_id: str = Field(pattern=r"^[A-Za-z0-9_.~/-]{3,200}$")
    purpose: Literal["discovery", "advertising"] = "discovery"
    input_template: dict[str, Any] = Field(default_factory=dict)
    allowed_input_keys: list[str] = Field(default_factory=list, max_length=30)
    field_mapping: dict[str, str] = Field(default_factory=dict)
    max_items: int = Field(default=100, ge=1, le=5000)
    max_cost_usd: Decimal = Field(default=Decimal("1"), ge=0, le=1000)
    enabled: bool = False


@router.get("/apify/actors")
def apify_actors(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"id": str(a.id), "name": a.name, "actor_id": a.actor_id, "purpose": a.purpose,
             "input_template": a.input_template, "allowed_input_keys": a.allowed_input_keys,
             "field_mapping": a.field_mapping, "max_items": a.max_items, "max_cost_usd": float(a.max_cost_usd),
             "enabled": a.enabled} for a in db.scalars(select(ApifyActorConfig).order_by(ApifyActorConfig.name))]


@router.post("/apify/actors")
def create_actor(body: ApifyActorIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    if len(str(body.input_template)) > 10_000:
        raise HTTPException(400, "too_large")
    a = ApifyActorConfig(**body.model_dump())
    db.add(a)
    db.flush()
    return {"id": str(a.id)}


@router.put("/apify/actors/{aid}")
def update_actor(aid: uuid.UUID, body: ApifyActorIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    a = db.get(ApifyActorConfig, aid)
    if a is None:
        raise HTTPException(404, "not_found")
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    return {"ok": True}


class ApifyRunIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    country: str | None = Field(default=None, max_length=2)
    industry: str | None = None


@router.post("/apify/actors/{aid}/run")
def run_actor(aid: uuid.UUID, body: ApifyRunIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    from leadradar.modules.advertising.apify import BudgetExceeded, check_budget, validate_input

    a = db.get(ApifyActorConfig, aid)
    if a is None or not a.enabled:
        raise HTTPException(400, "actor_disabled")
    try:
        check_budget(db, a)
        validate_input(a, body.input)
    except BudgetExceeded as exc:
        raise HTTPException(402, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    j = queue.enqueue(db, "apify_run", f"Apify: {a.name}", {"actor_config_id": str(a.id), **body.model_dump()},
                      created_by=user.id)
    return {"job_id": str(j.id)}


# --- Scoring configuration ------------------------------------------------------------------------

@router.get("/scoring/profiles")
def profiles(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    out = []
    for p in db.scalars(select(ScoringProfile).order_by(ScoringProfile.is_default.desc(), ScoringProfile.name_en)):
        rules = db.scalars(select(ScoringRule).where(ScoringRule.profile_id == p.id).order_by(ScoringRule.kind, ScoringRule.category, ScoringRule.key))
        out.append({"id": str(p.id), "key": p.key, "name_en": p.name_en, "name_tr": p.name_tr, "description": p.description,
                    "is_default": p.is_default, "category_limits": p.category_limits, "thresholds": p.thresholds,
                    "confidence_weights": p.confidence_weights, "service_focus": p.service_focus,
                    "min_confidence_for_high_priority": p.min_confidence_for_high_priority, "version": p.version,
                    "rules": [{"id": str(r.id), "key": r.key, "kind": r.kind, "category": r.category, "signal": r.signal,
                               "points": r.points, "exclusive_group": r.exclusive_group, "requires_absent": r.requires_absent,
                               "title_en": r.title_en, "title_tr": r.title_tr, "enabled": r.enabled, "version": r.version}
                              for r in rules]})
    return out


class ProfileIn(BaseModel):
    name_en: str | None = Field(default=None, max_length=120)
    name_tr: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category_limits: dict[str, int] | None = None
    thresholds: dict[str, int] | None = None
    confidence_weights: dict[str, int] | None = None
    service_focus: list[str] | None = None
    min_confidence_for_high_priority: int | None = Field(default=None, ge=0, le=100)


def _validate_profile(body: ProfileIn) -> None:
    if body.category_limits is not None:
        if set(body.category_limits) != {"service_need", "commercial_activity", "target_fit", "contactability"} or \
                any(not 0 <= v <= 100 for v in body.category_limits.values()) or sum(body.category_limits.values()) > 100:
            raise HTTPException(400, "invalid_category_limits")
    if body.thresholds is not None:
        t = body.thresholds
        if set(t) != {"high_priority", "strong_potential", "requires_review"} or not (
                100 >= t["high_priority"] > t["strong_potential"] > t["requires_review"] >= 0):
            raise HTTPException(400, "invalid_thresholds")
    if body.confidence_weights is not None and any(v < 0 or v > 100 for v in body.confidence_weights.values()):
        raise HTTPException(400, "invalid_weights")


@router.patch("/scoring/profiles/{pid}")
def patch_profile(pid: uuid.UUID, body: ProfileIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    p = db.get(ScoringProfile, pid)
    if p is None:
        raise HTTPException(404, "not_found")
    _validate_profile(body)
    # Only real changes create a new version; saving identical values is a no-op.
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if getattr(p, k) != v}
    if not changes:
        return {"ok": True, "version": p.version, "changed": False}
    for k, v in changes.items():
        setattr(p, k, v)
    p.version += 1
    p.admin_customized = True
    record_activity(db, "settings", "scoring_profile_updated", user_id=user.id, entity_id=p.key,
                    details={"fields": sorted(changes), "version": p.version})
    return {"ok": True, "version": p.version, "changed": True}


class CloneIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    name_en: str = Field(max_length=120)
    name_tr: str = Field(max_length=120)


@router.post("/scoring/profiles/{pid}/clone")
def clone_profile(pid: uuid.UUID, body: CloneIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    src = db.get(ScoringProfile, pid)
    if src is None:
        raise HTTPException(404, "not_found")
    if db.scalar(select(ScoringProfile.id).where(ScoringProfile.key == body.key)):
        raise HTTPException(409, "exists")
    p = ScoringProfile(key=body.key, name_en=body.name_en, name_tr=body.name_tr, description=src.description,
                       category_limits=dict(src.category_limits), thresholds=dict(src.thresholds),
                       confidence_weights=dict(src.confidence_weights), service_focus=list(src.service_focus),
                       min_confidence_for_high_priority=src.min_confidence_for_high_priority, admin_customized=True)
    db.add(p)
    db.flush()
    for r in db.scalars(select(ScoringRule).where(ScoringRule.profile_id == src.id)):
        db.add(ScoringRule(profile_id=p.id, key=r.key, kind=r.kind, category=r.category, signal=r.signal,
                           requires_absent=list(r.requires_absent), points=r.points, exclusive_group=r.exclusive_group,
                           title_en=r.title_en, title_tr=r.title_tr, explanation_en=r.explanation_en,
                           explanation_tr=r.explanation_tr, enabled=r.enabled, admin_customized=True))
    return {"id": str(p.id)}


class RulePatch(BaseModel):
    points: int | None = Field(default=None, ge=-100, le=100)
    enabled: bool | None = None
    exclusive_group: str | None = Field(default=None, max_length=48)


@router.patch("/scoring/rules/{rid}")
def patch_rule(rid: uuid.UUID, body: RulePatch, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    r = db.get(ScoringRule, rid)
    if r is None:
        raise HTTPException(404, "not_found")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if getattr(r, k) != v}
    if not data:
        return {"ok": True, "changed": False}
    if "points" in data and r.kind == "contribution" and data["points"] < 0:
        raise HTTPException(400, "contributions_must_be_positive")
    if "points" in data and r.kind == "penalty" and data["points"] > 0:
        raise HTTPException(400, "penalties_must_be_negative")
    for k, v in data.items():
        setattr(r, k, v)
    r.version += 1
    r.admin_customized = True
    p = db.get(ScoringProfile, r.profile_id)
    if p:
        p.version += 1
    record_activity(db, "settings", "scoring_rule_updated", user_id=user.id, entity_id=r.key, details=data)
    return {"ok": True, "changed": True}


@router.get("/scoring/service-rules")
def service_rules(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    return [{"id": str(r.id), "key": r.key, "service": r.service, "signal": r.signal, "requires_all": r.requires_all,
             "requires_absent": r.requires_absent, "points": r.points, "needs_review": r.needs_review,
             "recommendation_en": r.recommendation_en, "recommendation_tr": r.recommendation_tr, "enabled": r.enabled,
             "version": r.version} for r in db.scalars(select(ServiceRule).order_by(ServiceRule.service, ServiceRule.key))]


class ServiceRulePatch(BaseModel):
    points: int | None = Field(default=None, ge=0, le=100)
    enabled: bool | None = None


@router.patch("/scoring/service-rules/{rid}")
def patch_service_rule(rid: uuid.UUID, body: ServiceRulePatch, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    r = db.get(ServiceRule, rid)
    if r is None:
        raise HTTPException(404, "not_found")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if getattr(r, k) != v}
    if not data:
        return {"ok": True, "changed": False}
    for k, v in data.items():
        setattr(r, k, v)
    r.version += 1
    r.admin_customized = True
    return {"ok": True}


@router.post("/scoring/recalculate-all")
def recalc_all(profile_key: str | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    j = queue.enqueue(db, "recalculate_scores", "Recalculate all scores", {"profile_key": profile_key},
                      idempotency_key="recalculate_all", created_by=user.id)
    return {"job_id": str(j.id)}


# --- CRM statuses, review templates, activity ------------------------------------------------------

@router.get("/crm/statuses")
def crm_statuses(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    counts = dict(db.execute(select(Company.crm_status, func.count()).where(Company.merged_into_id.is_(None), Company.deleted_at.is_(None))
                             .group_by(Company.crm_status)).all())
    return [{"key": s.key, "name_en": s.name_en, "name_tr": s.name_tr, "sort_order": s.sort_order,
             "is_terminal": s.is_terminal, "show_in_pipeline": s.show_in_pipeline, "is_system": s.is_system,
             "count": counts.get(s.key, 0)}
            for s in db.scalars(select(CrmStatus).order_by(CrmStatus.sort_order))]


class CrmStatusIn(BaseModel):
    name_en: str = Field(min_length=1, max_length=64)
    name_tr: str = Field(min_length=1, max_length=64)
    is_terminal: bool = False
    show_in_pipeline: bool = True


def _status_key(db: Session, name: str) -> str:
    import re
    import unicodedata

    base = unicodedata.normalize("NFKD", name.replace("ı", "i").replace("İ", "I")).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_")[:24] or "status"
    key, n = base, 2
    while db.get(CrmStatus, key) is not None:
        key, n = f"{base}_{n}"[:32], n + 1
    return key


@router.post("/crm/statuses")
def create_crm_status(body: CrmStatusIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    last = db.scalar(select(func.max(CrmStatus.sort_order))) or 0
    s = CrmStatus(key=_status_key(db, body.name_en), name_en=body.name_en.strip(), name_tr=body.name_tr.strip(),
                  is_terminal=body.is_terminal, show_in_pipeline=body.show_in_pipeline, sort_order=last + 1)
    db.add(s)
    db.flush()
    record_activity(db, "settings", "crm_status_created", user_id=user.id, entity_id=s.key)
    return {"key": s.key}


@router.patch("/crm/statuses/{key}")
def update_crm_status(key: str, body: CrmStatusIn, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    s = db.get(CrmStatus, key)
    if s is None:
        raise HTTPException(404, "not_found")
    s.name_en, s.name_tr = body.name_en.strip(), body.name_tr.strip()
    s.is_terminal, s.show_in_pipeline = body.is_terminal, body.show_in_pipeline
    record_activity(db, "settings", "crm_status_updated", user_id=user.id, entity_id=key)
    return {"ok": True}


class ReorderIn(BaseModel):
    keys: list[str] = Field(max_length=100)


@router.post("/crm/statuses/reorder")
def reorder_crm_statuses(body: ReorderIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    rows = {s.key: s for s in db.scalars(select(CrmStatus))}
    if set(body.keys) != set(rows):
        raise HTTPException(400, "invalid_order")
    for i, k in enumerate(body.keys, start=1):
        rows[k].sort_order = i
    return {"ok": True}


@router.delete("/crm/statuses/{key}")
def delete_crm_status(key: str, move_to: str | None = None, db: Session = Depends(get_db),
                      user: User = Depends(current_user)) -> dict:
    """Delete a status. Companies in it are moved to ``move_to`` (required when there are any)."""
    s = db.get(CrmStatus, key)
    if s is None:
        raise HTTPException(404, "not_found")
    if s.is_system:
        raise HTTPException(409, "status_is_system")
    used = db.scalar(select(func.count()).select_from(Company).where(Company.crm_status == key)) or 0
    if used:
        target = db.get(CrmStatus, move_to) if move_to else None
        if target is None or target.key == key or target.key == "do_not_contact":
            raise HTTPException(409, "status_in_use")
        db.execute(update(Company).where(Company.crm_status == key).values(crm_status=target.key))
        if target.key == "archived":
            db.execute(update(Company).where(Company.crm_status == "archived").values(archived=True))
    db.delete(s)
    record_activity(db, "settings", "crm_status_deleted", user_id=user.id, entity_id=key,
                    details={"moved": used, "to": move_to})
    return {"moved": used}


@router.get("/crm/pipeline")
def pipeline(per_column: int = Query(30, le=100), db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    cols: dict[str, list[dict]] = {}
    for s in db.scalars(select(CrmStatus).where(CrmStatus.show_in_pipeline.is_(True)).order_by(CrmStatus.sort_order)):
        rows = db.scalars(select(Company).where(Company.crm_status == s.key, Company.merged_into_id.is_(None), Company.deleted_at.is_(None),
                                                Company.archived.is_(False))
                          .order_by(Company.updated_at.desc()).limit(per_column)).all()
        cols[s.key] = [{"id": str(c.id), "name": c.name, "score": c.effective_lead_score, "country": c.country_iso2,
                        "follow_up_at": c.follow_up_at, "classification": c.score_classification} for c in rows]
    return {"columns": cols}


@router.get("/crm/pipeline/table")
def pipeline_table(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), status: str | None = None,
                   db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    """Pipeline as a sales table: status, opportunities (highest first), lead score, report and
    advertising summaries. Companies in statuses hidden from the pipeline are not listed."""
    from leadradar.db.models import AdvertisingResearchRun, Report

    keys = [s.key for s in db.scalars(select(CrmStatus).where(CrmStatus.show_in_pipeline.is_(True)))]
    if status:
        keys = [k for k in keys if k == status]
    base = select(Company).where(Company.crm_status.in_(keys), Company.merged_into_id.is_(None),
                                 Company.archived.is_(False), Company.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Company.effective_lead_score.desc().nulls_last(), Company.name)
                      .offset((page - 1) * page_size).limit(page_size)).all()
    ids = [c.id for c in rows]
    reports: dict[uuid.UUID, list[Report]] = {i: [] for i in ids}
    for r in db.scalars(select(Report).where(Report.company_id.in_(ids)).order_by(Report.updated_at.desc())):
        reports[r.company_id].append(r)
    # Advertising: the latest research per company and platform.
    ads: dict[uuid.UUID, dict[str, int]] = {i: {} for i in ids}
    seen: set[tuple[uuid.UUID, str]] = set()
    for run in db.scalars(select(AdvertisingResearchRun).where(AdvertisingResearchRun.company_id.in_(ids))
                          .order_by(AdvertisingResearchRun.created_at.desc())):
        if (run.company_id, run.platform) in seen or run.status in ("not_checked", "error", "rate_limited"):
            continue
        seen.add((run.company_id, run.platform))
        if run.result_count:
            ads[run.company_id][run.platform] = run.result_count
    items = []
    for c in rows:
        services = sorted(((k, v) for k, v in (c.service_scores or {}).items() if v.get("score", 0) >= 30),
                          key=lambda kv: -kv[1]["score"])
        rs = reports[c.id]
        items.append({
            "id": str(c.id), "name": c.name, "country": c.country_iso2, "crm_status": c.crm_status,
            "score": c.effective_lead_score, "classification": c.score_classification, "follow_up_at": c.follow_up_at,
            "services": [{"key": k, "score": v["score"], "provisional": v.get("provisional", False)} for k, v in services],
            "reports": {"count": len(rs), "latest": [{"id": str(r.id), "title": r.title, "status": r.status,
                                                      "updated_at": r.updated_at} for r in rs[:5]]},
            "ads": {"total": sum(ads[c.id].values()),
                    "platforms": [{"platform": p, "count": n} for p, n in sorted(ads[c.id].items(), key=lambda x: -x[1])]},
        })
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/review-templates")
def review_templates(db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    out = []
    for t in db.scalars(select(ReviewTemplate).order_by(ReviewTemplate.is_default.desc(), ReviewTemplate.name_en)):
        qs = db.scalars(select(ReviewQuestion).where(ReviewQuestion.template_id == t.id).order_by(ReviewQuestion.sort_order))
        out.append({"id": str(t.id), "key": t.key, "name_en": t.name_en, "name_tr": t.name_tr, "is_default": t.is_default,
                    "questions": [{"id": str(q.id), "key": q.key, "text_en": q.text_en, "text_tr": q.text_tr,
                                   "yes_signal": q.yes_signal, "no_signal": q.no_signal, "enabled": q.enabled,
                                   "sort_order": q.sort_order} for q in qs]})
    return out


class QuestionIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    text_en: str = Field(min_length=3, max_length=400)
    text_tr: str = Field(min_length=3, max_length=400)
    yes_signal: str | None = Field(default=None, pattern=r"^[a-z0-9_.]{2,64}$")
    no_signal: str | None = Field(default=None, pattern=r"^[a-z0-9_.]{2,64}$")
    enabled: bool = True


@router.post("/review-templates/{tid}/questions")
def add_question(tid: uuid.UUID, body: QuestionIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    t = db.get(ReviewTemplate, tid)
    if t is None:
        raise HTTPException(404, "not_found")
    if db.scalar(select(ReviewQuestion.id).where(ReviewQuestion.template_id == tid, ReviewQuestion.key == body.key)):
        raise HTTPException(409, "exists")
    order = (db.scalar(select(func.max(ReviewQuestion.sort_order)).where(ReviewQuestion.template_id == tid)) or 0) + 1
    q = ReviewQuestion(template_id=tid, sort_order=order, **body.model_dump())
    db.add(q)
    db.flush()
    return {"id": str(q.id)}


@router.patch("/review-questions/{qid}")
def patch_question(qid: uuid.UUID, body: QuestionIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    q = db.get(ReviewQuestion, qid)
    if q is None:
        raise HTTPException(404, "not_found")
    for k, v in body.model_dump().items():
        if k != "key":
            setattr(q, k, v)
    return {"ok": True}


class TemplateIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_]{2,64}$")
    name_en: str = Field(max_length=120)
    name_tr: str = Field(max_length=120)
    copy_from: uuid.UUID | None = None


@router.post("/review-templates")
def create_template(body: TemplateIn, db: Session = Depends(get_db), _: User = Depends(current_user)) -> dict:
    if db.scalar(select(ReviewTemplate.id).where(ReviewTemplate.key == body.key)):
        raise HTTPException(409, "exists")
    t = ReviewTemplate(key=body.key, name_en=body.name_en, name_tr=body.name_tr)
    db.add(t)
    db.flush()
    if body.copy_from:
        for q in db.scalars(select(ReviewQuestion).where(ReviewQuestion.template_id == body.copy_from)):
            db.add(ReviewQuestion(template_id=t.id, key=q.key, text_en=q.text_en, text_tr=q.text_tr,
                                  yes_signal=q.yes_signal, no_signal=q.no_signal, sort_order=q.sort_order))
    return {"id": str(t.id)}


@router.get("/activity-log")
def activity_log(category: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)) -> list[dict]:
    q = select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(300)
    if category:
        q = q.where(ActivityLog.category == category)
    return [{"id": a.id, "category": a.category, "action": a.action, "entity_type": a.entity_type,
             "entity_id": a.entity_id, "details": a.details, "ip": str(a.ip_address or ""), "created_at": a.created_at}
            for a in db.scalars(q)]
