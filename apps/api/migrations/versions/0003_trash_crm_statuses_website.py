"""company trash, editable CRM statuses, website status fix

* companies.deleted_at: soft delete (trash), purged after 30 days.
* crm_statuses.is_system: new / do_not_contact / archived cannot be deleted.
* Companies without a website that still say "unverified" are set to "not_found".

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-28 10:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_companies_deleted_at"), "companies", ["deleted_at"], unique=False)
    op.add_column("crm_statuses", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE crm_statuses SET is_system = true WHERE key IN ('new', 'do_not_contact', 'archived')")
    op.execute("UPDATE companies SET website_status = 'not_found' "
               "WHERE (website_url IS NULL OR website_url = '') AND website_status = 'unverified'")


def downgrade() -> None:
    op.drop_column("crm_statuses", "is_system")
    op.drop_index(op.f("ix_companies_deleted_at"), table_name="companies")
    op.drop_column("companies", "deleted_at")
