"""add explicit collection stage state and search task cursor

Revision ID: 20260512_0004
Revises: 20260512_0003
Create Date: 2026-05-12 23:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260512_0004"
down_revision = "20260512_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("property_audit", sa.Column("seed_status", sa.String(length=32), nullable=True))
    op.add_column("property_audit", sa.Column("seed_first_seen_at", sa.DateTime(), nullable=True))
    op.add_column("property_audit", sa.Column("seed_last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("property_audit", sa.Column("seed_source_page_url", sa.Text(), nullable=True))
    op.add_column("property_audit", sa.Column("detail_status", sa.String(length=32), nullable=True))
    op.add_column("property_audit", sa.Column("detail_last_error", sa.Text(), nullable=True))
    op.add_column("property_audit", sa.Column("detail_retry_count", sa.Integer(), nullable=True))
    op.add_column("property_audit", sa.Column("detail_lease_until", sa.DateTime(), nullable=True))
    op.add_column("property_audit", sa.Column("analysis_status", sa.String(length=32), nullable=True))
    op.add_column("property_audit", sa.Column("analysis_ready", sa.Boolean(), nullable=True))
    op.add_column("property_audit", sa.Column("analysis_missing_fields", sa.JSON(), nullable=True))
    op.add_column("property_audit", sa.Column("analysis_last_scored_at", sa.DateTime(), nullable=True))
    op.add_column("property_audit", sa.Column("analysis_model_version", sa.String(length=64), nullable=True))

    op.create_index("ix_property_audit_seed_status", "property_audit", ["seed_status"], unique=False)
    op.create_index("ix_property_audit_detail_status", "property_audit", ["detail_status"], unique=False)
    op.create_index("ix_property_audit_analysis_status", "property_audit", ["analysis_status"], unique=False)
    op.create_index("ix_property_audit_analysis_ready", "property_audit", ["analysis_ready"], unique=False)

    op.create_table(
        "property_search_task",
        sa.Column("task_key", sa.String(length=128), nullable=False),
        sa.Column("location_code", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=True),
        sa.Column("sort_param", sa.String(length=16), nullable=True),
        sa.Column("next_page", sa.Integer(), nullable=False),
        sa.Column("max_page", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("leased_by", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("zero_bid_terminated", sa.Boolean(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("task_key"),
    )
    op.create_index("ix_property_search_task_location_code", "property_search_task", ["location_code"], unique=False)
    op.create_index("ix_property_search_task_category", "property_search_task", ["category"], unique=False)
    op.create_index("ix_property_search_task_sort_param", "property_search_task", ["sort_param"], unique=False)
    op.create_index("ix_property_search_task_status", "property_search_task", ["status"], unique=False)
    op.create_index("ix_property_search_task_leased_by", "property_search_task", ["leased_by"], unique=False)
    op.create_index("ix_property_search_task_lease_until", "property_search_task", ["lease_until"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_property_search_task_lease_until", table_name="property_search_task")
    op.drop_index("ix_property_search_task_leased_by", table_name="property_search_task")
    op.drop_index("ix_property_search_task_status", table_name="property_search_task")
    op.drop_index("ix_property_search_task_sort_param", table_name="property_search_task")
    op.drop_index("ix_property_search_task_category", table_name="property_search_task")
    op.drop_index("ix_property_search_task_location_code", table_name="property_search_task")
    op.drop_table("property_search_task")

    op.drop_index("ix_property_audit_analysis_ready", table_name="property_audit")
    op.drop_index("ix_property_audit_analysis_status", table_name="property_audit")
    op.drop_index("ix_property_audit_detail_status", table_name="property_audit")
    op.drop_index("ix_property_audit_seed_status", table_name="property_audit")

    op.drop_column("property_audit", "analysis_model_version")
    op.drop_column("property_audit", "analysis_last_scored_at")
    op.drop_column("property_audit", "analysis_missing_fields")
    op.drop_column("property_audit", "analysis_ready")
    op.drop_column("property_audit", "analysis_status")
    op.drop_column("property_audit", "detail_lease_until")
    op.drop_column("property_audit", "detail_retry_count")
    op.drop_column("property_audit", "detail_last_error")
    op.drop_column("property_audit", "detail_status")
    op.drop_column("property_audit", "seed_source_page_url")
    op.drop_column("property_audit", "seed_last_seen_at")
    op.drop_column("property_audit", "seed_first_seen_at")
    op.drop_column("property_audit", "seed_status")
