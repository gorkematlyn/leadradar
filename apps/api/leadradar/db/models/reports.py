from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leadradar.db.base import Base, TimestampMixin, new_uuid


class ReportTemplate(Base, TimestampMixin):
    __tablename__ = "report_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(120), nullable=False)
    default_sections: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Report(Base, TimestampMixin):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("report_templates.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="snapshot")  # live, snapshot
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    sections: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False, default=list)
    selected_evidence_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    selected_ad_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    public_notes: Mapped[str | None] = mapped_column(Text)
    branding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # draft, published, revoked
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    published_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReportVersion(Base):
    """Sanitized, self-contained public data for one approved version of a report.

    ``content`` is built by :mod:`leadradar.modules.reporting.builder` from an explicit
    allow-list; internal objects are never serialized into it.
    """

    __tablename__ = "report_versions"
    __table_args__ = (UniqueConstraint("report_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    audit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")  # draft, approved
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReportAccessToken(Base, TimestampMixin):
    __tablename__ = "report_access_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    token_hint: Mapped[str] = mapped_column(String(12), nullable=False)  # first chars, for admin display
    # For snapshot mode: pinned version. Null = follow report's published (live) version.
    pinned_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allow_pdf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReportAsset(Base):
    """Asset referenced by a report version (approved screenshots, generated PDFs)."""

    __tablename__ = "report_assets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    report_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("report_versions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # screenshot, pdf, logo
    language: Mapped[str | None] = mapped_column(String(8))
    # Opaque public id (never the blob id) so assets can be referenced from public pages.
    public_id: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    blob_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evidence_blobs.id", ondelete="CASCADE"))
    caption: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
