"""add standardized community audit fields to property_audit

Revision ID: 20260601_0006
Revises: 20260515_0005
Create Date: 2026-06-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260601_0006"
down_revision = "20260515_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("property_audit", sa.Column("community_name_source", sa.String(length=64), nullable=True))
    op.add_column("property_audit", sa.Column("community_name_confidence", sa.Numeric(6, 4), nullable=True))
    op.add_column("property_audit", sa.Column("community_stable_key", sa.String(length=512), nullable=True))
    op.add_column("property_audit", sa.Column("community_raw_name", sa.String(length=256), nullable=True))
    op.add_column("property_audit", sa.Column("beike_community_id", sa.String(length=128), nullable=True))
    op.create_index("ix_property_audit_community_stable_key", "property_audit", ["community_stable_key"], unique=False)
    op.create_index("ix_property_audit_beike_community_id", "property_audit", ["beike_community_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_property_audit_beike_community_id", table_name="property_audit")
    op.drop_index("ix_property_audit_community_stable_key", table_name="property_audit")
    op.drop_column("property_audit", "beike_community_id")
    op.drop_column("property_audit", "community_raw_name")
    op.drop_column("property_audit", "community_stable_key")
    op.drop_column("property_audit", "community_name_confidence")
    op.drop_column("property_audit", "community_name_source")
