from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import math
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import browserless_seed_probe, hybrid_seed_collector

DEFAULT_API_BASE = "http://127.0.0.1:8001/api"
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_SESSION_ID = "hybrid-seed-runner"
DEFAULT_PROFILE_DIR = REPO_ROOT / "output" / "taobao-auth-profile"
DEFAULT_MODE = "hybrid"
DEFAULT_RUNTIME_SUMMARY_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_collection_runtime.json"
DEFAULT_RUNTIME_HISTORY_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_collection_runtime_history.jsonl"
DEFAULT_RUNTIME_SWITCH_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_mode_switch_events.jsonl"
DEFAULT_RECOVERY_POLICY_STATE_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_recovery_policy_state.json"
DEFAULT_RECOVERY_POLICY_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_recovery_policy_events.jsonl"
DEFAULT_OPERATOR_ESCALATION_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_escalation_events.jsonl"
DEFAULT_OPERATOR_ESCALATION_STATE_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_escalation_state.json"
DEFAULT_OPERATOR_ESCALATION_RECOVERY_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_escalation_recovery_events.jsonl"
DEFAULT_OPERATOR_INTERVENTION_STATE_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_intervention_state.json"
DEFAULT_OPERATOR_INTERVENTION_EVENTS_PATH = REPO_ROOT / "datas" / "avm" / "hybrid_seed_operator_intervention_events.jsonl"
_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE = threading.local()


def build_next_task_request_url(api_base: str, session_id: str) -> str:
    return f"{api_base.rstrip('/')}/collection/seeds/next_task?session_id={session_id}"


def claim_next_seed_task(
    *,
    api_base: str,
    session_id: str,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    http = http_session or requests.Session()
    response = http.get(build_next_task_request_url(api_base, session_id), timeout=timeout)
    return response.json()


@contextmanager
def hybrid_collection_status_snapshot_scope():
    previous = getattr(_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE, "value", None)
    _HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE.value = {}
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE, "value")
            except AttributeError:
                pass
        else:
            _HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE.value = previous


