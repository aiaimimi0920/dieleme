"""add db backed seed scan and detail queue tables

Revision ID: 20260602_0007
Revises: 20260601_0006
Create Date: 2026-06-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260602_0007"
down_revision = "20260601_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fapai_seed_scan_job",
        sa.Column("job_key", sa.String(length=192), nullable=False),
        sa.Column("province", sa.String(length=64), nullable=True),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column("district", sa.String(length=64), nullable=True),
        sa.Column("location_code", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_url_template", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("job_key"),
    )
    op.create_index("ix_fapai_seed_scan_job_province", "fapai_seed_scan_job", ["province"], unique=False)
    op.create_index("ix_fapai_seed_scan_job_city", "fapai_seed_scan_job", ["city"], unique=False)
    op.create_index("ix_fapai_seed_scan_job_district", "fapai_seed_scan_job", ["district"], unique=False)
    op.create_index("ix_fapai_seed_scan_job_location_code", "fapai_seed_scan_job", ["location_code"], unique=False)
    op.create_index("ix_fapai_seed_scan_job_category", "fapai_seed_scan_job", ["category"], unique=False)
    op.create_index("ix_fapai_seed_scan_job_status", "fapai_seed_scan_job", ["status"], unique=False)
    op.create_index("ix_fapai_seed_scan_job_completed_at", "fapai_seed_scan_job", ["completed_at"], unique=False)

    op.create_table(
        "fapai_seed_scan_progress",
        sa.Column("progress_key", sa.String(length=256), nullable=False),
        sa.Column("job_key", sa.String(length=192), nullable=False),
        sa.Column("sort_key", sa.String(length=64), nullable=False),
        sa.Column("sort_name", sa.String(length=128), nullable=True),
        sa.Column("st_param", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("next_page", sa.Integer(), nullable=False),
        sa.Column("max_page", sa.Integer(), nullable=True),
        sa.Column("last_success_page", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("leased_by", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("last_fetch_url", sa.Text(), nullable=True),
        sa.Column("last_item_count", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_key"], ["fapai_seed_scan_job.job_key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("progress_key"),
        sa.UniqueConstraint("job_key", "sort_key", name="uq_fapai_seed_scan_progress_job_sort"),
    )
    op.create_index("ix_fapai_seed_scan_progress_job_key", "fapai_seed_scan_progress", ["job_key"], unique=False)
    op.create_index("ix_fapai_seed_scan_progress_sort_key", "fapai_seed_scan_progress", ["sort_key"], unique=False)
    op.create_index("ix_fapai_seed_scan_progress_st_param", "fapai_seed_scan_progress", ["st_param"], unique=False)
    op.create_index("ix_fapai_seed_scan_progress_status", "fapai_seed_scan_progress", ["status"], unique=False)
    op.create_index("ix_fapai_seed_scan_progress_leased_by", "fapai_seed_scan_progress", ["leased_by"], unique=False)
    op.create_index("ix_fapai_seed_scan_progress_lease_until", "fapai_seed_scan_progress", ["lease_until"], unique=False)
    op.create_index("ix_fapai_seed_scan_progress_completed_at", "fapai_seed_scan_progress", ["completed_at"], unique=False)

    op.create_table(
        "fapai_seed_item",
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("source_item_id", sa.String(length=64), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("first_seen_job_key", sa.String(length=192), nullable=True),
        sa.Column("first_seen_sort_key", sa.String(length=64), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("source_payload", sa.JSON(), nullable=True),
        sa.Column("detail_attempt_count", sa.Integer(), nullable=False),
        sa.Column("detail_last_error", sa.Text(), nullable=True),
        sa.Column("detail_leased_by", sa.String(length=128), nullable=True),
        sa.Column("detail_lease_until", sa.DateTime(), nullable=True),
        sa.Column("detail_completed_at", sa.DateTime(), nullable=True),
        sa.Column("final_json_path", sa.Text(), nullable=True),
        sa.Column("selected_json_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("item_id"),
    )
    op.create_index("ix_fapai_seed_item_source_item_id", "fapai_seed_item", ["source_item_id"], unique=False)
    op.create_index("ix_fapai_seed_item_status", "fapai_seed_item", ["status"], unique=False)
    op.create_index("ix_fapai_seed_item_first_seen_job_key", "fapai_seed_item", ["first_seen_job_key"], unique=False)
    op.create_index("ix_fapai_seed_item_first_seen_sort_key", "fapai_seed_item", ["first_seen_sort_key"], unique=False)
    op.create_index("ix_fapai_seed_item_first_seen_at", "fapai_seed_item", ["first_seen_at"], unique=False)
    op.create_index("ix_fapai_seed_item_last_seen_at", "fapai_seed_item", ["last_seen_at"], unique=False)
    op.create_index("ix_fapai_seed_item_detail_leased_by", "fapai_seed_item", ["detail_leased_by"], unique=False)
    op.create_index("ix_fapai_seed_item_detail_lease_until", "fapai_seed_item", ["detail_lease_until"], unique=False)
    op.create_index("ix_fapai_seed_item_detail_completed_at", "fapai_seed_item", ["detail_completed_at"], unique=False)

    op.create_table(
        "fapai_seed_occurrence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("occurrence_key", sa.String(length=128), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("job_key", sa.String(length=192), nullable=False),
        sa.Column("progress_key", sa.String(length=256), nullable=False),
        sa.Column("sort_key", sa.String(length=64), nullable=False),
        sa.Column("sort_name", sa.String(length=128), nullable=True),
        sa.Column("st_param", sa.String(length=16), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("source_page_url", sa.Text(), nullable=True),
        sa.Column("source_final_url", sa.Text(), nullable=True),
        sa.Column("raw_item", sa.JSON(), nullable=True),
        sa.Column("seen_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["fapai_seed_item.item_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fapai_seed_occurrence_occurrence_key", "fapai_seed_occurrence", ["occurrence_key"], unique=True)
    op.create_index("ix_fapai_seed_occurrence_item_id", "fapai_seed_occurrence", ["item_id"], unique=False)
    op.create_index("ix_fapai_seed_occurrence_job_key", "fapai_seed_occurrence", ["job_key"], unique=False)
    op.create_index("ix_fapai_seed_occurrence_progress_key", "fapai_seed_occurrence", ["progress_key"], unique=False)
    op.create_index("ix_fapai_seed_occurrence_sort_key", "fapai_seed_occurrence", ["sort_key"], unique=False)
    op.create_index("ix_fapai_seed_occurrence_st_param", "fapai_seed_occurrence", ["st_param"], unique=False)
    op.create_index("ix_fapai_seed_occurrence_page", "fapai_seed_occurrence", ["page"], unique=False)
    op.create_index("ix_fapai_seed_occurrence_seen_at", "fapai_seed_occurrence", ["seen_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_fapai_seed_occurrence_seen_at", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_page", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_st_param", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_sort_key", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_progress_key", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_job_key", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_item_id", table_name="fapai_seed_occurrence")
    op.drop_index("ix_fapai_seed_occurrence_occurrence_key", table_name="fapai_seed_occurrence")
    op.drop_table("fapai_seed_occurrence")

    op.drop_index("ix_fapai_seed_item_detail_completed_at", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_detail_lease_until", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_detail_leased_by", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_last_seen_at", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_first_seen_at", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_first_seen_sort_key", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_first_seen_job_key", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_status", table_name="fapai_seed_item")
    op.drop_index("ix_fapai_seed_item_source_item_id", table_name="fapai_seed_item")
    op.drop_table("fapai_seed_item")

    op.drop_index("ix_fapai_seed_scan_progress_completed_at", table_name="fapai_seed_scan_progress")
    op.drop_index("ix_fapai_seed_scan_progress_lease_until", table_name="fapai_seed_scan_progress")
    op.drop_index("ix_fapai_seed_scan_progress_leased_by", table_name="fapai_seed_scan_progress")
    op.drop_index("ix_fapai_seed_scan_progress_status", table_name="fapai_seed_scan_progress")
    op.drop_index("ix_fapai_seed_scan_progress_st_param", table_name="fapai_seed_scan_progress")
    op.drop_index("ix_fapai_seed_scan_progress_sort_key", table_name="fapai_seed_scan_progress")
    op.drop_index("ix_fapai_seed_scan_progress_job_key", table_name="fapai_seed_scan_progress")
    op.drop_table("fapai_seed_scan_progress")

    op.drop_index("ix_fapai_seed_scan_job_completed_at", table_name="fapai_seed_scan_job")
    op.drop_index("ix_fapai_seed_scan_job_status", table_name="fapai_seed_scan_job")
    op.drop_index("ix_fapai_seed_scan_job_category", table_name="fapai_seed_scan_job")
    op.drop_index("ix_fapai_seed_scan_job_location_code", table_name="fapai_seed_scan_job")
    op.drop_index("ix_fapai_seed_scan_job_district", table_name="fapai_seed_scan_job")
    op.drop_index("ix_fapai_seed_scan_job_city", table_name="fapai_seed_scan_job")
    op.drop_index("ix_fapai_seed_scan_job_province", table_name="fapai_seed_scan_job")
    op.drop_table("fapai_seed_scan_job")
