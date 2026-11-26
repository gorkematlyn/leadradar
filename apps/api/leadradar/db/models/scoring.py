from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from leadradar.db.base import Base, TimestampMixin, new_uuid


class ReviewTemplate(Base, TimestampMixin):
    __tablename__ = "review_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ReviewQuestion(Base, TimestampMixin):
    __tablename__ = "review_questions"
    __table_args__ = (UniqueConstraint("template_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    template_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_templates.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    text_en: Mapped[str] = mapped_column(Text, nullable=False)
    text_tr: Mapped[str] = mapped_column(Text, nullable=False)
    # Signal emitted for a "yes" answer (e.g. review.visual_redesign_confirmed).
    yes_signal: Mapped[str | None] = mapped_column(String(64))
    no_signal: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ReviewResponse(Base, TimestampMixin):
    __tablename__ = "review_responses"
    __table_args__ = (UniqueConstraint("audit_id", "question_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    audit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("website_audits.id", ondelete="CASCADE"), index=True)
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    answer: Mapped[str] = mapped_column(String(16), nullable=False)  # yes, no, unknown, not_applicable
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ScoringProfile(Base, TimestampMixin):
    __tablename__ = "scoring_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # {"service_need": 35, "commercial_activity": 30, "target_fit": 20, "contactability": 15}
    category_limits: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {"high_priority": 80, "strong_potential": 60, "requires_review": 40}
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Service keys whose opportunity scores receive a multiplier in this profile.
    service_focus: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False, default=list)
    min_confidence_for_high_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ScoringRule(Base, TimestampMixin):
    """A versioned rule: when ``signal`` is present, contribute ``points`` to ``category``.

    ``exclusive_group``: only the highest contribution within a group counts (prevents
    duplicate scoring for overlapping problems). ``kind`` is contribution, penalty or
    exclusion. ``requires_absent`` lists signals that must NOT be present.
    """

    __tablename__ = "scoring_rules"
    __table_args__ = (UniqueConstraint("profile_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scoring_profiles.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="contribution")
    category: Mapped[str | None] = mapped_column(String(32))
    signal: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_absent: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exclusive_group: Mapped[str | None] = mapped_column(String(48))
    title_en: Mapped[str] = mapped_column(String(200), nullable=False)
    title_tr: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    explanation_tr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ServiceRule(Base, TimestampMixin):
    """Service opportunity rule: signal -> points for one service."""

    __tablename__ = "service_rules"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    service: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(64), nullable=False)
    requires_all: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    requires_absent: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recommendation_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation_tr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class LeadScore(Base):
    __tablename__ = "lead_scores"
    __table_args__ = (Index("ix_lead_scores_company_time", "company_id", "calculated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    audit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("website_audits.id", ondelete="SET NULL"))
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scoring_profiles.id", ondelete="CASCADE"))
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)  # preliminary, final
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    classification: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)  # categories, rules, penalties, exclusions
    signals: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ServiceScore(Base):
    __tablename__ = "service_scores"
    __table_args__ = (Index("ix_service_scores_lead", "lead_score_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    lead_score_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("lead_scores.id", ondelete="CASCADE"))
    service: Mapped[str] = mapped_column(String(48), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rules: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)


class ScoreOverride(Base):
    __tablename__ = "score_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    original_score: Mapped[int | None] = mapped_column(Integer)
    override_score: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