def load_hybrid_collection_status_snapshot(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    cache = getattr(_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE, "value", None)
    cache_key = (api_base.rstrip("/"), timeout)
    if isinstance(cache, dict) and cache_key in cache:
        return _coerce_optional_mapping(cache[cache_key])
    http = http_session or requests.Session()
    response = http.get(f"{api_base.rstrip('/')}/status", timeout=timeout)
    payload = response.json()
    collection_stage = payload.get("collection_stage") if isinstance(payload, dict) else None
    snapshot = _coerce_optional_mapping(collection_stage)
    if isinstance(cache, dict):
        cache[cache_key] = dict(snapshot)
    return snapshot


def _load_hybrid_collection_stage_summary(
    api_base: str,
    summary_key: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    snapshot = load_hybrid_collection_status_snapshot(
        api_base,
        http_session=http_session,
        timeout=timeout,
    )
    return _coerce_optional_mapping(snapshot.get(summary_key))


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


def load_hybrid_collection_operator_status_bundle(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, dict[str, Any]]:
    def _safe_load(loader: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        try:
            return _coerce_optional_mapping(
                loader(
                api_base,
                http_session=http_session,
                timeout=timeout,
                )
            )
        except requests.exceptions.RequestException:
            return {}

    with hybrid_collection_status_snapshot_scope():
        return {
            "guidance": _safe_load(load_hybrid_collection_strategy_guidance),
            "recovery_policy": _safe_load(load_hybrid_collection_recovery_policy),
            "lifecycle_summary": _safe_load(load_hybrid_collection_lifecycle_state_summary),
            "intervention_summary": _safe_load(load_hybrid_collection_operator_intervention_policy_summary),
            "intervention_stability_summary": _safe_load(load_hybrid_collection_operator_intervention_stability_summary),
            "final_guidance_summary": _safe_load(load_hybrid_collection_operator_final_guidance_summary),
            "digest_summary": _safe_load(load_hybrid_collection_operator_digest_summary),
            "digest_stability_summary": _safe_load(load_hybrid_collection_operator_digest_stability_summary),
            "escalation_event_trend_summary": _safe_load(load_hybrid_collection_operator_escalation_event_trend_summary),
            "escalation_event_stability_summary": _safe_load(load_hybrid_collection_operator_escalation_event_stability_summary),
        }


def load_hybrid_collection_strategy_guidance(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_strategy_guidance",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_recovery_policy(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_recovery_policy",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_lifecycle_state_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_lifecycle_state_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_intervention_policy_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_intervention_policy_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_intervention_stability_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_intervention_stability_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_final_guidance_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_final_guidance_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_digest_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_digest_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_digest_stability_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_digest_stability_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_escalation_event_trend_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_escalation_event_trend_summary",
        http_session=http_session,
        timeout=timeout,
    )


def load_hybrid_collection_operator_escalation_event_stability_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_escalation_event_stability_summary",
        http_session=http_session,
        timeout=timeout,
    )


_DEFAULT_RUN_LOOP_STATUS_LOADERS = {
    "load_guidance_fn": load_hybrid_collection_strategy_guidance,
    "load_recovery_policy_fn": load_hybrid_collection_recovery_policy,
    "load_lifecycle_summary_fn": load_hybrid_collection_lifecycle_state_summary,
    "load_intervention_summary_fn": load_hybrid_collection_operator_intervention_policy_summary,
    "load_stability_summary_fn": load_hybrid_collection_operator_intervention_stability_summary,
    "load_final_guidance_summary_fn": load_hybrid_collection_operator_final_guidance_summary,
    "load_digest_summary_fn": load_hybrid_collection_operator_digest_summary,
    "load_digest_stability_summary_fn": load_hybrid_collection_operator_digest_stability_summary,
    "load_escalation_event_trend_summary_fn": load_hybrid_collection_operator_escalation_event_trend_summary,
    "load_escalation_event_stability_summary_fn": load_hybrid_collection_operator_escalation_event_stability_summary,
}


def resolve_effective_mode(
    *,
    requested_mode: str,
    guidance: dict[str, Any] | None,
    recovery_policy: dict[str, Any] | None,
    respect_operator_guidance: bool,
) -> dict[str, Any]:
    normalized_requested = str(
        _coerce_optional_text(requested_mode) or DEFAULT_MODE
    ).strip().lower()
    guidance = _coerce_optional_mapping(guidance)
    recovery_policy = _coerce_optional_mapping(recovery_policy)
    guidance_status = _coerce_optional_text(guidance.get("guidance_status"))
    if "guidance_status" in guidance:
        guidance["guidance_status"] = guidance_status
    recommended_mode_value = _coerce_optional_text(guidance.get("recommended_mode"))
    if "recommended_mode" in guidance:
        guidance["recommended_mode"] = recommended_mode_value
    if "top_guidance_reason" in guidance:
        guidance["top_guidance_reason"] = _coerce_optional_text(guidance.get("top_guidance_reason"))
    recommended_mode = str(recommended_mode_value or "").strip().lower()
    recovery_policy_mode_value = _coerce_optional_text(recovery_policy.get("effective_recommended_mode"))
    if "effective_recommended_mode" in recovery_policy:
        recovery_policy["effective_recommended_mode"] = recovery_policy_mode_value
    recovery_policy_mode = str(recovery_policy_mode_value or "").strip().lower()
    recovery_policy_status = _coerce_optional_text(recovery_policy.get("policy_status"))
    if "policy_status" in recovery_policy:
        recovery_policy["policy_status"] = recovery_policy_status
    recovery_policy_priority = _coerce_optional_text(recovery_policy.get("priority"))
    if "priority" in recovery_policy:
        recovery_policy["priority"] = recovery_policy_priority
    recovery_policy_mode_pin_active = _coerce_optional_bool(recovery_policy.get("mode_pin_active"))
    if "mode_pin_active" in recovery_policy:
        recovery_policy["mode_pin_active"] = recovery_policy_mode_pin_active
    if "top_policy_reason" in recovery_policy:
        recovery_policy["top_policy_reason"] = _coerce_optional_text(recovery_policy.get("top_policy_reason"))
    if (
        respect_operator_guidance
        and normalized_requested == "hybrid"
        and recovery_policy_mode_pin_active is True
        and recovery_policy_mode in {"hybrid", "browser"}
    ):
        effective_mode = recovery_policy_mode
        effective_mode_source = "recovery_policy"
    elif (
        respect_operator_guidance
        and normalized_requested == "hybrid"
        and recommended_mode in {"hybrid", "browser"}
    ):
        effective_mode = recommended_mode
        effective_mode_source = "guidance"
    else:
        effective_mode = normalized_requested
        effective_mode_source = "requested_mode"
    return {
        "requested_mode": normalized_requested,
        "effective_mode": effective_mode,
        "effective_mode_source": effective_mode_source,
        "guidance_applied": bool(
            respect_operator_guidance
            and normalized_requested == "hybrid"
            and effective_mode != normalized_requested
        ),
        "recovery_policy_applied": bool(
            respect_operator_guidance
            and normalized_requested == "hybrid"
            and effective_mode_source == "recovery_policy"
            and effective_mode != normalized_requested
        ),
        "guidance_status": guidance_status,
        "recovery_policy_status": recovery_policy_status,
        "recovery_policy_priority": recovery_policy_priority,
        "recovery_policy_mode_pin_active": recovery_policy_mode_pin_active,
        "guidance": guidance,
        "recovery_policy": recovery_policy,
    }


def build_browser_fallback_url(task_url: str) -> str:
    parsed = urlparse(task_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["uni_mode"] = ["SNIFF_WORKER"]
    rebuilt_query = urlencode(query, doseq=True)
    return urlunparse(parsed._replace(query=rebuilt_query))


def open_browser_fallback(url: str, profile_dir: Path, remote_debugging_port: int) -> None:
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            "chrome",
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={remote_debugging_port}",
            "--remote-allow-origins=*",
            "--disable-session-crashed-bubble",
            "--disable-restore-session-state",
            "--new-window",
            url,
        ],
        shell=False,
    )


def run_once(
    *,
    api_base: str,
    session_id: str,
    cdp_endpoint: str,
    submit: bool,
    mode: str = DEFAULT_MODE,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    open_browser_fallback: bool = False,
    claim_task_fn: Callable[..., dict[str, Any]] = claim_next_seed_task,
    export_cookies_fn: Callable[..., list[dict[str, Any]]] = browserless_seed_probe.export_cdp_cookies,
    hybrid_collect_fn: Callable[..., dict[str, Any]] = hybrid_seed_collector.run_hybrid_collection,
    open_browser_fn: Callable[[str, Path, int], None] = open_browser_fallback,
) -> dict[str, Any]:
    try:
        task_payload = claim_task_fn(api_base=api_base, session_id=session_id)
    except requests.exceptions.RequestException as exc:
        return {
            "decision": "api_unavailable",
            "reason": "dispatch_endpoint_unreachable",
            "error": _coerce_optional_text(str(exc)),
        }
    raw_task = task_payload.get("task") if isinstance(task_payload, dict) else None
    task = _normalize_task_payload(raw_task) if raw_task is not None else None
    if not isinstance(task, dict) or task.get("url") is None:
        return {
            "decision": "idle",
            "message": _coerce_optional_text(task_payload.get("message")) if isinstance(task_payload, dict) else "no task",
            "task": task,
        }

    normalized_mode = str(_coerce_optional_text(mode) or DEFAULT_MODE).strip().lower()
    if normalized_mode == "browser":
        fallback_url = build_browser_fallback_url(task["url"])
        result: dict[str, Any] = {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": task,
            "task_message": _coerce_optional_text(task_payload.get("message")) if isinstance(task_payload, dict) else None,
            "fallback_url": fallback_url,
        }
        if open_browser_fallback:
            open_browser_fn(fallback_url, profile_dir, urlparse(cdp_endpoint).port or 9223)
            result["browser_fallback_opened"] = True
        else:
            result["browser_fallback_opened"] = False
        return result

    cookies = export_cookies_fn(cdp_endpoint)
    collection_result = _normalize_collection_result_payload(
        hybrid_collect_fn(
            task["url"],
            cookies=cookies,
            submit=submit,
            api_base=api_base,
        )
    )
    decision = collection_result.get("decision")
    result: dict[str, Any] = {
        "decision": decision,
        "reason": collection_result.get("reason"),
        "task": task,
        "task_message": _coerce_optional_text(task_payload.get("message")) if isinstance(task_payload, dict) else None,
        "collection_result": collection_result,
    }
    if decision == "browser_fallback_required":
        fallback_url = build_browser_fallback_url(task["url"])
        result["fallback_url"] = fallback_url
        if normalized_mode == "hybrid" and open_browser_fallback:
            open_browser_fn(fallback_url, profile_dir, urlparse(cdp_endpoint).port or 9223)
            result["browser_fallback_opened"] = True
        else:
            result["browser_fallback_opened"] = False
    return result


def run_loop(
    *,
    api_base: str,
    session_id: str,
    cdp_endpoint: str,
    submit: bool,
    mode: str = DEFAULT_MODE,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    open_browser_fallback: bool = False,
    max_runs: int | None = None,
    idle_sleep_seconds: float = 10.0,
    success_sleep_seconds: float = 2.0,
    fallback_sleep_seconds: float = 15.0,
    stop_on_fallback: bool = False,
    stop_on_operator_escalation: bool = False,
    max_consecutive_fallbacks: int | None = None,
    respect_operator_guidance: bool = False,
    load_operator_status_bundle_fn: Callable[..., dict[str, dict[str, Any]]] | None = None,
    load_guidance_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_strategy_guidance,
    load_recovery_policy_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_recovery_policy,
    load_lifecycle_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_lifecycle_state_summary,
    load_intervention_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_intervention_policy_summary,
    load_stability_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_intervention_stability_summary,
    load_final_guidance_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_final_guidance_summary,
    load_digest_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_digest_summary,
    load_digest_stability_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_digest_stability_summary,
    load_escalation_event_trend_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_escalation_event_trend_summary,
    load_escalation_event_stability_summary_fn: Callable[..., dict[str, Any]] = load_hybrid_collection_operator_escalation_event_stability_summary,
    run_once_fn: Callable[..., dict[str, Any]] = run_once,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    iterations = 0
    normalized_requested_mode = str(_coerce_optional_text(mode) or DEFAULT_MODE).strip().lower()
    counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    effective_mode_counts: dict[str, int] = {}
    guidance_status_counts: dict[str, int] = {}
    guidance_applied_count = 0
    results: list[dict[str, Any]] = []
    consecutive_fallbacks = 0
    termination_reason = "max_runs_reached" if max_runs is not None else "stopped"
    should_load_operator_status = bool(respect_operator_guidance or stop_on_operator_escalation)
    if not should_load_operator_status:
        effective_load_operator_status_bundle_fn = None
    elif load_operator_status_bundle_fn is None:
        using_default_status_loaders = (
            load_guidance_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_guidance_fn"]
            and load_recovery_policy_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_recovery_policy_fn"]
            and load_lifecycle_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_lifecycle_summary_fn"]
            and load_intervention_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_intervention_summary_fn"]
            and load_stability_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_stability_summary_fn"]
            and load_final_guidance_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_final_guidance_summary_fn"]
            and load_digest_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_digest_summary_fn"]
            and load_digest_stability_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_digest_stability_summary_fn"]
            and load_escalation_event_trend_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_escalation_event_trend_summary_fn"]
            and load_escalation_event_stability_summary_fn is _DEFAULT_RUN_LOOP_STATUS_LOADERS["load_escalation_event_stability_summary_fn"]
        )
        effective_load_operator_status_bundle_fn = (
            load_hybrid_collection_operator_status_bundle if using_default_status_loaders else None
        )
    else:
        effective_load_operator_status_bundle_fn = load_operator_status_bundle_fn

    while max_runs is None or iterations < max_runs:
        guidance_payload: dict[str, Any] = {}
        recovery_policy_payload: dict[str, Any] = {}
        lifecycle_summary: dict[str, Any] = {}
        intervention_summary: dict[str, Any] = {}
        stability_summary: dict[str, Any] = {}
        final_guidance_summary: dict[str, Any] = {}
        digest_summary: dict[str, Any] = {}
        digest_stability_summary: dict[str, Any] = {}
        escalation_event_trend_summary: dict[str, Any] = {}
        escalation_event_stability_summary: dict[str, Any] = {}
        escalation_source = None
        with hybrid_collection_status_snapshot_scope():
            operator_status_bundle: dict[str, dict[str, Any]] = {}
            if effective_load_operator_status_bundle_fn is not None:
                try:
                    operator_status_bundle = effective_load_operator_status_bundle_fn(api_base)
                except requests.exceptions.RequestException:
                    operator_status_bundle = {}
            operator_status_bundle = _coerce_optional_mapping(operator_status_bundle)
            if respect_operator_guidance:
                if operator_status_bundle:
                    guidance_payload = _coerce_optional_mapping(operator_status_bundle.get("guidance"))
                    recovery_policy_payload = _coerce_optional_mapping(operator_status_bundle.get("recovery_policy"))
                else:
                    try:
                        guidance_payload = load_guidance_fn(api_base)
                    except requests.exceptions.RequestException:
                        guidance_payload = {}
                    try:
                        recovery_policy_payload = load_recovery_policy_fn(api_base)
                    except requests.exceptions.RequestException:
                        recovery_policy_payload = {}
            guidance_resolution = resolve_effective_mode(
                requested_mode=mode,
                guidance=guidance_payload,
                recovery_policy=recovery_policy_payload,
                respect_operator_guidance=respect_operator_guidance,
            )
            resolution_effective_mode = _coerce_optional_text(
                guidance_resolution.get("effective_mode")
            )
            effective_mode = _first_optional_text(
                resolution_effective_mode,
                guidance_resolution.get("requested_mode"),
                normalized_requested_mode,
            ) or DEFAULT_MODE
            effective_mode_for_result = resolution_effective_mode
            result = run_once_fn(
                api_base=api_base,
                session_id=session_id,
                cdp_endpoint=cdp_endpoint,
                submit=submit,
                mode=effective_mode,
                profile_dir=profile_dir,
                open_browser_fallback=open_browser_fallback,
            )
            result = _coerce_optional_mapping(result)
            if "task" in result:
                result["task"] = _normalize_task_payload(result.get("task"))
            if "collection_result" in result:
                result["collection_result"] = _normalize_collection_result_payload(
                    result.get("collection_result")
                )
            result["decision"] = _coerce_optional_text(result.get("decision"))
            result["reason"] = _coerce_optional_text(result.get("reason"))
            if "error" in result:
                result["error"] = _coerce_optional_text(result.get("error"))
            if "task_message" in result:
                result["task_message"] = _coerce_optional_text(result.get("task_message"))
            if "message" in result:
                result["message"] = _coerce_optional_text(result.get("message"))
            result["browser_fallback_opened"] = (
                _coerce_optional_bool(result.get("browser_fallback_opened")) is True
            )
            result["fallback_url"] = _coerce_optional_text(result.get("fallback_url"))
            requested_mode_for_result = (
                _coerce_optional_text(guidance_resolution.get("requested_mode"))
                or normalized_requested_mode
            )
            result["requested_mode"] = requested_mode_for_result
            result["effective_mode"] = effective_mode_for_result
            effective_mode_source = _coerce_optional_text(
                guidance_resolution.get("effective_mode_source")
            )
            result["effective_mode_source"] = effective_mode_source
            result["guidance_applied"] = (
                _coerce_optional_bool(guidance_resolution.get("guidance_applied")) is True
            )
            guidance_status = _coerce_optional_text(guidance_resolution.get("guidance_status"))
            result["guidance_status"] = guidance_status
            guidance_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("recommended_mode")
            guidance_recommended_mode = _coerce_optional_text(guidance_recommended_mode)
            result["guidance_recommended_mode"] = guidance_recommended_mode
            top_guidance_reason = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("top_guidance_reason")
            top_guidance_reason = _coerce_optional_text(top_guidance_reason)
            top_policy_reason = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("top_policy_reason")
            top_policy_reason = _coerce_optional_text(top_policy_reason)
            if effective_mode_source == "recovery_policy":
                top_guidance_reason = top_policy_reason or top_guidance_reason
            result["top_guidance_reason"] = top_guidance_reason
            result["top_policy_reason"] = top_policy_reason
            recovery_policy_status = _coerce_optional_text(
                guidance_resolution.get("recovery_policy_status")
            )
            result["recovery_policy_status"] = recovery_policy_status
            recovery_policy_priority = _coerce_optional_text(
                guidance_resolution.get("recovery_policy_priority")
            )
            result["recovery_policy_priority"] = recovery_policy_priority
            result["recovery_policy_mode_pin_active"] = _coerce_optional_bool(
                guidance_resolution.get("recovery_policy_mode_pin_active")
            )
            recovery_policy_effective_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("effective_recommended_mode")
            recovery_policy_effective_recommended_mode = _coerce_optional_text(
                recovery_policy_effective_recommended_mode
            )
            result["recovery_policy_effective_recommended_mode"] = (
                recovery_policy_effective_recommended_mode
            )
            if stop_on_operator_escalation:
                if operator_status_bundle:
                    lifecycle_summary = _coerce_optional_mapping(operator_status_bundle.get("lifecycle_summary"))
                    intervention_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_summary"))
                    stability_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_stability_summary"))
                    final_guidance_summary = _coerce_optional_mapping(operator_status_bundle.get("final_guidance_summary"))
                    digest_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_summary"))
                    digest_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_stability_summary"))
                    escalation_event_trend_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_trend_summary"))
                    escalation_event_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_stability_summary"))
                else:
                    try:
                        lifecycle_summary = load_lifecycle_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        lifecycle_summary = {}
                    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
                    try:
                        intervention_summary = load_intervention_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        intervention_summary = {}
                    intervention_summary = _coerce_optional_mapping(intervention_summary)
                    try:
                        stability_summary = load_stability_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        stability_summary = {}
                    stability_summary = _coerce_optional_mapping(stability_summary)
                    try:
                        final_guidance_summary = load_final_guidance_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        final_guidance_summary = {}
                    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
                    try:
                        digest_summary = load_digest_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        digest_summary = {}
                    digest_summary = _coerce_optional_mapping(digest_summary)
                    try:
                        digest_stability_summary = load_digest_stability_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        digest_stability_summary = {}
                    digest_stability_summary = _coerce_optional_mapping(digest_stability_summary)
                    try:
                        escalation_event_trend_summary = load_escalation_event_trend_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        escalation_event_trend_summary = {}
                    escalation_event_trend_summary = _coerce_optional_mapping(escalation_event_trend_summary)
                    try:
                        escalation_event_stability_summary = load_escalation_event_stability_summary_fn(api_base)
                    except requests.exceptions.RequestException:
                        escalation_event_stability_summary = {}
                    escalation_event_stability_summary = _coerce_optional_mapping(escalation_event_stability_summary)
        iterations += 1
        results.append(result)
        decision = result.get("decision")
        if decision not in {None, "", "unknown"}:
            decision_key = str(decision)
            counts[decision_key] = counts.get(decision_key, 0) + 1
        if effective_mode_for_result:
            effective_mode_counts[effective_mode_for_result] = (
                effective_mode_counts.get(effective_mode_for_result, 0) + 1
            )
        guidance_status = result.get("guidance_status")
        if guidance_status:
            guidance_key = str(guidance_status)
            guidance_status_counts[guidance_key] = guidance_status_counts.get(guidance_key, 0) + 1
        if _coerce_optional_bool(result.get("guidance_applied")) is True:
            guidance_applied_count += 1
        reason = result.get("reason")
        if reason in {"", "unknown"}:
            reason = None
        if reason:
            reason_key = str(reason)
            reason_counts[reason_key] = reason_counts.get(reason_key, 0) + 1
        if stop_on_operator_escalation:
            source_last_changed_at = _coerce_optional_text(
                escalation_event_trend_summary.get("last_source_change_at")
            )
            current_source = _coerce_optional_text(
                escalation_event_trend_summary.get("current_operator_escalation_source")
            )
            source_stability_status = _coerce_optional_text(
                escalation_event_stability_summary.get("stability_status")
            )
            source_stability_explanation = _coerce_optional_text(
                escalation_event_stability_summary.get("operator_readable_explanation")
            )
            digest_stability_explanation = _coerce_optional_text(
                digest_stability_summary.get("operator_readable_explanation")
            )
            final_guidance_label = _coerce_optional_text(
                final_guidance_summary.get("guidance_label")
            )
            final_guidance_priority = _coerce_optional_text(
                final_guidance_summary.get("guidance_priority")
            )
            final_guidance_message = _coerce_optional_text(
                final_guidance_summary.get("guidance_message")
            )
            digest_status = _coerce_optional_text(digest_summary.get("digest_status"))
            digest_stability_status = _coerce_optional_text(
                digest_stability_summary.get("stability_status")
            )
            digest_message = _coerce_optional_text(digest_summary.get("operator_digest_message"))
            digest_priority = _coerce_optional_text(digest_summary.get("digest_priority"))
            digest_stability_severity = _coerce_optional_text(
                digest_stability_summary.get("stability_severity")
            )
            previous_source = _coerce_optional_text(
                escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
            )
            source_stability_severity = _coerce_optional_text(
                escalation_event_stability_summary.get("stability_severity")
            )
            result["operator_digest_stability_status"] = digest_stability_status
            result["operator_digest_stability_severity"] = digest_stability_severity
            result["operator_digest_stability_explanation"] = digest_stability_explanation
            result["operator_escalation_current_source"] = current_source
            result["operator_escalation_previous_source"] = previous_source
            operator_escalation_source_change_count = _coerce_optional_int(
                escalation_event_trend_summary.get("recent_source_change_count")
            )
            if operator_escalation_source_change_count is not None and operator_escalation_source_change_count < 0:
                operator_escalation_source_change_count = 0
            result["operator_escalation_source_change_count"] = operator_escalation_source_change_count
            result["operator_escalation_source_last_changed_at"] = source_last_changed_at
            result["operator_escalation_source_stability_status"] = source_stability_status
            result["operator_escalation_source_stability_severity"] = source_stability_severity
            result["operator_escalation_source_stability_explanation"] = source_stability_explanation
            escalation_source = operator_escalation_source(
                result,
                lifecycle_summary=lifecycle_summary,
                intervention_summary=intervention_summary,
                stability_summary=stability_summary,
                include_flapping=True,
            )
            if escalation_source is not None:
                result["operator_escalation_source"] = escalation_source
                result["operator_action_hint"] = operator_action_hint(
                    result,
                    lifecycle_summary=lifecycle_summary,
                    intervention_summary=intervention_summary,
                    stability_summary=stability_summary,
                    include_flapping=True,
                )
                result["operator_final_guidance_label"] = final_guidance_label
                result["operator_final_guidance_priority"] = final_guidance_priority
                result["operator_final_guidance_message"] = final_guidance_message
                result["operator_digest_status"] = digest_status
                result["operator_digest_priority"] = digest_priority
                result["operator_digest_message"] = digest_message
                audit_message = operator_escalation_audit_message(
                    result,
                    lifecycle_summary=lifecycle_summary,
                    intervention_summary=intervention_summary,
                    stability_summary=stability_summary,
                    final_guidance_summary=final_guidance_summary,
                    digest_summary=digest_summary,
                    digest_stability_summary=digest_stability_summary,
                    include_flapping=True,
                )
                audit_message = _coerce_optional_text(audit_message)
                if audit_message is not None:
                    result["operator_escalation_audit_message"] = audit_message
                else:
                    result.pop("operator_escalation_audit_message", None)
            elif _coerce_optional_text(result.get("operator_escalation_source")) is None:
                result.pop("operator_escalation_source", None)
        if stop_on_fallback and decision == "browser_fallback_required":
            termination_reason = "stop_on_fallback"
            break
        if stop_on_operator_escalation and operator_escalation_exit_code(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=stability_summary,
            include_flapping=True,
            configured_exit_code=1,
        ) is not None:
            termination_reason = "operator_escalation"
            break
        if decision == "browser_fallback_required":
            consecutive_fallbacks += 1
            if max_consecutive_fallbacks is not None and consecutive_fallbacks >= max_consecutive_fallbacks:
                termination_reason = "fallback_escalation_threshold_reached"
                break
        else:
            consecutive_fallbacks = 0
        if max_runs is not None and iterations >= max_runs:
            termination_reason = "max_runs_reached"
            break

        if decision == "browserless_success":
            sleep_fn(success_sleep_seconds)
        elif decision == "browser_fallback_required":
            sleep_fn(fallback_sleep_seconds)
        else:
            sleep_fn(idle_sleep_seconds)

    last_operator_result = (
        _coerce_optional_mapping(results[-1])
        if results and termination_reason == "operator_escalation"
        else {}
    )
    return {
        "mode": "loop",
        "iterations": iterations,
        "counts": counts,
        "reason_counts": reason_counts,
        "effective_mode_counts": effective_mode_counts,
        "guidance_status_counts": guidance_status_counts,
        "guidance_applied_count": guidance_applied_count,
        "termination_reason": termination_reason,
        "operator_escalation_source": last_operator_result.get("operator_escalation_source"),
        "operator_escalation_audit_message": last_operator_result.get("operator_escalation_audit_message"),
        "operator_final_guidance_label": last_operator_result.get("operator_final_guidance_label"),
        "operator_final_guidance_priority": last_operator_result.get("operator_final_guidance_priority"),
        "operator_final_guidance_message": last_operator_result.get("operator_final_guidance_message"),
        "operator_digest_status": last_operator_result.get("operator_digest_status"),
        "operator_digest_priority": last_operator_result.get("operator_digest_priority"),
        "operator_digest_message": last_operator_result.get("operator_digest_message"),
        "operator_digest_stability_status": last_operator_result.get("operator_digest_stability_status"),
        "operator_digest_stability_severity": last_operator_result.get("operator_digest_stability_severity"),
        "operator_digest_stability_explanation": last_operator_result.get("operator_digest_stability_explanation"),
        "operator_escalation_current_source": last_operator_result.get("operator_escalation_current_source"),
        "operator_escalation_previous_source": last_operator_result.get("operator_escalation_previous_source"),
        "operator_escalation_source_change_count": last_operator_result.get("operator_escalation_source_change_count", 0),
        "operator_escalation_source_last_changed_at": last_operator_result.get("operator_escalation_source_last_changed_at"),
        "operator_escalation_source_stability_status": last_operator_result.get("operator_escalation_source_stability_status"),
        "operator_escalation_source_stability_severity": last_operator_result.get("operator_escalation_source_stability_severity"),
        "operator_escalation_source_stability_explanation": last_operator_result.get("operator_escalation_source_stability_explanation"),
        "results": results,
    }


def build_runtime_summary(
    *,
    result: dict[str, Any],
    requested_mode: str,
    effective_mode: str,
    submit: bool,
    api_base: str,
    cdp_endpoint: str,
    session_id: str,
    guidance_resolution: dict[str, Any] | None = None,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    intervention_stability_summary: dict[str, Any] | None = None,
    final_guidance_summary: dict[str, Any] | None = None,
    operator_digest_summary: dict[str, Any] | None = None,
    operator_digest_stability_summary: dict[str, Any] | None = None,
    operator_escalation_event_trend_summary: dict[str, Any] | None = None,
    operator_escalation_event_stability_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = _coerce_optional_mapping(result)
    guidance_resolution = _coerce_optional_mapping(guidance_resolution)
    guidance_details = _coerce_optional_mapping(guidance_resolution.get("guidance"))
    recovery_policy_details = _coerce_optional_mapping(guidance_resolution.get("recovery_policy"))
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    operator_digest_summary = _coerce_optional_mapping(operator_digest_summary)
    operator_digest_stability_summary = _coerce_optional_mapping(operator_digest_stability_summary)
    operator_escalation_event_trend_summary = _coerce_optional_mapping(operator_escalation_event_trend_summary)
    operator_escalation_event_stability_summary = _coerce_optional_mapping(operator_escalation_event_stability_summary)
    loop_mode = result.get("mode") == "loop"
    normalized_requested_mode = str(
        _coerce_optional_text(requested_mode) or DEFAULT_MODE
    ).strip().lower()
    normalized_effective_mode = None
    effective_mode_text = _coerce_optional_text(effective_mode)
    if effective_mode_text is not None:
        normalized_effective_mode = effective_mode_text.strip().lower()
    if loop_mode:
        results = list(result.get("results") or [])
        last_result = _coerce_optional_mapping(results[-1]) if results else {}
        decision_counts: dict[str, int] = {}
        for key, value in _coerce_optional_mapping(result.get("counts")).items():
            parsed_value = _coerce_optional_int(value)
            key_text = _coerce_optional_text(key)
            if key_text is None or parsed_value is None or parsed_value < 0:
                continue
            decision_counts[key_text] = parsed_value
        reason_counts = _coerce_optional_mapping(result.get("reason_counts"))
        effective_mode_counts: dict[str, int] = {}
        for key, value in _coerce_optional_mapping(result.get("effective_mode_counts")).items():
            parsed_value = _coerce_optional_int(value)
            key_text = _coerce_optional_text(key)
            if key_text is None or parsed_value is None or parsed_value < 0:
                continue
            effective_mode_counts[key_text] = parsed_value
        guidance_status_counts: dict[str, int] = {}
        for key, value in _coerce_optional_mapping(result.get("guidance_status_counts")).items():
            parsed_value = _coerce_optional_int(value)
            key_text = _coerce_optional_text(key)
            if key_text is None or parsed_value is None or parsed_value < 0:
                continue
            guidance_status_counts[key_text] = parsed_value
        guidance_applied_count = _coerce_optional_int(result.get("guidance_applied_count"))
        if guidance_applied_count is None or guidance_applied_count < 0:
            guidance_applied_count = 0
        iterations = _coerce_optional_int(result.get("iterations"))
        if iterations is None or iterations < 0:
            iterations = len(results)
        termination_reason = _coerce_optional_text(result.get("termination_reason"))
    else:
        last_result = dict(result or {})
        decision = _coerce_optional_text(last_result.get("decision"))
        decision_counts = {str(decision): 1} if decision else {}
        reason = _coerce_optional_text(last_result.get("reason"))
        reason_counts = {str(reason): 1} if reason else {}
        effective_mode_counts = {normalized_effective_mode: 1} if normalized_effective_mode else {}
        guidance_status = _coerce_optional_text(guidance_resolution.get("guidance_status"))
        guidance_status_counts = {str(guidance_status): 1} if guidance_status else {}
        guidance_applied_count = int(
            _coerce_optional_bool(guidance_resolution.get("guidance_applied")) is True
        )
        iterations = 1
        termination_reason = "single_run"

    collection_result = _normalize_collection_result_payload(last_result.get("collection_result"))
    last_probe_summary = _normalize_probe_summary_payload(collection_result.get("probe_summary"))
    last_submit_result = _normalize_submit_result_payload(collection_result.get("submit_result"))
    fallback_reason_counts: dict[str, int] = {}
    for key, value in reason_counts.items():
        parsed_value = _coerce_optional_int(value)
        key_text = _coerce_optional_text(key)
        if key_text is None or parsed_value is None or parsed_value <= 0:
            continue
        fallback_reason_counts[key_text] = parsed_value
    top_fallback_reason = (
        sorted(fallback_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if fallback_reason_counts
        else None
    )
    last_decision = _coerce_optional_text(last_result.get("decision"))
    last_reason = _coerce_optional_text(last_result.get("reason"))
    last_effective_mode = _first_optional_text(
        last_result.get("effective_mode"),
        normalized_effective_mode,
    )
    last_guidance_status = _first_optional_text(
        last_result.get("guidance_status"),
        guidance_resolution.get("guidance_status"),
    )
    last_guidance_recommended_mode = _first_optional_text(
        last_result.get("guidance_recommended_mode"),
        guidance_details.get("recommended_mode"),
    )
    last_recovery_policy_status = _first_optional_text(
        last_result.get("recovery_policy_status"),
        guidance_resolution.get("recovery_policy_status"),
    )
    last_recovery_policy_priority = _first_optional_text(
        last_result.get("recovery_policy_priority"),
        guidance_resolution.get("recovery_policy_priority"),
    )
    last_recovery_policy_effective_recommended_mode = _first_optional_text(
        last_result.get("recovery_policy_effective_recommended_mode"),
        recovery_policy_details.get("effective_recommended_mode"),
    )
    top_policy_reason = _first_optional_text(
        last_result.get("top_policy_reason"),
        recovery_policy_details.get("top_policy_reason"),
    )
    top_guidance_reason = _first_optional_text(
        last_result.get("top_guidance_reason"),
        guidance_details.get("top_guidance_reason"),
    )
    operator_escalation_audit_message = _first_optional_text(
        last_result.get("operator_escalation_audit_message"),
        result.get("operator_escalation_audit_message"),
    )
    operator_escalation_source_value = _first_optional_text(
        last_result.get("operator_escalation_source"),
        result.get("operator_escalation_source"),
    )
    operator_action_hint_value = _first_optional_text(
        last_result.get("operator_action_hint"),
        result.get("operator_action_hint"),
        operator_action_hint(last_result or result, lifecycle_summary=lifecycle_summary),
    )
    operator_final_guidance_message = _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    operator_final_guidance_priority = _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    lifecycle_state = _coerce_optional_text(lifecycle_summary.get("lifecycle_state"))
    lifecycle_reason = _coerce_optional_text(lifecycle_summary.get("lifecycle_reason"))
    lifecycle_follow_up = _coerce_optional_text(lifecycle_summary.get("recommended_follow_up"))
    lifecycle_suggested_mode = _coerce_optional_text(lifecycle_summary.get("suggested_mode"))
    lifecycle_priority_hint = _coerce_optional_text(lifecycle_summary.get("priority_hint"))
    lifecycle_active_unresolved_priority = _coerce_optional_text(
        lifecycle_summary.get("active_unresolved_priority")
    )
    lifecycle_active_high_priority_unresolved_count = _coerce_optional_int(
        lifecycle_summary.get("active_high_priority_unresolved_count")
    )
    if lifecycle_active_high_priority_unresolved_count is not None and lifecycle_active_high_priority_unresolved_count < 0:
        lifecycle_active_high_priority_unresolved_count = 0
    intervention_status = _coerce_optional_text(intervention_summary.get("intervention_status"))
    intervention_priority = _coerce_optional_text(intervention_summary.get("intervention_priority"))
    intervention_reason = _coerce_optional_text(intervention_summary.get("intervention_reason"))
    intervention_action_hint = _coerce_optional_text(
        intervention_summary.get("preferred_operator_action_hint")
    )
    intervention_suggested_mode = _coerce_optional_text(intervention_summary.get("suggested_mode"))
    intervention_stability_status = _coerce_optional_text(
        intervention_stability_summary.get("stability_status")
    )
    intervention_stability_severity = _coerce_optional_text(
        intervention_stability_summary.get("stability_severity")
    )
    intervention_stability_explanation = _coerce_optional_text(
        intervention_stability_summary.get("operator_readable_explanation")
    )
    intervention_stability_action_hint = _coerce_optional_text(
        intervention_stability_summary.get("stability_action_hint")
    )
    operator_final_guidance_label = _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    operator_digest_status = _coerce_optional_text(operator_digest_summary.get("digest_status"))
    operator_digest_priority = _coerce_optional_text(operator_digest_summary.get("digest_priority"))
    operator_digest_message = _coerce_optional_text(operator_digest_summary.get("operator_digest_message"))
    operator_digest_stability_status = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_status")
    )
    operator_digest_stability_severity = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_severity")
    )
    operator_digest_stability_explanation = _coerce_optional_text(
        operator_digest_stability_summary.get("operator_readable_explanation")
    )
    operator_escalation_source_last_changed_at = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("last_source_change_at")
    )
    operator_escalation_current_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("current_operator_escalation_source")
    )
    operator_escalation_previous_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
    )
    operator_escalation_source_stability_status = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_status")
    )
    operator_escalation_source_stability_severity = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_severity")
    )
    operator_escalation_source_stability_explanation = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("operator_readable_explanation")
    )
    operator_escalation_source_change_count = _coerce_optional_int(
        operator_escalation_event_trend_summary.get("recent_source_change_count")
    )
    if operator_escalation_source_change_count is not None and operator_escalation_source_change_count < 0:
        operator_escalation_source_change_count = 0
    requested_mode_value = _first_optional_text(
        last_result.get("requested_mode"),
        normalized_requested_mode,
    ) or normalized_requested_mode
    effective_mode_value = last_effective_mode
    last_fallback_url = _coerce_optional_text(last_result.get("fallback_url"))
    effective_mode_source = _first_optional_text(
        last_result.get("effective_mode_source"),
        guidance_resolution.get("effective_mode_source"),
    )
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "runner_mode": effective_mode_value,
        "requested_mode": str(requested_mode_value or DEFAULT_MODE).strip().lower(),
        "effective_mode": effective_mode_value,
        "effective_mode_source": effective_mode_source,
        "guidance_applied": (
            _coerce_optional_bool(
                last_result.get("guidance_applied", guidance_resolution.get("guidance_applied"))
            )
            is True
        ),
        "guidance_status": last_guidance_status,
        "guidance_recommended_mode": last_guidance_recommended_mode,
        "recovery_policy_status": last_recovery_policy_status,
        "recovery_policy_priority": last_recovery_policy_priority,
        "recovery_policy_mode_pin_active": _coerce_optional_bool(
            last_result.get("recovery_policy_mode_pin_active", guidance_resolution.get("recovery_policy_mode_pin_active"))
        ),
        "recovery_policy_effective_recommended_mode": last_recovery_policy_effective_recommended_mode,
        "top_policy_reason": top_policy_reason,
        "top_guidance_reason": top_guidance_reason,
        "effective_mode_counts": effective_mode_counts,
        "guidance_status_counts": guidance_status_counts,
        "guidance_applied_count": guidance_applied_count,
        "last_effective_mode": last_effective_mode,
        "loop_mode": loop_mode,
        "submit_enabled": bool(submit),
        "session_id": session_id,
        "api_base": api_base,
        "cdp_endpoint": cdp_endpoint,
        "iterations": iterations,
        "decision_counts": decision_counts,
        "reason_counts": fallback_reason_counts,
        "top_fallback_reason": top_fallback_reason,
        "termination_reason": termination_reason,
        "operator_escalation_source": operator_escalation_source_value,
        "operator_escalation_audit_message": operator_escalation_audit_message,
        "operator_action_hint": operator_action_hint_value,
        "lifecycle_state": lifecycle_state,
        "lifecycle_reason": lifecycle_reason,
        "lifecycle_follow_up": lifecycle_follow_up,
        "lifecycle_suggested_mode": lifecycle_suggested_mode,
        "lifecycle_priority_hint": lifecycle_priority_hint,
        "lifecycle_active_unresolved_priority": lifecycle_active_unresolved_priority,
        "lifecycle_active_high_priority_unresolved_count": lifecycle_active_high_priority_unresolved_count,
        "intervention_status": intervention_status,
        "intervention_required": _coerce_optional_bool(intervention_summary.get("intervention_required")),
        "intervention_priority": intervention_priority,
        "intervention_reason": intervention_reason,
        "intervention_action_hint": intervention_action_hint,
        "intervention_suggested_mode": intervention_suggested_mode,
        "intervention_stability_status": intervention_stability_status,
        "intervention_stability_severity": intervention_stability_severity,
        "intervention_stability_explanation": intervention_stability_explanation,
        "intervention_stability_action_hint": intervention_stability_action_hint,
        "operator_final_guidance_label": operator_final_guidance_label,
        "operator_final_guidance_priority": operator_final_guidance_priority,
        "operator_final_guidance_message": operator_final_guidance_message,
        "operator_digest_status": operator_digest_status,
        "operator_digest_priority": operator_digest_priority,
        "operator_digest_message": operator_digest_message,
        "operator_digest_stability_status": operator_digest_stability_status,
        "operator_digest_stability_severity": operator_digest_stability_severity,
        "operator_digest_stability_explanation": operator_digest_stability_explanation,
        "operator_escalation_current_source": operator_escalation_current_source,
        "operator_escalation_previous_source": operator_escalation_previous_source,
        "operator_escalation_source_change_count": operator_escalation_source_change_count,
        "operator_escalation_source_last_changed_at": operator_escalation_source_last_changed_at,
        "operator_escalation_source_stability_status": operator_escalation_source_stability_status,
        "operator_escalation_source_stability_severity": operator_escalation_source_stability_severity,
        "operator_escalation_source_stability_explanation": operator_escalation_source_stability_explanation,
        "last_decision": last_decision,
        "last_reason": last_reason,
        "last_task": _normalize_task_payload(last_result.get("task")),
        "last_fallback_url": last_fallback_url,
        "last_browser_fallback_opened": (
            _coerce_optional_bool(last_result.get("browser_fallback_opened")) is True
        ),
        "last_probe_summary": last_probe_summary,
        "last_submit_result": last_submit_result,
    }


