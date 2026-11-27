"""Company trash: soft delete, restore and permanent purge.

A company in the trash is hidden from every list, filter, export, dashboard and
pipeline. It can be restored for ``TRASH_DAYS`` days; after that the retention job
deletes it permanently (with its audits, reports and CRM history). Do Not Contact
entries are independent of companies and always survive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from leadradar.core.activity import record_activity
from leadradar.db.models import Company, Job
from leadradar.jobs import queue

TRASH_DAYS = 30


def now() -> datetime:
    return datetime.now(UTC)


def move_to_trash(db: Session, companies: list[Company], user_id: uuid.UUID | None) -> int:
    ids = [c.id for c in companies if c.deleted_at is None]
    for c in companies:
        if c.deleted_at is None:
            c.deleted_at = now()
    # Work queued for these companies is no longer needed.
    if ids:
        for j in db.scalars(select(Job).where(Job.company_id.in_(ids), Job.status.in_(["queued", "paused", "running"]))):
            queue.cancel(db, j)
        record_activity(db, "data", "companies_trashed", user_id=user_id, details={"count": len(ids)})
    return len(ids)


def restore(db: Session, ids: list[uuid.UUID], user_id: uuid.UUID | None) -> int:
    rows = db.scalars(select(Company).where(Company.id.in_(ids), Company.deleted_at.isnot(None))).all()
    for c in rows:
        c.deleted_at = None
    if rows:
        record_activity(db, "data", "companies_restored", user_id=user_id, details={"count": len(rows)})
    return len(rows)


def purge(db: Session, ids: list[uuid.UUID] | None, user_id: uuid.UUID | None, *, older_than_days: int | None = None) -> int:
    """Permanently delete trashed companies (all, the given ids, or those older than N days)."""
    q = select(Company).where(Company.deleted_at.isnot(None))
    if ids is not None:
        q = q.where(Company.id.in_(ids))
    if older_than_days is not None:
        q = q.where(Company.deleted_at < now() - timedelta(days=older_than_days))
    rows = db.scalars(q).all()
    for c in rows:
        db.delete(c)
    db.flush()
    if rows:
        record_activity(db, "data", "companies_purged", user_id=user_id, details={"count": len(rows)})
    return len(rows)
