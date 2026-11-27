from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leadradar.db.base import Base, TimestampMixin, new_uuid


class AdvertisingProvider(Base, TimestampMixin):
    __tablename__ = "advertising_providers"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)  # meta, google, linkedin, tiktok, microsoft, openai
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # automated (official API configured), manual (official link + manual entry), unsupported
    automation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    automation_note_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    automation_note_tr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manual_search_url_template: Mapped[str | None] = mapped_column(Text)
    official_source_url: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # non-secret config
    credentials_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted JSON
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    recheck_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True once an administrator edited the URLs; seeding then leaves them alone.
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                   server_default=sa_false())


class Advertiser(Base, TimestampMixin):
    __tablename__ = "advertisers"
    __table_args__ = (UniqueConstraint("platform", "platform_advertiser_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    platform: Mapped[str] = mapped_column(ForeignKey("advertising_providers.key"), nullable=False)
    platform_advertiser_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    match_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # pending (match required), confirmed, rejected
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    source_url: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AdvertisingResearchRun(Base, TimestampMixin):
    __tablename__ = "advertising_research_runs"
    __table_args__ = (Index("ix_ad_runs_company_platform", "company_id", "platform", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(ForeignKey("advertising_providers.key"), nullable=False)
    # found, no_results, match_required, not_checked, rate_limited, blocked, unsupported, error
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_checked")
    method: Mapped[str] = mapped_column(String(16), nullable=False)  # automated, manual
    search_terms: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    search_scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_ads_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    researched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Advertisement(Base, TimestampMixin):
    __tablename__ = "advertisements"
    __table_args__ = (UniqueConstraint("platform", "platform_ad_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    platform: Mapped[str] = mapped_column(ForeignKey("advertising_providers.key"), nullable=False)
    platform_ad_id: Mapped[str] = mapped_column(String(200), nullable=False)
    advertiser_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("advertisers.id", ondelete="CASCADE"), index=True)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("advertising_research_runs.id", ondelete="SET NULL")
    )
    ad_format: Mapped[str | None] = mapped_column(String(48))
    ad_text: Mapped[str | None] = mapped_column(Text)
    landing_page_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(16))  # active, inactive, unknown
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_start_date: Mapped[date | None] = mapped_column(Date)
    source_end_date: Mapped[date | None] = mapped_column(Date)
    geographic_scope: Mapped[list[str]] = mapped_column(ARRAY(String(8)), nullable=False, default=list)
    source_url: Mapped[str | None] = mapped_column(Text)
    approved_for_reports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ProviderUsage(Base):
    """Usage and cost tracking for optional paid providers and manual expenses."""

    __tablename__ = "provider_usage"
    __table_args__ = (Index("ix_provider_usage_provider_time", "provider", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)  # apify, meta_api, infrastructure, ...
    kind: Mapped[str] = mapped_column(String(24), nullable=False)  # actor_run, api_call, manual_expense
    description: Mapped[str | None] = mapped_column(String(300))
    reference: Mapped[str | None] = mapped_column(String(200))  # actor run id
    estimated_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 4))
    actual_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 4))
    cost_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    units: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str | None] = mapped_column(String(24))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ApifyActorConfig(Base, TimestampMixin):
    __tablename__ = "apify_actor_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # discovery, advertising
    input_template: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    allowed_input_keys: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    field_mapping: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    max_items: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    max_cost_usd: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
