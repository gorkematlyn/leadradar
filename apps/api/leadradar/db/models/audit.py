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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leadradar.db.base import Base, TimestampMixin, new_uuid


class WebsiteProperty(Base, TimestampMixin):
    """A distinct audited web property (canonical domain + meaningful path root).

    Companies / branches sharing a verified property reuse its audits.
    """

    __tablename__ = "website_properties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    property_key: Mapped[str] = mapped_column(String(300), unique=True, nullable=False)
    canonical_domain: Mapped[str] = mapped_column(String(253), nullable=False, index=True)
    start_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_shared_platform: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_audit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AuditRule(Base, TimestampMixin):
    __tablename__ = "audit_rules"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_tr: Mapped[str] = mapped_column(String(200), nullable=False)
    description_en: Mapped[str] = mapped_column(Text, nullable=False)
    description_tr: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # info, low, medium, high, critical
    applicable_industries: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    service_categories: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False, default=list)
    evidence_requirements: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Signals this rule emits when failed (consumed by the scoring engine).
    emits_signals: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    result_template_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_template_tr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation_tr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requires_browser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    public_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WebsiteAudit(Base, TimestampMixin):
    __tablename__ = "website_audits"
    __table_args__ = (Index("ix_website_audits_company_time", "company_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    property_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("website_properties.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="full")  # quick, full
    # queued, running, action_required, completed, failed, cancelled
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    start_url: Mapped[str | None] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reused_from_audit_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    pages_audited: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # lighthouse, http, timings
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # browser version, viewports
    technologies: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64))
    rule_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    automated_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditFinding(Base):
    __tablename__ = "audit_findings"
    __table_args__ = (UniqueConstraint("audit_id", "rule_key", "page_url"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_audits.id", ondelete="CASCADE"), index=True)
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # passed, failed, detected, not_detected, unknown, not_applicable, blocked, error, not_checked
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    page_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    message_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    admin_validated: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceBlob(Base):
    """Bounded binary storage for compressed evidence (screenshots, PDFs)."""

    __tablename__ = "evidence_blobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retain_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # required by reports/reviews


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_company_time", "company_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    audit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("website_audits.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("audit_findings.id", ondelete="CASCADE"), index=True)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("advertising_research_runs.id", ondelete="CASCADE")
    )
    # screenshot, html_snippet, dom_measurement, network_request, http_response, lighthouse, ad_source, osm_source
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source_url: Mapped[str | None] = mapped_column(Text)
    selector: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    blob_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evidence_blobs.id", ondelete="SET NULL"))
    detection_method: Mapped[str | None] = mapped_column(String(64))
    rule_version: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    limitations: Mapped[str | None] = mapped_column(Text)
    viewport: Mapped[str | None] = mapped_column(String(16))
    approved_for_reports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrackingDetection(Base):
    __tablename__ = "tracking_tags"
    __table_args__ = (UniqueConstraint("audit_id", "technology", "consent_state"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_audits.id", ondelete="CASCADE"), index=True)
    technology: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # detected, not_detected, unknown, blocked
    consent_state: Mapped[str] = mapped_column(String(24), nullable=False, default="initial")
    methods: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    evidence_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    identifiers_redacted: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    page_url: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    limitations: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrackingTechnology(Base, TimestampMixin):
    """Configurable detection rules for tracking technologies."""

    __tablename__ = "tracking_technologies"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)  # analytics, ads, tag_manager, consent, ux
    script_patterns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    network_patterns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    html_patterns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    runtime_globals: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    id_patterns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
