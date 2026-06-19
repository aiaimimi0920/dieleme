"""add seed scan rescan state columns

Revision ID: 20260606_0008
Revises: 20260602_0007
Create Date: 2026-06-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260606_0008"
down_revision = "20260602_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fapai_seed_scan_progress", sa.Column("last_rescan_at", sa.DateTime(), nullable=True))
    op.add_column(
        "fapai_seed_scan_progress",
        sa.Column("rescan_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_fapai_seed_scan_progress_last_rescan_at",
        "fapai_seed_scan_progress",
        ["last_rescan_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fapai_seed_scan_progress_last_rescan_at", table_name="fapai_seed_scan_progress")
    op.drop_column("fapai_seed_scan_progress", "rescan_count")
    op.drop_column("fapai_seed_scan_progress", "last_rescan_at")
