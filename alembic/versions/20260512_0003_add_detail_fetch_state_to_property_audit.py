"""add detail fetch state fields to property_audit

Revision ID: 20260512_0003
Revises: 20260512_0002
Create Date: 2026-05-12 22:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260512_0003"
down_revision = "20260512_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("property_audit", sa.Column("detail_fetch_status", sa.String(length=64), nullable=True))
    op.add_column("property_audit", sa.Column("detail_fetch_attempted_at", sa.DateTime(), nullable=True))
    op.add_column("property_audit", sa.Column("detail_fetch_attempt_count", sa.Integer(), nullable=True))
    op.add_column("property_audit", sa.Column("detail_fetch_last_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("property_audit", "detail_fetch_last_url")
    op.drop_column("property_audit", "detail_fetch_attempt_count")
    op.drop_column("property_audit", "detail_fetch_attempted_at")
    op.drop_column("property_audit", "detail_fetch_status")