def persist_runtime_summary(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_runtime_history(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False))
        handle.write("\n")


def append_mode_switch_events(result: dict[str, Any], output_path: Path, *, session_id: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    events: list[dict[str, Any]] = []
    for item in results:
        if _coerce_optional_bool(item.get("guidance_applied")) is not True:
            continue
        requested_mode = _coerce_optional_text(item.get("requested_mode"))
        effective_mode = _coerce_optional_text(item.get("effective_mode"))
        effective_mode_source = _coerce_optional_text(item.get("effective_mode_source"))
        guidance_status = _coerce_optional_text(item.get("guidance_status"))
        recovery_policy_status = _coerce_optional_text(item.get("recovery_policy_status"))
        top_guidance_reason = _first_optional_text(
            item.get("top_guidance_reason"),
            item.get("reason"),
            item.get("guidance_status"),
        )
        task_payload = _normalize_task_payload(item.get("task"))
        events.append(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": session_id,
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
                "effective_mode_source": effective_mode_source,
                "guidance_status": guidance_status,
                "recovery_policy_status": recovery_policy_status,
                "top_guidance_reason": top_guidance_reason,
                "task_url": task_payload.get("url"),
                "task_page": task_payload.get("page"),
            }
        )
    if not events:
        return
    with output_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")


