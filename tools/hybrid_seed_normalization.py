from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "" or normalized.lower() == "unknown":
            return None
        try:
            return int(normalized)
        except (TypeError, ValueError, OverflowError):
            return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        return parsed if value == parsed else None
    except Exception:
        return None

def _coerce_optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized == "" or normalized.lower() == "unknown":
            return None
        value = normalized
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None

def _coerce_optional_number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    parsed = _coerce_optional_float(value)
    if parsed is None:
        return None
    return int(parsed) if parsed.is_integer() else parsed

def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    normalized_int = _coerce_optional_int(value)
    if normalized_int == 1:
        return True
    if normalized_int == 0:
        return False
    return None

def _coerce_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized == "" or normalized.lower() == "unknown":
        return None
    return normalized

def _first_optional_text(*values: Any) -> str | None:
    for value in values:
        normalized = _coerce_optional_text(value)
        if normalized is not None:
            return normalized
    return None

def _normalize_task_payload(task: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(task)
    for key, value in list(payload.items()):
        if isinstance(value, str):
            payload[key] = _coerce_optional_text(value)
    if "url" in payload:
        payload["url"] = _coerce_optional_text(payload.get("url"))
    if "page" in payload:
        page = _coerce_optional_int(payload.get("page"))
        if page is None or page < 0:
            payload["page"] = None
        else:
            payload["page"] = page
    return payload

def _coerce_optional_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}

def _coerce_optional_identifier(value: Any) -> str | int | None:
    if isinstance(value, str):
        return _coerce_optional_text(value)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        parsed = int(value)
        return parsed if parsed >= 0 else None
    identifier = _coerce_optional_int(value)
    if identifier is not None and identifier >= 0:
        return identifier
    return None

