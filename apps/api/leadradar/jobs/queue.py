"""PostgreSQL-backed persistent job queue.

* Claiming uses ``FOR UPDATE SKIP LOCKED`` inside a transaction that also holds a
  transaction-level advisory lock per queue, so concurrency limits (heavy tasks, one
  Geofabrik import, one job per domain/company) are evaluated atomically.
* Running jobs hold a lease that is extended by heartbeats. Expired leases are
  recovered by the scheduler (requeued with backoff, or dead-lettered).
* Idempotency keys prevent duplicate active jobs.
* ``depends_on`` orders work: a job waits while a dependency is still active. A failed or
  cancelled dependency does not block the rest (one failed region must not stall a country).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from leadradar.core.app_settings import get_setting
from leadradar.db.models import Job, JobAttempt, JobLog

log = logging.getLogger(__name__)

LEASE_SECONDS = 180
ACTIVE = ("queued", "running", "paused")

# job type -> (queue, resource_class, default priority, max_attempts)
JOB_TYPES: dict[str, tuple[str, str, int, int]] = {
    "geofabrik_country_import": ("discovery", "light", 50, 3),
    "geofabrik_extract_import": ("discovery", "import", 50, 4),
    "csv_import": ("discovery", "light", 40, 1),
    "apify_run": ("discovery", "light", 60, 1),
    "website_audit": ("analysis", "heavy", 30, 2),
    "quick_audit": ("analysis", "light", 20, 2),
    "ad_research": ("analysis", "light", 40, 3),
    "report_pdf": ("analysis", "heavy", 10, 3),
    "campaign_run": ("discovery", "light", 60, 1),
    "monitor_company": ("analysis", "light", 80, 2),
    "retention_cleanup": ("discovery", "light", 90, 1),
    "recalculate_scores": ("discovery", "light", 70, 1),
}


def now() -> datetime:
    return datetime.now(UTC)


class DuplicateJob(Exception):
    def __init__(self, existing_id: uuid.UUID) -> None:
        super().__init__(str(existing_id))
        self.existing_id = existing_id


def enqueue(
    db: Session,
    job_type: str,
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    priority: int | None = None,
    idempotency_key: str | None = None,
    concurrency_key: str | None = None,
    run_at: datetime | None = None,
    depends_on: list[uuid.UUID] | None = None,
    parent_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    total_count: int | None = None,
    reuse_existing: bool = True,
) -> Job:
    queue, resource_class, default_priority, max_attempts = JOB_TYPES[job_type]
    if idempotency_key:
        existing = db.scalar(
            select(Job).where(Job.idempotency_key == idempotency_key, Job.status.in_(ACTIVE))
        )
        if existing is not None:
            if reuse_existing:
                return existing
            raise DuplicateJob(existing.id)
    job = Job(
        id=uuid.uuid4(),
        type=job_type,
        name=name[:300],
        queue=queue,
        resource_class=resource_class,
        status="queued",
        priority=default_priority if priority is None else priority,
        payload=payload or {},
        idempotency_key=idempotency_key,
        concurrency_key=concurrency_key,
        run_at=run_at or now(),
        depends_on=depends_on or [],
        parent_id=parent_id,
        max_attempts=max_attempts,
        company_id=company_id,
        created_by=created_by,
        total_count=total_count,
    )
    db.add(job)
    db.flush()
    return job


def _limits(db: Session) -> dict[str, int]:
    return {
        "heavy": int(get_setting(db, "limits.heavy_concurrency")),
        "light": int(get_setting(db, "limits.light_concurrency")),
        "import": int(get_setting(db, "limits.geofabrik_concurrency")),
    }


_CLAIM_SQL = text(
    """
    SELECT j.id FROM jobs j
    WHERE j.queue = :queue
      AND j.status = 'queued'
      AND j.run_at <= now()
      AND j.resource_class = ANY(:classes)
      AND (j.concurrency_key IS NULL OR NOT EXISTS (
            SELECT 1 FROM jobs r WHERE r.status = 'running' AND r.concurrency_key = j.concurrency_key))
      AND NOT EXISTS (
            SELECT 1 FROM jobs d WHERE d.id = ANY(j.depends_on) AND d.status IN ('queued', 'running', 'paused'))
    ORDER BY j.priority ASC, j.run_at ASC
    LIMIT 1
    FOR UPDATE SKIP LOCKED
    """
)


def claim(db: Session, queue: str, worker_id: str, allowed_classes: list[str] | None = None) -> Job | None:
    """Atomically claim the next runnable job for ``queue`` respecting global limits."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"leadradar.claim.{queue}"})
    limits = _limits(db)
    running = dict(
        db.execute(
            select(Job.resource_class, func.count()).where(Job.status == "running").group_by(Job.resource_class)
        ).all()
    )
    classes = [
        c for c in (allowed_classes or ["heavy", "light", "import"]) if running.get(c, 0) < limits.get(c, 1)
    ]
    if not classes:
        return None
    job_id = db.execute(_CLAIM_SQL, {"queue": queue, "classes": classes}).scalar()
    if job_id is None:
        return None
    job = db.get(Job, job_id)
    assert job is not None
    t = now()
    job.status = "running"
    job.locked_by = worker_id
    job.attempts += 1
    job.lease_until = t + timedelta(seconds=LEASE_SECONDS)
    job.heartbeat_at = t
    job.started_at = job.started_at or t
    job.error = None
    db.add(JobAttempt(job_id=job.id, attempt=job.attempts, worker=worker_id, started_at=t))
    db.flush()
    return job


