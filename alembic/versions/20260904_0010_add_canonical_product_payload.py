"""add source-neutral canonical product payload

Revision ID: 20260904_0010
Revises: 20260901_0009
Create Date: 2026-09-04 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260904_0010"
down_revision = "20260901_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("property_listing", sa.Column("record_schema_version", sa.Integer(), nullable=True))
    op.add_column("property_listing", sa.Column("canonical_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("property_listing", "canonical_payload")
    op.drop_column("property_listing", "record_schema_version")
