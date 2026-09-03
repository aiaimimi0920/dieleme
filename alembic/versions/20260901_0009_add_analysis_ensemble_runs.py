"""add versioned analysis module B run receipts

Revision ID: 20260901_0009
Revises: 20260606_0008
Create Date: 2026-09-01 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260901_0009"
down_revision = "20260606_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fapai_analysis_run",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("candidate_models", sa.JSON(), nullable=True),
        sa.Column("arbiter_model", sa.String(length=128), nullable=True),
        sa.Column("arbiter_independent_model", sa.Boolean(), nullable=True),
        sa.Column("artifact_paths", sa.JSON(), nullable=True),
        sa.Column("receipt", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["fapai_seed_item.item_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
        sa.UniqueConstraint(
            "item_id",
            "pipeline_version",
            "input_sha256",
            name="uq_fapai_analysis_run_item_version_input",
        ),
    )
    op.create_index("ix_fapai_analysis_run_item_id", "fapai_analysis_run", ["item_id"], unique=False)
    op.create_index(
        "ix_fapai_analysis_run_pipeline_version",
        "fapai_analysis_run",
        ["pipeline_version"],
        unique=False,
    )
    op.create_index(
        "ix_fapai_analysis_run_input_sha256",
        "fapai_analysis_run",
        ["input_sha256"],
        unique=False,
    )
    op.create_index("ix_fapai_analysis_run_mode", "fapai_analysis_run", ["mode"], unique=False)
    op.create_index("ix_fapai_analysis_run_status", "fapai_analysis_run", ["status"], unique=False)
    op.create_index(
        "ix_fapai_analysis_run_completed_at",
        "fapai_analysis_run",
        ["completed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fapai_analysis_run_completed_at", table_name="fapai_analysis_run")
    op.drop_index("ix_fapai_analysis_run_status", table_name="fapai_analysis_run")
    op.drop_index("ix_fapai_analysis_run_mode", table_name="fapai_analysis_run")
    op.drop_index("ix_fapai_analysis_run_input_sha256", table_name="fapai_analysis_run")
    op.drop_index("ix_fapai_analysis_run_pipeline_version", table_name="fapai_analysis_run")
    op.drop_index("ix_fapai_analysis_run_item_id", table_name="fapai_analysis_run")
    op.drop_table("fapai_analysis_run")