def heartbeat(
    db: Session,
    job_id: uuid.UUID,
    worker_id: str,
    *,
    stage: str | None = None,
    processed: int | None = None,
    total: int | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> bool:
    """Extend the lease. Returns False when the job was cancelled or lost."""
    values: dict[str, Any] = {"heartbeat_at": now(), "lease_until": now() + timedelta(seconds=LEASE_SECONDS)}
    if stage is not None:
        values["stage"] = stage[:120]
    if processed is not None:
        values["processed_count"] = processed
    if total is not None:
        values["total_count"] = total
    if checkpoint is not None:
        values["checkpoint"] = checkpoint
    row = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.locked_by == worker_id, Job.status == "running")
        .values(**values)
        .returning(Job.cancel_requested)
    ).first()
    return bool(row is not None and not row[0])


def _close_attempt(db: Session, job: Job, outcome: str, error: str | None = None) -> None:
    attempt = db.scalar(
        select(JobAttempt).where(JobAttempt.job_id == job.id, JobAttempt.attempt == job.attempts)
    )
    if attempt:
        attempt.finished_at = now()
        attempt.outcome = outcome
        attempt.error = error


def complete(db: Session, job: Job, result: dict[str, Any] | None = None, *, waiting_review: bool = False) -> None:
    job.status = "waiting_review" if waiting_review else "completed"
    job.result = result or job.result
    job.finished_at = now()
    job.lease_until = None
    job.locked_by = None
    _close_attempt(db, job, job.status)
    db.flush()


def backoff_seconds(attempt: int) -> int:
    return min(3600, 30 * (2 ** max(0, attempt - 1)))


def fail(db: Session, job: Job, error: str, *, retryable: bool = True) -> None:
    job.error = error[:4000]
    job.lease_until = None
    job.locked_by = None
    _close_attempt(db, job, "failed", error[:4000])
    if retryable and job.attempts < job.max_attempts and not job.cancel_requested:
        job.status = "queued"
        job.run_at = now() + timedelta(seconds=backoff_seconds(job.attempts))
    else:
        job.status = "dead" if retryable and job.attempts >= job.max_attempts else "failed"
        job.finished_at = now()
    db.flush()


def cancel(db: Session, job: Job) -> None:
    if job.status in ("queued", "paused"):
        job.status = "cancelled"
        job.finished_at = now()
    elif job.status == "running":
        job.cancel_requested = True  # worker observes it at next heartbeat
    db.flush()


def mark_cancelled(db: Session, job: Job) -> None:
    job.status = "cancelled"
    job.finished_at = now()
    job.lease_until = None
    job.locked_by = None
    _close_attempt(db, job, "cancelled")
    db.flush()


def retry(db: Session, job: Job) -> None:
    if job.status in ("failed", "dead", "cancelled"):
        job.status = "queued"
        job.run_at = now()
        job.cancel_requested = False
        job.max_attempts = max(job.max_attempts, job.attempts + 1)
        job.finished_at = None
        db.flush()


def pause(db: Session, job: Job) -> None:
    if job.status == "queued":
        job.status = "paused"
        db.flush()


def resume(db: Session, job: Job) -> None:
    if job.status == "paused":
        job.status = "queued"
        job.run_at = now()
        db.flush()


def recover_stale(db: Session) -> int:
    """Requeue (or dead-letter) running jobs whose lease expired (worker crash/restart)."""
    stale = db.scalars(
        select(Job).where(Job.status == "running", Job.lease_until < now()).with_for_update(skip_locked=True)
    ).all()
    for job in stale:
        add_log(db, job.id, "warning", "Lease expired; worker presumed lost. Recovering job.")
        if job.cancel_requested:
            mark_cancelled(db, job)
        else:
            fail(db, job, "worker_lost: lease expired (restart or crash)", retryable=True)
    return len(stale)


def add_log(db: Session, job_id: uuid.UUID, level: str, message: str, data: dict[str, Any] | None = None) -> None:
    db.execute(
        insert(JobLog).values(job_id=job_id, level=level, message=message[:4000], data=data or {}, created_at=now())
    )
