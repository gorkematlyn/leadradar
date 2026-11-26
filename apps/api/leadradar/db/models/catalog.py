from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from leadradar.db.base import Base, TimestampMixin, new_uuid


class Region(Base, TimestampMixin):
    __tablename__ = "regions"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # europe, asia, ...
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Country(Base, TimestampMixin):
    __tablename__ = "countries"

    iso2: Mapped[str] = mapped_column(String(2), primary_key=True)
    iso3: Mapped[str] = mapped_column(String(3), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(120), nullable=False)
    region_code: Mapped[str] = mapped_column(ForeignKey("regions.code"), nullable=False, index=True)
    subregion: Mapped[str | None] = mapped_column(String(64))
    # Flag asset path relative to the web app's /flags directory (self-hosted SVGs).
    flag_asset: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Geofabrik index id overrides (null = resolve from index by ISO code).
    geofabrik_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(120)))
    import_status: Mapped[str] = mapped_column(String(24), nullable=False, default="never")
    last_import_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Industry(Base, TimestampMixin):
    __tablename__ = "industries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    name_tr: Mapped[str] = mapped_column(String(120), nullable=False)
    description_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description_tr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_priority: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relevant_services: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False, default=list)
    # Audit rule keys applicable to this industry (empty = all general rules).
    applicable_audit_rules: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    # Conversion features that are relevant (booking, quote_form, reservation, ecommerce ...).
    relevant_features: Mapped[list[str]] = mapped_column(ARRAY(String(48)), nullable=False, default=list)
    review_template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_templates.id", ondelete="SET NULL"))
    scoring_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scoring_profiles.id", ondelete="SET NULL")
    )
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    rules: Mapped[list[IndustryRule]] = relationship(back_populates="industry", cascade="all, delete-orphan")


class IndustryRule(Base, TimestampMixin):
    """OSM tag matching rule.

    ``conditions`` structure::

        {"all": [{"key": "amenity", "op": "eq", "value": "dentist"}],
         "any": [...], "exclude": [...]}

    ``op`` is one of eq, in, exists, regex. ``classification`` is ``confident`` or
    ``review`` (uncertain matches become review candidates, never confirmed members).
    """

    __tablename__ = "industry_rules"
    __table_args__ = (UniqueConstraint("industry_id", "key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    industry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("industries.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False, default="confident")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    industry: Mapped[Industry] = relationship(back_populates="rules")


class ApplicationSetting(Base, TimestampMixin):
    __tablename__ = "application_settings"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSONB)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    admin_customized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SavedGeoSelection(Base, TimestampMixin):
    __tablename__ = "saved_geo_selections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    regions: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)), nullable=False, default=list)
    industries: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    cities: Mapped[list[str]] = mapped_column(ARRAY(String(120)), nullable=False, default=list)


class ImportRun(Base, TimestampMixin):
    __tablename__ = "import_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # geofabrik, csv, apify, manual
    country_iso2: Mapped[str | None] = mapped_column(ForeignKey("countries.iso2"))
    extract_id: Mapped[str | None] = mapped_column(String(120))
    extract_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