def _normalize_probe_summary_payload(value: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(value)
    if "final_url" in payload:
        payload["final_url"] = _coerce_optional_text(payload.get("final_url"))
    for key in ("status", "item_count", "cookie_count"):
        if key in payload:
            scalar = _coerce_optional_int(payload.get(key))
            payload[key] = scalar if scalar is not None and scalar >= 0 else None
    for key in (
        "has_script",
        "body_has_login",
        "body_has_captcha",
        "body_has_punish",
        "body_has_challenge",
    ):
        if key in payload:
            payload[key] = _coerce_optional_bool(payload.get(key))
    if "body_snippet" in payload:
        payload["body_snippet"] = _coerce_optional_text(payload.get("body_snippet"))
    if "batch_payload" in payload:
        payload["batch_payload"] = _normalize_batch_payload(payload.get("batch_payload"))
    if "first_ids" in payload:
        first_ids = payload.get("first_ids")
        payload["first_ids"] = (
            [
                _coerce_optional_identifier(item)
                for item in first_ids
            ]
            if isinstance(first_ids, list)
            else []
        )
    if "first_urls" in payload:
        first_urls = payload.get("first_urls")
        payload["first_urls"] = (
            [
                _coerce_optional_text(item) if isinstance(item, str) else None
                for item in first_urls
            ]
            if isinstance(first_urls, list)
            else []
        )
    return payload

def _normalize_status_response_payload(value: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(value)
    for key in ("status", "message", "error", "reason", "detail"):
        if key in payload:
            payload[key] = _coerce_optional_text(payload.get(key))
    return payload

def _normalize_seed_batch_response_payload(value: Any) -> dict[str, Any]:
    payload = _normalize_status_response_payload(value)
    if "new" in payload:
        new_count = _coerce_optional_int(payload.get("new"))
        payload["new"] = new_count if new_count is not None and new_count >= 0 else None
    return payload

def _normalize_seed_progress_response_payload(value: Any) -> dict[str, Any]:
    payload = _normalize_status_response_payload(value)
    if "updated" in payload:
        payload["updated"] = _coerce_optional_bool(payload.get("updated"))
    return payload

def _normalize_submit_result_payload(value: Any) -> dict[str, Any]:
    payload = _normalize_status_response_payload(value)
    if "batch" in payload:
        payload["batch"] = _normalize_seed_batch_response_payload(payload.get("batch"))
    if "progress" in payload:
        payload["progress"] = _normalize_seed_progress_response_payload(payload.get("progress"))
    return payload

def _normalize_seed_item_payload(value: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(value)
    for key in ("id", "source_item_id"):
        if key in payload:
            payload[key] = _coerce_optional_identifier(payload.get(key))
    for key in (
        "url",
        "title",
        "source_title",
        "status",
        "location",
        "full_address",
        "city",
        "district",
        "auction_date",
        "auction_start_time",
        "startTime",
        "end",
        "coordinate_source",
        "housing_type",
        "source_page_url",
        "page_url",
        "source_url",
        "source_platform",
        "list_payload_path",
    ):
        if key in payload:
            payload[key] = _coerce_optional_text(payload.get(key))
    for key in (
        "currentPrice",
        "initialPrice",
        "transaction_price",
        "starting_price",
        "deposit",
    ):
        if key in payload:
            amount = _coerce_optional_number(payload.get(key))
            payload[key] = amount if amount is not None and amount >= 0 else None
    for key in (
        "bidCount",
        "bid_count",
        "bidderCount",
        "bidder_count",
        "applyCount",
        "apply_count",
        "watchCount",
        "watch_count",
        "remindCount",
        "reminder_count",
        "viewCount",
        "view_count",
    ):
        if key in payload:
            count = _coerce_optional_int(payload.get(key))
            payload[key] = count if count is not None and count >= 0 else None
    if "auction_round" in payload:
        round_number = _coerce_optional_int(payload.get("auction_round"))
        payload["auction_round"] = (
            round_number
            if round_number is not None and round_number >= 0
            else _coerce_optional_text(payload.get("auction_round"))
        )
    if "is_processed" in payload:
        payload["is_processed"] = _coerce_optional_bool(payload.get("is_processed"))
    for key in ("latitude", "longitude"):
        if key in payload:
            payload[key] = _coerce_optional_float(payload.get(key))
    return payload

def _normalize_batch_payload(value: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(value)
    for key in ("source_page_url", "page_url", "url"):
        if key in payload:
            payload[key] = _coerce_optional_text(payload.get(key))
    if "items" in payload:
        items = payload.get("items")
        payload["items"] = (
            [_normalize_seed_item_payload(item) for item in items]
            if isinstance(items, list)
            else []
        )
    return payload

def _normalize_progress_payload(value: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(value)
    if "url" in payload:
        payload["url"] = _coerce_optional_text(payload.get("url"))
    if "page_num" in payload:
        page_num = _coerce_optional_int(payload.get("page_num"))
        payload["page_num"] = page_num if page_num is not None and page_num >= 0 else None
    if "total_pages" in payload:
        total_pages = _coerce_optional_int(payload.get("total_pages"))
        payload["total_pages"] = (
            total_pages if total_pages is not None and total_pages >= 0 else None
        )
    for key in ("has_next", "is_empty", "zero_bid_detected"):
        if key in payload:
            payload[key] = _coerce_optional_bool(payload.get(key))
    return payload

def _normalize_collection_result_payload(value: Any) -> dict[str, Any]:
    payload = _coerce_optional_mapping(value)
    if "decision" in payload:
        payload["decision"] = _coerce_optional_text(payload.get("decision"))
    if "reason" in payload:
        payload["reason"] = _coerce_optional_text(payload.get("reason"))
    if "error" in payload:
        payload["error"] = _coerce_optional_text(payload.get("error"))
    if "message" in payload:
        payload["message"] = _coerce_optional_text(payload.get("message"))
    if "cookie_count" in payload:
        cookie_count = _coerce_optional_int(payload.get("cookie_count"))
        payload["cookie_count"] = (
            cookie_count if cookie_count is not None and cookie_count >= 0 else None
        )
    if "probe_summary" in payload:
        payload["probe_summary"] = _normalize_probe_summary_payload(payload.get("probe_summary"))
    if "submit_result" in payload:
        payload["submit_result"] = _normalize_submit_result_payload(payload.get("submit_result"))
    if "batch_payload" in payload:
        payload["batch_payload"] = _normalize_batch_payload(payload.get("batch_payload"))
    if "progress_payload" in payload:
        payload["progress_payload"] = _normalize_progress_payload(payload.get("progress_payload"))
    return payload

__all__ = ('_coerce_optional_int', '_coerce_optional_float', '_coerce_optional_number', '_coerce_optional_bool', '_coerce_optional_text', '_first_optional_text', '_normalize_task_payload', '_coerce_optional_mapping', '_coerce_optional_identifier', '_normalize_probe_summary_payload', '_normalize_status_response_payload', '_normalize_seed_batch_response_payload', '_normalize_seed_progress_response_payload', '_normalize_submit_result_payload', '_normalize_seed_item_payload', '_normalize_batch_payload', '_normalize_progress_payload', '_normalize_collection_result_payload')
