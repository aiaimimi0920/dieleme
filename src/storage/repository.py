from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import and_, case, create_engine, func, not_, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.avm.collection_template import build_collection_record
from src.collection.stage_state import derive_stage_state

from .models import (
    Base,
    FapaiSeedItem,
    FapaiSeedOccurrence,
    FapaiSeedScanJob,
    FapaiSeedScanProgress,
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
        return _coerce_naive_utc(value)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d"}:
                dt = dt.replace(hour=0, minute=0, second=0)
            return _coerce_naive_utc(dt)
        except ValueError:
            continue
    return None


def _coerce_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=None)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_now() -> datetime:
    value = _coerce_naive_utc(datetime.utcnow())
    if value is None:
        raise RuntimeError("utc clock returned no value")
    return value


def _lease_reclaimable(
    lease_until: Optional[datetime],
    updated_at: Optional[datetime],
    *,
    now: datetime,
    lease_seconds: int,
) -> bool:
    normalized_lease_until = _coerce_naive_utc(lease_until)
    normalized_updated_at = _coerce_naive_utc(updated_at)
    if normalized_lease_until is None or normalized_lease_until < now:
        return True
    max_window = timedelta(seconds=max(max(int(lease_seconds or 0), 1) * 4, 300))
    if normalized_lease_until - now > max_window:
        return True
    if normalized_updated_at is not None and normalized_lease_until - normalized_updated_at > max_window:
        return True
    return False


def _cooldown_active(updated_at: Optional[datetime], *, now: datetime, cutoff: Optional[datetime]) -> bool:
    if cutoff is None:
        return False
    normalized_updated_at = _coerce_naive_utc(updated_at)
    if normalized_updated_at is None:
        return False
    if normalized_updated_at - now > timedelta(seconds=300):
        return False
    return normalized_updated_at >= cutoff


