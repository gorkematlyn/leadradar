"""bilingual tags, customizable ad provider URLs, scoring version reset

* tags: ``name``/``description`` become ``name_en``/``description_en``; ``name_tr`` and
  ``description_tr`` are added (filled from the English values). Saved filters that refer
  to tags by name are rewritten to refer to tag IDs.
* advertising_providers: ``admin_customized`` so edited URLs survive re-seeding.
* scoring_profiles: profiles whose values still equal the shipped defaults are reset to
  version 1 (earlier releases bumped the version even when "Save" changed nothing).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-27 10:00:00
"""
from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TAG_KEYS = ("tags_any", "tags_all", "tags_exclude")


def _is_uuid(v: object) -> bool:
    try:
        uuid.UUID(str(v))
        return True
    except ValueError:
        return False


def upgrade() -> None:
    conn = op.get_bind()

    # --- tags ---------------------------------------------------------------------------
    op.drop_constraint("uq_tags_name", "tags", type_="unique")
    op.alter_column("tags", "name", new_column_name="name_en")
    op.alter_column("tags", "description", new_column_name="description_en")
    op.add_column("tags", sa.Column("name_tr", sa.String(length=64), nullable=True))
    op.add_column("tags", sa.Column("description_tr", sa.String(length=300), nullable=True))
    conn.execute(sa.text("UPDATE tags SET name_tr = name_en, description_tr = description_en"))
    op.alter_column("tags", "name_tr", nullable=False)
    op.create_unique_constraint("uq_tags_name_en", "tags", ["name_en"])
    op.create_unique_constraint("uq_tags_name_tr", "tags", ["name_tr"])

    by_name = {str(n).lower(): str(i) for i, n in conn.execute(sa.text("SELECT id, name_en FROM tags"))}
    for fid, filters in conn.execute(sa.text("SELECT id, filters FROM saved_filters")).all():
        f = dict(filters or {})
        changed = False
        for key in TAG_KEYS:
            vals = f.get(key)
            if not isinstance(vals, list):
                continue
            new = []
            for v in vals:
                if _is_uuid(v):
                    new.append(str(v))
                elif str(v).lower() in by_name:
                    new.append(by_name[str(v).lower()])
                    changed = True
                else:
                    changed = True  # tag no longer exists: drop it
            f[key] = new
        if changed:
            conn.execute(sa.text("UPDATE saved_filters SET filters = CAST(:f AS jsonb) WHERE id = :id"),
                         {"f": json.dumps(f), "id": fid})

    # --- advertising providers -------------------------------------------------------------
    op.add_column("advertising_providers", sa.Column("admin_customized", sa.Boolean(), nullable=False,
                                                     server_default=sa.false()))

    # --- scoring version reset -------------------------------------------------------------
    from leadradar.seeds import defaults as D

    rows = conn.execute(sa.text(
        "SELECT id, category_limits, thresholds, confidence_weights, version FROM scoring_profiles")).all()
    for pid, limits, thresholds, weights, version in rows:
        if version == 1:
            continue
        if limits == D.CATEGORY_LIMITS and thresholds == D.THRESHOLDS and weights == D.CONFIDENCE_WEIGHTS:
            customized_rules = conn.execute(sa.text(
                "SELECT count(*) FROM scoring_rules WHERE profile_id = :p AND admin_customized"), {"p": pid}).scalar()
            if customized_rules:
                continue
            conn.execute(sa.text("UPDATE scoring_profiles SET version = 1 WHERE id = :p"), {"p": pid})
            conn.execute(sa.text(
                "UPDATE lead_scores SET profile_version = 1, "
                "breakdown = jsonb_set(breakdown, '{profile,version}', '1'::jsonb, false) "
                "WHERE profile_id = :p"), {"p": pid})


def downgrade() -> None:
    op.drop_column("advertising_providers", "admin_customized")
    op.drop_constraint("uq_tags_name_tr", "tags", type_="unique")
    op.drop_constraint("uq_tags_name_en", "tags", type_="unique")
    op.drop_column("tags", "description_tr")
    op.drop_column("tags", "name_tr")
    op.alter_column("tags", "description_en", new_column_name="description")
    op.alter_column("tags", "name_en", new_column_name="name")
    op.create_unique_constraint("uq_tags_name", "tags", ["name"])
