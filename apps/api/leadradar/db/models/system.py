from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leadradar.db.base import Base, TimestampMixin, new_uuid

JOB_STATUSES = (
    "queued",
    "running",
    "waiting_review",
    "completed",
    "failed",
    "cancelled",
    "paused",
    "dead",
)


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "queue", "status", "priority", "run_at"),
        Index("ix_jobs_concurrency_running", "concurrency_key", postgresql_where=text("status = 'running'")),
        Index(
            "uq_jobs_idempotency_active",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND status IN ('queued','running','paused')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    queue: Mapped[str] = mapped_column(String(24), nullable=False)  # discovery, analysis
    resource_class: Mapped[str] = mapped_column(String(16), nullable=False, default="light")  # light, heavy
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)  # lower = sooner
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    concurrency_key: Mapped[str | None] = mapped_column(String(200))
    depends_on: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage: Mapped[str | None] = mapped_column(String(120))
    processed_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_count: Mapped[int | None] = mapped_column(BigInteger)  # null = unknown (no fake percentages)
    error: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class JobAttempt(Base):
    __tablename__ = "job_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    worker: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)


class JobLog(Base):
    __tablename__ = "job_logs"
    __table_args__ = (Index("ix_job_logs_job_time", "job_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SchedulerLock(Base):
    """Named singleton tasks with last-run bookkeeping (guarded by advisory locks)."""

    __tablename__ = "scheduler_tasks"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(Text)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    queues: Mapped[list[str]] = mapped_column(ARRAY(String(24)), nullable=False, default=list)
    hostname: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    running_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SavedFilter(Base, TimestampMixin):
    __tablename__ = "saved_filters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class SavedCampaign(Base, TimestampMixin):
    """A saved discovery / research configuration (not an outreach campaign)."""

    __tablename__ = "saved_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    regions: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list)
    industries: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    cities: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False, default=list)
    discovery_sources: Mapped[list[str]] = mapped_column(ARRAY(String(24)), nullable=False, default=list)
    # Actions: import (geofabrik), audit (quick|full), ads
    actions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    audit_rules: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    scoring_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scoring_profiles.id", ondelete="SET NULL"))
    record_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    schedule_interval_hours: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignRun(Base, TimestampMixin):
    __tablename__ = "campaign_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("saved_campaigns.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # manual, schedule
    job_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_unread", "user_id", "read_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))  # null = all admins
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    # Translation key + params, rendered on the client in the user's language.
    message_key: Mapped[str] = mapped_column(String(96), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    link: Mapped[str | None] = mapped_column(String(300))
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RetentionPolicy(Base, TimestampMixin):
    __tablename__ = "retention_policies"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(120), nullable=False)
    retention_days: Mapped[int | None] = mapped_column(Integer)  # null = keep
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