def _normalize_recovery_policy_snapshot(policy: dict[str, Any] | None) -> dict[str, Any]:
    policy = _coerce_optional_mapping(policy)
    policy_status = _coerce_optional_text(policy.get("policy_status"))
    effective_recommended_mode = _coerce_optional_text(policy.get("effective_recommended_mode"))
    top_policy_reason = _coerce_optional_text(policy.get("top_policy_reason"))
    return {
        "policy_status": policy_status,
        "effective_recommended_mode": effective_recommended_mode,
        "mode_pin_active": _coerce_optional_bool(policy.get("mode_pin_active")),
        "top_policy_reason": top_policy_reason,
    }


def _load_recovery_policy_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def persist_recovery_policy_state(policy: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_normalize_recovery_policy_snapshot(policy), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_recovery_policy_transition_events(
    result: dict[str, Any],
    state_path: Path,
    events_path: Path,
    *,
    session_id: str,
) -> None:
    previous_state = _normalize_recovery_policy_snapshot(_load_recovery_policy_state(state_path))
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    current_state = previous_state
    events: list[dict[str, Any]] = []
    current_state_has_signal = any(value is not None for value in current_state.values())

    for item in results:
        next_state = _normalize_recovery_policy_snapshot(
            {
                "policy_status": item.get("recovery_policy_status"),
                "effective_recommended_mode": item.get("recovery_policy_effective_recommended_mode"),
                "mode_pin_active": item.get("recovery_policy_mode_pin_active"),
                "top_policy_reason": item.get("top_policy_reason"),
            }
        )
        if (
            not any(
                (
                    next_state.get("policy_status"),
                    next_state.get("effective_recommended_mode"),
                    next_state.get("top_policy_reason"),
                )
            )
            and next_state.get("mode_pin_active") is None
        ):
            continue
        if current_state_has_signal and next_state != current_state:
            requested_mode = _coerce_optional_text(item.get("requested_mode"))
            effective_mode = _coerce_optional_text(item.get("effective_mode"))
            task_payload = _normalize_task_payload(item.get("task"))
            if current_state.get("mode_pin_active") and not next_state.get("mode_pin_active"):
                transition_kind = "pin_released"
            elif not current_state.get("mode_pin_active") and next_state.get("mode_pin_active"):
                transition_kind = "pin_activated"
            elif current_state.get("policy_status") != next_state.get("policy_status"):
                transition_kind = "policy_status_changed"
            elif current_state.get("effective_recommended_mode") != next_state.get("effective_recommended_mode"):
                transition_kind = "recommended_mode_changed"
            else:
                transition_kind = "policy_updated"
            events.append(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_id": session_id,
                    "transition_kind": transition_kind,
                    "from_policy_status": current_state.get("policy_status"),
                    "to_policy_status": next_state.get("policy_status"),
                    "from_mode_pin_active": current_state.get("mode_pin_active"),
                    "to_mode_pin_active": next_state.get("mode_pin_active"),
                    "from_effective_recommended_mode": current_state.get("effective_recommended_mode"),
                    "to_effective_recommended_mode": next_state.get("effective_recommended_mode"),
                    "from_top_policy_reason": current_state.get("top_policy_reason"),
                    "to_top_policy_reason": next_state.get("top_policy_reason"),
                    "requested_mode": requested_mode,
                    "effective_mode": effective_mode,
                    "task_url": task_payload.get("url"),
                    "task_page": task_payload.get("page"),
                }
            )
        current_state = next_state
        current_state_has_signal = any(value is not None for value in current_state.values())

    persist_recovery_policy_state(current_state, state_path)
    if not events:
        return
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")


