from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Sequence
from uuid import uuid4

from sqlalchemy import and_, case, create_engine, func, not_, select, text
from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.avm.collection_template import build_collection_record
from src.collection.stage_state import derive_stage_state

from .models import (
    Base,
    ManualReviewReceipt,
    ManualReviewReceiptJob,
    ManualReviewReceiptOperation,
    PropertyAudit,
    PropertyIngestEvent,
    PropertyLegalContext,
    PropertyListing,
    PropertyRiskFlags,
    PropertySearchTask,
)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d"}:
                dt = dt.replace(hour=0, minute=0, second=0)
            return dt
        except ValueError:
            continue
    return None


def _manual_review_payload_fingerprint(payload: Any) -> str:
    normalized = json.dumps(payload if payload is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class DatabaseSettings:
    url: str | None
    echo: bool = False
    enable_postgis: bool = True
    auto_create: bool = True
    enabled: bool = True


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def create_repository_from_env() -> "PropertyRepository":
    url = os.getenv("FAPAI_DB_URL")
    settings = DatabaseSettings(
        url=url,
        echo=_env_flag("FAPAI_DB_ECHO", False),
        enable_postgis=_env_flag("FAPAI_DB_ENABLE_POSTGIS", True),
        auto_create=_env_flag("FAPAI_DB_AUTO_CREATE", True),
        enabled=_env_flag("FAPAI_DB_ENABLED", True) and bool(url),
    )
    return PropertyRepository(settings=settings)


class PropertyRepository:
    def __init__(self, settings: DatabaseSettings):
        self.settings = settings
        self._engine: Engine | None = None
        self._Session: sessionmaker[Session] | None = None
        self._initialized = False

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and self.settings.url)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            if not self.enabled:
                raise RuntimeError("database repository is disabled")
            self._engine = create_engine(self.settings.url, echo=self.settings.echo, future=True)
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._Session is None:
            self._Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        return self._Session

    def initialize(self) -> None:
        if not self.enabled or self._initialized:
            return
        if self.settings.auto_create:
            Base.metadata.create_all(self.engine)
        if self.settings.enable_postgis and self.engine.dialect.name == "postgresql":
            self._ensure_postgis()
        self._initialized = True

    def _ensure_postgis(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(
                text(
                    """
                    ALTER TABLE property_listing
                    ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_listing_geom
                    ON property_listing
                    USING GIST (geom)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE property_listing
                    SET geom = CASE
                        WHEN longitude IS NOT NULL AND latitude IS NOT NULL
                        THEN ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                        ELSE NULL
                    END
                    WHERE geom IS NULL
                    """
                )
            )

    def _apply_postgis_point(self, session: Session, item_id: str, latitude: Any, longitude: Any) -> None:
        if self.engine.dialect.name != "postgresql":
            return
        if latitude in (None, "") or longitude in (None, ""):
            session.execute(text("UPDATE property_listing SET geom = NULL WHERE item_id = :item_id"), {"item_id": item_id})
            return
        session.execute(
            text(
                """
                UPDATE property_listing
                SET geom = ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
                WHERE item_id = :item_id
                """
            ),
            {"item_id": item_id, "latitude": float(latitude), "longitude": float(longitude)},
        )

    def upsert_flat_item(self, item: Dict[str, Any], event_type: str, event_payload: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        self.initialize()
        record = build_collection_record(item)
        self.upsert_collection_record(record, event_type=event_type, event_payload=event_payload, aux_data=item)

    def upsert_flat_items(
        self,
        items: Iterable[Dict[str, Any]],
        event_type: str,
        event_payload_factory: Optional[Callable[[Dict[str, Any], int], Optional[Dict[str, Any]]]] = None,
    ) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        record_pairs = [(build_collection_record(item), item) for item in items if isinstance(item, dict)]
        records = [record for record, _item in record_pairs]
        if not records:
            return 0

        with self.session_factory.begin() as session:
            for index, (record, original_item) in enumerate(record_pairs):
                payload = event_payload_factory(record, index) if event_payload_factory else None
                self._upsert_collection_record_session(
                    session,
                    record,
                    event_type=event_type,
                    event_payload=payload,
                    aux_data=original_item,
                )
        return len(records)

    @staticmethod
    def _fmt_dt(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        return value.strftime("%Y-%m-%d %H:%M:%S")

    def _listing_payload_from_rows(
        self,
        listing: PropertyListing,
        risk: PropertyRiskFlags | None,
        legal: PropertyLegalContext | None,
        audit: PropertyAudit | None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": listing.item_id,
            "item_id": listing.item_id,
            "source_item_id": listing.source_item_id,
            "title": listing.source_title,
            "source_title": listing.source_title,
            "url": listing.source_url,
            "source_url": listing.source_url,
            "source_platform": listing.source_platform,
            "status": listing.status,
            "auction_date": self._fmt_dt(listing.auction_date),
            "交易时间": self._fmt_dt(listing.auction_date),
            "auction_start_time": self._fmt_dt(listing.auction_start_time),
            "开拍时间": self._fmt_dt(listing.auction_start_time),
            "auction_round": listing.auction_round,
            "transaction_price": float(listing.transaction_price) if listing.transaction_price is not None else None,
            "成交价格": float(listing.transaction_price) if listing.transaction_price is not None else None,
            "starting_price": float(listing.starting_price) if listing.starting_price is not None else None,
            "起拍价格": float(listing.starting_price) if listing.starting_price is not None else None,
            "actual_paid_price": float(listing.actual_paid_price) if listing.actual_paid_price is not None else None,
            "evaluation_price": float(listing.evaluation_price) if listing.evaluation_price is not None else None,
            "市场评估价": float(listing.evaluation_price) if listing.evaluation_price is not None else None,
            "deposit": float(listing.deposit) if listing.deposit is not None else None,
            "保证金": float(listing.deposit) if listing.deposit is not None else None,
            "apply_count": listing.apply_count,
            "竞拍人数": listing.apply_count,
            "bid_count": listing.bid_count,
            "出价次数": listing.bid_count,
            "bidder_count": listing.bidder_count,
            "出价人数": listing.bidder_count,
            "watch_count": listing.watch_count,
            "reminder_count": listing.reminder_count,
            "view_count": listing.view_count,
            "full_address": listing.full_address,
            "完整地址": listing.full_address,
            "地点": listing.full_address,
            "province": listing.province,
            "省份": listing.province,
            "city": listing.city,
            "城市": listing.city,
            "district": listing.district,
            "区": listing.district,
            "business_area": listing.business_area,
            "最靠近商圈": listing.business_area,
            "community_name": listing.community_name,
            "所属小区": listing.community_name,
            "latitude": listing.latitude,
            "纬度": listing.latitude,
            "longitude": listing.longitude,
            "经度": listing.longitude,
            "coordinate_source": listing.coordinate_source,
            "housing_type": listing.housing_type,
            "area_sqm": float(listing.area_sqm) if listing.area_sqm is not None else None,
            "建筑面积": float(listing.area_sqm) if listing.area_sqm is not None else None,
            "gross_area_sqm": float(listing.gross_area_sqm) if listing.gross_area_sqm is not None else None,
            "产权建筑面积": float(listing.gross_area_sqm) if listing.gross_area_sqm is not None else None,
            "interior_area_sqm": float(listing.interior_area_sqm) if listing.interior_area_sqm is not None else None,
            "land_area_sqm": float(listing.land_area_sqm) if listing.land_area_sqm is not None else None,
            "ownership_share_ratio": float(listing.ownership_share_ratio) if listing.ownership_share_ratio is not None else None,
            "产权份额比例": float(listing.ownership_share_ratio) if listing.ownership_share_ratio is not None else None,
            "layout": listing.layout,
            "build_year": listing.build_year,
            "total_floors": listing.total_floors,
            "floor_level": listing.floor_level,
            "has_elevator": listing.has_elevator,
            "orientation": listing.orientation,
            "includes_parking": listing.includes_parking,
            "special_school_tag": listing.special_school_tag,
            "has_keys": listing.has_keys,
        }

        risk_payload = {
            "land_right_type": risk.land_right_type if risk else None,
            "is_occupied": risk.is_occupied if risk else None,
            "has_long_lease": risk.has_long_lease if risk else None,
            "clear_delivery": risk.clear_delivery if risk else None,
            "tax_burden": risk.tax_burden if risk else None,
            "property_fee_owed": risk.property_fee_owed if risk else None,
            "is_restricted_purchase": risk.is_restricted_purchase if risk else None,
            "is_fractional_share": risk.is_fractional_share if risk else None,
            "tax_is_company_owned": risk.tax_is_company_owned if risk else None,
            "is_haunted": risk.is_haunted if risk else None,
            "has_lease_before_mortgage": risk.has_lease_before_mortgage if risk else None,
        }
        legal_payload = {
            "court_name": legal.court_name if legal else None,
            "法院名称": legal.court_name if legal else None,
            "case_number": legal.case_number if legal else None,
            "案号": legal.case_number if legal else None,
            "appraisal_agency_name": legal.appraisal_agency_name if legal else None,
            "appraisal_benchmark_date": self._fmt_dt(legal.appraisal_benchmark_date) if legal else None,
            "appraisal_report_urls": legal.appraisal_report_urls if legal and legal.appraisal_report_urls else [],
            "announcement_attachment_urls": legal.announcement_attachment_urls if legal and legal.announcement_attachment_urls else [],
        }
        audit_payload = {
            "detail_archive_path": audit.detail_archive_path if audit else None,
            "source_json_path": audit.source_json_path if audit else None,
            "json_file": audit.source_json_path if audit else None,
            "__file_path": audit.source_json_path if audit else None,
            "list_payload_path": audit.list_payload_path if audit else None,
            "detail_text_path": audit.detail_text_path if audit else None,
            "component_payload_path": audit.component_payload_path if audit else None,
            "notice_text_path": audit.notice_text_path if audit else None,
            "desc_text_path": audit.desc_text_path if audit else None,
            "attachment_manifest_path": audit.attachment_manifest_path if audit else None,
            "image_manifest_path": audit.image_manifest_path if audit else None,
            "extraction_confidence": float(audit.extraction_confidence) if audit and audit.extraction_confidence is not None else None,
            "evidence_span": audit.evidence_span if audit else None,
            "evidence_source": audit.evidence_source if audit else None,
            "extraction_version": audit.extraction_version if audit else None,
            "is_processed": audit.is_processed if audit else None,
            "detail_captured": audit.detail_captured if audit else None,
            "detail_fetch_status": audit.detail_fetch_status if audit else None,
            "detail_fetch_attempted_at": self._fmt_dt(audit.detail_fetch_attempted_at) if audit else None,
            "detail_fetch_attempt_count": audit.detail_fetch_attempt_count if audit else None,
            "detail_fetch_last_url": audit.detail_fetch_last_url if audit else None,
            "seed_status": audit.seed_status if audit else None,
            "seed_first_seen_at": self._fmt_dt(audit.seed_first_seen_at) if audit else None,
            "seed_last_seen_at": self._fmt_dt(audit.seed_last_seen_at) if audit else None,
            "seed_source_page_url": audit.seed_source_page_url if audit else None,
            "detail_status": audit.detail_status if audit else None,
            "detail_last_error": audit.detail_last_error if audit else None,
            "detail_retry_count": audit.detail_retry_count if audit else None,
            "detail_lease_until": self._fmt_dt(audit.detail_lease_until) if audit else None,
            "analysis_status": audit.analysis_status if audit else None,
            "analysis_ready": audit.analysis_ready if audit else None,
            "analysis_missing_fields": audit.analysis_missing_fields if audit else None,
            "analysis_last_scored_at": self._fmt_dt(audit.analysis_last_scored_at) if audit else None,
            "analysis_model_version": audit.analysis_model_version if audit else None,
        }

        payload.update({key: value for key, value in {**risk_payload, **legal_payload, **audit_payload}.items() if value not in (None, "", [])})
        payload["avm_risk_features"] = {
            **risk_payload,
            "housing_type": listing.housing_type,
            "community_name": listing.community_name,
            "build_year": listing.build_year,
            "total_floors": listing.total_floors,
            "floor_level": listing.floor_level,
            "has_elevator": listing.has_elevator,
            "orientation": listing.orientation,
            "has_keys": listing.has_keys,
            "special_school_tag": listing.special_school_tag,
            "evaluation_price": float(listing.evaluation_price) if listing.evaluation_price is not None else None,
            "layout": listing.layout,
            "includes_parking": listing.includes_parking,
            "extraction_confidence": audit_payload["extraction_confidence"],
            "evidence_span": audit_payload["evidence_span"],
            "evidence_source": audit_payload["evidence_source"],
            "extraction_version": audit_payload["extraction_version"],
        }
        return payload

    def _feature_source_payload_from_rows(
        self,
        listing: PropertyListing,
        risk: PropertyRiskFlags | None,
        audit: PropertyAudit | None,
    ) -> Dict[str, Any]:
        return {
            "item_id": listing.item_id,
            "auction_date": self._fmt_dt(listing.auction_date),
            "province": listing.province,
            "city": listing.city,
            "district": listing.district,
            "community_name": listing.community_name,
            "business_area": listing.business_area,
            "area_sqm": float(listing.area_sqm) if listing.area_sqm is not None else None,
            "starting_price": float(listing.starting_price) if listing.starting_price is not None else None,
            "transaction_price": float(listing.transaction_price) if listing.transaction_price is not None else None,
            "actual_paid_price": float(listing.actual_paid_price) if listing.actual_paid_price is not None else None,
            "latitude": listing.latitude,
            "longitude": listing.longitude,
            "status": listing.status,
            "auction_round": listing.auction_round,
            "housing_type": listing.housing_type,
            "bid_count": listing.bid_count,
            "apply_count": listing.apply_count,
            "build_year": listing.build_year,
            "total_floors": listing.total_floors,
            "floor_level": listing.floor_level,
            "has_elevator": listing.has_elevator,
            "orientation": listing.orientation,
            "land_right_type": risk.land_right_type if risk else None,
            "is_occupied": risk.is_occupied if risk else None,
            "has_long_lease": risk.has_long_lease if risk else None,
            "clear_delivery": risk.clear_delivery if risk else None,
            "tax_burden": risk.tax_burden if risk else None,
            "is_haunted": risk.is_haunted if risk else None,
            "has_keys": listing.has_keys,
            "property_fee_owed": risk.property_fee_owed if risk else None,
            "special_school_tag": listing.special_school_tag,
            "evaluation_price": float(listing.evaluation_price) if listing.evaluation_price is not None else None,
            "layout": listing.layout,
            "is_restricted_purchase": risk.is_restricted_purchase if risk else None,
            "includes_parking": listing.includes_parking,
            "is_fractional_share": risk.is_fractional_share if risk else None,
            "tax_is_company_owned": risk.tax_is_company_owned if risk else None,
            "has_lease_before_mortgage": risk.has_lease_before_mortgage if risk else None,
            "extraction_confidence": float(audit.extraction_confidence) if audit and audit.extraction_confidence is not None else None,
            "evidence_source": audit.evidence_source if audit else None,
            "extraction_version": audit.extraction_version if audit else None,
            "analysis_ready": audit.analysis_ready if audit else None,
            "analysis_status": audit.analysis_status if audit else None,
        }

    def get_flat_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        with self.session_factory() as session:
            listing = session.get(PropertyListing, item_id)
            if listing is None or listing.is_deleted:
                return None
            risk = session.get(PropertyRiskFlags, item_id)
            legal = session.get(PropertyLegalContext, item_id)
            audit = session.get(PropertyAudit, item_id)
            return self._listing_payload_from_rows(listing, risk, legal, audit)

    def _select_flat_item_rows(self, session: Session, where_clause=None, limit: int | None = None):
        stmt = (
            select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
            .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
            .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
            .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
            .where(PropertyListing.is_deleted.is_(False))
            .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
        )
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        if limit and limit > 0:
            stmt = stmt.limit(limit)
        return session.execute(stmt).all()

    def iter_flat_items(self, limit: int | None = None) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            rows = self._select_flat_item_rows(session, limit=limit)
            result = []
            for listing, risk, legal, audit in rows:
                result.append(
                    self._listing_payload_from_rows(
                        listing,
                        risk,
                        legal,
                        audit,
                    )
                )
            return result

    def yield_feature_source_rows(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(PropertyListing.is_deleted.is_(False))
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, audit in stream:
                yield self._feature_source_payload_from_rows(listing, risk, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def iter_feature_candidate_rows(
        self,
        subject: Dict[str, Any],
        *,
        per_bucket_limit: int = 1500,
        global_limit: int = 2000,
        total_limit: int = 5000,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()

        def _norm(value: Any) -> str:
            text_value = str(value or "").strip()
            if not text_value or text_value == "UNK":
                return ""
            return text_value

        community = _norm(subject.get("community_name"))
        business_area = _norm(subject.get("business_area"))
        district = _norm(subject.get("district"))
        city = _norm(subject.get("city"))

        def _query(session: Session, *conditions, limit: int) -> list[Dict[str, Any]]:
            rows = (
                session.execute(
                    select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                    .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(PropertyListing.is_deleted.is_(False), *conditions)
                    .order_by(PropertyListing.auction_date.desc().nulls_last(), PropertyListing.item_id.asc())
                    .limit(limit)
                )
                .all()
            )
            return [self._feature_source_payload_from_rows(listing, risk, audit) for listing, risk, audit in rows]

        ordered_candidates: list[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _extend(rows: list[Dict[str, Any]]) -> None:
            for row in rows:
                item_id = str(row.get("item_id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                ordered_candidates.append(row)
                if len(ordered_candidates) >= total_limit:
                    return

        with self.session_factory() as session:
            if community:
                _extend(_query(session, PropertyListing.community_name == community, limit=per_bucket_limit))
            if len(ordered_candidates) < total_limit and city and district and business_area:
                _extend(
                    _query(
                        session,
                        PropertyListing.city == city,
                        PropertyListing.district == district,
                        PropertyListing.business_area == business_area,
                        limit=per_bucket_limit,
                    )
                )
            if len(ordered_candidates) < total_limit and city and district:
                _extend(
                    _query(
                        session,
                        PropertyListing.city == city,
                        PropertyListing.district == district,
                        limit=per_bucket_limit,
                    )
                )
            if len(ordered_candidates) < total_limit and city:
                _extend(_query(session, PropertyListing.city == city, limit=per_bucket_limit))
            if len(ordered_candidates) < total_limit:
                _extend(_query(session, limit=global_limit))

        return ordered_candidates[:total_limit]

    def yield_flat_items(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(PropertyListing.is_deleted.is_(False))
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, legal, audit in stream:
                yield self._listing_payload_from_rows(listing, risk, legal, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def iter_recent_flat_items(self, window_days: int, limit: int | None = None) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            max_dt = session.scalar(
                select(func.max(PropertyListing.auction_date)).where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.auction_date.is_not(None),
                )
            )
            if max_dt is None:
                return []
            recent_start = max_dt - timedelta(days=max(window_days - 1, 0))
            rows = self._select_flat_item_rows(
                session,
                where_clause=PropertyListing.auction_date >= recent_start,
                limit=limit,
            )
            result = []
            for listing, risk, legal, audit in rows:
                result.append(self._listing_payload_from_rows(listing, risk, legal, audit))
            return result

    def yield_recent_flat_items(
        self,
        window_days: int,
        limit: int | None = None,
        chunk_size: int = 1000,
    ) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            max_dt = session.scalar(
                select(func.max(PropertyListing.auction_date)).where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.auction_date.is_not(None),
                )
            )
            if max_dt is None:
                return
            recent_start = max_dt - timedelta(days=max(window_days - 1, 0))
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.auction_date >= recent_start,
                )
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, legal, audit in stream:
                yield self._listing_payload_from_rows(listing, risk, legal, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def yield_coordinate_rows(self, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(
                    PropertyListing.city,
                    PropertyListing.district,
                    PropertyListing.business_area,
                    PropertyListing.community_name,
                    PropertyListing.latitude,
                    PropertyListing.longitude,
                )
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.latitude.is_not(None),
                    PropertyListing.longitude.is_not(None),
                )
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for city, district, business_area, community_name, latitude, longitude in stream:
                yield {
                    "city": city,
                    "district": district,
                    "business_area": business_area,
                    "community_name": community_name,
                    "latitude": float(latitude) if latitude is not None else None,
                    "longitude": float(longitude) if longitude is not None else None,
                }

    def build_coordinate_centroids(self) -> Dict[str, tuple[float, float]]:
        if not self.enabled:
            return {}
        self.initialize()

        def _non_empty(column):
            return and_(column.is_not(None), column != "")

        base_filters = (
            PropertyListing.is_deleted.is_(False),
            PropertyListing.latitude.is_not(None),
            PropertyListing.longitude.is_not(None),
            PropertyListing.latitude >= 3.0,
            PropertyListing.latitude <= 54.5,
            PropertyListing.longitude >= 73.0,
            PropertyListing.longitude <= 136.0,
        )

        centroids: Dict[str, tuple[float, float]] = {}
        with self.session_factory() as session:
            community_stmt = (
                select(
                    PropertyListing.community_name,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(*base_filters, _non_empty(PropertyListing.community_name))
                .group_by(PropertyListing.community_name)
            )
            for community_name, lat_avg, lon_avg in session.execute(community_stmt):
                centroids[f"community::{community_name}"] = (round(float(lat_avg), 6), round(float(lon_avg), 6))

            business_stmt = (
                select(
                    PropertyListing.city,
                    PropertyListing.district,
                    PropertyListing.business_area,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(
                    *base_filters,
                    _non_empty(PropertyListing.city),
                    _non_empty(PropertyListing.district),
                    _non_empty(PropertyListing.business_area),
                )
                .group_by(PropertyListing.city, PropertyListing.district, PropertyListing.business_area)
            )
            for city, district, business_area, lat_avg, lon_avg in session.execute(business_stmt):
                centroids[f"business::{city}::{district}::{business_area}"] = (
                    round(float(lat_avg), 6),
                    round(float(lon_avg), 6),
                )

            district_stmt = (
                select(
                    PropertyListing.city,
                    PropertyListing.district,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(
                    *base_filters,
                    _non_empty(PropertyListing.city),
                    _non_empty(PropertyListing.district),
                )
                .group_by(PropertyListing.city, PropertyListing.district)
            )
            for city, district, lat_avg, lon_avg in session.execute(district_stmt):
                centroids[f"district::{city}::{district}"] = (
                    round(float(lat_avg), 6),
                    round(float(lon_avg), 6),
                )

            city_stmt = (
                select(
                    PropertyListing.city,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(*base_filters, _non_empty(PropertyListing.city))
                .group_by(PropertyListing.city)
            )
            for city, lat_avg, lon_avg in session.execute(city_stmt):
                centroids[f"city::{city}"] = (round(float(lat_avg), 6), round(float(lon_avg), 6))

        return centroids

    def _audit_stage_snapshot(self, audit_row: PropertyAudit | None) -> Dict[str, Any]:
        if audit_row is None:
            return {}
        return {
            "seed_status": audit_row.seed_status,
            "seed_first_seen_at": audit_row.seed_first_seen_at,
            "seed_last_seen_at": audit_row.seed_last_seen_at,
            "seed_source_page_url": audit_row.seed_source_page_url,
            "detail_status": audit_row.detail_status,
            "detail_last_error": audit_row.detail_last_error,
            "detail_retry_count": audit_row.detail_retry_count,
            "detail_lease_until": audit_row.detail_lease_until,
            "analysis_status": audit_row.analysis_status,
            "analysis_ready": audit_row.analysis_ready,
            "analysis_missing_fields": audit_row.analysis_missing_fields,
            "analysis_last_scored_at": audit_row.analysis_last_scored_at,
            "analysis_model_version": audit_row.analysis_model_version,
            "detail_fetch_status": audit_row.detail_fetch_status,
        }

    @staticmethod
    def _changed_stage_events(existing_stage: Dict[str, Any], stage_state: Dict[str, Any]) -> list[tuple[str, Dict[str, Any]]]:
        events: list[tuple[str, Dict[str, Any]]] = []

        def _append(event_type: str, field: str) -> None:
            previous = existing_stage.get(field)
            current = stage_state.get(field)
            if previous == current or current in (None, "", []):
                return
            events.append(
                (
                    event_type,
                    {
                        "field": field,
                        "previous": previous,
                        "current": current,
                    },
                )
            )

        _append("seed_stage_transition", "seed_status")
        _append("detail_stage_transition", "detail_status")
        _append("analysis_stage_transition", "analysis_status")
        if existing_stage.get("analysis_ready") != stage_state.get("analysis_ready") and stage_state.get("analysis_ready") is not None:
            events.append(
                (
                    "analysis_ready_transition",
                    {
                        "field": "analysis_ready",
                        "previous": existing_stage.get("analysis_ready"),
                        "current": stage_state.get("analysis_ready"),
                        "missing_fields": stage_state.get("analysis_missing_fields") or [],
                    },
                )
            )
        return events

    def upsert_collection_record(
        self,
        record: Dict[str, Any],
        event_type: str,
        event_payload: Optional[Dict[str, Any]] = None,
        aux_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            self._upsert_collection_record_session(
                session,
                record,
                event_type=event_type,
                event_payload=event_payload,
                aux_data=aux_data,
            )

    def _upsert_collection_record_session(
        self,
        session: Session,
        record: Dict[str, Any],
        event_type: str,
        event_payload: Optional[Dict[str, Any]] = None,
        aux_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        source = record["source"]
        archive = record["archive"]
        auction = record["auction"]
        location = record["location"]
        property_section = record["property"]
        legal_context = record["legal_context"]
        risk_flags = record["risk_flags"]
        audit = record["audit"]
        item_id = source["item_id"]
        now = datetime.now()
        listing = session.get(PropertyListing, item_id) or PropertyListing(item_id=item_id)
        listing.source_item_id = source.get("source_item_id")
        listing.source_url = source.get("source_url")
        listing.source_title = source.get("source_title")
        listing.source_platform = source.get("source_platform")
        listing.status = auction.get("status")
        listing.auction_date = _parse_dt(auction.get("auction_date"))
        listing.auction_start_time = _parse_dt(auction.get("auction_start_time"))
        listing.auction_round = auction.get("auction_round")
        listing.transaction_price = auction.get("transaction_price")
        listing.starting_price = auction.get("starting_price")
        listing.actual_paid_price = auction.get("actual_paid_price")
        listing.evaluation_price = auction.get("evaluation_price")
        listing.deposit = auction.get("deposit")
        listing.apply_count = auction.get("apply_count")
        listing.bid_count = auction.get("bid_count")
        listing.bidder_count = auction.get("bidder_count")
        listing.watch_count = auction.get("watch_count")
        listing.reminder_count = auction.get("reminder_count")
        listing.view_count = auction.get("view_count")
        listing.full_address = location.get("full_address")
        listing.province = location.get("province")
        listing.city = location.get("city")
        listing.district = location.get("district")
        listing.business_area = location.get("business_area")
        listing.community_name = location.get("community_name")
        listing.latitude = location.get("latitude")
        listing.longitude = location.get("longitude")
        listing.coordinate_source = location.get("coordinate_source")
        listing.housing_type = property_section.get("housing_type")
        listing.area_sqm = property_section.get("area_sqm")
        listing.gross_area_sqm = property_section.get("gross_area_sqm")
        listing.interior_area_sqm = property_section.get("interior_area_sqm")
        listing.land_area_sqm = property_section.get("land_area_sqm")
        listing.ownership_share_ratio = property_section.get("ownership_share_ratio")
        listing.layout = property_section.get("layout")
        listing.build_year = property_section.get("build_year")
        listing.total_floors = property_section.get("total_floors")
        listing.floor_level = property_section.get("floor_level")
        listing.has_elevator = property_section.get("has_elevator")
        listing.orientation = property_section.get("orientation")
        listing.includes_parking = property_section.get("includes_parking")
        listing.special_school_tag = property_section.get("special_school_tag")
        listing.has_keys = property_section.get("has_keys")
        listing.is_deleted = False
        listing.deleted_reason = None
        listing.last_synced_at = now
        session.add(listing)

        risk_row = session.get(PropertyRiskFlags, item_id) or PropertyRiskFlags(item_id=item_id)
        for key, value in risk_flags.items():
            setattr(risk_row, key, value)
        session.add(risk_row)

        legal_row = session.get(PropertyLegalContext, item_id) or PropertyLegalContext(item_id=item_id)
        legal_row.court_name = legal_context.get("court_name")
        legal_row.case_number = legal_context.get("case_number")
        legal_row.appraisal_agency_name = legal_context.get("appraisal_agency_name")
        legal_row.appraisal_benchmark_date = _parse_dt(legal_context.get("appraisal_benchmark_date"))
        legal_row.appraisal_report_urls = legal_context.get("appraisal_report_urls") or []
        legal_row.announcement_attachment_urls = legal_context.get("announcement_attachment_urls") or []
        session.add(legal_row)

        audit_row = session.get(PropertyAudit, item_id) or PropertyAudit(item_id=item_id)
        existing_stage = self._audit_stage_snapshot(audit_row)
        audit_row.detail_archive_path = source.get("detail_archive_path")
        source_json_path = None
        if isinstance(event_payload, dict):
            source_json_path = (
                event_payload.get("source_file")
                or event_payload.get("json_file")
                or event_payload.get("file_path")
            )
        if source_json_path in ("", None):
            source_json_path = record.get("json_file") or record.get("__file_path")
        if source_json_path not in ("", None):
            audit_row.source_json_path = str(source_json_path)
        audit_row.list_payload_path = archive.get("list_payload_path")
        audit_row.detail_text_path = archive.get("detail_text_path")
        audit_row.component_payload_path = archive.get("component_payload_path")
        audit_row.notice_text_path = archive.get("notice_text_path")
        audit_row.desc_text_path = archive.get("desc_text_path")
        audit_row.attachment_manifest_path = archive.get("attachment_manifest_path")
        audit_row.image_manifest_path = archive.get("image_manifest_path")
        audit_row.extraction_confidence = audit.get("extraction_confidence")
        evidence_span = audit.get("evidence_span")
        audit_row.evidence_span = evidence_span if isinstance(evidence_span, str) else str(evidence_span)
        audit_row.evidence_source = audit.get("evidence_source")
        audit_row.extraction_version = audit.get("extraction_version")
        audit_row.is_processed = audit.get("is_processed")
        audit_row.detail_captured = audit.get("detail_captured")
        raw_item = aux_data or {}
        audit_row.detail_fetch_status = raw_item.get("detail_fetch_status")
        audit_row.detail_fetch_attempted_at = _parse_dt(raw_item.get("detail_fetch_attempted_at"))
        audit_row.detail_fetch_attempt_count = raw_item.get("detail_fetch_attempt_count")
        audit_row.detail_fetch_last_url = raw_item.get("detail_fetch_last_url")
        stage_state = derive_stage_state(
            record,
            raw_item,
            event_type=event_type,
            existing=existing_stage,
            now=now,
        )
        audit_row.seed_status = stage_state.get("seed_status")
        audit_row.seed_first_seen_at = stage_state.get("seed_first_seen_at")
        audit_row.seed_last_seen_at = stage_state.get("seed_last_seen_at")
        audit_row.seed_source_page_url = stage_state.get("seed_source_page_url")
        audit_row.detail_status = stage_state.get("detail_status")
        audit_row.detail_last_error = stage_state.get("detail_last_error")
        audit_row.detail_retry_count = stage_state.get("detail_retry_count")
        audit_row.detail_lease_until = _parse_dt(stage_state.get("detail_lease_until"))
        audit_row.analysis_status = stage_state.get("analysis_status")
        audit_row.analysis_ready = stage_state.get("analysis_ready")
        audit_row.analysis_missing_fields = stage_state.get("analysis_missing_fields") or []
        audit_row.analysis_last_scored_at = _parse_dt(stage_state.get("analysis_last_scored_at"))
        audit_row.analysis_model_version = stage_state.get("analysis_model_version")
        session.add(audit_row)

        for transition_type, transition_payload in self._changed_stage_events(existing_stage, stage_state):
            session.add(
                PropertyIngestEvent(
                    item_id=item_id,
                    event_type=transition_type,
                    event_payload=transition_payload,
                )
            )

        event_record = event_payload or {"record": record}
        if not isinstance(event_record, dict):
            event_record = {"payload": event_record}
        session.add(
            PropertyIngestEvent(
                item_id=item_id,
                event_type=event_type,
                event_payload=event_record,
            )
        )
        session.flush()
        self._apply_postgis_point(session, item_id, listing.latitude, listing.longitude)

    def mark_deleted(self, item_id: str, reason: str, event_payload: Optional[Dict[str, Any]] = None) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            listing = session.get(PropertyListing, item_id)
            if listing is None:
                listing = PropertyListing(item_id=item_id)
                session.add(listing)
            listing.is_deleted = True
            listing.deleted_reason = reason
            listing.last_synced_at = datetime.now()
            session.add(
                PropertyIngestEvent(
                    item_id=item_id,
                    event_type="mark_deleted",
                    event_payload=event_payload or {"reason": reason},
                )
            )

    @staticmethod
    def _done_like_statuses() -> tuple[str, ...]:
        return ("done", "成交", "failure", "failed_timeout")

    @staticmethod
    def _pending_detail_statuses() -> tuple[str, ...]:
        return ("pending", "failed", "replay_requested", "archived")

    @staticmethod
    def _analysis_status_ready_values() -> tuple[str, ...]:
        return ("done", "成交")

    def _detail_pending_filter(self):
        return and_(
            PropertyListing.is_deleted.is_(False),
            PropertyListing.source_url.is_not(None),
            PropertyListing.source_url != "",
            PropertyListing.status.in_(self._done_like_statuses()),
            or_(PropertyAudit.is_processed.is_(False), PropertyAudit.is_processed.is_(None)),
            or_(
                PropertyAudit.detail_status.in_(self._pending_detail_statuses()),
                PropertyAudit.detail_status.is_(None),
            ),
        )

    def _analysis_contract_has_price_anchor(self):
        return or_(
            PropertyListing.transaction_price.is_not(None),
            PropertyListing.starting_price.is_not(None),
            PropertyListing.actual_paid_price.is_not(None),
            PropertyListing.evaluation_price.is_not(None),
        )

    def _analysis_contract_has_location_precision(self):
        return or_(
            and_(PropertyListing.latitude.is_not(None), PropertyListing.longitude.is_not(None)),
            PropertyListing.community_name.is_not(None),
            PropertyListing.business_area.is_not(None),
        )

    def _analysis_contract_fallback_ready(self):
        return and_(
            PropertyListing.is_deleted.is_(False),
            PropertyListing.status.in_(self._done_like_statuses()),
            PropertyAudit.detail_captured.is_(True),
            PropertyListing.area_sqm.is_not(None),
            PropertyListing.city.is_not(None),
            PropertyListing.district.is_not(None),
            self._analysis_contract_has_price_anchor(),
            self._analysis_contract_has_location_precision(),
        )

    def _analysis_ready_filter(self):
        return or_(
            PropertyAudit.analysis_ready.is_(True),
            and_(PropertyAudit.analysis_status == "ready", PropertyAudit.analysis_ready.is_not(False)),
            and_(PropertyAudit.analysis_ready.is_(None), self._analysis_contract_fallback_ready()),
        )

    def _analysis_not_ready_filter(self):
        return and_(
            PropertyListing.is_deleted.is_(False),
            or_(
                PropertyAudit.analysis_ready.is_(False),
                PropertyAudit.analysis_status == "not_ready",
                and_(
                    PropertyAudit.analysis_ready.is_(None),
                    PropertyAudit.analysis_status.is_(None),
                    not_(self._analysis_contract_fallback_ready()),
                ),
            ),
        )

    def count_listings(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            return session.scalar(select(func.count()).select_from(PropertyListing)) or 0

    def count_processed_listings(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyAudit.is_processed.is_(True),
                )
            )
            return session.scalar(stmt) or 0

    def counts_snapshot(self) -> Dict[str, int]:
        if not self.enabled:
            return {
                "db_total_ids": 0,
                "db_processed_ids": 0,
                "db_pending_ids": 0,
                "db_detail_captured_ids": 0,
            }
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(
                    func.count(PropertyListing.item_id),
                    func.sum(case((PropertyAudit.is_processed.is_(True), 1), else_=0)),
                    func.sum(case((PropertyAudit.detail_captured.is_(True), 1), else_=0)),
                    func.sum(
                        case(
                            (
                                self._detail_pending_filter(),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                )
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(PropertyListing.is_deleted.is_(False))
            )
            total_ids, processed_ids, detail_captured_ids, pending_ids = session.execute(stmt).one()
            return {
                "db_total_ids": int(total_ids or 0),
                "db_processed_ids": int(processed_ids or 0),
                "db_pending_ids": int(pending_ids or 0),
                "db_detail_captured_ids": int(detail_captured_ids or 0),
            }

    def count_detail_captured_items(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyAudit.detail_captured.is_(True),
                )
            )
            return session.scalar(stmt) or 0

    def count_analysis_ready_items(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_ready_filter())
            )
            return session.scalar(stmt) or 0

    def analysis_readiness_snapshot(self) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "ready": 0,
                "not_ready": 0,
                "invalid": 0,
                "blockers": {},
            }
        self.initialize()
        detail_stage_ready = or_(
            PropertyAudit.detail_status.in_(("archived", "enriched")),
            and_(PropertyAudit.detail_status.is_(None), PropertyAudit.detail_captured.is_(True)),
        )
        strict_status_ready = PropertyListing.status.in_(self._analysis_status_ready_values())
        strict_location_precision = or_(
            PropertyListing.latitude.is_not(None),
            and_(PropertyListing.community_name.is_not(None), PropertyListing.community_name != ""),
        )
        with self.session_factory() as session:
            stage_counts = self.stage_status_counts()
            blocker_stmt = (
                select(
                    func.sum(case((PropertyListing.auction_date.is_(None), 1), else_=0)),
                    func.sum(case((PropertyListing.area_sqm.is_(None), 1), else_=0)),
                    func.sum(case((or_(PropertyListing.city.is_(None), PropertyListing.city == ""), 1), else_=0)),
                    func.sum(case((or_(PropertyListing.district.is_(None), PropertyListing.district == ""), 1), else_=0)),
                    func.sum(case((or_(PropertyListing.business_area.is_(None), PropertyListing.business_area == ""), 1), else_=0)),
                    func.sum(case((not_(self._analysis_contract_has_price_anchor()), 1), else_=0)),
                    func.sum(case((not_(detail_stage_ready), 1), else_=0)),
                    func.sum(case((not_(strict_status_ready), 1), else_=0)),
                    func.sum(case((not_(strict_location_precision), 1), else_=0)),
                )
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_not_ready_filter())
            )
            row = session.execute(blocker_stmt).one()
        blocker_keys = (
            "auction_date",
            "area_sqm",
            "city",
            "district",
            "business_area",
            "price_anchor",
            "detail_stage",
            "status",
            "location_precision",
        )
        blockers = {
            key: int(value or 0)
            for key, value in zip(blocker_keys, row)
            if int(value or 0) > 0
        }
        return {
            "ready": int(stage_counts.get("analysis_ready", 0) or 0),
            "not_ready": int(stage_counts.get("analysis_not_ready", 0) or 0),
            "invalid": int(stage_counts.get("analysis_invalid", 0) or 0),
            "blockers": blockers,
        }

    def dataset_signature(self) -> tuple[int, str | None]:
        if not self.enabled:
            return (0, None)
        self.initialize()
        with self.session_factory() as session:
            row = session.execute(
                select(
                    func.count(PropertyListing.item_id),
                    func.max(PropertyListing.last_synced_at),
                ).where(PropertyListing.is_deleted.is_(False))
            ).one()
            count_value, max_synced = row
            max_synced_text = None
            if max_synced is not None:
                max_synced_text = max_synced.isoformat(sep=" ", timespec="seconds")
            return int(count_value or 0), max_synced_text

    def yield_analysis_ready_rows(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_ready_filter())
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, audit in stream:
                yield self._feature_source_payload_from_rows(listing, risk, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def yield_analysis_ready_flat_items(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_ready_filter())
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, legal, audit in stream:
                yield self._listing_payload_from_rows(listing, risk, legal, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def iter_analysis_candidate_rows(
        self,
        subject: Dict[str, Any],
        *,
        per_bucket_limit: int = 1500,
        global_limit: int = 2000,
        total_limit: int = 5000,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()

        def _norm(value: Any) -> str:
            text_value = str(value or "").strip()
            if not text_value or text_value == "UNK":
                return ""
            return text_value

        community = _norm(subject.get("community_name"))
        business_area = _norm(subject.get("business_area"))
        district = _norm(subject.get("district"))
        city = _norm(subject.get("city"))

        def _query(session: Session, *conditions, limit: int) -> list[Dict[str, Any]]:
            rows = (
                session.execute(
                    select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                    .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        self._analysis_ready_filter(),
                        *conditions,
                    )
                    .order_by(PropertyListing.auction_date.desc().nulls_last(), PropertyListing.item_id.asc())
                    .limit(limit)
                )
                .all()
            )
            return [self._feature_source_payload_from_rows(listing, risk, audit) for listing, risk, audit in rows]

        ordered_candidates: list[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _extend(rows: list[Dict[str, Any]]) -> None:
            for row in rows:
                item_id = str(row.get("item_id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                ordered_candidates.append(row)
                if len(ordered_candidates) >= total_limit:
                    return

        with self.session_factory() as session:
            if community:
                _extend(_query(session, PropertyListing.community_name == community, limit=per_bucket_limit))
            if len(ordered_candidates) < total_limit and city and district and business_area:
                _extend(
                    _query(
                        session,
                        PropertyListing.city == city,
                        PropertyListing.district == district,
                        PropertyListing.business_area == business_area,
                        limit=per_bucket_limit,
                    )
                )
            if len(ordered_candidates) < total_limit and city and district:
                _extend(
                    _query(
                        session,
                        PropertyListing.city == city,
                        PropertyListing.district == district,
                        limit=per_bucket_limit,
                    )
                )
            if len(ordered_candidates) < total_limit and city:
                _extend(_query(session, PropertyListing.city == city, limit=per_bucket_limit))
            if len(ordered_candidates) < total_limit:
                _extend(_query(session, limit=global_limit))

        return ordered_candidates[:total_limit]

    def iter_pending_task_items(self, limit: int = 100) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing.item_id, PropertyListing.source_url, PropertyListing.status)
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._detail_pending_filter())
                .order_by(PropertyListing.auction_date.asc().nulls_last(), PropertyListing.item_id.asc())
                .limit(limit)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "id": str(item_id),
                    "url": source_url,
                    "status": status,
                }
                for item_id, source_url, status in rows
            ]

    def count_pending_task_items(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._detail_pending_filter())
            )
            return session.scalar(stmt) or 0

    def iter_pending_flat_items(self, limit: int = 100) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            rows = (
                session.execute(
                    select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                    .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(self._detail_pending_filter())
                    .order_by(PropertyListing.auction_date.asc().nulls_last(), PropertyListing.item_id.asc())
                    .limit(limit)
                )
                .all()
            )
            return [
                self._listing_payload_from_rows(listing, risk, legal, audit)
                for listing, risk, legal, audit in rows
            ]

    def iter_archived_detail_candidates(
        self,
        limit: int = 100,
        *,
        require_missing_coordinates: bool = True,
        require_missing_risk: bool = False,
        require_missing_artifacts: bool = True,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            conditions = [
                PropertyListing.is_deleted.is_(False),
                PropertyAudit.detail_archive_path.is_not(None),
                PropertyAudit.detail_archive_path != "",
                PropertyAudit.source_json_path.is_not(None),
                PropertyAudit.source_json_path != "",
            ]
            missing_filters = []
            if require_missing_coordinates:
                missing_filters.append(
                    or_(
                        PropertyListing.latitude.is_(None),
                        PropertyListing.longitude.is_(None),
                    )
                )
            if require_missing_risk:
                missing_filters.append(
                    and_(
                        PropertyRiskFlags.is_occupied.is_(None),
                        PropertyRiskFlags.has_long_lease.is_(None),
                        PropertyRiskFlags.clear_delivery.is_(None),
                        PropertyRiskFlags.tax_burden.is_(None),
                        PropertyRiskFlags.is_fractional_share.is_(None),
                    )
                )
            if require_missing_artifacts:
                missing_filters.append(
                    or_(
                        PropertyAudit.detail_text_path.is_(None),
                        PropertyAudit.detail_text_path == "",
                        PropertyAudit.notice_text_path.is_(None),
                        PropertyAudit.notice_text_path == "",
                        PropertyAudit.desc_text_path.is_(None),
                        PropertyAudit.desc_text_path == "",
                        PropertyAudit.component_payload_path.is_(None),
                        PropertyAudit.component_payload_path == "",
                        PropertyAudit.attachment_manifest_path.is_(None),
                        PropertyAudit.attachment_manifest_path == "",
                        PropertyAudit.image_manifest_path.is_(None),
                        PropertyAudit.image_manifest_path == "",
                    )
                )
            if missing_filters:
                conditions.append(or_(*missing_filters))

            rows = (
                session.execute(
                    select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                    .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(*conditions)
                    .order_by(PropertyListing.auction_date.asc().nulls_last(), PropertyListing.item_id.asc())
                    .limit(limit)
                )
                .all()
            )
            return [
                self._listing_payload_from_rows(listing, risk, legal, audit)
                for listing, risk, legal, audit in rows
            ]

    def iter_detail_fetch_candidates(self, limit: int = 100) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        done_like_statuses = ("done", "成交", "failure", "failed_timeout")
        blocked_ids = self.recent_event_item_ids(
            ("detail_archive_fetch_blocked", "detail_archive_fetch_failed"),
            hours=24,
        )
        with self.session_factory() as session:
            rows = (
                session.execute(
                    select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                    .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        PropertyListing.is_deleted.is_(False),
                        PropertyListing.source_url.is_not(None),
                        PropertyListing.source_url != "",
                        PropertyListing.status.in_(done_like_statuses),
                        PropertyAudit.source_json_path.is_not(None),
                        PropertyAudit.source_json_path != "",
                        or_(PropertyAudit.detail_archive_path.is_(None), PropertyAudit.detail_archive_path == ""),
                    )
                    .order_by(PropertyListing.auction_date.asc().nulls_last(), PropertyListing.item_id.asc())
                    .limit(limit * 20)
                )
                .all()
            )
            return [
                self._listing_payload_from_rows(listing, risk, legal, audit)
                for listing, risk, legal, audit in rows
                if str(listing.item_id) not in blocked_ids
            ][:limit]

    def recent_event_item_ids(self, event_types: Sequence[str], hours: int) -> set[str]:
        if not self.enabled or not event_types:
            return set()
        self.initialize()
        since = datetime.now() - timedelta(hours=max(hours, 0))
        with self.session_factory() as session:
            stmt = (
                select(PropertyIngestEvent.item_id)
                .where(
                    PropertyIngestEvent.item_id.is_not(None),
                    PropertyIngestEvent.event_type.in_(tuple(event_types)),
                    PropertyIngestEvent.created_at >= since,
                )
                .distinct()
            )
            return {str(item_id) for item_id in session.scalars(stmt).all() if item_id}

    def event_type_counts(self, event_types: Sequence[str], hours: int | None = None) -> Dict[str, int]:
        counts = {event_type: 0 for event_type in event_types}
        if not self.enabled or not event_types:
            return counts
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(PropertyIngestEvent.event_type, func.count(PropertyIngestEvent.id))
                .where(PropertyIngestEvent.event_type.in_(tuple(event_types)))
                .group_by(PropertyIngestEvent.event_type)
            )
            if hours is not None:
                since = datetime.now() - timedelta(hours=max(hours, 0))
                stmt = stmt.where(PropertyIngestEvent.created_at >= since)
            for event_type, count_value in session.execute(stmt):
                counts[str(event_type)] = int(count_value or 0)
        return counts

    @staticmethod
    def _search_task_key(location_code: str, category: str, sort_param: str) -> str:
        return f"{location_code}:{category}:{sort_param}"

    @staticmethod
    def _build_search_task_url(location_code: str, category: str, sort_param: str, page: int) -> str:
        return (
            f"https://sf.taobao.com/list/{category}__2.htm"
            f"?location_code={location_code}&st_param={sort_param}&auction_start_seg=-1&page={page}"
        )

    def bootstrap_search_task(self, task: Dict[str, Any], leased_by: str | None = None, lease_seconds: int = 90) -> None:
        if not self.enabled:
            return
        self.initialize()
        location_code = str(task.get("location_code") or "").strip()
        category = str(task.get("category") or "").strip()
        sort_param = str(task.get("st_param") or "").strip()
        page = int(task.get("page") or 1)
        if not location_code or not category or not sort_param:
            return
        task_key = self._search_task_key(location_code, category, sort_param)
        now = datetime.now()
        with self.session_factory.begin() as session:
            row = session.get(PropertySearchTask, task_key) or PropertySearchTask(task_key=task_key)
            row.location_code = location_code
            row.category = category
            row.sort_param = sort_param
            row.next_page = page
            row.source_url = task.get("url") or self._build_search_task_url(location_code, category, sort_param, page)
            row.last_seen_at = now
            if leased_by:
                row.leased_by = leased_by
                row.lease_until = now + timedelta(seconds=max(lease_seconds, 1))
                row.status = "in_progress"
            else:
                row.status = row.status or "pending"
            session.add(row)

    def claim_search_task(
        self,
        session_id: str,
        lease_seconds: int = 90,
        *,
        priority_codes: Sequence[str] | None = None,
        sort_order: Sequence[str] | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = datetime.now()
        priority_index = {code: idx for idx, code in enumerate(priority_codes or [])}
        sort_index = {code: idx for idx, code in enumerate(sort_order or ("2", "1", "0", "3", "4", "5"))}
        with self.session_factory.begin() as session:
            rows = session.execute(
                select(PropertySearchTask)
                .where(
                    or_(
                        PropertySearchTask.status == "pending",
                        and_(
                            PropertySearchTask.status == "in_progress",
                            or_(
                                PropertySearchTask.lease_until.is_(None),
                                PropertySearchTask.lease_until < now,
                                PropertySearchTask.leased_by == session_id,
                            ),
                        ),
                    )
                )
            ).scalars().all()
            ordered_rows = sorted(
                rows,
                key=lambda row: (
                    0 if row.status == "pending" else 1,
                    priority_index.get(str(row.location_code), 10**9),
                    sort_index.get(str(row.sort_param), 10**9),
                    row.updated_at or datetime.min,
                    row.task_key,
                ),
            )
            for row in ordered_rows:
                row.status = "in_progress"
                row.leased_by = session_id
                row.lease_until = now + timedelta(seconds=max(lease_seconds, 1))
                row.last_seen_at = now
                session.add(row)
                page = int(row.next_page or 1)
                return {
                    "location_code": row.location_code,
                    "category": row.category,
                    "st_param": row.sort_param,
                    "page": page,
                    "url": self._build_search_task_url(row.location_code, row.category or "", row.sort_param or "", page),
                    "desc": f"Sniff-{row.location_code}-S{row.sort_param}-P{page}",
                    "is_resume": page > 1,
                }
        return None

    def report_search_task_progress(
        self,
        *,
        url: str,
        page_num: int,
        has_next: bool = True,
        max_page: int | None = None,
        zero_bid_detected: bool = False,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        from urllib.parse import parse_qs, urlparse
        import re

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        location_code = params.get("location_code", [""])[0]
        sort_param = params.get("st_param", ["2"])[0]
        match = re.search(r"/list/(\d+)", parsed.path)
        category = match.group(1) if match else "50025969"
        if not location_code:
            return

        task_key = self._search_task_key(location_code, category, sort_param)
        now = datetime.now()
        with self.session_factory.begin() as session:
            row = session.get(PropertySearchTask, task_key) or PropertySearchTask(task_key=task_key)
            row.location_code = location_code
            row.category = category
            row.sort_param = sort_param
            row.source_url = url
            row.last_seen_at = now
            if max_page and (row.max_page is None or max_page > row.max_page):
                row.max_page = max_page

            if zero_bid_detected or (sort_param == "2" and not has_next and int(page_num or 1) < 83):
                row.status = "done"
                row.zero_bid_terminated = True
                row.next_page = max(int(page_num or 1), 1)
                row.leased_by = None
                row.lease_until = None
                sibling_status = "pruned"
            elif has_next:
                row.status = "pending"
                row.next_page = max(int(page_num or 1) + 1, row.next_page or 1)
                row.leased_by = None
                row.lease_until = None
                sibling_status = None
            else:
                row.status = "done"
                row.next_page = max(int(page_num or 1), row.next_page or 1)
                row.leased_by = None
                row.lease_until = None
                sibling_status = "pending" if sort_param == "2" and int(page_num or 1) >= 83 else None

            session.add(row)
            if sort_param == "2" and sibling_status in {"pending", "pruned"}:
                for sibling_sort in ("1", "0", "3", "4", "5"):
                    sibling_key = self._search_task_key(location_code, category, sibling_sort)
                    sibling = session.get(PropertySearchTask, sibling_key) or PropertySearchTask(task_key=sibling_key)
                    sibling.location_code = location_code
                    sibling.category = category
                    sibling.sort_param = sibling_sort
                    sibling.next_page = max(int(sibling.next_page or 1), 1)
                    sibling.source_url = self._build_search_task_url(location_code, category, sibling_sort, sibling.next_page)
                    sibling.status = sibling_status
                    sibling.zero_bid_terminated = sibling_status == "pruned"
                    sibling.leased_by = None
                    sibling.lease_until = None
                    sibling.last_seen_at = now
                    session.add(sibling)

    def search_task_counts(self) -> Dict[str, int]:
        counts = {
            "search_pending": 0,
            "search_in_progress": 0,
            "search_done": 0,
            "search_pruned": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        with self.session_factory() as session:
            stmt = select(PropertySearchTask.status, func.count(PropertySearchTask.task_key)).group_by(PropertySearchTask.status)
            for status, count_value in session.execute(stmt):
                key = f"search_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
        return counts

    def count_search_tasks(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(PropertySearchTask)) or 0)

    def ensure_seed_search_tasks(self, location_codes: Sequence[str], categories: Sequence[str], sort_param: str = "2") -> int:
        if not self.enabled:
            return 0
        self.initialize()
        inserted = 0
        with self.session_factory.begin() as session:
            for location_code in location_codes:
                if not location_code:
                    continue
                for category in categories:
                    task_key = self._search_task_key(str(location_code), str(category), str(sort_param))
                    row = session.get(PropertySearchTask, task_key)
                    if row is not None:
                        continue
                    row = PropertySearchTask(
                        task_key=task_key,
                        location_code=str(location_code),
                        category=str(category),
                        sort_param=str(sort_param),
                        next_page=1,
                        status="pending",
                        zero_bid_terminated=False,
                        retry_count=0,
                        source_url=self._build_search_task_url(str(location_code), str(category), str(sort_param), 1),
                    )
                    session.add(row)
                    inserted += 1
        return inserted

    def import_search_task_snapshots(self, snapshots: Sequence[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        imported = 0
        with self.session_factory.begin() as session:
            for snapshot in snapshots:
                location_code = str(snapshot.get("location_code") or "").strip()
                category = str(snapshot.get("category") or "").strip()
                sort_param = str(snapshot.get("sort_param") or "").strip()
                if not location_code or not category or not sort_param:
                    continue
                task_key = self._search_task_key(location_code, category, sort_param)
                row = session.get(PropertySearchTask, task_key) or PropertySearchTask(task_key=task_key)
                pages = snapshot.get("pages") or []
                page_floor = max([int(p) for p in pages if isinstance(p, int) or str(p).isdigit()] or [0])
                dispatched_page = int(snapshot.get("dispatched_page") or 0)
                next_page = max(page_floor, dispatched_page, 0) + 1 if not snapshot.get("is_done") else max(page_floor, dispatched_page, 1)
                last_update = _parse_dt(snapshot.get("last_update_time"))
                need_try = bool(snapshot.get("need_try", True))
                is_done = bool(snapshot.get("is_done", False))
                max_page = snapshot.get("max_page")
                max_page_int = int(max_page) if max_page not in (None, "") and str(max_page).lstrip("-").isdigit() else None

                status = "pending"
                zero_bid_terminated = False
                if is_done and not need_try and sort_param != "2":
                    status = "pruned"
                elif is_done:
                    status = "done"
                    if sort_param == "2" and max_page_int is not None and 0 < max_page_int < 83:
                        zero_bid_terminated = True
                elif snapshot.get("now_session_id"):
                    status = "in_progress"

                row.location_code = location_code
                row.category = category
                row.sort_param = sort_param
                row.next_page = max(next_page, 1)
                row.max_page = max_page_int
                row.status = status
                row.leased_by = str(snapshot.get("now_session_id") or "").strip() or None
                row.lease_until = last_update + timedelta(seconds=90) if row.leased_by and last_update else None
                row.zero_bid_terminated = zero_bid_terminated
                row.source_url = self._build_search_task_url(location_code, category, sort_param, row.next_page)
                row.last_seen_at = last_update
                row.retry_count = int(row.retry_count or 0)
                session.add(row)
                imported += 1
        return imported

    def _manual_review_receipt_payload_from_row(self, row: ManualReviewReceipt) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "action": row.action,
            "ready_signal": row.ready_signal,
            "status": row.status,
            "payload": dict(row.payload or {}),
            "updated_at": self._fmt_dt(row.receipt_updated_at or row.updated_at or row.created_at),
        }
        if row.source:
            payload["source"] = row.source
        if row.resolution_notes:
            payload["resolution_notes"] = row.resolution_notes
        return payload

    def list_manual_review_receipts(self) -> Dict[str, list[Dict[str, Any]]]:
        if not self.enabled:
            return {"receipts": []}
        self.initialize()
        with self.session_factory() as session:
            rows = session.execute(
                select(ManualReviewReceipt).order_by(ManualReviewReceipt.action.asc(), ManualReviewReceipt.ready_signal.asc())
            ).scalars()
            return {"receipts": [self._manual_review_receipt_payload_from_row(row) for row in rows]}

    def upsert_manual_review_receipt(self, receipt: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {"operation": "created", "receipt": dict(receipt), "receipt_count": 0}
        self.initialize()
        action = str(receipt.get("action") or "").strip()
        ready_signal = str(receipt.get("ready_signal") or "").strip()
        now = datetime.now()
        with self.session_factory.begin() as session:
            row = session.get(ManualReviewReceipt, {"action": action, "ready_signal": ready_signal})
            operation = "updated" if row is not None else "created"
            if row is None:
                row = ManualReviewReceipt(action=action, ready_signal=ready_signal, status=str(receipt.get("status") or "").strip())
            row.status = str(receipt.get("status") or "").strip()
            row.payload = dict(receipt.get("payload") or {})
            row.source = str(receipt.get("source") or "").strip() or None
            row.resolution_notes = str(receipt.get("resolution_notes") or "").strip() or None
            row.receipt_updated_at = now
            session.add(row)

        snapshot = self.list_manual_review_receipts()
        persisted = next(
            (
                dict(item)
                for item in snapshot.get("receipts") or []
                if item.get("action") == action and item.get("ready_signal") == ready_signal
            ),
            {
                "action": action,
                "ready_signal": ready_signal,
                "status": str(receipt.get("status") or "").strip(),
                "payload": dict(receipt.get("payload") or {}),
                "updated_at": self._fmt_dt(now),
            },
        )
        return {
            "operation": operation,
            "receipt": persisted,
            "receipt_count": len(snapshot.get("receipts") or []),
        }

    def import_manual_review_receipt_snapshot(self, snapshot: Dict[str, Any]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        receipts = snapshot.get("receipts") if isinstance(snapshot, dict) else []
        if not isinstance(receipts, list):
            return 0
        imported = 0
        with self.session_factory.begin() as session:
            for item in receipts:
                if not isinstance(item, dict):
                    continue
                action = str(item.get("action") or "").strip()
                ready_signal = str(item.get("ready_signal") or "").strip()
                if not action or not ready_signal:
                    continue
                row = session.get(ManualReviewReceipt, {"action": action, "ready_signal": ready_signal})
                if row is None:
                    row = ManualReviewReceipt(action=action, ready_signal=ready_signal, status=str(item.get("status") or "").strip())
                row.status = str(item.get("status") or "").strip()
                row.payload = dict(item.get("payload") or {})
                row.source = str(item.get("source") or "").strip() or None
                row.resolution_notes = str(item.get("resolution_notes") or "").strip() or None
                row.receipt_updated_at = _parse_dt(item.get("updated_at")) or datetime.now()
                session.add(row)
                imported += 1
        return imported

    def delete_manual_review_receipt(self, action: str, ready_signal: str) -> Dict[str, Any]:
        if not self.enabled:
            return {"deleted": False, "receipt_count": 0}
        self.initialize()
        action_key = str(action or "").strip()
        ready_signal_key = str(ready_signal or "").strip()
        deleted = False
        with self.session_factory.begin() as session:
            row = session.get(ManualReviewReceipt, {"action": action_key, "ready_signal": ready_signal_key})
            if row is not None:
                session.delete(row)
                deleted = True
        receipt_count = len(self.list_manual_review_receipts().get("receipts") or [])
        return {"deleted": deleted, "receipt_count": receipt_count}

    def _manual_review_receipt_operation_payload_from_row(self, row: ManualReviewReceiptOperation) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "operation_id": row.operation_id,
            "operation": row.operation,
            "action": row.action,
            "ready_signal": row.ready_signal,
            "status": row.status or "",
            "payload_fingerprint": row.payload_fingerprint,
            "source": row.source,
            "execution_mode": row.execution_mode,
            "requested_at": self._fmt_dt(row.requested_at),
        }
        if row.maintenance_job_id:
            payload["maintenance_job_id"] = row.maintenance_job_id
        if row.deleted is not None:
            payload["deleted"] = bool(row.deleted)
        if row.resolution_notes:
            payload["resolution_notes"] = row.resolution_notes
        return payload

    def append_manual_review_receipt_operation(
        self,
        *,
        operation: str,
        receipt: Dict[str, Any] | None,
        execution_mode: str,
        maintenance_job_id: str | None = None,
        deleted: bool | None = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        self.initialize()
        receipt = dict(receipt or {})
        now = datetime.now()
        row = ManualReviewReceiptOperation(
            operation_id=str(uuid4()),
            operation=str(operation or "").strip(),
            action=str(receipt.get("action") or "").strip(),
            ready_signal=str(receipt.get("ready_signal") or "").strip(),
            status=str(receipt.get("status") or "").strip(),
            payload_fingerprint=_manual_review_payload_fingerprint(receipt.get("payload")),
            source=str(receipt.get("source") or "").strip() or None,
            execution_mode=str(execution_mode or "").strip() or "sync",
            maintenance_job_id=str(maintenance_job_id or "").strip() or None,
            deleted=deleted,
            resolution_notes=str(receipt.get("resolution_notes") or "").strip() or None,
            requested_at=now,
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return self._manual_review_receipt_operation_payload_from_row(row)

    def import_manual_review_receipt_operations(self, operations: Sequence[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        imported = 0
        with self.session_factory.begin() as session:
            for item in operations:
                if not isinstance(item, dict):
                    continue
                operation_id = str(item.get("operation_id") or "").strip()
                action = str(item.get("action") or "").strip()
                ready_signal = str(item.get("ready_signal") or "").strip()
                if not operation_id or not action or not ready_signal:
                    continue
                row = session.execute(
                    select(ManualReviewReceiptOperation).where(ManualReviewReceiptOperation.operation_id == operation_id)
                ).scalar_one_or_none()
                if row is None:
                    row = ManualReviewReceiptOperation(operation_id=operation_id)
                row.operation = str(item.get("operation") or "").strip()
                row.action = action
                row.ready_signal = ready_signal
                row.status = str(item.get("status") or "").strip()
                row.payload_fingerprint = str(item.get("payload_fingerprint") or "").strip() or _manual_review_payload_fingerprint({})
                row.source = str(item.get("source") or "").strip() or None
                row.execution_mode = str(item.get("execution_mode") or "").strip() or "sync"
                row.maintenance_job_id = str(item.get("maintenance_job_id") or "").strip() or None
                row.deleted = item.get("deleted") if item.get("deleted") is not None else None
                row.resolution_notes = str(item.get("resolution_notes") or "").strip() or None
                row.requested_at = _parse_dt(item.get("requested_at")) or datetime.now()
                session.add(row)
                imported += 1
        return imported

    def list_manual_review_receipt_operations(
        self,
        *,
        action: str | None = None,
        ready_signal: str | None = None,
        limit: int | None = None,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            stmt = select(ManualReviewReceiptOperation).order_by(
                ManualReviewReceiptOperation.requested_at.asc(),
                ManualReviewReceiptOperation.id.asc(),
            )
            if action:
                stmt = stmt.where(ManualReviewReceiptOperation.action == str(action).strip())
            if ready_signal:
                stmt = stmt.where(ManualReviewReceiptOperation.ready_signal == str(ready_signal).strip())
            rows = list(session.execute(stmt).scalars())
        payloads = [self._manual_review_receipt_operation_payload_from_row(row) for row in rows]
        if limit is not None and limit >= 0:
            return payloads[-limit:]
        return payloads

    def _manual_review_receipt_job_payload_from_row(self, row: ManualReviewReceiptJob) -> Dict[str, Any]:
        return {
            "job_id": row.job_id,
            "status": row.status,
            "receipt_key": {
                "action": row.receipt_action,
                "ready_signal": row.receipt_ready_signal,
            },
            "created_at": self._fmt_dt(row.created_at),
            "started_at": self._fmt_dt(row.started_at),
            "finished_at": self._fmt_dt(row.finished_at),
            "maintenance_options": dict(row.maintenance_options or {}),
            "result_summary": dict(row.result_summary or {}) if isinstance(row.result_summary, dict) else row.result_summary,
            "error": row.error,
        }

    def create_manual_review_receipt_job(self, *, receipt_key: Dict[str, Any], maintenance_options: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {}
        self.initialize()
        row = ManualReviewReceiptJob(
            job_id=str(uuid4()),
            status="queued",
            receipt_action=str(receipt_key.get("action") or "").strip(),
            receipt_ready_signal=str(receipt_key.get("ready_signal") or "").strip(),
            maintenance_options=dict(maintenance_options or {}),
        )
        with self.session_factory.begin() as session:
            session.add(row)
        return self._manual_review_receipt_job_payload_from_row(row)

    def import_manual_review_receipt_jobs_snapshot(self, snapshot: Dict[str, Any]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        jobs = snapshot.get("jobs") if isinstance(snapshot, dict) else []
        if not isinstance(jobs, list):
            return 0
        imported = 0
        with self.session_factory.begin() as session:
            for item in jobs:
                if not isinstance(item, dict):
                    continue
                job_id = str(item.get("job_id") or "").strip()
                receipt_key = item.get("receipt_key") if isinstance(item.get("receipt_key"), dict) else {}
                receipt_action = str(receipt_key.get("action") or "").strip()
                receipt_ready_signal = str(receipt_key.get("ready_signal") or "").strip()
                if not job_id or not receipt_action or not receipt_ready_signal:
                    continue
                row = session.get(ManualReviewReceiptJob, job_id) or ManualReviewReceiptJob(
                    job_id=job_id,
                    status=str(item.get("status") or "").strip() or "queued",
                    receipt_action=receipt_action,
                    receipt_ready_signal=receipt_ready_signal,
                )
                row.status = str(item.get("status") or "").strip() or row.status
                row.receipt_action = receipt_action
                row.receipt_ready_signal = receipt_ready_signal
                row.maintenance_options = dict(item.get("maintenance_options") or {})
                row.result_summary = dict(item.get("result_summary") or {}) if isinstance(item.get("result_summary"), dict) else None
                row.error = str(item.get("error") or "").strip() or None
                row.started_at = _parse_dt(item.get("started_at"))
                row.finished_at = _parse_dt(item.get("finished_at"))
                created_at = _parse_dt(item.get("created_at"))
                if created_at is not None:
                    row.created_at = created_at
                session.add(row)
                imported += 1
        return imported

    def update_manual_review_receipt_job(self, job_id: str, **fields: Any) -> Dict[str, Any] | None:
        if not self.enabled:
            return None
        self.initialize()
        with self.session_factory.begin() as session:
            row = session.get(ManualReviewReceiptJob, str(job_id or "").strip())
            if row is None:
                return None
            if "status" in fields:
                row.status = str(fields.get("status") or "").strip() or row.status
            if "maintenance_options" in fields:
                row.maintenance_options = dict(fields.get("maintenance_options") or {})
            if "result_summary" in fields:
                result_summary = fields.get("result_summary")
                row.result_summary = dict(result_summary or {}) if isinstance(result_summary, dict) else None
            if "error" in fields:
                row.error = str(fields.get("error") or "").strip() or None
            if "started_at" in fields:
                row.started_at = _parse_dt(fields.get("started_at"))
            if "finished_at" in fields:
                row.finished_at = _parse_dt(fields.get("finished_at"))
        with self.session_factory() as session:
            row = session.get(ManualReviewReceiptJob, str(job_id or "").strip())
            return self._manual_review_receipt_job_payload_from_row(row) if row is not None else None

    def get_manual_review_receipt_job(self, job_id: str) -> Dict[str, Any] | None:
        if not self.enabled:
            return None
        self.initialize()
        with self.session_factory() as session:
            row = session.get(ManualReviewReceiptJob, str(job_id or "").strip())
            return self._manual_review_receipt_job_payload_from_row(row) if row is not None else None

    def manual_review_receipt_jobs_snapshot(self) -> Dict[str, Any]:
        if not self.enabled:
            return {"jobs": [], "queue": [], "running_job_id": None}
        self.initialize()
        with self.session_factory() as session:
            rows = list(
                session.execute(
                    select(ManualReviewReceiptJob).order_by(ManualReviewReceiptJob.created_at.asc(), ManualReviewReceiptJob.job_id.asc())
                ).scalars()
            )
        jobs = [self._manual_review_receipt_job_payload_from_row(row) for row in rows]
        queue = [job["job_id"] for job in jobs if job.get("status") == "queued"]
        running_job = next((job for job in jobs if job.get("status") == "running"), None)
        return {
            "jobs": jobs,
            "queue": queue,
            "running_job_id": running_job.get("job_id") if running_job else None,
        }

    def manual_review_control_plane_counts(self) -> Dict[str, int]:
        if not self.enabled:
            return {
                "receipt_count": 0,
                "job_count": 0,
                "operation_count": 0,
            }
        self.initialize()
        with self.session_factory() as session:
            return {
                "receipt_count": int(session.scalar(select(func.count()).select_from(ManualReviewReceipt)) or 0),
                "job_count": int(session.scalar(select(func.count()).select_from(ManualReviewReceiptJob)) or 0),
                "operation_count": int(session.scalar(select(func.count()).select_from(ManualReviewReceiptOperation)) or 0),
            }

    def stage_status_counts(self) -> Dict[str, int]:
        counts = {
            "seed_stored": 0,
            "detail_pending": 0,
            "detail_archived": 0,
            "detail_enriched": 0,
            "detail_blocked": 0,
            "detail_failed": 0,
            "detail_replay_requested": 0,
            "analysis_ready": 0,
            "analysis_not_ready": 0,
            "analysis_invalid": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        with self.session_factory() as session:
            counts["seed_stored"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        PropertyListing.is_deleted.is_(False),
                        or_(
                            PropertyAudit.seed_status == "stored",
                            and_(
                                PropertyAudit.seed_status.is_(None),
                                PropertyListing.source_url.is_not(None),
                                PropertyListing.source_url != "",
                            ),
                        ),
                    )
                )
                or 0
            )
            counts["detail_pending"] = int(
                session.scalar(select(func.count()).select_from(PropertyListing).outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id).where(self._detail_pending_filter()))
                or 0
            )
            counts["detail_archived"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        PropertyListing.is_deleted.is_(False),
                        or_(
                            PropertyAudit.detail_status == "archived",
                            and_(
                                PropertyAudit.detail_status.is_(None),
                                PropertyAudit.detail_archive_path.is_not(None),
                                PropertyAudit.detail_archive_path != "",
                                or_(PropertyAudit.detail_captured.is_(False), PropertyAudit.detail_captured.is_(None)),
                            ),
                        ),
                    )
                )
                or 0
            )
            counts["detail_enriched"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        PropertyListing.is_deleted.is_(False),
                        or_(
                            PropertyAudit.detail_status == "enriched",
                            and_(PropertyAudit.detail_status.is_(None), PropertyAudit.detail_captured.is_(True)),
                        ),
                    )
                )
                or 0
            )
            counts["detail_blocked"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        PropertyListing.is_deleted.is_(False),
                        or_(
                            PropertyAudit.detail_status == "blocked",
                            and_(
                                PropertyAudit.detail_status.is_(None),
                                PropertyAudit.detail_fetch_status.in_(("login_redirect", "anti_bot_gate", "empty_html")),
                            ),
                        ),
                    )
                )
                or 0
            )
            counts["detail_failed"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        PropertyListing.is_deleted.is_(False),
                        or_(
                            PropertyAudit.detail_status == "failed",
                            and_(
                                PropertyAudit.detail_status.is_(None),
                                PropertyAudit.detail_fetch_status.in_(("failed", "fetch_failed", "timeout", "http_error", "parse_error")),
                            ),
                        ),
                    )
                )
                or 0
            )
            counts["detail_replay_requested"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(PropertyListing.is_deleted.is_(False), PropertyAudit.detail_status == "replay_requested")
                )
                or 0
            )
            counts["analysis_ready"] = int(
                session.scalar(select(func.count()).select_from(PropertyListing).outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id).where(self._analysis_ready_filter()))
                or 0
            )
            counts["analysis_invalid"] = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(PropertyListing.is_deleted.is_(False), PropertyAudit.analysis_status == "invalid")
                )
                or 0
            )
            total_active = int(
                session.scalar(
                    select(func.count())
                    .select_from(PropertyListing)
                    .where(PropertyListing.is_deleted.is_(False))
                )
                or 0
            )
            counts["analysis_not_ready"] = max(0, total_active - counts["analysis_ready"] - counts["analysis_invalid"])
        return counts
