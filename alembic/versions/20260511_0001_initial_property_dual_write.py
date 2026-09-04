"""initial property dual write schema

Revision ID: 20260511_0001
Revises: None
Create Date: 2026-05-11 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260511_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_listing",
        sa.Column("item_id", sa.String(length=64), primary_key=True),
        sa.Column("source_item_id", sa.String(length=64)),
        sa.Column("source_url", sa.Text()),
        sa.Column("source_title", sa.Text()),
        sa.Column("source_platform", sa.String(length=32)),
        sa.Column("status", sa.String(length=32)),
        sa.Column("auction_date", sa.DateTime()),
        sa.Column("auction_start_time", sa.DateTime()),
        sa.Column("auction_round", sa.Integer()),
        sa.Column("transaction_price", sa.Numeric(18, 2)),
        sa.Column("starting_price", sa.Numeric(18, 2)),
        sa.Column("actual_paid_price", sa.Numeric(18, 2)),
        sa.Column("evaluation_price", sa.Numeric(18, 2)),
        sa.Column("deposit", sa.Numeric(18, 2)),
        sa.Column("apply_count", sa.Integer()),
        sa.Column("bid_count", sa.Integer()),
        sa.Column("bidder_count", sa.Integer()),
        sa.Column("watch_count", sa.Integer()),
        sa.Column("reminder_count", sa.Integer()),
        sa.Column("view_count", sa.Integer()),
        sa.Column("full_address", sa.Text()),
        sa.Column("province", sa.String(length=64)),
        sa.Column("city", sa.String(length=64)),
        sa.Column("district", sa.String(length=64)),
        sa.Column("business_area", sa.String(length=128)),
        sa.Column("community_name", sa.String(length=256)),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("coordinate_source", sa.String(length=64)),
        sa.Column("housing_type", sa.String(length=32)),
        sa.Column("area_sqm", sa.Numeric(12, 2)),
        sa.Column("gross_area_sqm", sa.Numeric(12, 2)),
        sa.Column("interior_area_sqm", sa.Numeric(12, 2)),
        sa.Column("land_area_sqm", sa.Numeric(12, 2)),
        sa.Column("ownership_share_ratio", sa.Numeric(10, 6)),
        sa.Column("layout", sa.String(length=128)),
        sa.Column("build_year", sa.Integer()),
        sa.Column("total_floors", sa.Integer()),
        sa.Column("floor_level", sa.String(length=32)),
        sa.Column("has_elevator", sa.Boolean()),
        sa.Column("orientation", sa.String(length=32)),
        sa.Column("includes_parking", sa.Boolean()),
        sa.Column("special_school_tag", sa.Boolean()),
        sa.Column("has_keys", sa.Boolean()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deleted_reason", sa.Text()),
        sa.Column("last_synced_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_property_listing_city", "property_listing", ["city"])
    op.create_index("ix_property_listing_district", "property_listing", ["district"])
    op.create_index("ix_property_listing_business_area", "property_listing", ["business_area"])
    op.create_index("ix_property_listing_community_name", "property_listing", ["community_name"])
    op.create_index("ix_property_listing_housing_type", "property_listing", ["housing_type"])

    op.create_table(
        "property_risk_flags",
        sa.Column("item_id", sa.String(length=64), sa.ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("land_right_type", sa.String(length=32)),
        sa.Column("is_occupied", sa.Boolean()),
        sa.Column("has_long_lease", sa.Boolean()),
        sa.Column("clear_delivery", sa.Boolean()),
        sa.Column("tax_burden", sa.String(length=64)),
        sa.Column("property_fee_owed", sa.Boolean()),
        sa.Column("is_restricted_purchase", sa.Boolean()),
        sa.Column("is_fractional_share", sa.Boolean()),
        sa.Column("tax_is_company_owned", sa.Boolean()),
        sa.Column("is_haunted", sa.Boolean()),
        sa.Column("has_lease_before_mortgage", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "property_legal_context",
        sa.Column("item_id", sa.String(length=64), sa.ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("court_name", sa.String(length=256)),
        sa.Column("case_number", sa.String(length=256)),
        sa.Column("appraisal_agency_name", sa.String(length=256)),
        sa.Column("appraisal_benchmark_date", sa.DateTime()),
        sa.Column("appraisal_report_urls", sa.JSON()),
        sa.Column("announcement_attachment_urls", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "property_audit",
        sa.Column("item_id", sa.String(length=64), sa.ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("detail_archive_path", sa.Text()),
        sa.Column("list_payload_path", sa.Text()),
        sa.Column("detail_text_path", sa.Text()),
        sa.Column("component_payload_path", sa.Text()),
        sa.Column("notice_text_path", sa.Text()),
        sa.Column("desc_text_path", sa.Text()),
        sa.Column("attachment_manifest_path", sa.Text()),
        sa.Column("image_manifest_path", sa.Text()),
        sa.Column("extraction_confidence", sa.Numeric(6, 4)),
        sa.Column("evidence_span", sa.Text()),
        sa.Column("evidence_source", sa.String(length=64)),
        sa.Column("extraction_version", sa.String(length=64)),
        sa.Column("is_processed", sa.Boolean()),
        sa.Column("detail_captured", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "property_ingest_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("item_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_payload", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_property_ingest_event_item_id", "property_ingest_event", ["item_id"])
    op.create_index("ix_property_ingest_event_event_type", "property_ingest_event", ["event_type"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        op.execute("ALTER TABLE property_listing ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_property_listing_geom ON property_listing USING GIST (geom)")


def downgrade() -> None:
    op.drop_index("ix_property_ingest_event_event_type", table_name="property_ingest_event")
    op.drop_index("ix_property_ingest_event_item_id", table_name="property_ingest_event")
    op.drop_table("property_ingest_event")
    op.drop_table("property_audit")
    op.drop_table("property_legal_context")
    op.drop_table("property_risk_flags")
    op.drop_index("ix_property_listing_housing_type", table_name="property_listing")
    op.drop_index("ix_property_listing_community_name", table_name="property_listing")
    op.drop_index("ix_property_listing_business_area", table_name="property_listing")
    op.drop_index("ix_property_listing_district", table_name="property_listing")
    op.drop_index("ix_property_listing_city", table_name="property_listing")
    op.drop_table("property_listing")