def append_operator_escalation_events(
    result: dict[str, Any],
    output_path: Path,
    *,
    session_id: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    events: list[dict[str, Any]] = []

    for item in results:
        source = _coerce_optional_text(item.get("operator_escalation_source")) or ""
        requested_mode = _coerce_optional_text(item.get("requested_mode"))
        policy_status = _coerce_optional_text(item.get("recovery_policy_status"))
        policy_priority = _first_optional_text(
            item.get("recovery_policy_priority"),
            item.get("intervention_priority"),
        )
        top_policy_reason = _first_optional_text(
            item.get("top_policy_reason"),
            item.get("intervention_reason"),
        )
        operator_escalation_audit_message = _coerce_optional_text(
            item.get("operator_escalation_audit_message")
        )
        effective_mode = _coerce_optional_text(item.get("effective_mode"))
        effective_mode_source = _coerce_optional_text(item.get("effective_mode_source"))
        task_payload = _normalize_task_payload(item.get("task"))
        if policy_status == "escalate_repeated_repin":
            escalation_kind = "repeated_repin_cycle"
            if not source:
                source = "recovery_policy"
        elif source in {
            "lifecycle_high_priority_backlog",
            "intervention_policy",
            "intervention_stability",
            "intervention_stability_flapping",
        }:
            escalation_kind = source
        else:
            continue
        events.append(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "session_id": session_id,
                "escalation_kind": escalation_kind,
                "operator_escalation_source": source or None,
                "policy_status": policy_status,
                "policy_priority": policy_priority,
                "top_policy_reason": top_policy_reason,
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
                "effective_mode_source": effective_mode_source,
                "task_url": task_payload.get("url"),
                "task_page": task_payload.get("page"),
                "operator_escalation_audit_message": operator_escalation_audit_message,
            }
        )
    if not events:
        return
    with output_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")


def _normalize_operator_escalation_snapshot(result: dict[str, Any] | None) -> dict[str, Any]:
    result = _coerce_optional_mapping(result)
    policy_status = _first_optional_text(
        result.get("recovery_policy_status"),
        result.get("policy_status"),
    )
    policy_priority = _first_optional_text(
        result.get("recovery_policy_priority"),
        result.get("policy_priority"),
    )
    top_policy_reason = _coerce_optional_text(result.get("top_policy_reason"))
    explicit_escalation_kind = _coerce_optional_text(result.get("escalation_kind")) or ""
    operator_escalation_source = _coerce_optional_text(result.get("operator_escalation_source")) or ""
    source_driven_escalation_kinds = {
        "lifecycle_high_priority_backlog",
        "intervention_policy",
        "intervention_stability",
        "intervention_stability_flapping",
    }
    if policy_status == "escalate_repeated_repin":
        escalation_kind = "repeated_repin_cycle"
    elif operator_escalation_source in source_driven_escalation_kinds:
        escalation_kind = operator_escalation_source
    elif explicit_escalation_kind in {"repeated_repin_cycle", *source_driven_escalation_kinds}:
        escalation_kind = explicit_escalation_kind
    else:
        escalation_kind = None
    return {
        "escalation_kind": escalation_kind,
        "policy_status": policy_status,
        "policy_priority": policy_priority,
        "top_policy_reason": top_policy_reason,
    }


def _load_operator_escalation_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def persist_operator_escalation_state(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_normalize_operator_escalation_snapshot(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_operator_escalation_recovery_events(
    result: dict[str, Any],
    state_path: Path,
    recovery_events_path: Path,
    *,
    session_id: str,
) -> None:
    previous_state = _normalize_operator_escalation_snapshot(_load_operator_escalation_state(state_path))
    result = _coerce_optional_mapping(result)
    loop_mode = result.get("mode") == "loop"
    results = list(result.get("results") or []) if loop_mode else [result]
    current_state = previous_state
    events: list[dict[str, Any]] = []

    for item in results:
        next_state = _normalize_operator_escalation_snapshot(item)
        previous_active = bool(current_state.get("escalation_kind"))
        next_active = bool(next_state.get("escalation_kind"))
        effective_mode = _coerce_optional_text(item.get("effective_mode"))
        task_payload = _normalize_task_payload(item.get("task"))
        if previous_active and not next_active:
            events.append(
                {
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "session_id": session_id,
                    "transition_kind": "escalation_cleared",
                    "from_escalation_kind": current_state.get("escalation_kind"),
                    "from_policy_status": current_state.get("policy_status"),
                    "to_policy_status": next_state.get("policy_status"),
                    "effective_mode": effective_mode,
                    "task_url": task_payload.get("url"),
                    "task_page": task_payload.get("page"),
                }
            )
        current_state = next_state

    persist_operator_escalation_state(current_state, state_path)
    if not events:
        return []
    recovery_events_path.parent.mkdir(parents=True, exist_ok=True)
    with recovery_events_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False))
            handle.write("\n")
    return events


def _normalize_operator_intervention_snapshot(summary: dict[str, Any] | None) -> dict[str, Any]:
    summary = _coerce_optional_mapping(summary)
    intervention_status = _coerce_optional_text(summary.get("intervention_status"))
    intervention_required = _coerce_optional_bool(summary.get("intervention_required"))
    intervention_priority = _coerce_optional_text(summary.get("intervention_priority"))
    intervention_reason = _coerce_optional_text(summary.get("intervention_reason"))
    preferred_operator_action_hint = _coerce_optional_text(
        summary.get("preferred_operator_action_hint")
    )
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    return {
        "intervention_status": intervention_status,
        "intervention_required": intervention_required,
        "intervention_priority": intervention_priority,
        "intervention_reason": intervention_reason,
        "preferred_operator_action_hint": preferred_operator_action_hint,
        "suggested_mode": suggested_mode,
    }


def _load_operator_intervention_state(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def persist_operator_intervention_state(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_normalize_operator_intervention_snapshot(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_operator_intervention_transition_events(
    result: dict[str, Any],
    intervention_summary: dict[str, Any],
    final_guidance_summary: dict[str, Any],
    state_path: Path,
    events_path: Path,
    *,
    session_id: str,
) -> None:
    previous_state = _normalize_operator_intervention_snapshot(_load_operator_intervention_state(state_path))
    next_state = _normalize_operator_intervention_snapshot(intervention_summary)
    result = _coerce_optional_mapping(result)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    if (
        not any(
            (
                next_state.get("intervention_status"),
                next_state.get("intervention_priority"),
                next_state.get("intervention_reason"),
                next_state.get("preferred_operator_action_hint"),
                next_state.get("suggested_mode"),
            )
        )
        and next_state.get("intervention_required") is None
    ):
        return

    loop_mode = result.get("mode") == "loop"
    loop_results = list(result.get("results") or []) if loop_mode else []
    last_result = (
        _coerce_optional_mapping(loop_results[-1]) if loop_results else result
    )
    previous_state_has_signal = any(value is not None for value in previous_state.values())
    if previous_state == next_state:
        persist_operator_intervention_state(next_state, state_path)
        return
    if not previous_state_has_signal:
        persist_operator_intervention_state(next_state, state_path)
        return

    if not previous_state.get("intervention_status") and next_state.get("intervention_status"):
        transition_kind = "status_initialized"
    elif previous_state.get("intervention_status") != next_state.get("intervention_status"):
        transition_kind = "status_changed"
    elif bool(previous_state.get("intervention_required")) != bool(next_state.get("intervention_required")):
        transition_kind = "required_flag_changed"
    elif previous_state.get("intervention_priority") != next_state.get("intervention_priority"):
        transition_kind = "priority_changed"
    else:
        transition_kind = "reason_changed"

    final_guidance_priority = _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    final_guidance_label = _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    final_guidance_message = _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    effective_mode = _coerce_optional_text(last_result.get("effective_mode"))
    task_payload = _normalize_task_payload(last_result.get("task"))

    event = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": session_id,
        "transition_kind": transition_kind,
        "from_intervention_status": previous_state.get("intervention_status"),
        "to_intervention_status": next_state.get("intervention_status"),
        "from_intervention_required": bool(previous_state.get("intervention_required")),
        "to_intervention_required": bool(next_state.get("intervention_required")),
        "from_intervention_priority": previous_state.get("intervention_priority"),
        "to_intervention_priority": next_state.get("intervention_priority"),
        "from_intervention_reason": previous_state.get("intervention_reason"),
        "to_intervention_reason": next_state.get("intervention_reason"),
        "to_action_hint": next_state.get("preferred_operator_action_hint"),
        "to_suggested_mode": next_state.get("suggested_mode"),
        "to_final_guidance_label": final_guidance_label,
        "to_final_guidance_priority": final_guidance_priority,
        "to_final_guidance_message": final_guidance_message,
        "effective_mode": effective_mode,
        "task_url": task_payload.get("url"),
        "task_page": task_payload.get("page"),
    }
    persist_operator_intervention_state(next_state, state_path)
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def operator_escalation_source(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
) -> str | None:
    policy_status = _coerce_optional_text(result.get("recovery_policy_status")) or ""
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    stability_summary = _coerce_optional_mapping(stability_summary)
    priority_hint = _coerce_optional_text(lifecycle_summary.get("priority_hint")) or ""
    intervention_required = _coerce_optional_bool(intervention_summary.get("intervention_required"))
    intervention_reason = _coerce_optional_text(intervention_summary.get("intervention_reason")) or ""
    stability_status = _coerce_optional_text(stability_summary.get("stability_status")) or ""
    if policy_status == "escalate_repeated_repin":
        return "recovery_policy"
    if (
        priority_hint == "high_priority_backlog_present"
        or intervention_reason == "high_priority_unresolved_escalation_backlog"
    ):
        return "lifecycle_high_priority_backlog"
    if stability_status in {"escalating", "persistent_intervention_required"}:
        return "intervention_stability"
    if stability_status == "flapping":
        if include_flapping:
            return "intervention_stability_flapping"
        return None
    if intervention_required is True:
        return "intervention_policy"
    return None


def operator_action_hint(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
) -> str | None:
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
        include_flapping=include_flapping,
    )
    suggested_mode = _first_optional_text(
        intervention_summary.get("suggested_mode"),
        lifecycle_summary.get("suggested_mode"),
        result.get("recovery_policy_effective_recommended_mode"),
        result.get("effective_mode"),
    )
    suggested_mode_suffix = (
        f"; suggested mode={suggested_mode}"
        if suggested_mode is not None
        else ""
    )
    preferred_intervention_action_hint = _coerce_optional_text(
        intervention_summary.get("preferred_operator_action_hint")
    )
    if preferred_intervention_action_hint is not None:
        return preferred_intervention_action_hint
    if source == "lifecycle_high_priority_backlog":
        return f"inspect unresolved high-priority backlog{suggested_mode_suffix}"
    if source == "recovery_policy":
        return f"follow recovery policy escalation guidance{suggested_mode_suffix}"
    if source == "intervention_policy":
        return f"prefer browser and investigate escalation{suggested_mode_suffix}"
    if source == "intervention_stability":
        return f"prefer browser and investigate escalation{suggested_mode_suffix}"
    if source == "intervention_stability_flapping":
        return f"monitor until stable{suggested_mode_suffix}"
    return None


def operator_escalation_audit_message(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    final_guidance_summary: dict[str, Any] | None = None,
    digest_summary: dict[str, Any] | None = None,
    digest_stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
) -> str | None:
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    stability_summary = _coerce_optional_mapping(stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    digest_summary = _coerce_optional_mapping(digest_summary)
    digest_stability_summary = _coerce_optional_mapping(digest_stability_summary)
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
        include_flapping=include_flapping,
    )
    if source is None:
        return None
    guidance_message = _first_optional_text(
        result.get("operator_final_guidance_message"),
        final_guidance_summary.get("guidance_message"),
        digest_summary.get("operator_digest_message"),
    )
    digest_status = _first_optional_text(
        result.get("operator_digest_status"),
        digest_summary.get("digest_status"),
    )
    digest_stability = _first_optional_text(
        result.get("operator_digest_stability_status"),
        digest_stability_summary.get("stability_status"),
    )
    detail_parts = [f"source={source}"]
    if digest_status is not None:
        detail_parts.append(f"digest={digest_status}")
    if digest_stability is not None:
        detail_parts.append(f"digest_stability={digest_stability}")
    return f"{guidance_message or 'Operator escalation'} [{', '.join(detail_parts)}]"


def emit_operator_console_summary(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    final_guidance_summary: dict[str, Any] | None = None,
    digest_summary: dict[str, Any] | None = None,
    digest_stability_summary: dict[str, Any] | None = None,
    stream=None,
) -> None:
    stream = stream or sys.stderr
    lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
    intervention_summary = _coerce_optional_mapping(intervention_summary)
    stability_summary = _coerce_optional_mapping(stability_summary)
    final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
    digest_summary = _coerce_optional_mapping(digest_summary)
    digest_stability_summary = _coerce_optional_mapping(digest_stability_summary)
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
    )
    if source is not None:
        audit_message = _coerce_optional_text(result.get("operator_escalation_audit_message"))
        has_audit_message = audit_message is not None
        if has_audit_message:
            print(
                f"[OPERATOR] Operator escalation audit: {audit_message}",
                file=stream,
            )
        policy_status = _coerce_optional_text(result.get("recovery_policy_status"))
        priority = _first_optional_text(
            result.get("recovery_policy_priority"),
            intervention_summary.get("intervention_priority"),
        )
        mode = _first_optional_text(
            result.get("recovery_policy_effective_recommended_mode"),
            intervention_summary.get("suggested_mode"),
            lifecycle_summary.get("suggested_mode"),
            result.get("effective_mode"),
        )
        reason = _first_optional_text(
            result.get("top_policy_reason"),
            intervention_summary.get("intervention_reason"),
            lifecycle_summary.get("priority_hint"),
        )
        guidance_label = _first_optional_text(
            result.get("operator_final_guidance_label"),
            final_guidance_summary.get("guidance_label"),
        )
        digest_status = _first_optional_text(
            result.get("operator_digest_status"),
            digest_summary.get("digest_status"),
        )
        digest_stability_status = _first_optional_text(
            result.get("operator_digest_stability_status"),
            digest_stability_summary.get("stability_status"),
        )
        task_payload = _normalize_task_payload(result.get("task"))
        page = task_payload.get("page")
        intervention_status_label = _coerce_optional_text(intervention_summary.get("intervention_status"))
        stability_status_label = _coerce_optional_text(stability_summary.get("stability_status"))
        lifecycle_state_label = _coerce_optional_text(lifecycle_summary.get("lifecycle_state"))
        status_label = (
            policy_status
            or intervention_status_label
            or stability_status_label
            or lifecycle_state_label
            or "operator_escalation"
        )
        if has_audit_message:
            parts = []
            if mode is not None:
                parts.append(f"mode={mode}")
            if priority is not None:
                parts.append(f"priority={priority}")
            if reason is not None:
                parts.append(f"reason={reason}")
            if page not in {None, "", "unknown"}:
                parts.append(f"page={page}")
            if parts:
                message = (
                    f"[OPERATOR] Operator escalation: {status_label} "
                    f"({', '.join(parts)})"
                )
            else:
                message = f"[OPERATOR] Operator escalation: {status_label}"
        else:
            parts = [
                f"source={source}",
            ]
            if mode is not None:
                parts.append(f"mode={mode}")
            if priority is not None:
                parts.append(f"priority={priority}")
            if reason is not None:
                parts.append(f"reason={reason}")
            if guidance_label is not None:
                parts.append(f"guidance={guidance_label}")
            if digest_status is not None:
                parts.append(f"digest_status={digest_status}")
            if digest_stability_status is not None:
                parts.append(f"digest_stability={digest_stability_status}")
            if page not in {None, "", "unknown"}:
                parts.append(f"page={page}")
            message = (
                f"[OPERATOR] Operator escalation: {status_label} "
                f"({', '.join(parts)})"
            )
        print(message, file=stream)


