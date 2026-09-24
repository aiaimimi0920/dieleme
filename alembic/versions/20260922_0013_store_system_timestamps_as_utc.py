"""Store system timestamps as UTC-aware PostgreSQL instants."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0013"
down_revision = "20260921_0012"
branch_labels = None
depends_on = None

INSTANT_COLUMNS = (
    ("property_listing", "created_at"),
    ("property_listing", "updated_at"),
    ("property_listing", "last_synced_at"),
    ("property_risk_flags", "created_at"),
    ("property_risk_flags", "updated_at"),
    ("property_legal_context", "created_at"),
    ("property_legal_context", "updated_at"),
    ("property_audit", "created_at"),
    ("property_audit", "updated_at"),
    ("property_audit", "detail_fetch_attempted_at"),
    ("property_audit", "seed_first_seen_at"),
    ("property_audit", "seed_last_seen_at"),
    ("property_audit", "detail_lease_until"),
    ("property_audit", "analysis_last_scored_at"),
    ("property_search_task", "created_at"),
    ("property_search_task", "updated_at"),
    ("property_search_task", "lease_until"),
    ("property_search_task", "last_seen_at"),
    ("fapai_seed_scan_job", "created_at"),
    ("fapai_seed_scan_job", "updated_at"),
    ("fapai_seed_scan_job", "completed_at"),
    ("fapai_seed_scan_progress", "created_at"),
    ("fapai_seed_scan_progress", "updated_at"),
    ("fapai_seed_scan_progress", "lease_until"),
    ("fapai_seed_scan_progress", "completed_at"),
    ("fapai_seed_scan_progress", "last_rescan_at"),
    ("fapai_seed_item", "created_at"),
    ("fapai_seed_item", "updated_at"),
    ("fapai_seed_item", "first_seen_at"),
    ("fapai_seed_item", "last_seen_at"),
    ("fapai_seed_item", "detail_lease_until"),
    ("fapai_seed_item", "detail_completed_at"),
    ("fapai_analysis_run", "created_at"),
    ("fapai_analysis_run", "updated_at"),
    ("fapai_analysis_run", "completed_at"),
    ("fapai_seed_occurrence", "seen_at"),
    ("property_ingest_event", "created_at"),
    ("manual_review_receipt", "created_at"),
    ("manual_review_receipt", "updated_at"),
    ("manual_review_receipt", "receipt_updated_at"),
    ("manual_review_receipt_job", "created_at"),
    ("manual_review_receipt_job", "updated_at"),
    ("manual_review_receipt_job", "started_at"),
    ("manual_review_receipt_job", "finished_at"),
    ("manual_review_receipt_operation", "requested_at"),
)


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table_name, column_name in INSTANT_COLUMNS:
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(timezone=False),
            type_=sa.DateTime(timezone=True),
            postgresql_using=f'"{column_name}" AT TIME ZONE \'UTC\'',
        )


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table_name, column_name in reversed(INSTANT_COLUMNS):
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=False),
            postgresql_using=f'"{column_name}" AT TIME ZONE \'UTC\'',
        )
