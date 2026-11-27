from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import false as sa_false
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadradar.db.base import Base, TimestampMixin, new_uuid


class CrmStatus(Base, TimestampMixin):
    __tablename__ = "crm_statuses"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(64), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(64), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_terminal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_in_pipeline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # System statuses (new, do_not_contact, archived) are used by the application and cannot be deleted.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=sa_false())


class Company(Base, TimestampMixin):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_country_industry", "country_iso2", "primary_industry_id"),
        Index("ix_companies_canonical_domain", "canonical_domain"),
        Index("ix_companies_phone", "phone_normalized"),
        Index("ix_companies_lead_score", "final_lead_score"),
        Index("ix_companies_crm_status", "crm_status"),
        Index("ix_companies_name_trgm_fallback", "normalized_name"),
        Index("ix_companies_latlon", "latitude", "longitude"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(300), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(300))
    primary_industry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("industries.id", ondelete="SET NULL"))
    additional_industry_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, default=list
    )
    industry_confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="confident")
    country_iso2: Mapped[str | None] = mapped_column(ForeignKey("countries.iso2"))
    region: Mapped[str | None] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(160), index=True)
    address: Mapped[str | None] = mapped_column(String(400))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    website_url: Mapped[str | None] = mapped_column(Text)
    canonical_domain: Mapped[str | None] = mapped_column(String(253))
    # not_found = source has no website (NOT proof of absence); unverified; verified; verified_absent
    website_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phone: Mapped[str | None] = mapped_column(String(64))
    phone_normalized: Mapped[str | None] = mapped_column(String(32))
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    crm_status: Mapped[str] = mapped_column(ForeignKey("crm_statuses.key"), nullable=False, default="new")
    analysis_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_analyzed")
    preliminary_lead_score: Mapped[int | None] = mapped_column(Integer)
    final_lead_score: Mapped[int | None] = mapped_column(Integer)
    effective_lead_score: Mapped[int | None] = mapped_column(Integer)  # override > final > preliminary
    score_classification: Mapped[str | None] = mapped_column(String(24))
    confidence_score: Mapped[int | None] = mapped_column(Integer)
    service_scores: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    advertising_platforms: Mapped[list[str]] = mapped_column(ARRAY(String(24)), nullable=False, default=list)
    last_audit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Soft delete ("trash"): hidden everywhere, restorable, purged after 30 days.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    is_chain: Mapped[bool | None] = mapped_column(Boolean)
    permanently_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rejected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    watchlisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # field -> {"source": "osm|manual|csv|apify|audit", "at": iso, "confirmed": bool}
    field_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    website_property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("website_properties.id", ondelete="SET NULL"), index=True
    )

    sources: Mapped[list[CompanySource]] = relationship(back_populates="company", cascade="all, delete-orphan")
    social_profiles: Mapped[list[SocialProfile]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    tags: Mapped[list[Tag]] = relationship(secondary="company_tags", lazy="selectin")


class CompanyLocation(Base, TimestampMixin):
    __tablename__ = "company_locations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    label: Mapped[str | None] = mapped_column(String(160))
    address: Mapped[str | None] = mapped_column(String(400))
    city: Mapped[str | None] = mapped_column(String(160))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country_iso2: Mapped[str | None] = mapped_column(String(2))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(64))


class CompanySource(Base, TimestampMixin):
    __tablename__ = "company_sources"
    __table_args__ = (
        UniqueConstraint("source", "source_key", name="uq_company_sources_source_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # osm, csv, manual, apify, quick_audit
    source_key: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g. "node/123"
    source_url: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    import_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_runs.id", ondelete="SET NULL"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship(back_populates="sources")


class Contact(Base, TimestampMixin):
    """Business contact channels only (no private employee data)."""

    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # email, phone, whatsapp, form
    value: Mapped[str] = mapped_column(String(400), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SocialProfile(Base, TimestampMixin):
    __tablename__ = "social_profiles"
    __table_args__ = (UniqueConstraint("company_id", "platform", "handle"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(24), nullable=False)
    handle: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    company: Mapped[Company] = relationship(back_populates="social_profiles")


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name_en: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_tr: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description_en: Mapped[str | None] = mapped_column(String(300))
    description_tr: Mapped[str | None] = mapped_column(String(300))
    color: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")


class CompanyTag(Base):
    __tablename__ = "company_tags"

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)


class DuplicateCandidate(Base, TimestampMixin):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (UniqueConstraint("company_a_id", "company_b_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    company_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending/merged/dismissed


class MergeHistory(Base):
    __tablename__ = "merge_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    target_company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    merged_company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    merged_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CompanyChange(Base):
    """Field-level change history (manual edits, imports, merges)."""

    __tablename__ = "company_changes"
    __table_args__ = (Index("ix_company_changes_company_time", "company_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    new_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrmActivity(Base, TimestampMixin):
    __tablename__ = "crm_activities"
    __table_args__ = (Index("ix_crm_activities_company_time", "company_id", "occurred_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    # note, status_change, call, email, meeting, proposal, follow_up, won, lost
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SuppressionEntry(Base, TimestampMixin):
    """System-wide Do Not Contact suppression; survives re-imports and deletions."""

    __tablename__ = "suppression_entries"
    __table_args__ = (
        Index(
            "uq_suppression_active",
            "kind",
            "value",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # company, domain, email, phone, source
    value: Mapped[str] = mapped_column(String(400), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(400))
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removal_reason: Mapped[str | None] = mapped_column(String(400))


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (Index("ix_change_events_company_time", "company_id", "detected_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    before: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    after: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    significance: Mapped[str] = mapped_column(String(16), nullable=False, default="minor")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CompanySnapshot(Base):
    """Normalized monitoring snapshot used for change detection."""

    __tablename__ = "company_snapshots"
    __table_args__ = (Index("ix_company_snapshots_company_time", "company_id", "taken_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
