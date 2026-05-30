from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional


DETAIL_BLOCKED_STATES = {"login_redirect", "anti_bot_gate", "empty_html"}
DETAIL_FAILED_STATES = {"failed", "fetch_failed", "timeout", "http_error", "parse_error"}


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if text in {"done", "成交", "true", "finished", "ended", "success"}:
        return "done"
    if text in {"pending", "todo", "false"}:
        return "pending"
    return text


def _model_version() -> str:
    try:
        from src.avm.service import MODEL_VERSION

        return MODEL_VERSION
    except Exception:
        return "avm_multidim_v1"


def derive_stage_state(
    record: Dict[str, Any],
    raw_item: Optional[Dict[str, Any]] = None,
    *,
    event_type: Optional[str] = None,
    existing: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    raw_item = raw_item or {}
    existing = existing or {}
    now = now or datetime.now()

    source = record.get("source", {}) or {}
    archive = record.get("archive", {}) or {}
    auction = record.get("auction", {}) or {}
    location = record.get("location", {}) or {}
    property_section = record.get("property", {}) or {}
    legal_context = record.get("legal_context", {}) or {}
    risk_flags = record.get("risk_flags", {}) or {}
    audit = record.get("audit", {}) or {}

    has_source_url = _present(source.get("source_url"))
    has_seed_payload = has_source_url or _present(raw_item.get("url")) or _present(raw_item.get("source_url"))
    seed_status = "stored" if has_seed_payload else existing.get("seed_status")
    seed_first_seen_at = existing.get("seed_first_seen_at")
    seed_last_seen_at = existing.get("seed_last_seen_at")
    if seed_status == "stored":
        seed_last_seen_at = now
        if not seed_first_seen_at:
            seed_first_seen_at = now
    seed_source_page_url = (
        raw_item.get("source_page_url")
        or raw_item.get("list_page_url")
        or source.get("list_payload_path")
        or existing.get("seed_source_page_url")
    )

    detail_fetch_status = str(raw_item.get("detail_fetch_status") or existing.get("detail_fetch_status") or "").strip()
    replay_requested = _present(raw_item.get("detail_replay_requested_at")) or _present(raw_item.get("detail_replay_reason"))
    has_detail_archive = any(
        _present(source.get("detail_archive_path")) or _present(archive.get(key))
        for key in (
            "detail_text_path",
            "component_payload_path",
            "notice_text_path",
            "desc_text_path",
            "attachment_manifest_path",
            "image_manifest_path",
        )
    )
    detail_captured = bool(audit.get("detail_captured") or raw_item.get("detail_captured"))
    detail_sidecar_ready = any(
        _present(archive.get(key))
        for key in (
            "detail_text_path",
            "component_payload_path",
            "notice_text_path",
            "desc_text_path",
            "attachment_manifest_path",
            "image_manifest_path",
        )
    )
    risk_present = any(_present(value) for value in risk_flags.values())
    legal_present = any(_present(value) for value in legal_context.values())

    detail_status = existing.get("detail_status")
    if replay_requested:
        detail_status = "replay_requested"
    elif detail_fetch_status in DETAIL_BLOCKED_STATES:
        detail_status = "blocked"
    elif detail_fetch_status in DETAIL_FAILED_STATES:
        detail_status = "failed"
    elif detail_captured and (detail_sidecar_ready or risk_present or legal_present):
        detail_status = "enriched"
    elif detail_captured or has_detail_archive:
        detail_status = "archived"
    elif has_source_url:
        detail_status = "pending"

    detail_last_error = existing.get("detail_last_error")
    if detail_fetch_status in DETAIL_BLOCKED_STATES | DETAIL_FAILED_STATES:
        detail_last_error = detail_fetch_status
    elif detail_status in {"archived", "enriched"}:
        detail_last_error = None

    detail_retry_count = _coerce_int(
        raw_item.get("detail_retry_count", raw_item.get("detail_fetch_attempt_count", existing.get("detail_retry_count", 0))),
        0,
    )
    if detail_fetch_status in DETAIL_BLOCKED_STATES | DETAIL_FAILED_STATES and detail_retry_count <= 0:
        detail_retry_count = 1

    detail_lease_until = existing.get("detail_lease_until")

    status_text = _normalized_status(auction.get("status"))
    missing_fields: list[str] = []
    for name, value in (
        ("auction_date", auction.get("auction_date")),
        ("area_sqm", property_section.get("area_sqm")),
        ("city", location.get("city")),
        ("district", location.get("district")),
        ("business_area", location.get("business_area")),
    ):
        if not _present(value):
            missing_fields.append(name)

    if not any(
        _present(auction.get(key))
        for key in ("transaction_price", "starting_price", "actual_paid_price", "evaluation_price")
    ):
        missing_fields.append("price_anchor")

    if detail_status not in {"archived", "enriched"}:
        missing_fields.append("detail_stage")

    if status_text != "done":
        missing_fields.append("status")

    if not _present(location.get("latitude")) and not _present(location.get("community_name")):
        missing_fields.append("location_precision")

    analysis_ready = len(missing_fields) == 0
    analysis_status = "ready" if analysis_ready else "not_ready"
    if event_type == "mark_deleted":
        analysis_status = "invalid"
        analysis_ready = False

    analysis_last_scored_at = existing.get("analysis_last_scored_at")
    analysis_model_version = existing.get("analysis_model_version")
    if analysis_ready:
        analysis_model_version = _model_version()

    return {
        "seed_status": seed_status,
        "seed_first_seen_at": seed_first_seen_at,
        "seed_last_seen_at": seed_last_seen_at,
        "seed_source_page_url": seed_source_page_url,
        "detail_status": detail_status,
        "detail_last_error": detail_last_error,
        "detail_retry_count": detail_retry_count,
        "detail_lease_until": detail_lease_until,
        "analysis_status": analysis_status,
        "analysis_ready": analysis_ready,
        "analysis_missing_fields": missing_fields,
        "analysis_last_scored_at": analysis_last_scored_at,
        "analysis_model_version": analysis_model_version,
    }