def _manual_review_payload_fingerprint(payload: Any) -> str:
    normalized = json.dumps(payload if payload is not None else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# Keep the locked candidate window small so detail/analysis claim paths do not
# hold broad row locks while filtering candidates in Python.
SEED_ITEM_CLAIM_BATCH_LIMIT = 16
# Avoid starving long-stuck retryable failures behind a large pending backlog.
SEED_ITEM_STALE_FAILED_PRIORITY_SECONDS = 300


def _seed_claim_cursor_clause(
    priority_expr,
    sort_first_seen_at,
    last_cursor: tuple[int, datetime, str] | None,
):
    if last_cursor is None:
        return None
    last_priority, last_first_seen_at, last_item_id = last_cursor
    return or_(
        priority_expr > last_priority,
        and_(priority_expr == last_priority, sort_first_seen_at > last_first_seen_at),
        and_(
            priority_expr == last_priority,
            sort_first_seen_at == last_first_seen_at,
            FapaiSeedItem.item_id > last_item_id,
        ),
    )


def _normalized_seed_text(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    text_value = str(value).strip()
    return text_value or None


def _shared_data_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()
    for env_name in (
        "FAPAI_SHARED_ARTIFACT_ROOT",
        "FAPAI_SHARED_DATA_ROOT_HOST",
        "FAPAI_DATA_ROOT_HOST",
        "FAPAI_SHARED_DATA_ROOT",
        "FAPAI_DATA_ROOT",
    ):
        raw = str(os.getenv(env_name) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(path)
    return candidates


def _shared_artifact_relative_path(path_value: str) -> str | None:
    """Extract a relative path from a Windows/UNC FPFData artifact path.

    Workers may run on Windows and persist their host path in the central DB.
    The API runs in Linux, so only the portion below the shared FPFData root is
    portable. Reject traversal rather than resolving arbitrary host paths.
    """
    normalized = path_value.replace("\\", "/")
    lowered = normalized.lower()
    marker = "/fpfdata/"
    marker_index = lowered.find(marker)
    if marker_index < 0:
        return None
    relative = normalized[marker_index + len(marker) :].lstrip("/")
    if not relative:
        return None
    parts = [part for part in relative.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return None
    return "/".join(parts)


def _resolve_from_shared_artifact_roots(path_value: str) -> str | None:
    relative = _shared_artifact_relative_path(path_value)
    if not relative:
        return None
    for root in _shared_data_root_candidates():
        try:
            candidate = (root / relative).resolve()
            resolved_root = root.resolve()
            candidate.relative_to(resolved_root)
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            return str(candidate)
    return None


def _resolve_collection_artifact_path(path_value: Any) -> str | None:
    text = str(path_value or "").strip()
    if not text:
        return None
    if os.path.isfile(text):
        return text

    shared_candidate = _resolve_from_shared_artifact_roots(text)
    if shared_candidate:
        return shared_candidate

    normalized = text.replace("\\", "/")
    if not normalized.startswith("/data/"):
        return text

    relative_parts = [part for part in normalized[len("/data/") :].split("/") if part]
    if not relative_parts:
        return text

    for root in _shared_data_root_candidates():
        candidate = root.joinpath(*relative_parts)
        if candidate.is_file():
            return str(candidate)
    return text


def _taobao_location_override_path() -> Path:
    configured = str(os.getenv("FAPAI_TAOBAO_LOCATIONS_FILE") or "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "datas" / "taobao_sf_location_overrides.json"


def _load_taobao_region_override_filter() -> tuple[set[str], set[str]]:
    path = _taobao_location_override_path()
    if not path.exists():
        return set(), set()
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), set()
    if not isinstance(decoded, dict):
        return set(), set()
    raw_locations = decoded.get("locations") or []
    raw_replace_admin_provinces = decoded.get("replace_admin_provinces") or []
    override_codes = {
        str(item.get("location_code") or item.get("code") or "").strip()
        for item in raw_locations
        if isinstance(item, dict)
    }
    replace_admin_provinces = {
        str(item or "").strip()
        for item in raw_replace_admin_provinces
    }
    return {code for code in override_codes if code}, {province for province in replace_admin_provinces if province}


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
        value = _coerce_naive_utc(value)
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
            "community_name_source": audit.community_name_source if audit else None,
            "community_name_confidence": float(audit.community_name_confidence) if audit and audit.community_name_confidence is not None else None,
            "community_stable_key": audit.community_stable_key if audit else None,
            "community_raw_name": audit.community_raw_name if audit else None,
            "beike_community_id": audit.beike_community_id if audit else None,
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
            "community_name_source": audit_payload["community_name_source"],
            "community_name_confidence": audit_payload["community_name_confidence"],
            "community_stable_key": audit_payload["community_stable_key"],
            "community_raw_name": audit_payload["community_raw_name"],
            "beike_community_id": audit_payload["beike_community_id"],
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
        now = _utc_now()
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
        audit_row.community_name_source = audit.get("community_name_source")
        audit_row.community_name_confidence = audit.get("community_name_confidence")
        audit_row.community_stable_key = audit.get("community_stable_key")
        audit_row.community_raw_name = audit.get("community_raw_name")
        audit_row.beike_community_id = audit.get("beike_community_id")
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
            listing.last_synced_at = _utc_now()
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
        since = _utc_now() - timedelta(hours=max(hours, 0))
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
                since = _utc_now() - timedelta(hours=max(hours, 0))
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
        now = _utc_now()
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
        now = _utc_now()
        priority_index = {code: idx for idx, code in enumerate(priority_codes or [])}
        sort_index = {code: idx for idx, code in enumerate(sort_order or ("2", "1", "0", "3", "4", "5"))}
        with self.session_factory.begin() as session:
            rows = session.execute(
                select(PropertySearchTask).where(PropertySearchTask.status.in_(("pending", "in_progress")))
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
                if row.status == "in_progress" and row.leased_by != session_id:
                    if not _lease_reclaimable(row.lease_until, row.updated_at, now=now, lease_seconds=lease_seconds):
                        continue
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
        now = _utc_now()
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

    @staticmethod
    def _seed_scan_job_key(job: Dict[str, Any]) -> str:
        explicit = _normalized_seed_text(job.get("job_key"))
        if explicit:
            return explicit
        location_code = _normalized_seed_text(job.get("location_code")) or "unknown-location"
        category = _normalized_seed_text(job.get("category")) or "unknown-category"
        district = _normalized_seed_text(job.get("district")) or _normalized_seed_text(job.get("city")) or "scope"
        return f"{location_code}:{category}:{district}"

    @staticmethod
    def _seed_scan_progress_key(job_key: str, sort_key: str) -> str:
        raw = f"{job_key}:{sort_key}"
        if len(raw) <= 256:
            return raw
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        return f"{job_key[:210]}:{digest}"

    @staticmethod
    def _build_seed_scan_url(location_code: str, category: str, st_param: str, page: int) -> str:
        return (
            f"https://sf.taobao.com/list/{category}__2.htm"
            f"?location_code={location_code}&st_param={st_param}&auction_start_seg=-1&page={page}"
        )

    @staticmethod
    def _occurrence_key(
        *,
        item_id: str,
        job_key: str,
        sort_key: str,
        page: int,
        rank: int,
    ) -> str:
        raw = f"{item_id}|{job_key}|{sort_key}|{page}|{rank}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _seed_item_url(item_id: str, explicit_url: Any = None) -> str:
        url = _normalized_seed_text(explicit_url)
        if url:
            if url.startswith("//"):
                url = f"https:{url}"
            try:
                parsed = urlsplit(url)
            except ValueError:
                return url
            if (parsed.hostname or "").lower() == "sf-item.taobao.com":
                path = parsed.path
                while "//" in path:
                    path = path.replace("//", "/")
                return urlunsplit((parsed.scheme or "https", parsed.netloc, path, parsed.query, parsed.fragment))
            return url
        return f"https://sf-item.taobao.com/sf_item/{item_id}.htm"

    @staticmethod
    def _seed_scan_progress_payload(row: FapaiSeedScanProgress, job: FapaiSeedScanJob) -> Dict[str, Any]:
        page = int(row.next_page or 1)
        url = PropertyRepository._build_seed_scan_url(job.location_code, job.category, row.st_param, page)
        return {
            "job_key": row.job_key,
            "progress_key": row.progress_key,
            "province": job.province,
            "city": job.city,
            "district": job.district,
            "location_code": job.location_code,
            "category": job.category,
            "sort_key": row.sort_key,
            "sort_name": row.sort_name,
            "st_param": row.st_param,
            "sort_order": row.sort_order,
            "page": page,
            "max_page": row.max_page,
            "url": url,
        }

    @staticmethod
    def _seed_category_order(category: str | None) -> tuple[int, str]:
        normalized = _normalized_seed_text(category)
        preferred = {
            "50025969": 0,
            "200782003": 1,
        }
        return preferred.get(normalized, 10_000), normalized

    @staticmethod
    def _seed_scan_scope_order_key(job: FapaiSeedScanJob | None) -> tuple[Any, ...]:
        if job is None:
            return ("", "", "", "", 10_000, "", "")
        category_rank, category = PropertyRepository._seed_category_order(job.category)
        return (
            _normalized_seed_text(job.province),
            _normalized_seed_text(job.city),
            _normalized_seed_text(job.district),
            _normalized_seed_text(job.location_code),
            category_rank,
            category,
            _normalized_seed_text(job.job_key),
        )

    def _refresh_seed_scan_job_status(self, session: Session, job_key: str, now: datetime | None = None) -> None:
        now = now or _utc_now()
        job = session.get(FapaiSeedScanJob, job_key)
        if job is None:
            return
        progress_rows = session.scalars(
            select(FapaiSeedScanProgress).where(FapaiSeedScanProgress.job_key == job_key)
        ).all()
        if not progress_rows:
            job.status = "pending"
            job.completed_at = None
            session.add(job)
            return
        statuses = {row.status for row in progress_rows}
        if statuses and statuses.issubset({"exhausted"}):
            job.status = "completed"
            job.completed_at = job.completed_at or now
        elif "blocked" in statuses and statuses.issubset({"exhausted", "blocked"}):
            job.status = "blocked"
            job.completed_at = None
        elif "in_progress" in statuses:
            job.status = "in_progress"
            job.completed_at = None
        else:
            job.status = "pending"
            job.completed_at = None
        session.add(job)

    def ensure_seed_scan_job(
        self,
        job: Dict[str, Any],
        *,
        sort_specs: Sequence[Dict[str, Any]],
        max_page: int | None = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"job_key": self._seed_scan_job_key(job), "created": False, "progress_created": 0}
        self.initialize()
        job_key = self._seed_scan_job_key(job)
        location_code = _normalized_seed_text(job.get("location_code"))
        category = _normalized_seed_text(job.get("category")) or "50025969"
        if not location_code:
            raise ValueError("seed scan job requires location_code")
        if not sort_specs:
            raise ValueError("seed scan job requires at least one sort spec")

        now = _utc_now()
        progress_created = 0

        def apply_job_fields(row: FapaiSeedScanJob) -> None:
            row.province = _normalized_seed_text(job.get("province"))
            row.city = _normalized_seed_text(job.get("city"))
            row.district = _normalized_seed_text(job.get("district"))
            row.location_code = location_code
            row.category = category
            if row.status in (None, ""):
                row.status = "pending"
                row.completed_at = None
            row.source_url_template = self._build_seed_scan_url(location_code, category, "{st_param}", 1)
            row.metadata_json = dict(job.get("metadata") or {})

        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedScanJob, job_key)
            if row is None:
                row = FapaiSeedScanJob(job_key=job_key)
                apply_job_fields(row)
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                    created = True
                except IntegrityError:
                    created = False
                    row = session.get(FapaiSeedScanJob, job_key)
                    if row is None:
                        raise
            else:
                created = False
            apply_job_fields(row)
            session.add(row)

            for index, sort_spec in enumerate(sort_specs):
                sort_key = _normalized_seed_text(sort_spec.get("sort_key")) or _normalized_seed_text(sort_spec.get("st_param")) or f"sort_{index}"
                st_param = _normalized_seed_text(sort_spec.get("st_param")) or sort_key
                progress_key = self._seed_scan_progress_key(job_key, sort_key)
                progress = session.get(FapaiSeedScanProgress, progress_key)
                if progress is None:
                    progress = FapaiSeedScanProgress(
                        progress_key=progress_key,
                        job_key=job_key,
                        sort_key=sort_key,
                        st_param=st_param,
                        next_page=1,
                        status="pending",
                        retry_count=0,
                    )
                    try:
                        with session.begin_nested():
                            session.add(progress)
                            session.flush()
                        progress_created += 1
                    except IntegrityError:
                        progress = session.get(FapaiSeedScanProgress, progress_key)
                        if progress is None:
                            progress = session.scalar(
                                select(FapaiSeedScanProgress).where(
                                    FapaiSeedScanProgress.job_key == job_key,
                                    FapaiSeedScanProgress.sort_key == sort_key,
                                )
                            )
                        if progress is None:
                            raise
                progress.sort_name = _normalized_seed_text(sort_spec.get("sort_name")) or sort_key
                progress.st_param = st_param
                progress.sort_order = int(sort_spec.get("sort_order") if sort_spec.get("sort_order") is not None else index)
                progress.max_page = int(max_page) if max_page else None
                if progress.status in (None, "", "archived"):
                    progress.status = "pending"
                    progress.completed_at = None
                session.add(progress)

            self._refresh_seed_scan_job_status(session, job_key, now)
        return {"job_key": job_key, "created": created, "progress_created": progress_created}

    def archive_seed_scan_jobs_except(self, active_job_keys: Sequence[str]) -> Dict[str, int]:
        normalized_keys = sorted(
            {
                key
                for key in (_normalized_seed_text(value) for value in active_job_keys)
                if key
            }
        )
        if not self.enabled:
            return {
                "active_job_count": len(normalized_keys),
                "archived_jobs": 0,
                "archived_progress": 0,
            }
        if not normalized_keys:
            raise ValueError("active_job_keys must not be empty")
        self.initialize()
        now = _utc_now()
        archived_jobs = 0
        archived_progress = 0
        with self.session_factory.begin() as session:
            stale_jobs = session.scalars(
                select(FapaiSeedScanJob).where(not_(FapaiSeedScanJob.job_key.in_(normalized_keys)))
            ).all()
            stale_job_keys = [row.job_key for row in stale_jobs]
            stale_progress_rows: list[FapaiSeedScanProgress] = []
            if stale_job_keys:
                stale_progress_rows = session.scalars(
                    select(FapaiSeedScanProgress).where(FapaiSeedScanProgress.job_key.in_(stale_job_keys))
                ).all()

            for row in stale_jobs:
                if row.status != "archived":
                    archived_jobs += 1
                row.status = "archived"
                row.leased_by = None
                row.lease_until = None
                row.updated_at = now
                session.add(row)

            for row in stale_progress_rows:
                if row.status != "archived":
                    archived_progress += 1
                row.status = "archived"
                row.leased_by = None
                row.lease_until = None
                row.updated_at = now
                session.add(row)

        return {
            "active_job_count": len(normalized_keys),
            "archived_jobs": archived_jobs,
            "archived_progress": archived_progress,
        }

    def release_seed_scan_worker_leases(self, worker_id: str) -> Dict[str, int]:
        if not self.enabled:
            return {"released": 0}
        normalized_worker_id = str(worker_id or "").strip()
        if not normalized_worker_id:
            return {"released": 0}
        self.initialize()
        now = _utc_now()
        released = 0
        with self.session_factory.begin() as session:
            rows = session.scalars(
                select(FapaiSeedScanProgress).where(
                    FapaiSeedScanProgress.status == "in_progress",
                    FapaiSeedScanProgress.leased_by == normalized_worker_id,
                )
            ).all()
            for row in rows:
                row.status = "pending"
                row.leased_by = None
                row.lease_until = None
                row.updated_at = now
                session.add(row)
                self._refresh_seed_scan_job_status(session, row.job_key, now)
                released += 1
        return {"released": released}

    def claim_seed_scan_page(
        self,
        worker_id: str,
        lease_seconds: int = 90,
        *,
        parallel_sorts: bool = False,
        failure_cooldown_threshold: int | None = None,
        failure_cooldown_seconds: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        cooldown_threshold = max(int(failure_cooldown_threshold or 0), 0)
        cooldown_seconds = max(int(failure_cooldown_seconds or 0), 0)
        failure_cooldown_cutoff = now - timedelta(seconds=cooldown_seconds) if cooldown_seconds > 0 else None

        def failure_in_cooldown(row: FapaiSeedScanProgress) -> bool:
            if cooldown_threshold <= 0 or failure_cooldown_cutoff is None:
                return False
            if not str(row.last_error or "").strip():
                return False
            if int(row.retry_count or 0) < cooldown_threshold:
                return False
            return _cooldown_active(row.updated_at, now=now, cutoff=failure_cooldown_cutoff)

        with self.session_factory.begin() as session:
            if parallel_sorts:
                category_rank_expr = case(
                    (FapaiSeedScanJob.category == "50025969", 0),
                    (FapaiSeedScanJob.category == "200782003", 1),
                    else_=10_000,
                )
                ordered = session.scalars(
                    select(FapaiSeedScanProgress)
                    .join(FapaiSeedScanJob, FapaiSeedScanProgress.job_key == FapaiSeedScanJob.job_key)
                    .where(FapaiSeedScanProgress.status.in_(("pending", "in_progress")))
                    .order_by(
                        FapaiSeedScanJob.province,
                        FapaiSeedScanJob.city,
                        FapaiSeedScanJob.district,
                        FapaiSeedScanJob.location_code,
                        category_rank_expr,
                        FapaiSeedScanJob.category,
                        FapaiSeedScanProgress.retry_count,
                        FapaiSeedScanProgress.next_page,
                        FapaiSeedScanProgress.job_key,
                        FapaiSeedScanProgress.sort_order,
                        FapaiSeedScanProgress.progress_key,
                    )
                    .limit(512)
                ).all()
                progress_by_job: Dict[str, list[FapaiSeedScanProgress]] = {}
            else:
                rows = session.scalars(select(FapaiSeedScanProgress)).all()
                jobs_by_key = {
                    job.job_key: job
                    for job in session.scalars(select(FapaiSeedScanJob)).all()
                }
                progress_by_job = {}
                for row in rows:
                    progress_by_job.setdefault(row.job_key, []).append(row)

                ordered = sorted(
                    rows,
                    key=lambda row: (
                        self._seed_scan_scope_order_key(jobs_by_key.get(row.job_key)),
                        int(row.sort_order or 0),
                        int(row.next_page or 1),
                        row.progress_key,
                    ),
                )
            blocked_job_keys: set[str] = set()
            for row in ordered:
                if not parallel_sorts and row.job_key in blocked_job_keys:
                    continue
                if row.status not in {"pending", "in_progress"}:
                    continue
                if row.status == "in_progress" and row.leased_by != worker_id:
                    if not _lease_reclaimable(row.lease_until, row.updated_at, now=now, lease_seconds=lease_seconds):
                        if parallel_sorts:
                            continue
                        blocked_job_keys.add(row.job_key)
                        continue
                if failure_in_cooldown(row):
                    if parallel_sorts:
                        continue
                    blocked_job_keys.add(row.job_key)
                    continue
                if row.max_page is not None and int(row.next_page or 1) > int(row.max_page):
                    row.status = "exhausted"
                    row.leased_by = None
                    row.lease_until = None
                    row.completed_at = row.completed_at or now
                    session.add(row)
                    self._refresh_seed_scan_job_status(session, row.job_key, now)
                    continue

                if not parallel_sorts:
                    siblings = sorted(progress_by_job.get(row.job_key, []), key=lambda sibling: (int(sibling.sort_order or 0), sibling.progress_key))
                    if any(
                        int(sibling.sort_order or 0) < int(row.sort_order or 0)
                        and sibling.status in {"pending", "in_progress"}
                        and not failure_in_cooldown(sibling)
                        and not (
                            sibling.status == "in_progress"
                            and sibling.leased_by != worker_id
                            and _lease_reclaimable(
                                sibling.lease_until,
                                sibling.updated_at,
                                now=now,
                                lease_seconds=lease_seconds,
                            )
                        )
                        for sibling in siblings
                    ):
                        blocked_job_keys.add(row.job_key)
                        continue

                job = session.get(FapaiSeedScanJob, row.job_key)
                if job is None:
                    continue
                row.status = "in_progress"
                row.leased_by = worker_id
                row.lease_until = lease_until
                session.add(row)
                self._refresh_seed_scan_job_status(session, row.job_key, now)
                return self._seed_scan_progress_payload(row, job)
        return None

    def complete_seed_scan_page(
        self,
        *,
        progress_key: str,
        page: int,
        item_count: int,
        has_next: bool,
        source_url: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedScanProgress, progress_key)
            if row is None:
                return
            row.last_success_page = max(int(page or 1), int(row.last_success_page or 0))
            row.last_item_count = int(item_count or 0)
            row.last_fetch_url = source_url
            row.last_error = None
            row.retry_count = 0
            row.leased_by = None
            row.lease_until = None
            max_page = int(row.max_page) if row.max_page else None
            next_page = int(page or 1) + 1
            if bool(has_next) and (max_page is None or next_page <= max_page):
                row.status = "pending"
                row.next_page = max(int(row.next_page or 1), next_page)
                row.completed_at = None
            else:
                row.status = "exhausted"
                row.next_page = max(int(row.next_page or 1), int(page or 1))
                row.completed_at = now
            session.add(row)
            self._refresh_seed_scan_job_status(session, row.job_key, now)

    def fail_seed_scan_page(self, progress_key: str, error: str, *, retryable: bool = True) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedScanProgress, progress_key)
            if row is None:
                return
            previous_error = str(row.last_error or "").strip()
            row.last_error = str(error)
            if previous_error:
                row.retry_count = int(row.retry_count or 0) + 1
            else:
                row.retry_count = 1
            row.leased_by = None
            row.lease_until = None
            row.status = "pending" if retryable else "blocked"
            row.updated_at = now
            session.add(row)
            self._refresh_seed_scan_job_status(session, row.job_key, now)

    def upsert_seed_items(
        self,
        *,
        job_key: str,
        progress_key: str,
        sort_key: str,
        sort_name: str | None,
        st_param: str,
        page: int,
        source_page_url: str,
        items: Sequence[Dict[str, Any]],
        source_final_url: str | None = None,
    ) -> Dict[str, int]:
        if not self.enabled:
            return {"seen": 0, "new_items": 0, "existing_items": 0, "new_occurrences": 0}
        self.initialize()
        now = _utc_now()
        seen = 0
        new_items = 0
        existing_items = 0
        new_occurrences = 0
        with self.session_factory.begin() as session:
            dialect_name = session.get_bind().dialect.name
            for rank, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                item_id = _normalized_seed_text(item.get("id") or item.get("item_id") or item.get("source_item_id"))
                if not item_id:
                    continue
                seen += 1
                url = self._seed_item_url(item_id, item.get("url") or item.get("source_url") or item.get("itemUrl"))
                title = _normalized_seed_text(item.get("title") or item.get("source_title"))
                seed_item = session.get(FapaiSeedItem, item_id)
                if seed_item is None:
                    insert_values = {
                        "item_id": item_id,
                        "source_item_id": item_id,
                        "source_url": url,
                        "title": title,
                        "first_seen_job_key": job_key,
                        "first_seen_sort_key": sort_key,
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "source_payload": dict(item),
                        "status": "pending_detail",
                        "detail_attempt_count": 0,
                    }
                    if dialect_name == "postgresql":
                        insert_stmt = postgresql_insert(FapaiSeedItem).values(**insert_values)
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=[FapaiSeedItem.item_id])
                    elif dialect_name == "sqlite":
                        insert_stmt = sqlite_insert(FapaiSeedItem).values(**insert_values)
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=[FapaiSeedItem.item_id])
                    else:
                        insert_stmt = None
                    if insert_stmt is not None:
                        result = session.execute(insert_stmt)
                        if int(result.rowcount or 0) > 0:
                            new_items += 1
                        else:
                            existing_items += 1
                    else:
                        try:
                            session.add(
                                FapaiSeedItem(
                                    item_id=item_id,
                                    source_item_id=item_id,
                                    source_url=url,
                                    title=title,
                                    first_seen_job_key=job_key,
                                    first_seen_sort_key=sort_key,
                                    first_seen_at=now,
                                    last_seen_at=now,
                                    source_payload=dict(item),
                                    status="pending_detail",
                                    detail_attempt_count=0,
                                )
                            )
                            session.flush()
                            new_items += 1
                        except IntegrityError:
                            session.rollback()
                            existing_items += 1
                    seed_item = session.get(FapaiSeedItem, item_id)
                    if seed_item is None:
                        continue
                else:
                    existing_items += 1
                if not seed_item.source_url and url:
                    seed_item.source_url = url
                if not seed_item.title and title:
                    seed_item.title = title
                seed_item.last_seen_at = now
                seed_item.source_payload = dict(item)
                if seed_item.status in (None, "", "blocked"):
                    seed_item.status = "pending_detail"
                session.add(seed_item)

                occurrence_key = self._occurrence_key(
                    item_id=item_id,
                    job_key=job_key,
                    sort_key=sort_key,
                    page=int(page or 1),
                    rank=rank,
                )
                occurrence_values = {
                    "occurrence_key": occurrence_key,
                    "item_id": item_id,
                    "job_key": job_key,
                    "progress_key": progress_key,
                    "sort_key": sort_key,
                    "sort_name": sort_name,
                    "st_param": st_param,
                    "page": int(page or 1),
                    "rank": rank,
                    "source_page_url": source_page_url,
                    "source_final_url": source_final_url,
                    "raw_item": dict(item),
                    "seen_at": now,
                }
                if dialect_name == "postgresql":
                    occurrence_stmt = postgresql_insert(FapaiSeedOccurrence).values(**occurrence_values)
                    occurrence_stmt = occurrence_stmt.on_conflict_do_nothing(
                        index_elements=[FapaiSeedOccurrence.occurrence_key]
                    )
                    occurrence_result = session.execute(occurrence_stmt)
                    if int(occurrence_result.rowcount or 0) > 0:
                        new_occurrences += 1
                elif dialect_name == "sqlite":
                    occurrence_stmt = sqlite_insert(FapaiSeedOccurrence).values(**occurrence_values)
                    occurrence_stmt = occurrence_stmt.on_conflict_do_nothing(
                        index_elements=[FapaiSeedOccurrence.occurrence_key]
                    )
                    occurrence_result = session.execute(occurrence_stmt)
                    if int(occurrence_result.rowcount or 0) > 0:
                        new_occurrences += 1
                else:
                    occurrence = session.scalars(
                        select(FapaiSeedOccurrence).where(FapaiSeedOccurrence.occurrence_key == occurrence_key)
                    ).first()
                    if occurrence is None:
                        occurrence = FapaiSeedOccurrence(**occurrence_values)
                        session.add(occurrence)
                        new_occurrences += 1
        return {
            "seen": seen,
            "new_items": new_items,
            "existing_items": existing_items,
            "new_occurrences": new_occurrences,
        }

    def claim_seed_detail_item(
        self,
        worker_id: str,
        lease_seconds: int = 300,
        *,
        exclude_item_ids: Iterable[str] | None = None,
        max_item_attempts: int | None = None,
        failure_cooldown_seconds: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        excluded = {str(item_id) for item_id in (exclude_item_ids or ())}
        attempt_limit = max(int(max_item_attempts), 1) if max_item_attempts is not None else None
        cooldown_seconds = max(int(failure_cooldown_seconds or 0), 0)
        failure_cooldown_cutoff = now - timedelta(seconds=cooldown_seconds) if cooldown_seconds > 0 else None
        claimed_item_id: str | None = None
        claimed_payload: Dict[str, Any] | None = None
        with self.session_factory.begin() as session:
            stale_failed_retry_cutoff = now - timedelta(seconds=SEED_ITEM_STALE_FAILED_PRIORITY_SECONDS)
            stale_retry_timestamp = func.coalesce(FapaiSeedItem.updated_at, FapaiSeedItem.first_seen_at)
            sort_first_seen_at = func.coalesce(FapaiSeedItem.first_seen_at, datetime.min)
            detail_claim_priority = case(
                (
                    and_(
                        FapaiSeedItem.status == "in_progress",
                        or_(
                            FapaiSeedItem.detail_lease_until.is_(None),
                            FapaiSeedItem.detail_lease_until < now,
                        ),
                    ),
                    0,
                ),
                (
                    and_(
                        FapaiSeedItem.status == "detail_failed",
                        stale_retry_timestamp < stale_failed_retry_cutoff,
                    ),
                    1,
                ),
                (FapaiSeedItem.status == "pending_detail", 2),
                (FapaiSeedItem.status == "detail_failed", 3),
                (FapaiSeedItem.status == "in_progress", 4),
                else_=99,
            )

            def _detail_row_priority(row: FapaiSeedItem) -> int:
                if (
                    row.status == "in_progress"
                    and row.detail_leased_by != worker_id
                    and _lease_reclaimable(row.detail_lease_until, row.updated_at, now=now, lease_seconds=lease_seconds)
                ):
                    return 0
                if row.status == "detail_failed" and (
                    (_coerce_naive_utc(row.updated_at) or row.first_seen_at or datetime.min) < stale_failed_retry_cutoff
                ):
                    return 1
                if row.status == "pending_detail":
                    return 2
                if row.status == "detail_failed":
                    return 3
                return 4

            last_cursor: tuple[int, datetime, str] | None = None
            while claimed_payload is None:
                candidate_query = (
                    select(
                        FapaiSeedItem.item_id,
                        detail_claim_priority.label("claim_priority"),
                        sort_first_seen_at.label("sort_first_seen_at"),
                    )
                    .where(FapaiSeedItem.status.in_(("pending_detail", "detail_failed", "in_progress")))
                    .order_by(detail_claim_priority, sort_first_seen_at.asc(), FapaiSeedItem.item_id.asc())
                    .limit(SEED_ITEM_CLAIM_BATCH_LIMIT)
                )
                if excluded:
                    candidate_query = candidate_query.where(not_(FapaiSeedItem.item_id.in_(excluded)))
                cursor_clause = _seed_claim_cursor_clause(detail_claim_priority, sort_first_seen_at, last_cursor)
                if cursor_clause is not None:
                    candidate_query = candidate_query.where(cursor_clause)
                candidates = session.execute(candidate_query).all()
                if not candidates:
                    break
                locked_rows: list[FapaiSeedItem] = []
                for candidate in candidates:
                    candidate_item_id = str(candidate.item_id)
                    row = session.scalars(
                        select(FapaiSeedItem)
                        .where(FapaiSeedItem.item_id == candidate_item_id)
                        .with_for_update(skip_locked=True)
                    ).first()
                    if row is None:
                        continue
                    locked_rows.append(row)
                remaining_rows: list[FapaiSeedItem] = []
                for row in locked_rows:
                    attempt_count = int(row.detail_attempt_count or 0)
                    if attempt_limit is not None and attempt_count >= attempt_limit:
                        row.status = "detail_blocked"
                        row.detail_leased_by = None
                        row.detail_lease_until = None
                        previous_error = (row.detail_last_error or "").strip()
                        limit_error = f"retry limit reached: attempts={attempt_count}, max={attempt_limit}"
                        row.detail_last_error = (
                            f"{limit_error}; previous_error={previous_error}" if previous_error else limit_error
                        )
                        session.add(row)
                        continue
                    remaining_rows.append(row)
                remaining_rows.sort(
                    key=lambda row: (
                        _detail_row_priority(row),
                        row.first_seen_at or datetime.min,
                        row.item_id,
                    )
                )
                for row in remaining_rows:
                    if row.status == "in_progress" and row.detail_leased_by != worker_id:
                        if not _lease_reclaimable(
                            row.detail_lease_until,
                            row.updated_at,
                            now=now,
                            lease_seconds=lease_seconds,
                        ):
                            continue
                    if (
                        failure_cooldown_cutoff is not None
                        and row.status == "detail_failed"
                        and _cooldown_active(row.updated_at, now=now, cutoff=failure_cooldown_cutoff)
                    ):
                        continue
                    attempt_count = int(row.detail_attempt_count or 0)
                    row.status = "in_progress"
                    row.detail_leased_by = worker_id
                    row.detail_lease_until = lease_until
                    row.detail_attempt_count = attempt_count + 1
                    session.add(row)
                    claimed_item_id = row.item_id
                    claimed_payload = dict(row.source_payload or {})
                    claimed_payload.setdefault("id", row.item_id)
                    claimed_payload.setdefault("item_id", row.item_id)
                    claimed_payload.setdefault("source_item_id", row.source_item_id or row.item_id)
                    canonical_url = self._seed_item_url(
                        row.item_id,
                        row.source_url or claimed_payload.get("url") or claimed_payload.get("source_url"),
                    )
                    claimed_payload["url"] = canonical_url
                    claimed_payload["source_url"] = canonical_url
                    if row.title:
                        claimed_payload.setdefault("title", row.title)
                        claimed_payload.setdefault("source_title", row.title)
                    break
                if claimed_payload is not None:
                    break
                last_candidate = candidates[-1]
                last_cursor = (
                    int(last_candidate.claim_priority),
                    _coerce_naive_utc(last_candidate.sort_first_seen_at) or datetime.min,
                    str(last_candidate.item_id),
                )
                if len(candidates) < SEED_ITEM_CLAIM_BATCH_LIMIT:
                    break
        if claimed_payload is None or claimed_item_id is None:
            return None
        with self.session_factory() as session:
            occurrence = session.scalars(
                select(FapaiSeedOccurrence)
                .where(FapaiSeedOccurrence.item_id == claimed_item_id)
                .order_by(FapaiSeedOccurrence.seen_at.asc(), FapaiSeedOccurrence.id.asc())
            ).first()
            if occurrence is not None:
                claimed_payload.setdefault("source_page_url", occurrence.source_page_url)
                claimed_payload.setdefault("list_location_code", None)
                claimed_payload.setdefault("list_category", None)
                claimed_payload.setdefault("list_st_param", occurrence.st_param)
                claimed_payload.setdefault("list_page", occurrence.page)
                claimed_payload.setdefault("list_sort_key", occurrence.sort_key)
                claimed_payload.setdefault("list_sort_name", occurrence.sort_name)
        return claimed_payload

    def release_seed_detail_worker_leases(self, worker_id: str) -> Dict[str, int]:
        if not self.enabled:
            return {"released": 0}
        normalized_worker_id = str(worker_id or "").strip()
        if not normalized_worker_id:
            return {"released": 0}
        self.initialize()
        now = _utc_now()
        released = 0
        with self.session_factory.begin() as session:
            rows = session.scalars(
                select(FapaiSeedItem).where(
                    FapaiSeedItem.detail_leased_by == normalized_worker_id,
                    FapaiSeedItem.status.in_(("in_progress", "analysis_in_progress")),
                )
            ).all()
            for row in rows:
                if row.status == "analysis_in_progress":
                    row.status = "raw_detail_captured"
                    payload = dict(row.source_payload or {})
                    payload["_analysis_attempt_count"] = max(int(payload.get("_analysis_attempt_count") or 0) - 1, 0)
                    row.source_payload = payload
                else:
                    row.status = "pending_detail"
                    row.detail_attempt_count = max(int(row.detail_attempt_count or 0) - 1, 0)
                row.detail_leased_by = None
                row.detail_lease_until = None
                row.updated_at = now
                session.add(row)
                released += 1
        return {"released": released}

    def mark_seed_detail_completed(
        self,
        item_id: str,
        *,
        final_json_path: str | None = None,
        selected_json_path: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, str(item_id))
            if row is None:
                return
            row.status = "detail_completed"
            row.detail_completed_at = now
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = None
            row.final_json_path = final_json_path
            row.selected_json_path = selected_json_path
            session.add(row)

    def mark_seed_raw_detail_captured(
        self,
        item_id: str,
        *,
        detail_html_path: str | None = None,
        description_json_path: str | None = None,
        selected_json_path: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, str(item_id))
            if row is None:
                return
            row.status = "raw_detail_captured"
            row.detail_completed_at = now
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = None
            row.final_json_path = None
            row.selected_json_path = selected_json_path
            payload = dict(row.source_payload or {})
            payload["_raw_detail_artifacts"] = {
                "detail_html_path": detail_html_path,
                "description_json_path": description_json_path,
                "selected_json_path": selected_json_path,
            }
            row.source_payload = payload
            session.add(row)

    def claim_seed_raw_detail_item(
        self,
        worker_id: str,
        lease_seconds: int = 300,
        *,
        exclude_item_ids: Iterable[str] | None = None,
        max_analysis_attempts: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        excluded = {str(item_id) for item_id in (exclude_item_ids or ())}
        attempt_limit = max(int(max_analysis_attempts), 1) if max_analysis_attempts is not None else None
        claimed_payload: Dict[str, Any] | None = None
        with self.session_factory.begin() as session:
            stale_failed_retry_cutoff = now - timedelta(seconds=SEED_ITEM_STALE_FAILED_PRIORITY_SECONDS)
            stale_retry_timestamp = func.coalesce(FapaiSeedItem.updated_at, FapaiSeedItem.first_seen_at)
            sort_first_seen_at = func.coalesce(FapaiSeedItem.first_seen_at, datetime.min)
            raw_claim_priority = case(
                (
                    and_(
                        FapaiSeedItem.status == "analysis_failed",
                        stale_retry_timestamp < stale_failed_retry_cutoff,
                    ),
                    0,
                ),
                (FapaiSeedItem.status == "raw_detail_captured", 1),
                (FapaiSeedItem.status == "analysis_failed", 2),
                (FapaiSeedItem.status == "analysis_in_progress", 3),
                else_=99,
            )

            def _analysis_row_priority(row: FapaiSeedItem) -> int:
                if row.status == "analysis_failed" and (
                    (_coerce_naive_utc(row.updated_at) or row.first_seen_at or datetime.min) < stale_failed_retry_cutoff
                ):
                    return 0
                if row.status == "raw_detail_captured":
                    return 1
                if row.status == "analysis_failed":
                    return 2
                if (
                    row.status == "analysis_in_progress"
                    and row.detail_leased_by != worker_id
                    and _lease_reclaimable(row.detail_lease_until, row.updated_at, now=now, lease_seconds=lease_seconds)
                ):
                    return 3
                return 4

            last_cursor: tuple[int, datetime, str] | None = None
            while claimed_payload is None:
                candidate_query = (
                    select(
                        FapaiSeedItem.item_id,
                        raw_claim_priority.label("claim_priority"),
                        sort_first_seen_at.label("sort_first_seen_at"),
                    )
                    .where(FapaiSeedItem.status.in_(("raw_detail_captured", "analysis_failed", "analysis_in_progress")))
                    .order_by(raw_claim_priority, sort_first_seen_at.asc(), FapaiSeedItem.item_id.asc())
                    .limit(SEED_ITEM_CLAIM_BATCH_LIMIT)
                )
                if excluded:
                    candidate_query = candidate_query.where(not_(FapaiSeedItem.item_id.in_(excluded)))
                cursor_clause = _seed_claim_cursor_clause(raw_claim_priority, sort_first_seen_at, last_cursor)
                if cursor_clause is not None:
                    candidate_query = candidate_query.where(cursor_clause)
                candidates = session.execute(candidate_query).all()
                if not candidates:
                    break
                locked_rows: list[FapaiSeedItem] = []
                for candidate in candidates:
                    candidate_item_id = str(candidate.item_id)
                    row = session.scalars(
                        select(FapaiSeedItem)
                        .where(FapaiSeedItem.item_id == candidate_item_id)
                        .with_for_update(skip_locked=True)
                    ).first()
                    if row is None:
                        continue
                    locked_rows.append(row)
                remaining_rows: list[tuple[FapaiSeedItem, Dict[str, Any], Dict[str, Any], str, str, str]] = []
                for row in locked_rows:
                    payload = dict(row.source_payload or {})
                    artifacts = dict(payload.get("_raw_detail_artifacts") or {})
                    detail_html_path = str(
                        _resolve_collection_artifact_path(artifacts.get("detail_html_path")) or ""
                    ).strip()
                    selected_json_path = str(
                        _resolve_collection_artifact_path(artifacts.get("selected_json_path") or row.selected_json_path) or ""
                    ).strip()
                    description_json_path = str(
                        _resolve_collection_artifact_path(artifacts.get("description_json_path")) or ""
                    ).strip()
                    if not detail_html_path or not os.path.isfile(detail_html_path):
                        row.status = "analysis_blocked"
                        row.detail_leased_by = None
                        row.detail_lease_until = None
                        row.detail_last_error = (
                            f"analysis raw detail artifact missing: detail_html_path={detail_html_path or '<missing>'}"
                        )
                        session.add(row)
                        continue
                    attempt_count = int(payload.get("_analysis_attempt_count") or 0)
                    if attempt_limit is not None and attempt_count >= attempt_limit:
                        row.status = "analysis_blocked"
                        row.detail_leased_by = None
                        row.detail_lease_until = None
                        previous_error = (row.detail_last_error or "").strip()
                        limit_error = f"analysis retry limit reached: attempts={attempt_count}, max={attempt_limit}"
                        row.detail_last_error = (
                            f"{limit_error}; previous_error={previous_error}" if previous_error else limit_error
                        )
                        session.add(row)
                        continue
                    remaining_rows.append(
                        (
                            row,
                            payload,
                            artifacts,
                            detail_html_path,
                            selected_json_path,
                            description_json_path,
                        )
                    )
                remaining_rows.sort(
                    key=lambda row: (
                        _analysis_row_priority(row[0]),
                        row[0].first_seen_at or datetime.min,
                        row[0].item_id,
                    )
                )
                for row, payload, artifacts, detail_html_path, selected_json_path, description_json_path in remaining_rows:
                    if row.status == "analysis_in_progress" and row.detail_leased_by != worker_id:
                        if not _lease_reclaimable(
                            row.detail_lease_until,
                            row.updated_at,
                            now=now,
                            lease_seconds=lease_seconds,
                        ):
                            continue
                    attempt_count = int(payload.get("_analysis_attempt_count") or 0)

                    row.status = "analysis_in_progress"
                    row.detail_leased_by = worker_id
                    row.detail_lease_until = lease_until
                    payload["_analysis_attempt_count"] = attempt_count + 1
                    payload.setdefault("id", row.item_id)
                    payload.setdefault("item_id", row.item_id)
                    payload.setdefault("source_item_id", row.source_item_id or row.item_id)
                    payload.setdefault("url", self._seed_item_url(row.item_id, row.source_url))
                    payload.setdefault("source_url", payload.get("url"))
                    if row.title:
                        payload.setdefault("title", row.title)
                        payload.setdefault("source_title", row.title)
                    artifacts["detail_html_path"] = detail_html_path
                    if selected_json_path:
                        artifacts["selected_json_path"] = selected_json_path
                    if description_json_path:
                        artifacts["description_json_path"] = description_json_path
                    payload["_raw_detail_artifacts"] = artifacts
                    row.source_payload = payload
                    session.add(row)
                    claimed_payload = dict(payload)
                    break
                if claimed_payload is not None:
                    break
                last_candidate = candidates[-1]
                last_cursor = (
                    int(last_candidate.claim_priority),
                    _coerce_naive_utc(last_candidate.sort_first_seen_at) or datetime.min,
                    str(last_candidate.item_id),
                )
                if len(candidates) < SEED_ITEM_CLAIM_BATCH_LIMIT:
                    break
        return claimed_payload

    def mark_seed_detail_analysis_failed(
        self,
        item_id: str,
        error: str,
        *,
        retryable: bool = True,
        revert_attempt: bool = False,
        restore_raw: bool = False,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, str(item_id))
            if row is None:
                return
            row.status = "raw_detail_captured" if restore_raw else "analysis_failed" if retryable else "analysis_blocked"
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = str(error)
            if revert_attempt:
                payload = dict(row.source_payload or {})
                payload["_analysis_attempt_count"] = max(int(payload.get("_analysis_attempt_count") or 0) - 1, 0)
                row.source_payload = payload
            session.add(row)

    def mark_seed_detail_failed(
        self,
        item_id: str,
        error: str,
        *,
        retryable: bool = True,
        revert_attempt: bool = False,
        restore_pending: bool = False,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, str(item_id))
            if row is None:
                return
            if restore_pending:
                row.status = "pending_detail"
            else:
                row.status = "detail_failed" if retryable else "detail_blocked"
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = str(error)
            if revert_attempt:
                row.detail_attempt_count = max(int(row.detail_attempt_count or 0) - 1, 0)
            session.add(row)

    @staticmethod
    def _seed_artifacts_from_row(row: FapaiSeedItem) -> Dict[str, str | None]:
        payload = dict(row.source_payload or {})
        artifacts = dict(payload.get("_raw_detail_artifacts") or {})
        if row.selected_json_path:
            artifacts["selected_json_path"] = row.selected_json_path
        if row.final_json_path:
            artifacts["final_json_path"] = row.final_json_path

        # Older completed rows sometimes retained only final/selected paths.
        # Derive sibling raw artifacts when they are present so the observer can
        # still show the collected source rather than reporting a false gap.
        final_path = str(artifacts.get("final_json_path") or "").strip()
        if final_path:
            normalized_final = final_path.replace("\\", "/")
            parent = normalized_final.rsplit("/", 1)[0] if "/" in normalized_final else ""
            parent_candidates = [parent] if parent else []
            if "/detail_analysis_worker" in parent:
                parent_candidates.append(parent.replace("/detail_analysis_worker", "/detail_worker", 1))
            for candidate_parent in parent_candidates:
                for key, filename in (
                    ("detail_html_path", "detail.html"),
                    ("description_json_path", "description-data.json"),
                ):
                    if artifacts.get(key):
                        continue
                    candidate = f"{candidate_parent}/{filename}"
                    if _resolve_collection_artifact_path(candidate):
                        artifacts[key] = candidate
        return {
            "detail_html_path": artifacts.get("detail_html_path"),
            "description_json_path": artifacts.get("description_json_path"),
            "selected_json_path": artifacts.get("selected_json_path"),
            "final_json_path": artifacts.get("final_json_path"),
        }

    def _collection_observer_stage_clauses(self, stage: str):
        normalized = (stage or "links").strip().lower()
        if normalized == "details":
            return [
                FapaiSeedItem.status.in_(
                    (
                        "raw_detail_captured",
                        "analysis_in_progress",
                        "analysis_failed",
                        "analysis_blocked",
                        "detail_completed",
                    )
                )
            ]
        if normalized == "analysis":
            return [FapaiSeedItem.status == "detail_completed"]
        return []

    def _latest_seed_occurrence_payload(self, session: Session, item_id: str) -> Dict[str, Any] | None:
        occurrence = session.scalars(
            select(FapaiSeedOccurrence)
            .join(FapaiSeedScanJob, FapaiSeedOccurrence.job_key == FapaiSeedScanJob.job_key)
            .where(
                FapaiSeedOccurrence.item_id == str(item_id),
                FapaiSeedScanJob.status != "archived",
            )
            .order_by(FapaiSeedOccurrence.seen_at.desc(), FapaiSeedOccurrence.id.desc())
        ).first()
        if occurrence is None:
            occurrence = session.scalars(
                select(FapaiSeedOccurrence)
                .where(FapaiSeedOccurrence.item_id == str(item_id))
                .order_by(FapaiSeedOccurrence.seen_at.desc(), FapaiSeedOccurrence.id.desc())
            ).first()
        if occurrence is None:
            return None
        job = session.get(FapaiSeedScanJob, occurrence.job_key)
        return {
            "id": occurrence.id,
            "job_key": occurrence.job_key,
            "location_code": job.location_code if job is not None else None,
            "province": job.province if job is not None else None,
            "city": job.city if job is not None else None,
            "district": job.district if job is not None else None,
            "progress_key": occurrence.progress_key,
            "sort_key": occurrence.sort_key,
            "sort_name": occurrence.sort_name,
            "st_param": occurrence.st_param,
            "page": occurrence.page,
            "rank": occurrence.rank,
            "source_page_url": occurrence.source_page_url,
            "source_final_url": occurrence.source_final_url,
            "seen_at": self._fmt_dt(occurrence.seen_at),
        }

    def _seed_item_observer_payload(self, session: Session, row: FapaiSeedItem) -> Dict[str, Any]:
        return {
            "item_id": row.item_id,
            "source_item_id": row.source_item_id,
            "source_url": row.source_url,
            "title": row.title,
            "status": row.status,
            "first_seen_job_key": row.first_seen_job_key,
            "first_seen_sort_key": row.first_seen_sort_key,
            "first_seen_at": self._fmt_dt(row.first_seen_at),
            "last_seen_at": self._fmt_dt(row.last_seen_at),
            "updated_at": self._fmt_dt(row.updated_at),
            "detail_attempt_count": int(row.detail_attempt_count or 0),
            "detail_last_error": row.detail_last_error,
            "detail_leased_by": row.detail_leased_by,
            "detail_lease_until": self._fmt_dt(row.detail_lease_until),
            "detail_completed_at": self._fmt_dt(row.detail_completed_at),
            "final_json_path": row.final_json_path,
            "selected_json_path": row.selected_json_path,
            "source_payload": dict(row.source_payload or {}),
            "artifacts": self._seed_artifacts_from_row(row),
            "latest_occurrence": self._latest_seed_occurrence_payload(session, row.item_id),
        }

    @staticmethod
    def _region_label(province: str | None, city: str | None, district: str | None, location_code: str) -> str:
        parts = [str(value).strip() for value in (city, district) if str(value or "").strip()]
        if parts:
            return " ".join(parts)
        if province:
            return str(province)
        return f"地区代码 {location_code}"

    @staticmethod
    def _region_stage_status(stage: str, counts: Dict[str, int]) -> tuple[bool, str]:
        if stage == "links":
            total_jobs = int(counts.get("total_jobs", 0) or 0)
            total_progress = int(counts.get("total_progress", 0) or 0)
            blocked = int(counts.get("blocked_progress", 0) or 0) + int(counts.get("blocked_jobs", 0) or 0)
            pending = (
                int(counts.get("pending_progress", 0) or 0)
                + int(counts.get("in_progress_progress", 0) or 0)
                + int(counts.get("pending_jobs", 0) or 0)
                + int(counts.get("in_progress_jobs", 0) or 0)
            )
            exhausted = int(counts.get("exhausted_progress", 0) or 0)
            completed_jobs = int(counts.get("completed_jobs", 0) or 0)
            completed = total_jobs > 0 and total_progress > 0 and blocked == 0 and pending == 0 and exhausted == total_progress and completed_jobs == total_jobs
            if completed:
                return True, "收集完成"
            if blocked:
                return False, "存在失败/阻塞"
            if total_progress == 0 or pending == 0:
                return False, "待采集"
            return False, "采集中"

        total_items = int(counts.get("total_items", 0) or 0)
        failed = int(counts.get("failed", 0) or 0)
        blocked = int(counts.get("blocked", 0) or 0)
        pending = int(counts.get("pending", 0) or 0)
        completed_items = int(counts.get("completed_items", 0) or 0)
        completed = total_items > 0 and completed_items == total_items and failed == 0 and blocked == 0 and pending == 0
        if completed:
            return True, "收集完成"
        if failed or blocked:
            return False, "存在失败/阻塞"
        if total_items == 0:
            return False, "待采集"
        return False, "采集中"

    def collection_observer_regions(self, *, stage: str = "links") -> Dict[str, Any]:
        normalized_stage = (stage or "links").strip().lower()
        if normalized_stage not in {"links", "details", "analysis"}:
            normalized_stage = "links"
        if not self.enabled:
            return {"ok": True, "stage": normalized_stage, "regions": []}
        self.initialize()
        with self.session_factory() as session:
            region_rows = session.execute(
                select(
                    FapaiSeedScanJob.location_code,
                    func.min(FapaiSeedScanJob.province),
                    func.min(FapaiSeedScanJob.city),
                    func.min(FapaiSeedScanJob.district),
                )
                .where(FapaiSeedScanJob.status != "archived")
                .group_by(FapaiSeedScanJob.location_code)
                .order_by(
                    func.min(FapaiSeedScanJob.province),
                    func.min(FapaiSeedScanJob.city),
                    FapaiSeedScanJob.location_code,
                    func.min(FapaiSeedScanJob.district),
                )
            ).all()
            taobao_override_codes, taobao_replace_admin_provinces = _load_taobao_region_override_filter()
            if normalized_stage == "links":
                job_counts_by_code: dict[str, dict[str, int]] = {}
                for location_code, status, count_value in session.execute(
                    select(
                        FapaiSeedScanJob.location_code,
                        FapaiSeedScanJob.status,
                        func.count(FapaiSeedScanJob.job_key),
                    )
                    .where(FapaiSeedScanJob.status != "archived")
                    .group_by(FapaiSeedScanJob.location_code, FapaiSeedScanJob.status)
                ):
                    code = str(location_code or "").strip()
                    if not code:
                        continue
                    job_counts_by_code.setdefault(code, {})[str(status)] = int(count_value or 0)

                progress_counts_by_code: dict[str, dict[str, int]] = {}
                for location_code, status, count_value in session.execute(
                    select(
                        FapaiSeedScanJob.location_code,
                        FapaiSeedScanProgress.status,
                        func.count(FapaiSeedScanProgress.progress_key),
                    )
                    .join(FapaiSeedScanJob, FapaiSeedScanProgress.job_key == FapaiSeedScanJob.job_key)
                    .where(
                        FapaiSeedScanJob.status != "archived",
                        FapaiSeedScanProgress.status != "archived",
                    )
                    .group_by(FapaiSeedScanJob.location_code, FapaiSeedScanProgress.status)
                ):
                    code = str(location_code or "").strip()
                    if not code:
                        continue
                    progress_counts_by_code.setdefault(code, {})[str(status)] = int(count_value or 0)
                item_status_counts_by_code: dict[str, dict[str, int]] = {}
            else:
                job_counts_by_code = {}
                progress_counts_by_code = {}
                item_status_counts_by_code = {}
                for location_code, status, count_value in session.execute(
                    select(
                        FapaiSeedScanJob.location_code,
                        FapaiSeedItem.status,
                        func.count(func.distinct(FapaiSeedItem.item_id)),
                    )
                    .join(FapaiSeedOccurrence, FapaiSeedOccurrence.item_id == FapaiSeedItem.item_id)
                    .join(FapaiSeedScanJob, FapaiSeedOccurrence.job_key == FapaiSeedScanJob.job_key)
                    .where(FapaiSeedScanJob.status != "archived")
                    .group_by(FapaiSeedScanJob.location_code, FapaiSeedItem.status)
                ):
                    code = str(location_code or "").strip()
                    if not code:
                        continue
                    item_status_counts_by_code.setdefault(code, {})[str(status)] = int(count_value or 0)
            regions: list[Dict[str, Any]] = []
            for location_code, province, city, district in region_rows:
                code = str(location_code or "").strip()
                if not code:
                    continue
                if (
                    taobao_replace_admin_provinces
                    and str(province or "").strip() in taobao_replace_admin_provinces
                    and code not in taobao_override_codes
                ):
                    continue
                counts: Dict[str, int] = {}
                if normalized_stage == "links":
                    job_counts = job_counts_by_code.get(code, {})
                    progress_counts = progress_counts_by_code.get(code, {})
                    counts = {
                        "total_jobs": sum(job_counts.values()),
                        "pending_jobs": job_counts.get("pending", 0),
                        "in_progress_jobs": job_counts.get("in_progress", 0),
                        "completed_jobs": job_counts.get("completed", 0),
                        "blocked_jobs": job_counts.get("blocked", 0),
                        "total_progress": sum(progress_counts.values()),
                        "pending_progress": progress_counts.get("pending", 0),
                        "in_progress_progress": progress_counts.get("in_progress", 0),
                        "exhausted_progress": progress_counts.get("exhausted", 0),
                        "blocked_progress": progress_counts.get("blocked", 0),
                    }
                else:
                    status_counts = item_status_counts_by_code.get(code, {})
                    total_items = sum(status_counts.values())
                    if normalized_stage == "details":
                        completed_statuses = {
                            "raw_detail_captured",
                            "analysis_in_progress",
                            "analysis_failed",
                            "analysis_blocked",
                            "detail_completed",
                        }
                        failed = status_counts.get("detail_failed", 0)
                        blocked = status_counts.get("detail_blocked", 0)
                    else:
                        completed_statuses = {"detail_completed"}
                        failed = sum(value for key, value in status_counts.items() if key.endswith("_failed"))
                        blocked = sum(value for key, value in status_counts.items() if key.endswith("_blocked"))
                    completed_items = sum(status_counts.get(status, 0) for status in completed_statuses)
                    counts = {
                        "total_items": total_items,
                        "completed_items": completed_items,
                        "pending": max(0, total_items - completed_items - failed - blocked),
                        "failed": failed,
                        "blocked": blocked,
                        "by_status": status_counts,
                    }
                completed, status_label = self._region_stage_status(normalized_stage, counts)
                regions.append(
                    {
                        "location_code": code,
                        "province": province,
                        "city": city,
                        "district": district,
                        "label": self._region_label(province, city, district, code),
                        "completed": completed,
                        "status_label": status_label,
                        "counts": counts,
                    }
                )
            return {"ok": True, "stage": normalized_stage, "regions": regions}

    def reset_seed_link_region(self, location_code: str) -> Dict[str, Any]:
        safe_location_code = str(location_code or "").strip()
        if not self.enabled or not safe_location_code:
            return {"ok": False, "location_code": safe_location_code, "error": "location_code is required"}
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            jobs = session.scalars(select(FapaiSeedScanJob).where(FapaiSeedScanJob.location_code == safe_location_code)).all()
            job_keys = [job.job_key for job in jobs]
            for job in jobs:
                job.status = "pending"
                job.completed_at = None
                job.updated_at = now
                session.add(job)
            progress_rows = []
            if job_keys:
                progress_rows = session.scalars(select(FapaiSeedScanProgress).where(FapaiSeedScanProgress.job_key.in_(job_keys))).all()
            for progress in progress_rows:
                progress.status = "pending"
                progress.next_page = 1
                progress.last_success_page = None
                progress.completed_at = None
                progress.leased_by = None
                progress.lease_until = None
                progress.retry_count = 0
                progress.last_error = None
                progress.updated_at = now
                session.add(progress)
            return {
                "ok": True,
                "location_code": safe_location_code,
                "reset": {"jobs": len(jobs), "progress": len(progress_rows)},
            }

    def collection_observer_items(
        self,
        *,
        stage: str = "links",
        limit: int = 100,
        offset: int = 0,
        location_code: str | None = None,
    ) -> Dict[str, Any]:
        normalized_stage = (stage or "links").strip().lower()
        if normalized_stage not in {"links", "details", "analysis"}:
            normalized_stage = "links"
        safe_limit = max(1, min(int(limit or 100), 500))
        safe_offset = max(0, int(offset or 0))
        safe_location_code = str(location_code or "").strip()
        if not self.enabled:
            return {
                "stage": normalized_stage,
                "limit": safe_limit,
                "offset": safe_offset,
                "location_code": safe_location_code or None,
                "total": 0,
                "items": [],
            }
        self.initialize()
        clauses = self._collection_observer_stage_clauses(normalized_stage)
        with self.session_factory() as session:
            total_stmt = select(func.count()).select_from(FapaiSeedItem)
            list_stmt = select(FapaiSeedItem)
            for clause in clauses:
                total_stmt = total_stmt.where(clause)
                list_stmt = list_stmt.where(clause)
            if safe_location_code:
                region_item_ids = (
                    select(FapaiSeedOccurrence.item_id)
                    .join(FapaiSeedScanJob, FapaiSeedOccurrence.job_key == FapaiSeedScanJob.job_key)
                    .where(
                        FapaiSeedScanJob.location_code == safe_location_code,
                        FapaiSeedScanJob.status != "archived",
                    )
                    .distinct()
                )
                total_stmt = total_stmt.where(FapaiSeedItem.item_id.in_(region_item_ids))
                list_stmt = list_stmt.where(FapaiSeedItem.item_id.in_(region_item_ids))
            total = int(session.scalar(total_stmt) or 0)
            rows = session.scalars(
                list_stmt.order_by(
                    FapaiSeedItem.last_seen_at.desc(),
                    FapaiSeedItem.first_seen_at.desc(),
                    FapaiSeedItem.item_id.asc(),
                )
                .offset(safe_offset)
                .limit(safe_limit)
            ).all()
            return {
                "stage": normalized_stage,
                "limit": safe_limit,
                "offset": safe_offset,
                "location_code": safe_location_code or None,
                "total": total,
                "items": [self._seed_item_observer_payload(session, row) for row in rows],
            }

    @staticmethod
    def _read_collection_artifact(path_value: str | None, *, max_chars: int) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": path_value,
            "resolved_path": None,
            "exists": False,
            "content": None,
            "truncated": False,
            "json": None,
            "error": None,
        }
        if not path_value:
            return payload
        try:
            resolved_path = _resolve_collection_artifact_path(path_value)
            payload["resolved_path"] = resolved_path
            if not resolved_path or not os.path.isfile(resolved_path):
                return payload
            payload["exists"] = True
            with open(resolved_path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.read(max_chars + 1)
            if len(content) > max_chars:
                payload["content"] = content[:max_chars]
                payload["truncated"] = True
            else:
                payload["content"] = content
            if str(path_value).lower().endswith(".json") and payload["content"] is not None and not payload["truncated"]:
                try:
                    payload["json"] = json.loads(str(payload["content"]))
                except json.JSONDecodeError as exc:
                    payload["error"] = f"json_decode_error: {exc}"
        except OSError as exc:
            payload["error"] = str(exc)
        return payload

    def collection_observer_item_detail(self, item_id: str, *, max_chars: int = 100_000) -> Dict[str, Any]:
        safe_item_id = str(item_id or "").strip()
        safe_max_chars = max(1, min(int(max_chars or 100_000), 1_000_000))
        if not self.enabled or not safe_item_id:
            return {"found": False, "item_id": safe_item_id, "item": None, "occurrences": [], "artifacts": {}}
        self.initialize()
        with self.session_factory() as session:
            row = session.get(FapaiSeedItem, safe_item_id)
            if row is None:
                return {"found": False, "item_id": safe_item_id, "item": None, "occurrences": [], "artifacts": {}}
            item_payload = self._seed_item_observer_payload(session, row)
            occurrences = [
                {
                    "id": occurrence.id,
                    "job_key": occurrence.job_key,
                    "progress_key": occurrence.progress_key,
                    "sort_key": occurrence.sort_key,
                    "sort_name": occurrence.sort_name,
                    "st_param": occurrence.st_param,
                    "page": occurrence.page,
                    "rank": occurrence.rank,
                    "source_page_url": occurrence.source_page_url,
                    "source_final_url": occurrence.source_final_url,
                    "raw_item": dict(occurrence.raw_item or {}),
                    "seen_at": self._fmt_dt(occurrence.seen_at),
                }
                for occurrence in session.scalars(
                    select(FapaiSeedOccurrence)
                    .where(FapaiSeedOccurrence.item_id == safe_item_id)
                    .order_by(FapaiSeedOccurrence.seen_at.desc(), FapaiSeedOccurrence.id.desc())
                    .limit(100)
                ).all()
            ]
            flat_item = self.get_flat_item(safe_item_id)
        artifacts = item_payload.get("artifacts") or {}
        artifact_contents = {
            "detail_html": self._read_collection_artifact(artifacts.get("detail_html_path"), max_chars=safe_max_chars),
            "description_json": self._read_collection_artifact(
                artifacts.get("description_json_path"), max_chars=safe_max_chars
            ),
            "selected_json": self._read_collection_artifact(artifacts.get("selected_json_path"), max_chars=safe_max_chars),
            "final_json": self._read_collection_artifact(artifacts.get("final_json_path"), max_chars=safe_max_chars),
        }
        return {
            "found": True,
            "item_id": safe_item_id,
            "max_chars": safe_max_chars,
            "item": item_payload,
            "occurrences": occurrences,
            "flat_item": flat_item,
            "artifacts": artifact_contents,
        }

    def requeue_seed_detail_analysis(self, item_id: str, *, reason: str = "operator_requested") -> Dict[str, Any]:
        safe_item_id = str(item_id or "").strip()
        if not self.enabled or not safe_item_id:
            return {"ok": False, "item_id": safe_item_id, "error": "item_id is required"}
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, safe_item_id)
            if row is None:
                return {"ok": False, "item_id": safe_item_id, "error": "item not found"}
            artifacts = self._seed_artifacts_from_row(row)
            if not artifacts.get("detail_html_path") and not artifacts.get("selected_json_path"):
                return {
                    "ok": False,
                    "item_id": safe_item_id,
                    "error": "detail artifacts are required before AI reanalysis",
                }
            payload = dict(row.source_payload or {})
            attempt_count = int(payload.get("_analysis_attempt_count") or 0)
            payload["_manual_reanalysis_requested_at"] = self._fmt_dt(now)
            payload["_manual_reanalysis_reason"] = str(reason or "operator_requested")
            row.source_payload = payload
            row.status = "raw_detail_captured"
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = None
            session.add(row)
            return {
                "ok": True,
                "item_id": safe_item_id,
                "status": row.status,
                "reason": payload["_manual_reanalysis_reason"],
                "analysis_attempt_count": attempt_count,
                "artifacts": artifacts,
            }

    def manual_update_flat_item(self, item_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        safe_item_id = str(item_id or "").strip()
        if not self.enabled or not safe_item_id:
            return {"ok": False, "item_id": safe_item_id, "error": "item_id is required"}
        if not isinstance(updates, dict) or not updates:
            return {"ok": False, "item_id": safe_item_id, "error": "updates must be a non-empty object"}
        existing = self.get_flat_item(safe_item_id)
        if existing is None:
            return {"ok": False, "item_id": safe_item_id, "error": "item not found"}

        normalized_updates = dict(updates)
        if "title" in normalized_updates:
            normalized_updates.setdefault("source_title", normalized_updates["title"])
        if "url" in normalized_updates:
            normalized_updates.setdefault("source_url", normalized_updates["url"])
        if "full_address" in normalized_updates:
            normalized_updates.setdefault("location", normalized_updates["full_address"])
        if "transaction_price" in normalized_updates:
            normalized_updates.setdefault("currentPrice", normalized_updates["transaction_price"])
        if "starting_price" in normalized_updates:
            normalized_updates.setdefault("initialPrice", normalized_updates["starting_price"])
        if "court_name" in normalized_updates:
            normalized_updates.setdefault("法院名称", normalized_updates["court_name"])

        merged = dict(existing)
        merged.update(normalized_updates)
        merged["id"] = safe_item_id
        merged["item_id"] = safe_item_id
        if "source_item_id" not in merged or not merged.get("source_item_id"):
            merged["source_item_id"] = safe_item_id
        self.upsert_flat_item(
            merged,
            event_type="manual_operator_update",
            event_payload={"item_id": safe_item_id, "updated_fields": sorted(str(key) for key in normalized_updates)},
        )
        return {
            "ok": True,
            "item_id": safe_item_id,
            "updated_fields": sorted(str(key) for key in normalized_updates),
            "flat_item": self.get_flat_item(safe_item_id),
        }

    def seed_queue_counts(self) -> Dict[str, int]:
        counts = {
            "seed_scan_job_pending": 0,
            "seed_scan_job_in_progress": 0,
            "seed_scan_job_completed": 0,
            "seed_scan_job_blocked": 0,
            "seed_scan_progress_pending": 0,
            "seed_scan_progress_in_progress": 0,
            "seed_scan_progress_exhausted": 0,
            "seed_scan_progress_blocked": 0,
            "seed_item_pending_detail": 0,
            "seed_item_in_progress": 0,
            "seed_item_raw_detail_captured": 0,
            "seed_item_analysis_in_progress": 0,
            "seed_item_analysis_failed": 0,
            "seed_item_analysis_blocked": 0,
            "seed_item_detail_completed": 0,
            "seed_item_detail_failed": 0,
            "seed_item_detail_blocked": 0,
            "seed_occurrence_total": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        with self.session_factory() as session:
            for status, count_value in session.execute(
                select(FapaiSeedScanJob.status, func.count(FapaiSeedScanJob.job_key)).group_by(FapaiSeedScanJob.status)
            ):
                key = f"seed_scan_job_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
            for status, count_value in session.execute(
                select(FapaiSeedScanProgress.status, func.count(FapaiSeedScanProgress.progress_key)).group_by(FapaiSeedScanProgress.status)
            ):
                key = f"seed_scan_progress_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
            for status, count_value in session.execute(
                select(FapaiSeedItem.status, func.count(FapaiSeedItem.item_id)).group_by(FapaiSeedItem.status)
            ):
                key = f"seed_item_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
            counts["seed_occurrence_total"] = int(session.scalar(select(func.count()).select_from(FapaiSeedOccurrence)) or 0)
        return counts

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
        now = _utc_now()
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
                row.receipt_updated_at = _parse_dt(item.get("updated_at")) or _utc_now()
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
        now = _utc_now()
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
                row.requested_at = _parse_dt(item.get("requested_at")) or _utc_now()
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
