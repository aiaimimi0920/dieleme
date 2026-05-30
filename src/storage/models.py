from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PropertyListing(Base, TimestampMixin):
    __tablename__ = "property_listing"

    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_item_id: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_title: Mapped[str | None] = mapped_column(Text)
    source_platform: Mapped[str | None] = mapped_column(String(32))

    status: Mapped[str | None] = mapped_column(String(32))
    auction_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    auction_start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    auction_round: Mapped[int | None] = mapped_column(Integer)
    transaction_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    starting_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    actual_paid_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    evaluation_price: Mapped[float | None] = mapped_column(Numeric(18, 2))
    deposit: Mapped[float | None] = mapped_column(Numeric(18, 2))
    apply_count: Mapped[int | None] = mapped_column(Integer)
    bid_count: Mapped[int | None] = mapped_column(Integer)
    bidder_count: Mapped[int | None] = mapped_column(Integer)
    watch_count: Mapped[int | None] = mapped_column(Integer)
    reminder_count: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(Integer)

    full_address: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(String(64))
    city: Mapped[str | None] = mapped_column(String(64), index=True)
    district: Mapped[str | None] = mapped_column(String(64), index=True)
    business_area: Mapped[str | None] = mapped_column(String(128), index=True)
    community_name: Mapped[str | None] = mapped_column(String(256), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    coordinate_source: Mapped[str | None] = mapped_column(String(64))

    housing_type: Mapped[str | None] = mapped_column(String(32), index=True)
    area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    gross_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    interior_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    land_area_sqm: Mapped[float | None] = mapped_column(Numeric(12, 2))
    ownership_share_ratio: Mapped[float | None] = mapped_column(Numeric(10, 6))
    layout: Mapped[str | None] = mapped_column(String(128))
    build_year: Mapped[int | None] = mapped_column(Integer)
    total_floors: Mapped[int | None] = mapped_column(Integer)
    floor_level: Mapped[str | None] = mapped_column(String(32))
    has_elevator: Mapped[bool | None] = mapped_column(Boolean)
    orientation: Mapped[str | None] = mapped_column(String(32))
    includes_parking: Mapped[bool | None] = mapped_column(Boolean)
    special_school_tag: Mapped[bool | None] = mapped_column(Boolean)
    has_keys: Mapped[bool | None] = mapped_column(Boolean)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_reason: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), server_default=func.now())


class PropertyRiskFlags(Base, TimestampMixin):
    __tablename__ = "property_risk_flags"

    item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True
    )
    land_right_type: Mapped[str | None] = mapped_column(String(32))
    is_occupied: Mapped[bool | None] = mapped_column(Boolean)
    has_long_lease: Mapped[bool | None] = mapped_column(Boolean)
    clear_delivery: Mapped[bool | None] = mapped_column(Boolean)
    tax_burden: Mapped[str | None] = mapped_column(String(64))
    property_fee_owed: Mapped[bool | None] = mapped_column(Boolean)
    is_restricted_purchase: Mapped[bool | None] = mapped_column(Boolean)
    is_fractional_share: Mapped[bool | None] = mapped_column(Boolean)
    tax_is_company_owned: Mapped[bool | None] = mapped_column(Boolean)
    is_haunted: Mapped[bool | None] = mapped_column(Boolean)
    has_lease_before_mortgage: Mapped[bool | None] = mapped_column(Boolean)


class PropertyLegalContext(Base, TimestampMixin):
    __tablename__ = "property_legal_context"

    item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True
    )
    court_name: Mapped[str | None] = mapped_column(String(256))
    case_number: Mapped[str | None] = mapped_column(String(256))
    appraisal_agency_name: Mapped[str | None] = mapped_column(String(256))
    appraisal_benchmark_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    appraisal_report_urls: Mapped[list | None] = mapped_column(JSON)
    announcement_attachment_urls: Mapped[list | None] = mapped_column(JSON)


class PropertyAudit(Base, TimestampMixin):
    __tablename__ = "property_audit"

    item_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("property_listing.item_id", ondelete="CASCADE"), primary_key=True
    )
    detail_archive_path: Mapped[str | None] = mapped_column(Text)
    source_json_path: Mapped[str | None] = mapped_column(Text)
    list_payload_path: Mapped[str | None] = mapped_column(Text)
    detail_text_path: Mapped[str | None] = mapped_column(Text)
    component_payload_path: Mapped[str | None] = mapped_column(Text)
    notice_text_path: Mapped[str | None] = mapped_column(Text)
    desc_text_path: Mapped[str | None] = mapped_column(Text)
    attachment_manifest_path: Mapped[str | None] = mapped_column(Text)
    image_manifest_path: Mapped[str | None] = mapped_column(Text)
    extraction_confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    evidence_span: Mapped[str | None] = mapped_column(Text)
    evidence_source: Mapped[str | None] = mapped_column(String(64))
    extraction_version: Mapped[str | None] = mapped_column(String(64))
    is_processed: Mapped[bool | None] = mapped_column(Boolean)
    detail_captured: Mapped[bool | None] = mapped_column(Boolean)
    detail_fetch_status: Mapped[str | None] = mapped_column(String(64))
    detail_fetch_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    detail_fetch_attempt_count: Mapped[int | None] = mapped_column(Integer)
    detail_fetch_last_url: Mapped[str | None] = mapped_column(Text)
    seed_status: Mapped[str | None] = mapped_column(String(32), index=True)
    seed_first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    seed_last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    seed_source_page_url: Mapped[str | None] = mapped_column(Text)
    detail_status: Mapped[str | None] = mapped_column(String(32), index=True)
    detail_last_error: Mapped[str | None] = mapped_column(Text)
    detail_retry_count: Mapped[int | None] = mapped_column(Integer)
    detail_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    analysis_status: Mapped[str | None] = mapped_column(String(32), index=True)
    analysis_ready: Mapped[bool | None] = mapped_column(Boolean, index=True)
    analysis_missing_fields: Mapped[list | None] = mapped_column(JSON)
    analysis_last_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))
    analysis_model_version: Mapped[str | None] = mapped_column(String(64))


class PropertySearchTask(Base, TimestampMixin):
    __tablename__ = "property_search_task"

    task_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    location_code: Mapped[str] = mapped_column(String(16), index=True)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    sort_param: Mapped[str | None] = mapped_column(String(16), index=True)
    next_page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_page: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    leased_by: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    zero_bid_terminated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False))


class PropertyIngestEvent(Base):
    __tablename__ = "property_ingest_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str | None] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_payload: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now(), nullable=False)


class ManualReviewReceipt(Base, TimestampMixin):
    __tablename__ = "manual_review_receipt"

    action: Mapped[str] = mapped_column(String(128), primary_key=True)
    ready_signal: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(128))
    receipt_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)


class ManualReviewReceiptJob(Base, TimestampMixin):
    __tablename__ = "manual_review_receipt_job"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    receipt_action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    receipt_ready_signal: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    maintenance_options: Mapped[dict | None] = mapped_column(JSON)
    result_summary: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), index=True)


class ManualReviewReceiptOperation(Base):
    __tablename__ = "manual_review_receipt_operation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ready_signal: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str | None] = mapped_column(String(64))
    payload_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str | None] = mapped_column(String(128))
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    maintenance_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    deleted: Mapped[bool | None] = mapped_column(Boolean)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True, server_default=func.now())
