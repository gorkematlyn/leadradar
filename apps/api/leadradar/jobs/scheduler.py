"""Database-locked scheduler, embedded in the discovery worker.

A session-level advisory lock (``pg_try_advisory_lock``) held on a dedicated
connection guarantees a single active scheduler even if several workers run it.
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from leadradar.core.app_settings import get_setting, set_setting
from leadradar.core.config import get_settings
from leadradar.db.models import Company, Country, SavedCampaign, SchedulerLock
from leadradar.db.session import get_engine, session_scope
from leadradar.jobs import queue

log = logging.getLogger(__name__)

LOCK_KEY = "leadradar.scheduler"


def schedule_initial_import(db) -> list[str]:  # type: ignore[no-untyped-def]
    """Schedule the first Geofabrik imports exactly once (persisted flag + idempotency keys)."""
    if get_setting(db, "discovery.initial_import_scheduled"):
        return []
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('leadradar.initial_import'))"))
    if get_setting(db, "discovery.initial_import_scheduled"):
        return []
    scheduled = []
    for i, iso2 in enumerate(get_setting(db, "discovery.initial_countries") or []):
        country = db.get(Country, iso2)
        if country is None or not country.enabled:
            continue
        queue.enqueue(
            db, "geofabrik_country_import", f"Initial import: {country.name_en}", {"country": iso2, "initial": True},
            idempotency_key=f"geofabrik_country:{iso2}", priority=50 + i,
        )
        country.import_status = "queued"
        scheduled.append(iso2)
    set_setting(db, "discovery.initial_import_scheduled", True, admin=False)
    return scheduled


def _due(db, name: str, every: timedelta) -> bool:  # type: ignore[no-untyped-def]
    row = db.get(SchedulerLock, name)
    now = queue.now()
    if row is None:
        db.execute(insert(SchedulerLock).values(name=name, last_run_at=now, last_status="ok").on_conflict_do_nothing())
        return True
    if row.last_run_at is None or now - row.last_run_at >= every:
        row.last_run_at = now
        return True
    return False


def task_recover(db) -> None:  # type: ignore[no-untyped-def]
    n = queue.recover_stale(db)
    if n:
        log.warning("recovered stale jobs", extra={"data": {"count": n}})


def task_campaigns(db) -> None:  # type: ignore[no-untyped-def]
    now = queue.now()
    due = db.scalars(
        select(SavedCampaign).where(
            SavedCampaign.enabled.is_(True), SavedCampaign.schedule_interval_hours.isnot(None),
            SavedCampaign.next_run_at <= now,
        )
    ).all()
    for c in due:
        queue.enqueue(db, "campaign_run", f"Campaign: {c.name}", {"campaign_id": str(c.id), "trigger": "schedule"},
                      idempotency_key=f"campaign:{c.id}")
        c.next_run_at = now + timedelta(hours=c.schedule_interval_hours or 24)


def task_monitoring(db) -> None:  # type: ignore[no-untyped-def]
    days = int(get_setting(db, "monitoring.recheck_days"))
    cutoff = queue.now() - timedelta(days=days)
    rows = db.scalars(
        select(Company.id).where(
            Company.watchlisted.is_(True), Company.archived.is_(False), Company.do_not_contact.is_(False),
            (Company.last_audit_at.is_(None)) | (Company.last_audit_at < cutoff),
        ).limit(25)
    ).all()
    for cid in rows:
        queue.enqueue(db, "monitor_company", "Monitoring re-check", {"company_id": str(cid)},
                      idempotency_key=f"monitor:{cid}", company_id=cid, concurrency_key=f"company:{cid}")


def task_retention(db) -> None:  # type: ignore[no-untyped-def]
    queue.enqueue(db, "retention_cleanup", "Retention cleanup", {}, idempotency_key="retention_cleanup")


def task_disk(db) -> None:  # type: ignore[no-untyped-def]
    from leadradar.modules.crm.notifications import notify

    reserve = int(get_setting(db, "limits.min_free_disk_gb"))
    path = get_settings().worker_tmp_dir
    try:
        free_gb = shutil.disk_usage(path).free / 1e9
    except FileNotFoundError:
        free_gb = shutil.disk_usage("/").free / 1e9
    if free_gb < reserve:
        notify(db, "low_disk", "notifications.lowDisk", {"free_gb": round(free_gb, 1), "reserve_gb": reserve},
               severity="warning", link="/settings/health", dedupe_key="low_disk", dedupe_hours=12)


TASKS = [
    ("recover_stale_jobs", timedelta(seconds=60), task_recover),
    ("scheduled_campaigns", timedelta(minutes=5), task_campaigns),
    ("watchlist_monitoring", timedelta(hours=1), task_monitoring),
    ("retention_cleanup", timedelta(hours=24), task_retention),
    ("disk_check", timedelta(minutes=10), task_disk),
]


def scheduler_loop(stop: threading.Event | None = None) -> None:
    stop = stop or threading.Event()
    engine = get_engine()
    while not stop.is_set():
        try:
            with engine.connect() as conn:
                got = conn.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": LOCK_KEY}).scalar()
                conn.commit()
                if not got:
                    stop.wait(60)
                    continue
                log.info("scheduler lock acquired")
                with session_scope() as db:
                    schedule_initial_import(db)
                while not stop.is_set():
                    conn.execute(text("SELECT 1"))  # keep the lock connection alive
                    conn.commit()
                    for name, every, fn in TASKS:
                        try:
                            with session_scope() as db:
                                if _due(db, name, every):
                                    fn(db)
                        except Exception as exc:
                            log.exception("scheduler task failed")
                            with session_scope() as db:
                                row = db.get(SchedulerLock, name)
                                if row:
                                    row.last_status, row.last_error = "error", str(exc)[:2000]
                    stop.wait(15)
        except Exception:
            log.exception("scheduler connection error; retrying")
            stop.wait(30)


def utc_now() -> datetime:
    return datetime.now(UTC)