def emit_operator_recovery_console_summary(events: list[dict[str, Any]], *, stream=None) -> None:
    stream = stream or sys.stderr
    for event in events:
        if _coerce_optional_text(event.get("transition_kind")) != "escalation_cleared":
            continue
        from_status = _coerce_optional_text(event.get("from_policy_status"))
        to_status = _coerce_optional_text(event.get("to_policy_status"))
        mode = _coerce_optional_text(event.get("effective_mode"))
        page = _coerce_optional_int(event.get("task_page"))
        if page is not None and page < 0:
            page = None
        parts = []
        if from_status is not None:
            parts.append(f"from={from_status}")
        if to_status is not None:
            parts.append(f"to={to_status}")
        if mode is not None:
            parts.append(f"mode={mode}")
        if page not in {None, "", "unknown"}:
            parts.append(f"page={page}")
        if parts:
            message = f"[OPERATOR] Operator recovery: escalation_cleared ({', '.join(parts)})"
        else:
            message = "[OPERATOR] Operator recovery: escalation_cleared"
        print(message, file=stream)


def emit_operator_lifecycle_console_summary(summary: dict[str, Any], *, stream=None) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    if not summary and not summary.get("lifecycle_state"):
        return
    lifecycle_state = _coerce_optional_text(summary.get("lifecycle_state"))
    if lifecycle_state in {None, "steady"}:
        return
    reason = _coerce_optional_text(summary.get("lifecycle_reason"))
    follow_up = _coerce_optional_text(summary.get("recommended_follow_up"))
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    priority_hint = _coerce_optional_text(summary.get("priority_hint"))
    active_unresolved_priority = _coerce_optional_text(summary.get("active_unresolved_priority"))
    active_high_priority_unresolved_count = _coerce_optional_int(
        summary.get("active_high_priority_unresolved_count")
    )
    if active_high_priority_unresolved_count is not None and active_high_priority_unresolved_count < 0:
        active_high_priority_unresolved_count = None
    parts = []
    if reason is not None:
        parts.append(f"reason={reason}")
    if follow_up is not None:
        parts.append(f"follow_up={follow_up}")
    if suggested_mode is not None:
        parts.append(f"suggested_mode={suggested_mode}")
    if priority_hint is not None:
        parts.append(f"priority_hint={priority_hint}")
    if active_unresolved_priority is not None:
        parts.append(f"active_unresolved_priority={active_unresolved_priority}")
    if active_high_priority_unresolved_count is not None:
        parts.append(f"active_high_priority_unresolved_count={active_high_priority_unresolved_count}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    message = f"[OPERATOR] Lifecycle state: {lifecycle_state}{detail_suffix}"
    print(message, file=stream)


def emit_operator_intervention_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_reason: bool = False,
    suppress_priority: bool = False,
    suppress_suggested_mode: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    intervention_status = _coerce_optional_text(summary.get("intervention_status"))
    if intervention_status in {None, "ready"}:
        return
    intervention_required = _coerce_optional_bool(summary.get("intervention_required"))
    priority = _coerce_optional_text(summary.get("intervention_priority"))
    reason = _coerce_optional_text(summary.get("intervention_reason"))
    action_hint = _coerce_optional_text(summary.get("preferred_operator_action_hint"))
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    effective_suppress_action_hint = action_hint is None
    effective_suppress_suggested_mode = suppress_suggested_mode or (
        suggested_mode is None
        or (
            action_hint is not None
            and f"suggested mode={suggested_mode}" in action_hint
        )
    )
    parts = []
    if intervention_required is not None:
        parts.append(f"required={intervention_required}")
    if not suppress_priority and priority is not None:
        parts.append(f"priority={priority}")
    if not suppress_reason and reason is not None:
        parts.append(f"reason={reason}")
    if not effective_suppress_action_hint:
        parts.append(f"action_hint={action_hint}")
    if not effective_suppress_suggested_mode:
        parts.append(f"suggested_mode={suggested_mode}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    message = f"[OPERATOR] Intervention status: {intervention_status}{detail_suffix}"
    print(message, file=stream)


def emit_operator_intervention_stability_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_action_hint: bool = False,
    suppress_current: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    stability_status = _coerce_optional_text(summary.get("stability_status"))
    if stability_status in {None, "stable_ready"}:
        return
    stability_severity = _coerce_optional_text(summary.get("stability_severity"))
    current_status = _coerce_optional_text(summary.get("current_intervention_status"))
    previous_status = _coerce_optional_text(summary.get("previous_intervention_status"))
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count"))
    if recent_change_count is not None and recent_change_count < 0:
        recent_change_count = None
    explanation = _coerce_optional_text(summary.get("operator_readable_explanation"))
    action_hint = _coerce_optional_text(summary.get("stability_action_hint"))
    effective_suppress_action_hint = suppress_action_hint or action_hint is None
    parts = []
    if not suppress_status:
        parts.append(stability_status)
    if stability_severity is not None:
        parts.append(f"severity={stability_severity}")
    if not suppress_current and current_status is not None:
        parts.append(f"current={current_status}")
    if previous_status is not None:
        parts.append(f"previous={previous_status}")
    if recent_change_count is not None:
        parts.append(f"changes={recent_change_count}")
    if explanation is not None:
        parts.append(f"explanation={explanation}")
    if not effective_suppress_action_hint:
        parts.append(f"action_hint={action_hint}")
    if not parts:
        parts.append(stability_status)
    message = f"[OPERATOR] Intervention stability: {', '.join(parts)}"
    print(message, file=stream)


def emit_operator_final_guidance_console_summary(summary: dict[str, Any], *, stream=None) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    raw_priority = summary.get("guidance_priority")
    priority = _coerce_optional_text(raw_priority)
    priority_key = (priority or "").lower()
    if priority_key == "info" or (priority is None and not raw_priority):
        return
    if priority_key == "unknown":
        priority = None
    guidance_label = _coerce_optional_text(summary.get("guidance_label"))
    label = str(guidance_label or "Operator guidance")
    guidance_message = _coerce_optional_text(summary.get("guidance_message"))
    message = str(guidance_message or label)
    suggested_mode = _coerce_optional_text(summary.get("suggested_mode"))
    parts = []
    if priority is not None:
        parts.append(f"priority={priority}")
    if suggested_mode is not None:
        parts.append(f"suggested_mode={suggested_mode}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    print(f"[OPERATOR] Final guidance: {message}{detail_suffix}", file=stream)


def emit_operator_digest_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_message: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    digest_status = _coerce_optional_text(summary.get("digest_status"))
    if digest_status in {None, "ready"}:
        return
    digest_priority = _coerce_optional_text(summary.get("digest_priority"))
    digest_message = _coerce_optional_text(summary.get("operator_digest_message"))
    has_priority = digest_priority is not None
    effective_suppress_message = suppress_message or digest_message is None
    if effective_suppress_message and suppress_status:
        if not has_priority:
            return
        message = f"[OPERATOR] Operator digest: priority={digest_priority}"
    elif effective_suppress_message:
        if has_priority:
            message = f"[OPERATOR] Operator digest: {digest_status} (priority={digest_priority})"
        else:
            message = f"[OPERATOR] Operator digest: {digest_status}"
    elif suppress_status:
        if has_priority:
            message = f"[OPERATOR] Operator digest: {digest_message} (priority={digest_priority})"
        else:
            message = f"[OPERATOR] Operator digest: {digest_message}"
    else:
        parts = [f"status={digest_status}"]
        if has_priority:
            parts.append(f"priority={digest_priority}")
        message = f"[OPERATOR] Operator digest: {digest_message} ({', '.join(parts)})"
    print(message, file=stream)


def emit_operator_digest_stability_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_current: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    stability_status = _coerce_optional_text(summary.get("stability_status"))
    if stability_status in {None, "stable_digest"}:
        return
    stability_severity = _coerce_optional_text(summary.get("stability_severity"))
    current_status = _coerce_optional_text(summary.get("current_digest_status"))
    previous_status = _coerce_optional_text(summary.get("previous_digest_status"))
    recent_change_count = _coerce_optional_int(summary.get("recent_change_count"))
    if recent_change_count is not None and recent_change_count < 0:
        recent_change_count = None
    explanation = _coerce_optional_text(summary.get("operator_readable_explanation"))
    effective_suppress_status = suppress_status or explanation is not None
    parts = []
    if not effective_suppress_status:
        parts.append(stability_status)
    if stability_severity is not None:
        parts.append(f"severity={stability_severity}")
    if not suppress_current and current_status is not None:
        parts.append(f"current={current_status}")
    if previous_status is not None:
        parts.append(f"previous={previous_status}")
    if recent_change_count is not None:
        parts.append(f"changes={recent_change_count}")
    if explanation is not None:
        parts.append(f"explanation={explanation}")
    if not parts:
        parts.append(stability_status)
    message = f"[OPERATOR] Operator digest stability: {', '.join(parts)}"
    print(message, file=stream)


def emit_operator_escalation_event_trend_console_summary(summary: dict[str, Any], *, stream=None) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    current_source = _coerce_optional_text(summary.get("current_operator_escalation_source"))
    recent_change_count = _coerce_optional_int(summary.get("recent_source_change_count"))
    if recent_change_count is not None and recent_change_count < 0:
        recent_change_count = None
    previous_source = _coerce_optional_text(summary.get("previous_distinct_operator_escalation_source"))
    last_changed_at = _coerce_optional_text(summary.get("last_source_change_at"))
    if current_source is None or (
        recent_change_count in {None, 0}
        and not previous_source
        and last_changed_at is None
    ):
        return
    parts = []
    if previous_source is not None:
        parts.append(f"previous={previous_source}")
    if recent_change_count is not None:
        parts.append(f"changes={recent_change_count}")
    if last_changed_at is not None:
        parts.append(f"last_changed_at={last_changed_at}")
    detail_suffix = f" ({', '.join(parts)})" if parts else ""
    message = f"[OPERATOR] Operator escalation source trend: current={current_source}{detail_suffix}"
    print(message, file=stream)


def emit_operator_escalation_event_stability_console_summary(
    summary: dict[str, Any],
    *,
    stream=None,
    suppress_source_context: bool = False,
    suppress_status: bool = False,
) -> None:
    stream = stream or sys.stderr
    summary = _coerce_optional_mapping(summary)
    stability_status = _coerce_optional_text(summary.get("stability_status"))
    if stability_status in {None, "stable_escalation_source"}:
        return
    stability_severity = _coerce_optional_text(summary.get("stability_severity"))
    current_source = _coerce_optional_text(summary.get("current_operator_escalation_source"))
    previous_source = _coerce_optional_text(summary.get("previous_operator_escalation_source"))
    recent_source_change_count = _coerce_optional_int(summary.get("recent_source_change_count"))
    if recent_source_change_count is not None and recent_source_change_count < 0:
        recent_source_change_count = None
    explanation = _coerce_optional_text(summary.get("operator_readable_explanation"))
    parts = []
    if not suppress_status:
        parts.append(stability_status)
    if stability_severity is not None:
        parts.append(f"severity={stability_severity}")
    if not suppress_source_context:
        if current_source is not None:
            parts.append(f"current={current_source}")
        if previous_source is not None:
            parts.append(f"previous={previous_source}")
        if recent_source_change_count is not None:
            parts.append(f"changes={recent_source_change_count}")
    if explanation is not None:
        parts.append(f"explanation={explanation}")
    if not parts:
        return
    message = f"[OPERATOR] Operator escalation source stability: {', '.join(parts)}"
    print(message, file=stream)


def operator_escalation_exit_code(
    result: dict[str, Any],
    *,
    lifecycle_summary: dict[str, Any] | None = None,
    intervention_summary: dict[str, Any] | None = None,
    stability_summary: dict[str, Any] | None = None,
    include_flapping: bool = False,
    configured_exit_code: int,
) -> int | None:
    source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=stability_summary,
        include_flapping=include_flapping,
    )
    if source is not None:
        return int(configured_exit_code)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run browserless-first hybrid seed collection against the real seed task dispatcher.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--mode", choices=["hybrid", "browserless", "browser"], default=DEFAULT_MODE)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--idle-sleep-seconds", type=float, default=10.0)
    parser.add_argument("--success-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--fallback-sleep-seconds", type=float, default=15.0)
    parser.add_argument("--stop-on-fallback", action="store_true")
    parser.add_argument("--stop-on-operator-escalation", action="store_true")
    parser.add_argument("--max-consecutive-fallbacks", type=int, default=None)
    parser.add_argument("--open-browser-fallback", action="store_true")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--respect-operator-guidance", action="store_true")
    parser.add_argument("--runtime-summary-path", default=str(DEFAULT_RUNTIME_SUMMARY_PATH))
    parser.add_argument("--runtime-history-path", default=str(DEFAULT_RUNTIME_HISTORY_PATH))
    parser.add_argument("--runtime-switch-events-path", default=str(DEFAULT_RUNTIME_SWITCH_EVENTS_PATH))
    parser.add_argument("--runtime-recovery-policy-state-path", default=str(DEFAULT_RECOVERY_POLICY_STATE_PATH))
    parser.add_argument("--runtime-recovery-policy-events-path", default=str(DEFAULT_RECOVERY_POLICY_EVENTS_PATH))
    parser.add_argument("--runtime-operator-escalation-events-path", default=str(DEFAULT_OPERATOR_ESCALATION_EVENTS_PATH))
    parser.add_argument("--runtime-operator-escalation-state-path", default=str(DEFAULT_OPERATOR_ESCALATION_STATE_PATH))
    parser.add_argument("--runtime-operator-escalation-recovery-events-path", default=str(DEFAULT_OPERATOR_ESCALATION_RECOVERY_EVENTS_PATH))
    parser.add_argument("--runtime-operator-intervention-state-path", default=str(DEFAULT_OPERATOR_INTERVENTION_STATE_PATH))
    parser.add_argument("--runtime-operator-intervention-events-path", default=str(DEFAULT_OPERATOR_INTERVENTION_EVENTS_PATH))
    parser.add_argument("--fail-on-operator-escalation", action="store_true")
    parser.add_argument("--operator-escalation-exit-code", type=int, default=42)
    args = parser.parse_args(argv)

    guidance_payload: dict[str, Any] = {}
    recovery_policy_payload: dict[str, Any] = {}
    guidance_resolution: dict[str, Any] = {}
    effective_mode = str(_coerce_optional_text(args.mode) or DEFAULT_MODE)

    if args.loop:
        result = run_loop(
            api_base=args.api_base,
            session_id=args.session_id,
            cdp_endpoint=args.cdp_endpoint,
            submit=args.submit,
            mode=args.mode,
            profile_dir=Path(args.profile_dir),
            open_browser_fallback=args.open_browser_fallback,
            max_runs=args.max_runs,
            idle_sleep_seconds=args.idle_sleep_seconds,
            success_sleep_seconds=args.success_sleep_seconds,
            fallback_sleep_seconds=args.fallback_sleep_seconds,
            stop_on_fallback=args.stop_on_fallback,
            stop_on_operator_escalation=args.stop_on_operator_escalation,
            max_consecutive_fallbacks=args.max_consecutive_fallbacks,
            respect_operator_guidance=bool(args.respect_operator_guidance),
            load_operator_status_bundle_fn=load_hybrid_collection_operator_status_bundle,
            load_recovery_policy_fn=load_hybrid_collection_recovery_policy,
            load_lifecycle_summary_fn=load_hybrid_collection_lifecycle_state_summary,
            load_intervention_summary_fn=load_hybrid_collection_operator_intervention_policy_summary,
            load_stability_summary_fn=load_hybrid_collection_operator_intervention_stability_summary,
            load_digest_summary_fn=load_hybrid_collection_operator_digest_summary,
            load_digest_stability_summary_fn=load_hybrid_collection_operator_digest_stability_summary,
            load_escalation_event_trend_summary_fn=load_hybrid_collection_operator_escalation_event_trend_summary,
            load_escalation_event_stability_summary_fn=load_hybrid_collection_operator_escalation_event_stability_summary,
        )
    else:
        with hybrid_collection_status_snapshot_scope():
            try:
                operator_status_bundle = load_hybrid_collection_operator_status_bundle(args.api_base)
            except requests.exceptions.RequestException:
                operator_status_bundle = {}
            operator_status_bundle = _coerce_optional_mapping(operator_status_bundle)
            if args.respect_operator_guidance:
                guidance_payload = _coerce_optional_mapping(operator_status_bundle.get("guidance"))
                recovery_policy_payload = _coerce_optional_mapping(operator_status_bundle.get("recovery_policy"))
            guidance_resolution = resolve_effective_mode(
                requested_mode=args.mode,
                guidance=guidance_payload,
                recovery_policy=recovery_policy_payload,
                respect_operator_guidance=bool(args.respect_operator_guidance),
            )
            resolution_effective_mode = _coerce_optional_text(
                guidance_resolution.get("effective_mode")
            )
            effective_mode = _first_optional_text(
                resolution_effective_mode,
                guidance_resolution.get("requested_mode"),
                args.mode,
                DEFAULT_MODE,
            ) or DEFAULT_MODE
            effective_mode_for_result = resolution_effective_mode
            result = run_once(
                api_base=args.api_base,
                session_id=args.session_id,
                cdp_endpoint=args.cdp_endpoint,
                submit=args.submit,
                mode=effective_mode,
                profile_dir=Path(args.profile_dir),
                open_browser_fallback=args.open_browser_fallback,
            )
            result = _coerce_optional_mapping(result)
            if "task" in result:
                result["task"] = _normalize_task_payload(result.get("task"))
            if "collection_result" in result:
                result["collection_result"] = _normalize_collection_result_payload(
                    result.get("collection_result")
                )
            result["decision"] = _coerce_optional_text(result.get("decision"))
            result["reason"] = _coerce_optional_text(result.get("reason"))
            if "error" in result:
                result["error"] = _coerce_optional_text(result.get("error"))
            if "task_message" in result:
                result["task_message"] = _coerce_optional_text(result.get("task_message"))
            if "message" in result:
                result["message"] = _coerce_optional_text(result.get("message"))
            result["browser_fallback_opened"] = (
                _coerce_optional_bool(result.get("browser_fallback_opened")) is True
            )
            result["fallback_url"] = _coerce_optional_text(result.get("fallback_url"))
            requested_mode_for_result = _first_optional_text(
                guidance_resolution.get("requested_mode"),
                args.mode,
                DEFAULT_MODE,
            )
            result["requested_mode"] = requested_mode_for_result
            result["effective_mode"] = effective_mode_for_result
            effective_mode_source = _coerce_optional_text(guidance_resolution.get("effective_mode_source"))
            result["effective_mode_source"] = effective_mode_source
            result["guidance_applied"] = (
                _coerce_optional_bool(guidance_resolution.get("guidance_applied")) is True
            )
            guidance_status = _coerce_optional_text(guidance_resolution.get("guidance_status"))
            result["guidance_status"] = guidance_status
            guidance_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("recommended_mode")
            guidance_recommended_mode = _coerce_optional_text(guidance_recommended_mode)
            result["guidance_recommended_mode"] = guidance_recommended_mode
            top_guidance_reason = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("top_guidance_reason")
            top_guidance_reason = _coerce_optional_text(top_guidance_reason)
            top_policy_reason = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("top_policy_reason")
            top_policy_reason = _coerce_optional_text(top_policy_reason)
            if guidance_resolution.get("effective_mode_source") == "recovery_policy":
                top_guidance_reason = top_policy_reason or top_guidance_reason
            result["top_guidance_reason"] = top_guidance_reason
            result["top_policy_reason"] = top_policy_reason
            recovery_policy_status = _coerce_optional_text(guidance_resolution.get("recovery_policy_status"))
            result["recovery_policy_status"] = recovery_policy_status
            recovery_policy_priority = _coerce_optional_text(guidance_resolution.get("recovery_policy_priority"))
            result["recovery_policy_priority"] = recovery_policy_priority
            result["recovery_policy_mode_pin_active"] = _coerce_optional_bool(
                guidance_resolution.get("recovery_policy_mode_pin_active")
            )
            recovery_policy_effective_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("effective_recommended_mode")
            recovery_policy_effective_recommended_mode = _coerce_optional_text(
                recovery_policy_effective_recommended_mode
            )
            result["recovery_policy_effective_recommended_mode"] = (
                recovery_policy_effective_recommended_mode
            )
            lifecycle_summary = _coerce_optional_mapping(operator_status_bundle.get("lifecycle_summary"))
            intervention_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_summary"))
            intervention_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_stability_summary"))
            final_guidance_summary = _coerce_optional_mapping(operator_status_bundle.get("final_guidance_summary"))
            operator_digest_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_summary"))
            operator_digest_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_stability_summary"))
            operator_escalation_event_trend_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_trend_summary"))
            operator_escalation_event_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_stability_summary"))
    if args.loop:
        with hybrid_collection_status_snapshot_scope():
            try:
                lifecycle_summary = load_hybrid_collection_lifecycle_state_summary(args.api_base)
            except requests.exceptions.RequestException:
                lifecycle_summary = {}
            lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
            try:
                intervention_summary = load_hybrid_collection_operator_intervention_policy_summary(args.api_base)
            except requests.exceptions.RequestException:
                intervention_summary = {}
            intervention_summary = _coerce_optional_mapping(intervention_summary)
            try:
                intervention_stability_summary = load_hybrid_collection_operator_intervention_stability_summary(args.api_base)
            except requests.exceptions.RequestException:
                intervention_stability_summary = {}
            intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
            try:
                final_guidance_summary = load_hybrid_collection_operator_final_guidance_summary(args.api_base)
            except requests.exceptions.RequestException:
                final_guidance_summary = {}
            final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
            try:
                operator_digest_summary = load_hybrid_collection_operator_digest_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_digest_summary = {}
            operator_digest_summary = _coerce_optional_mapping(operator_digest_summary)
            try:
                operator_digest_stability_summary = load_hybrid_collection_operator_digest_stability_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_digest_stability_summary = {}
            operator_digest_stability_summary = _coerce_optional_mapping(operator_digest_stability_summary)
            try:
                operator_escalation_event_trend_summary = load_hybrid_collection_operator_escalation_event_trend_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_escalation_event_trend_summary = {}
            operator_escalation_event_trend_summary = _coerce_optional_mapping(operator_escalation_event_trend_summary)
            try:
                operator_escalation_event_stability_summary = load_hybrid_collection_operator_escalation_event_stability_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_escalation_event_stability_summary = {}
            operator_escalation_event_stability_summary = _coerce_optional_mapping(operator_escalation_event_stability_summary)
    digest_status = _coerce_optional_text(operator_digest_summary.get("digest_status"))
    result["operator_digest_status"] = digest_status
    digest_priority = _coerce_optional_text(operator_digest_summary.get("digest_priority"))
    result["operator_digest_priority"] = digest_priority
    digest_message = _coerce_optional_text(operator_digest_summary.get("operator_digest_message"))
    result["operator_digest_message"] = digest_message
    digest_stability_status = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_status")
    )
    digest_stability_severity = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_severity")
    )
    digest_stability_explanation = _coerce_optional_text(
        operator_digest_stability_summary.get("operator_readable_explanation")
    )
    result["operator_digest_stability_status"] = digest_stability_status
    result["operator_digest_stability_severity"] = digest_stability_severity
    result["operator_digest_stability_explanation"] = digest_stability_explanation
    source_last_changed_at = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("last_source_change_at")
    )
    current_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("current_operator_escalation_source")
    )
    previous_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
    )
    source_stability_status = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_status")
    )
    source_stability_severity = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_severity")
    )
    source_stability_explanation = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("operator_readable_explanation")
    )
    final_guidance_label = _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    final_guidance_priority = _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    final_guidance_message = _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    result["operator_escalation_current_source"] = current_source
    result["operator_escalation_previous_source"] = previous_source
    operator_escalation_source_change_count = _coerce_optional_int(
        operator_escalation_event_trend_summary.get("recent_source_change_count")
    )
    if operator_escalation_source_change_count is not None and operator_escalation_source_change_count < 0:
        operator_escalation_source_change_count = 0
    result["operator_escalation_source_change_count"] = operator_escalation_source_change_count
    result["operator_escalation_source_last_changed_at"] = source_last_changed_at
    result["operator_escalation_source_stability_status"] = source_stability_status
    result["operator_escalation_source_stability_severity"] = source_stability_severity
    result["operator_escalation_source_stability_explanation"] = source_stability_explanation
    escalation_source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=intervention_stability_summary,
    )
    if escalation_source is not None:
        result["operator_escalation_source"] = escalation_source
        result["operator_action_hint"] = operator_action_hint(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=intervention_stability_summary,
        )
        result["operator_final_guidance_label"] = final_guidance_label
        result["operator_final_guidance_priority"] = final_guidance_priority
        result["operator_final_guidance_message"] = final_guidance_message
        audit_message = operator_escalation_audit_message(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=intervention_stability_summary,
            final_guidance_summary=final_guidance_summary,
            digest_summary=operator_digest_summary,
            digest_stability_summary=operator_digest_stability_summary,
        )
        audit_message = _coerce_optional_text(audit_message)
        if audit_message is not None:
            result["operator_escalation_audit_message"] = audit_message
        else:
            result.pop("operator_escalation_audit_message", None)
    elif _coerce_optional_text(result.get("operator_escalation_source")) is None:
        result.pop("operator_escalation_source", None)
    audit_message = _coerce_optional_text(result.get("operator_escalation_audit_message"))
    if audit_message is not None:
        result["operator_escalation_audit_message"] = audit_message
    else:
        result.pop("operator_escalation_audit_message", None)
    runtime_summary = build_runtime_summary(
        result=result,
        requested_mode=args.mode,
        effective_mode=effective_mode_for_result if not args.loop else effective_mode,
        submit=args.submit,
        api_base=args.api_base,
        cdp_endpoint=args.cdp_endpoint,
        session_id=args.session_id,
        guidance_resolution=guidance_resolution,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        intervention_stability_summary=intervention_stability_summary,
        final_guidance_summary=final_guidance_summary,
        operator_digest_summary=operator_digest_summary,
        operator_digest_stability_summary=operator_digest_stability_summary,
        operator_escalation_event_trend_summary=operator_escalation_event_trend_summary,
        operator_escalation_event_stability_summary=operator_escalation_event_stability_summary,
    )
    persist_runtime_summary(runtime_summary, Path(args.runtime_summary_path))
    append_runtime_history(runtime_summary, Path(args.runtime_history_path))
    append_mode_switch_events(
        result,
        Path(args.runtime_switch_events_path),
        session_id=args.session_id,
    )
    append_recovery_policy_transition_events(
        result,
        Path(args.runtime_recovery_policy_state_path),
        Path(args.runtime_recovery_policy_events_path),
        session_id=args.session_id,
    )
    append_operator_escalation_events(
        result,
        Path(args.runtime_operator_escalation_events_path),
        session_id=args.session_id,
    )
    recovery_events = append_operator_escalation_recovery_events(
        result,
        Path(args.runtime_operator_escalation_state_path),
        Path(args.runtime_operator_escalation_recovery_events_path),
        session_id=args.session_id,
    )
    append_operator_intervention_transition_events(
        result,
        intervention_summary,
        final_guidance_summary,
        Path(args.runtime_operator_intervention_state_path),
        Path(args.runtime_operator_intervention_events_path),
        session_id=args.session_id,
    )
    digest_message = _coerce_optional_text(operator_digest_summary.get("operator_digest_message")) or ""
    digest_status = _coerce_optional_text(operator_digest_summary.get("digest_status")) or ""
    audit_message = _coerce_optional_text(result.get("operator_escalation_audit_message")) or ""
    has_audit_message = bool(audit_message)
    final_guidance_message = _coerce_optional_text(result.get("operator_final_guidance_message")) or ""
    suppress_digest_message = False
    suppress_digest_status = False
    if digest_message:
        suppress_digest_message = (
            (has_audit_message and digest_message in audit_message)
            or (not has_audit_message and digest_message == final_guidance_message)
        )
    if digest_status:
        suppress_digest_status = has_audit_message and f"digest={digest_status}" in audit_message
    emit_operator_digest_console_summary(
        operator_digest_summary,
        suppress_message=suppress_digest_message,
        suppress_status=suppress_digest_status,
    )
    digest_stability_current = _coerce_optional_text(
        operator_digest_stability_summary.get("current_digest_status")
    )
    suppress_digest_stability_current = digest_status != "" and digest_status == digest_stability_current
    digest_stability_status = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_status")
    )
    suppress_digest_stability_status = (
        digest_stability_status is not None
        and has_audit_message
        and f"digest_stability={digest_stability_status}" in audit_message
    )
    emit_operator_digest_stability_console_summary(
        operator_digest_stability_summary,
        suppress_current=suppress_digest_stability_current,
        suppress_status=suppress_digest_stability_status,
    )
    if not has_audit_message:
        emit_operator_final_guidance_console_summary(final_guidance_summary)
    emit_operator_escalation_event_trend_console_summary(operator_escalation_event_trend_summary)
    trend_current_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("current_operator_escalation_source")
    ) or ""
    trend_previous_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
    )
    trend_last_changed_at = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("last_source_change_at")
    )
    trend_recent_change_count = _coerce_optional_int(
        operator_escalation_event_trend_summary.get("recent_source_change_count")
    )
    if trend_recent_change_count is not None and trend_recent_change_count < 0:
        trend_recent_change_count = None
    stability_current_source = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("current_operator_escalation_source")
    ) or ""
    stability_previous_source = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("previous_operator_escalation_source")
    )
    stability_recent_source_change_count = _coerce_optional_int(
        operator_escalation_event_stability_summary.get("recent_source_change_count")
    )
    if stability_recent_source_change_count is not None and stability_recent_source_change_count < 0:
        stability_recent_source_change_count = None
    trend_line_visible = bool(trend_current_source) and (
        trend_recent_change_count not in {None, 0}
        or bool(trend_previous_source)
        or trend_last_changed_at is not None
    )
    suppress_escalation_stability_source_context = trend_line_visible and (
        trend_current_source == stability_current_source
    ) and (
        trend_previous_source == stability_previous_source
    ) and (
        trend_recent_change_count == stability_recent_source_change_count
    )
    suppress_escalation_stability_status = (
        _coerce_optional_text(
            operator_escalation_event_stability_summary.get("operator_readable_explanation")
        )
        is not None
    )
    emit_operator_escalation_event_stability_console_summary(
        operator_escalation_event_stability_summary,
        suppress_source_context=suppress_escalation_stability_source_context,
        suppress_status=suppress_escalation_stability_status,
    )
    emit_operator_console_summary(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=intervention_stability_summary,
        final_guidance_summary=final_guidance_summary,
        digest_summary=operator_digest_summary,
        digest_stability_summary=operator_digest_stability_summary,
    )
    emit_operator_recovery_console_summary(recovery_events)
    suppression_source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=intervention_stability_summary,
    )
    suppression_reason = _coerce_optional_text(intervention_summary.get("intervention_reason"))
    suppression_priority = _coerce_optional_text(intervention_summary.get("intervention_priority"))
    suppression_suggested_mode = _coerce_optional_text(intervention_summary.get("suggested_mode"))
    suppression_escalation_reason = _first_optional_text(
        result.get("top_policy_reason"),
        intervention_summary.get("intervention_reason"),
        lifecycle_summary.get("priority_hint"),
    )
    suppression_escalation_priority = _first_optional_text(
        result.get("recovery_policy_priority"),
        intervention_summary.get("intervention_priority"),
    )
    suppression_escalation_mode = _first_optional_text(
        result.get("recovery_policy_effective_recommended_mode"),
        intervention_summary.get("suggested_mode"),
        lifecycle_summary.get("suggested_mode"),
        result.get("effective_mode"),
    )
    suppress_intervention_reason = bool(suppression_source) and bool(suppression_reason) and (
        suppression_reason == suppression_escalation_reason
    )
    suppress_intervention_priority = bool(suppression_source) and bool(suppression_priority) and (
        suppression_priority == suppression_escalation_priority
    )
    suppress_intervention_suggested_mode = bool(suppression_source) and bool(suppression_suggested_mode) and (
        suppression_suggested_mode == suppression_escalation_mode
    )
    emit_operator_intervention_console_summary(
        intervention_summary,
        suppress_reason=suppress_intervention_reason,
        suppress_priority=suppress_intervention_priority,
        suppress_suggested_mode=suppress_intervention_suggested_mode,
    )
    intervention_action_hint = _coerce_optional_text(
        intervention_summary.get("preferred_operator_action_hint")
    )
    intervention_stability_action_hint = _coerce_optional_text(
        intervention_stability_summary.get("stability_action_hint")
    )
    suppress_intervention_stability_action_hint = (
        intervention_action_hint is not None
        and intervention_action_hint == intervention_stability_action_hint
    )
    intervention_status = _coerce_optional_text(intervention_summary.get("intervention_status"))
    intervention_stability_current = _coerce_optional_text(
        intervention_stability_summary.get("current_intervention_status")
    )
    suppress_intervention_stability_current = (
        intervention_status is not None
        and intervention_status == intervention_stability_current
    )
    suppress_intervention_stability_status = (
        _coerce_optional_text(intervention_stability_summary.get("operator_readable_explanation"))
        is not None
    )
    emit_operator_intervention_stability_console_summary(
        intervention_stability_summary,
        suppress_action_hint=suppress_intervention_stability_action_hint,
        suppress_current=suppress_intervention_stability_current,
        suppress_status=suppress_intervention_stability_status,
    )
    emit_operator_lifecycle_console_summary(lifecycle_summary)
    print(json.dumps(result, ensure_ascii=False))
    if args.fail_on_operator_escalation:
        escalation_exit_code = operator_escalation_exit_code(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=intervention_stability_summary,
            configured_exit_code=args.operator_escalation_exit_code,
        )
        if escalation_exit_code is not None:
            print(
                f"[OPERATOR] Returning dedicated operator escalation exit code {escalation_exit_code} "
                f"(source={result.get('operator_escalation_source')})",
                file=sys.stderr,
            )
            return escalation_exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
