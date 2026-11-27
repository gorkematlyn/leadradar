"""Country import status and progress, derived from the job queue.

A country import is one ``geofabrik_country_import`` job (planning) with one child
``geofabrik_extract_import`` job per Geofabrik region. The status shown to the
administrator is derived from the *latest* such batch, so cancelling, pausing or
retrying individual jobs is always reflected correctly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from leadradar.db.models import Country, ImportRun, Job
from leadradar.jobs import queue

COUNTRY_JOB = "geofabrik_country_import"
EXTRACT_JOB = "geofabrik_extract_import"
ACTIVE = {"queued", "running", "paused"}


def _latest_country_jobs(db: Session, iso2: str | None = None) -> dict[str, Job]:
    q = select(Job).where(Job.type == COUNTRY_JOB)
    if iso2:
        q = q.where(Job.payload["country"].astext == iso2.upper())
    latest: dict[str, Job] = {}
    for j in db.scalars(q.order_by(Job.created_at.desc())):
        c = str((j.payload or {}).get("country", "")).upper()
        if c and c not in latest:
            latest[c] = j
    return latest


def _derive(parent: Job, children: list[Job]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for c in children:
        counts[c.status] = counts.get(c.status, 0) + 1
    total = len(children)
    done = counts.get("completed", 0)
    failed = counts.get("failed", 0) + counts.get("dead", 0)
    cancelled = counts.get("cancelled", 0)
    if parent.status in ACTIVE and not children:
        status = "paused" if parent.status == "paused" else ("planning" if parent.status == "running" else "queued")
    elif not children:
        status = {"failed": "failed", "dead": "failed", "cancelled": "cancelled"}.get(parent.status, "completed")
    elif counts.get("running"):
        status = "running"
    elif counts.get("queued"):
        status = "queued"
    elif counts.get("paused"):
        status = "paused"
    elif failed:
        status = "partial" if done else "failed"
    elif cancelled:
        status = "partial" if done else "cancelled"
    else:
        status = "completed"
    total_bytes = sum(int((c.payload or {}).get("size") or 0) for c in children)
    done_bytes = sum(int((c.payload or {}).get("size") or 0) for c in children if c.status == "completed")
    current = None
    for c in children:
        if c.status == "running":
            stage = c.stage or ""
            if stage == "download" and c.processed_count:
                done_bytes += int(c.processed_count)
            current = {"job_id": str(c.id), "name": (c.payload or {}).get("region_name") or (c.payload or {}).get("extract_id"),
                       "stage": stage.split(":")[0] or None, "processed": c.processed_count, "total": c.total_count}
            break
    return {
        "status": status, "job_id": str(parent.id), "regions_total": total, "regions_done": done,
        "regions_failed": failed, "regions_cancelled": cancelled, "bytes_total": total_bytes or None,
        "bytes_done": min(done_bytes, total_bytes) if total_bytes else None, "current": current,
        "error": next((c.error for c in children if c.status in ("failed", "dead") and c.error), parent.error),
        "started_at": parent.created_at,
    }


def _orphan_batches(db: Session, iso2: str | None) -> dict[str, list[Job]]:
    """Region jobs whose planning job record was deleted (``parent_id`` set to NULL).
    Regions planned together are created within seconds of each other, so the latest
    group per country is the regions created close to its newest region."""
    q = select(Job).where(Job.type == EXTRACT_JOB, Job.parent_id.is_(None))
    if iso2:
        q = q.where(Job.payload["country"].astext == iso2.upper())
    by_country: dict[str, list[Job]] = {}
    for j in db.scalars(q.order_by(Job.created_at.desc())):
        c = str((j.payload or {}).get("country", "")).upper()
        if c:
            by_country.setdefault(c, []).append(j)
    out: dict[str, list[Job]] = {}
    for c, jobs in by_country.items():
        newest = jobs[0].created_at
        group = [j for j in jobs if newest - j.created_at <= timedelta(minutes=10)]
        out[c] = sorted(group, key=lambda j: (j.priority, j.created_at))
    return out


def country_progress(db: Session, iso2: str | None = None) -> dict[str, dict[str, Any]]:
    """Latest import batch per country: status, region counts, byte progress."""
    parents = _latest_country_jobs(db, iso2)
    children: dict[uuid.UUID, list[Job]] = {p.id: [] for p in parents.values()}
    if children:
        for c in db.scalars(select(Job).where(Job.parent_id.in_(list(children))).order_by(Job.priority, Job.created_at)):
            children[c.parent_id].append(c)  # type: ignore[index]
    out = {iso: _derive(p, children[p.id]) for iso, p in parents.items()}
    for iso, jobs in _orphan_batches(db, iso2).items():
        parent = parents.get(iso)
        if parent is not None and parent.created_at >= max(j.created_at for j in jobs):
            continue  # a newer complete batch exists
        stand_in = SimpleNamespace(id=jobs[0].id, status="completed", error=None,
                                   created_at=min(j.created_at for j in jobs))
        out[iso] = _derive(stand_in, jobs)  # type: ignore[arg-type]
    return out


def display_status(country: Country, progress: dict[str, Any] | None) -> str:
    if not country.enabled:
        return "disabled"
    if progress:
        return str(progress["status"])
    # No job history (never imported, or records were cleared): never report a stale active state.
    if country.import_status in ("completed", "failed", "cancelled", "partial"):
        return country.import_status
    return "completed" if country.last_import_at else "never"


def sync_country_status(db: Session, iso2: str) -> None:
    country = db.get(Country, iso2.upper())
    if country is None:
        return
    prog = country_progress(db, iso2).get(iso2.upper())
    country.import_status = display_status(country, prog)


def on_job_cancelled(db: Session, job: Job) -> None:
    """Keep import runs consistent when a queued extract job is cancelled without running."""
    if job.type == EXTRACT_JOB and job.status == "cancelled":
        run_id = (job.payload or {}).get("import_run_id")
        if run_id:
            db.execute(update(ImportRun).where(ImportRun.id == uuid.UUID(run_id), ImportRun.status.in_(["queued", "running"]))
                       .values(status="cancelled", finished_at=datetime.now(UTC)))


def on_job_retried(db: Session, job: Job) -> None:
    if job.type == EXTRACT_JOB:
        run_id = (job.payload or {}).get("import_run_id")
        if run_id:
            db.execute(update(ImportRun).where(ImportRun.id == uuid.UUID(run_id))
                       .values(status="queued", finished_at=None, error=None))


def country_action(db: Session, iso2: str, action: str) -> int:
    """cancel / pause / resume every job of the country's latest import batch."""
    parent = _latest_country_jobs(db, iso2).get(iso2.upper())
    orphans = _orphan_batches(db, iso2).get(iso2.upper(), [])
    if parent is not None:
        jobs = [parent, *db.scalars(select(Job).where(Job.parent_id == parent.id))]
        if orphans and max(j.created_at for j in orphans) > parent.created_at:
            jobs = orphans
    elif orphans:
        jobs = orphans
    else:
        return 0
    affected = 0
    for j in jobs:
        before = j.status
        if action == "cancel" and j.status in ACTIVE:
            queue.cancel(db, j)
            on_job_cancelled(db, j)
        elif action == "pause":
            queue.pause(db, j)
        elif action == "resume":
            queue.resume(db, j)
        if j.status != before or (action == "cancel" and j.cancel_requested and before == "running"):
            affected += 1
    db.flush()
    sync_country_status(db, iso2)
    return affected
