"""Worker runtime: claims jobs, runs handlers in threads, heartbeats, shutdown."""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psutil
from sqlalchemy.dialects.postgresql import insert

from leadradar.core.app_settings import get_setting
from leadradar.db.models import Job, WorkerHeartbeat
from leadradar.db.session import session_scope
from leadradar.jobs import queue

log = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class PermanentJobError(Exception):
    """Failure that must not be retried (invalid input, unsupported, ...)."""


@dataclass
class HandlerResult:
    result: dict[str, Any] = field(default_factory=dict)
    waiting_review: bool = False


class JobContext:
    def __init__(self, job_id: uuid.UUID, worker_id: str, payload: dict[str, Any], checkpoint: dict[str, Any],
                 job_type: str, company_id: uuid.UUID | None, attempts: int) -> None:
        self.job_id = job_id
        self.worker_id = worker_id
        self.payload = payload
        self.checkpoint_data = dict(checkpoint or {})
        self.job_type = job_type
        self.company_id = company_id
        self.attempts = attempts
        self._cancelled = threading.Event()
        self._stage: str | None = None
        self._processed: int | None = None
        self._total: int | None = None
        self._lock = threading.Lock()

    # --- progress -----------------------------------------------------------------
    def progress(self, stage: str | None = None, processed: int | None = None, total: int | None = None) -> None:
        with self._lock:
            if stage is not None:
                self._stage = stage
            if processed is not None:
                self._processed = processed
            if total is not None:
                self._total = total
        self.flush()

    def checkpoint(self, data: dict[str, Any]) -> None:
        self.checkpoint_data = dict(data)
        self.flush(with_checkpoint=True)

    def flush(self, with_checkpoint: bool = False) -> None:
        with self._lock, session_scope() as db:
            ok = queue.heartbeat(
                db, self.job_id, self.worker_id, stage=self._stage, processed=self._processed,
                total=self._total, checkpoint=self.checkpoint_data if with_checkpoint else None,
            )
        if not ok:
            self._cancelled.set()

    def log(self, level: str, message: str, **data: Any) -> None:
        with session_scope() as db:
            queue.add_log(db, self.job_id, level, message, data)

    def raise_if_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise JobCancelled()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()


Handler = Callable[[JobContext], HandlerResult | dict[str, Any] | None]
HANDLERS: dict[str, Handler] = {}


def handler(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return deco


def resources_ok(resource_class: str) -> bool:
    """CPU/memory-aware scheduling: hold back heavy work when the host is saturated."""
    with session_scope() as db:
        max_mem = int(get_setting(db, "limits.max_memory_percent"))
        max_cpu = int(get_setting(db, "limits.max_cpu_percent"))
    mem = psutil.virtual_memory().percent
    if mem >= max_mem:
        return False
    if resource_class in ("heavy", "import"):
        cpu = psutil.cpu_percent(interval=0.2)
        return cpu < max_cpu
    return True


class Worker:
    def __init__(self, queues: list[str], concurrency: int, allowed_classes: list[str] | None = None) -> None:
        self.queues = queues
        self.concurrency = max(1, concurrency)
        self.allowed_classes = allowed_classes
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self._stop = threading.Event()
        self._active: dict[uuid.UUID, JobContext] = {}
        self._threads: list[threading.Thread] = []
        self.started_at = queue.now()
        self.extra_loops: list[Callable[[], None]] = []

    def stop(self, *_: Any) -> None:
        log.info("shutdown requested; finishing current jobs")
        self._stop.set()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        for i in range(self.concurrency):
            t = threading.Thread(target=self._slot, name=f"slot-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        hb = threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)
        hb.start()
        for fn in self.extra_loops:
            threading.Thread(target=fn, name=getattr(fn, "__name__", "loop"), daemon=True).start()
        while not self._stop.is_set():
            time.sleep(1)
        deadline = time.time() + 25  # Docker stop_grace_period is 30s
        for t in self._threads:
            t.join(timeout=max(0.1, deadline - time.time()))
        # Jobs still running will be recovered via lease expiry.
        log.info("worker stopped")

    def _heartbeat_loop(self) -> None:
        import platform

        while not self._stop.is_set():
            try:
                with session_scope() as db:
                    stmt = insert(WorkerHeartbeat).values(
                        worker_id=self.worker_id, queues=self.queues, hostname=platform.node()[:120],
                        started_at=self.started_at, last_seen_at=queue.now(), running_jobs=len(self._active),
                        stats={"memory_percent": psutil.virtual_memory().percent},
                    )
                    db.execute(stmt.on_conflict_do_update(
                        index_elements=["worker_id"],
                        set_={"last_seen_at": queue.now(), "running_jobs": len(self._active),
                              "stats": stmt.excluded.stats},
                    ))
                for ctx in list(self._active.values()):
                    ctx.flush()
            except Exception:  # pragma: no cover - keep heartbeating
                log.exception("heartbeat failed")
            self._stop.wait(30)

    def _slot(self) -> None:
        idle = 1.0
        while not self._stop.is_set():
            ran = False
            for q in self.queues:
                if self._stop.is_set():
                    break
                try:
                    ran = self.run_once(q) or ran
                except Exception:
                    log.exception("worker loop error")
                    time.sleep(5)
            idle = 0.5 if ran else min(idle * 1.5, 5.0)
            self._stop.wait(idle)

    def run_once(self, queue_name: str) -> bool:
        classes = self.allowed_classes or ["heavy", "light", "import"]
        classes = [c for c in classes if c == "light" or resources_ok(c)]
        if not classes:
            return False
        with session_scope() as db:
            job = queue.claim(db, queue_name, self.worker_id, classes)
            if job is None:
                return False
            ctx = JobContext(job.id, self.worker_id, dict(job.payload), dict(job.checkpoint), job.type,
                             job.company_id, job.attempts)
            queue.add_log(db, job.id, "info", f"Started attempt {job.attempts} on {self.worker_id}")
        self._execute(ctx)
        return True

    def _execute(self, ctx: JobContext) -> None:
        fn = HANDLERS.get(ctx.job_type)
        self._active[ctx.job_id] = ctx
        try:
            if fn is None:
                raise PermanentJobError(f"no handler for job type {ctx.job_type}")
            out = fn(ctx)
            res = out if isinstance(out, HandlerResult) else HandlerResult(result=out or {})
            with session_scope() as db:
                job = db.get(Job, ctx.job_id)
                if job is not None and job.status == "running":
                    queue.complete(db, job, res.result, waiting_review=res.waiting_review)
                    queue.add_log(db, job.id, "info", "Completed" if not res.waiting_review else "Waiting for review")
        except JobCancelled:
            with session_scope() as db:
                job = db.get(Job, ctx.job_id)
                if job is not None:
                    queue.mark_cancelled(db, job)
                    queue.add_log(db, job.id, "info", "Cancelled")
            _on_failure_hook(ctx, "cancelled")
        except Exception as exc:
            permanent = isinstance(exc, PermanentJobError)
            tb = traceback.format_exc(limit=8)
            log.warning("job failed", extra={"data": {"job": str(ctx.job_id), "type": ctx.job_type}})
            with session_scope() as db:
                job = db.get(Job, ctx.job_id)
                if job is not None:
                    queue.fail(db, job, f"{type(exc).__name__}: {exc}", retryable=not permanent)
                    queue.add_log(db, job.id, "error", f"{type(exc).__name__}: {exc}", {"traceback": tb})
                    final = job.status in ("failed", "dead")
                else:
                    final = True
            if final:
                _on_failure_hook(ctx, "failed")
        finally:
            self._active.pop(ctx.job_id, None)


FAILURE_HOOKS: dict[str, Callable[[JobContext, str], None]] = {}
# Job types whose failure hook already creates a more specific notification.
SPECIFIC_FAILURE_NOTIFICATIONS: set[str] = set()


def _on_failure_hook(ctx: JobContext, outcome: str) -> None:
    hook = FAILURE_HOOKS.get(ctx.job_type)
    try:
        if hook:
            hook(ctx, outcome)
        from leadradar.modules.crm.notifications import notify

        if outcome != "failed" or ctx.job_type in SPECIFIC_FAILURE_NOTIFICATIONS:
            return
        with session_scope() as db:
            job = db.get(Job, ctx.job_id)
            notify(db, "job_failed", "notifications.jobFailedNamed",
                   {"type": ctx.job_type, "name": job.name if job else ctx.job_type, "job_id": str(ctx.job_id)},
                   severity="error", link=f"/jobs/{ctx.job_id}", dedupe_key=f"job_failed:{ctx.job_id}")
    except Exception:  # pragma: no cover
        log.exception("failure hook error")
