from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from urllib.error import URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.storage.repository import PropertyRepository, create_repository_from_env
from tools.internal_api_http import fetch_json, post_json
from tools.live_batch_smoke import (
    CdpEndpointUnavailableError,
    DEFAULT_API_BASE_URL,
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_USER_AGENT,
    build_http,
    captcha_solver_enabled,
    export_cookies,
    fetch_list_page,
    resolve_runtime_user_agent,
    write_json,
)


DEFAULT_SEED_SORTS = (
    "sort_0:0:默认排序,"
    "sort_3:3:价格由高到低,"
    "bid_desc:2:出价次数由高到低,"
    "end_time_soon:1:结拍时间由近到远,"
    "sort_4:4:排序4,"
    "sort_5:5:排序5"
)
DEFAULT_SEED_JOB_KEY = "guangdong-guangzhou-nansha-50025969"
DEFAULT_SEED_LOCATION_CODE = "440115"
DEFAULT_SEED_CATEGORY = "50025969"
STATUS_UNAVAILABLE_RETRY_ATTEMPTS = 3
STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS = 1.0
DEFAULT_AUTH_PROBE_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class SeedSortSpec:
    sort_key: str
    st_param: str
    sort_name: str
    sort_order: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sort_key": self.sort_key,
            "st_param": self.st_param,
            "sort_name": self.sort_name,
            "sort_order": self.sort_order,
        }


@dataclass(frozen=True)
class SeedScanJobSpec:
    job_key: str
    province: str
    city: str
    district: str
    location_code: str
    category: str
    sort_specs: tuple[SeedSortSpec, ...]
    max_page: int

    def as_job_dict(self) -> dict[str, Any]:
        return {
            "job_key": self.job_key,
            "province": self.province,
            "city": self.city,
            "district": self.district,
            "location_code": self.location_code,
            "category": self.category,
        }


@dataclass(frozen=True)
class SeedCollectorConfig:
    job_key: str
    province: str
    city: str
    district: str
    location_code: str
    category: str
    sort_specs: tuple[SeedSortSpec, ...]
    max_page: int
    cdp_endpoint: str
    output_dir: Path
    worker_id: str
    lease_seconds: int = 120
    loop_interval_seconds: int = 1800
    active_loop_interval_seconds: int | None = None
    max_runs: int | None = None
    pages_per_run: int = 10
    solver_enabled: bool = False
    manual_challenge_reporting: bool = False
    api_base_url: str = ""
    seed_jobs: tuple[SeedScanJobSpec, ...] = ()
    parallel_sorts: bool = False
    failure_cooldown_threshold: int = 0
    failure_cooldown_seconds: int = 0
    auth_probe_interval_seconds: int = DEFAULT_AUTH_PROBE_INTERVAL_SECONDS


SeedRuntimeContextFactory = Callable[[], Any]
SeedProgressEmitFunc = Callable[[dict[str, Any]], None]


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def parse_seed_sort_specs(raw: str | None) -> tuple[SeedSortSpec, ...]:
    text = _clean_text(raw, DEFAULT_SEED_SORTS)
    specs: list[SeedSortSpec] = []
    seen_keys: set[str] = set()
    for index, chunk in enumerate(text.replace(";", ",").split(",")):
        value = chunk.strip()
        if not value:
            continue
        parts = [part.strip() for part in value.split(":", 2)]
        if len(parts) == 1:
            sort_key = f"sort_{parts[0]}"
            st_param = parts[0]
            sort_name = sort_key
        elif len(parts) == 2:
            sort_key, st_param = parts
            sort_name = sort_key
        else:
            sort_key, st_param, sort_name = parts
        sort_key = sort_key or f"sort_{index}"
        st_param = st_param or sort_key
        sort_name = sort_name or sort_key
        if sort_key in seen_keys:
            continue
        seen_keys.add(sort_key)
        specs.append(SeedSortSpec(sort_key=sort_key, st_param=st_param, sort_name=sort_name, sort_order=len(specs)))
    if not specs:
        raise ValueError("at least one seed sort spec is required")
    return tuple(specs)


def _safe_sort_order(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_seed_sort_specs_value(value: Any, fallback: tuple[SeedSortSpec, ...]) -> tuple[SeedSortSpec, ...]:
    if isinstance(value, str):
        return parse_seed_sort_specs(value)
    if not isinstance(value, list):
        return fallback
    specs: list[SeedSortSpec] = []
    seen_keys: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        sort_key = _clean_text(item.get("sort_key") or item.get("key") or item.get("st_param"), f"sort_{index}")
        st_param = _clean_text(item.get("st_param") or item.get("value"), sort_key)
        sort_name = _clean_text(item.get("sort_name") or item.get("name"), sort_key)
        if sort_key in seen_keys:
            continue
        seen_keys.add(sort_key)
        specs.append(
            SeedSortSpec(
                sort_key=sort_key,
                st_param=st_param,
                sort_name=sort_name,
                sort_order=_safe_sort_order(item.get("sort_order"), len(specs)),
            )
        )
    return tuple(sorted(specs, key=lambda spec: (spec.sort_order, spec.sort_key))) if specs else fallback


def parse_seed_job_specs(
    raw_jobs: Any,
    *,
    fallback_sort_specs: tuple[SeedSortSpec, ...],
    fallback_max_page: int,
) -> tuple[SeedScanJobSpec, ...]:
    if raw_jobs in (None, ""):
        return ()
    if isinstance(raw_jobs, str):
        decoded = json.loads(raw_jobs)
    else:
        decoded = raw_jobs
    if not isinstance(decoded, list):
        raise ValueError("seed jobs must be a JSON array")
    jobs: list[SeedScanJobSpec] = []
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            continue
        location_code = _clean_text(item.get("location_code"))
        if not location_code:
            raise ValueError(f"seed job at index {index} requires location_code")
        category = _clean_text(item.get("category"), DEFAULT_SEED_CATEGORY)
        sort_specs = _parse_seed_sort_specs_value(
            item.get("sorts") if "sorts" in item else item.get("sort_specs"),
            fallback_sort_specs,
        )
        max_page = _safe_int(item.get("max_page"), fallback_max_page)
        fallback_key = f"{location_code}-{category}"
        jobs.append(
            SeedScanJobSpec(
                job_key=_clean_text(item.get("job_key"), fallback_key),
                province=_clean_text(item.get("province")),
                city=_clean_text(item.get("city")),
                district=_clean_text(item.get("district")),
                location_code=location_code,
                category=category,
                sort_specs=sort_specs,
                max_page=max_page,
            )
        )
    return tuple(jobs)


def _job_payload(config: SeedCollectorConfig) -> dict[str, Any]:
    return {
        "job_key": config.job_key,
        "province": config.province,
        "city": config.city,
        "district": config.district,
        "location_code": config.location_code,
        "category": config.category,
    }


def _default_seed_job(config: SeedCollectorConfig) -> SeedScanJobSpec:
    return SeedScanJobSpec(
        job_key=config.job_key,
        province=config.province,
        city=config.city,
        district=config.district,
        location_code=config.location_code,
        category=config.category,
        sort_specs=config.sort_specs,
        max_page=config.max_page,
    )


def _seed_jobs(config: SeedCollectorConfig) -> tuple[SeedScanJobSpec, ...]:
    return config.seed_jobs or (_default_seed_job(config),)


def _ensure_seed_scan_jobs(config: SeedCollectorConfig, repository: PropertyRepository) -> list[dict[str, Any]]:
    ensured: list[dict[str, Any]] = []
    for job in _seed_jobs(config):
        ensured.append(
            repository.ensure_seed_scan_job(
                job.as_job_dict(),
                sort_specs=[spec.as_dict() for spec in job.sort_specs],
                max_page=job.max_page,
            )
        )
    return ensured


def _should_archive_stale_seed_jobs(config: SeedCollectorConfig) -> bool:
    if not config.seed_jobs:
        return False
    job_keys = {job.job_key for job in config.seed_jobs if _clean_text(job.job_key)}
    if len(job_keys) != len(config.seed_jobs):
        return False
    return True


def _archive_stale_seed_jobs(config: SeedCollectorConfig, repository: PropertyRepository) -> dict[str, int]:
    active_job_keys = [job.job_key for job in _seed_jobs(config)]
    return repository.archive_seed_scan_jobs_except(active_job_keys)


def _has_seed_scan_work(repository: PropertyRepository) -> tuple[bool, dict[str, int]]:
    counts = repository.seed_queue_counts()
    pending = int(counts.get("seed_scan_progress_pending", 0) or 0)
    in_progress = int(counts.get("seed_scan_progress_in_progress", 0) or 0)
    return pending + in_progress > 0, counts


def _seed_scan_queue_progress_total(counts: dict[str, int]) -> int:
    return sum(
        _summary_int(counts.get(key))
        for key in (
            "seed_scan_progress_pending",
            "seed_scan_progress_in_progress",
            "seed_scan_progress_exhausted",
            "seed_scan_progress_blocked",
        )
    )


def _should_ensure_seed_jobs(config: SeedCollectorConfig, counts: dict[str, int]) -> bool:
    if _seed_scan_queue_progress_total(counts) <= 0:
        return True
    return config.worker_id in {"seed-1", "seed-test"}


def _extract_seed_items(browserless_seed_probe: Any, html: str, *, final_url: str) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    if not isinstance(summary, dict):
        summary = {}
    payload = browserless_seed_probe.extract_list_payload(html)
    if payload is None:
        has_challenge = bool(summary.get("body_has_challenge") or summary.get("body_has_login") or summary.get("body_has_punish"))
        return [], summary, has_challenge
    batch = browserless_seed_probe.build_userscript_like_batch_payload(payload, source_page_url=final_url)
    items = [dict(item) for item in (batch.get("items") or []) if isinstance(item, dict)]
    return items, summary, False


def _browser_page_payload_missing_without_challenge(fetch_method: str, list_summary: dict[str, Any]) -> bool:
    if not str(fetch_method or "").startswith("browser_page"):
        return False
    if not isinstance(list_summary, dict):
        return True
    has_script = list_summary.get("has_script")
    item_count = list_summary.get("item_count")
    return has_script is False and item_count is None


def _write_runtime_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "seed_collector_summary.json", summary)


def _collection_pause_state(api_base_url: str) -> dict[str, Any]:
    if not str(api_base_url or "").strip():
        return {"paused": False, "reason": "status_probe_disabled"}

    endpoint = api_base_url.rstrip("/") + "/status"
    try:
        payload = fetch_json(endpoint, timeout=5)
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"paused": False, "reason": "status_unavailable", "error": repr(exc)}

    if not isinstance(payload, dict):
        return {"paused": False, "reason": "status_unavailable", "error": "non_object_status"}

    return _normalize_collection_pause_state(payload)


def _normalize_collection_pause_state(payload: dict[str, Any]) -> dict[str, Any]:
    captcha_solver = payload.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        captcha_solver = {}
    manual_required = bool(captcha_solver.get("manual_required"))
    force_unlock = bool(captcha_solver.get("force_unlock_flag_exists"))
    solver_running_for_current_node = _captcha_solver_targets_current_node(captcha_solver)
    solver_running_only = (
        bool(payload.get("paused"))
        and bool(captcha_solver.get("running"))
        and bool(captcha_solver.get("paused"))
        and not manual_required
        and not force_unlock
    )
    paused = bool(payload.get("paused")) or manual_required or force_unlock or solver_running_for_current_node
    if solver_running_only and not solver_running_for_current_node:
        paused = False
    reason = "captcha_solver_manual_required" if manual_required else "collection_paused" if paused else None
    if solver_running_for_current_node and not manual_required and not force_unlock:
        reason = "captcha_solver_running"
    elif solver_running_only:
        reason = "captcha_solver_running_other_node"
    return {
        "paused": paused,
        "reason": reason,
        "captcha_solver": captcha_solver,
    }


def _captcha_solver_targets_current_node(captcha_solver: dict[str, Any]) -> bool:
    if not bool(captcha_solver.get("running")):
        return False
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return True
    target_node_id = str(last_request.get("node_id") or "").strip().casefold()
    current_node_id = str(os.environ.get("FAPAI_NODE_ID") or "").strip().casefold()
    if not target_node_id or not current_node_id:
        return True
    return target_node_id == current_node_id


def _collection_pause_state_with_retry(api_base_url: str) -> dict[str, Any]:
    pause_state = _collection_pause_state(api_base_url)
    if not str(api_base_url or "").strip() or pause_state.get("reason") != "status_unavailable":
        return pause_state

    for _attempt in range(1, STATUS_UNAVAILABLE_RETRY_ATTEMPTS):
        time.sleep(STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS)
        retry_state = _collection_pause_state(api_base_url)
        pause_state = retry_state
        if retry_state.get("reason") != "status_unavailable":
            break
    return pause_state


def _pause_state_targets_detail_page(pause_state: dict[str, Any]) -> bool:
    captcha_solver = pause_state.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        return False
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return False
    target_url = str(last_request.get("target_url") or "").lower()
    return "sf-item.taobao.com" in target_url or "/sf_item/" in target_url


def _default_seed_auth_probe_target_url() -> str:
    return "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"


def _normalize_seed_challenge_target_url(target_url: str, *, allow_default: bool = False) -> str:
    fallback = _default_seed_auth_probe_target_url() if allow_default else ""
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return fallback
    if str(parsed.hostname or "").casefold() != "sf.taobao.com":
        return fallback

    path = str(parsed.path or "")
    punish_index = path.casefold().find("/_____tmd_____/punish")
    if punish_index >= 0:
        path = path[:punish_index]
    while "//" in path:
        path = path.replace("//", "/")
    if not path.lower().startswith("/list/"):
        return fallback

    allowed_query_keys = {"location_code", "st_param", "auction_start_seg", "page"}
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key in allowed_query_keys
    ]
    query_pairs.append(("__captcha_solver_bg", "1"))
    return urlunsplit(("https", "sf.taobao.com", path, urlencode(query_pairs, doseq=True), ""))


def _pause_state_seed_probe_target_url(pause_state: dict[str, Any], *, allow_default: bool = False) -> str:
    captcha_solver = pause_state.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        return _default_seed_auth_probe_target_url() if allow_default else ""
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return _default_seed_auth_probe_target_url() if allow_default else ""
    target_url = str(last_request.get("target_url") or last_request.get("url") or "").strip()
    return _normalize_seed_challenge_target_url(target_url, allow_default=allow_default)


def _pause_state_blocks_seed_stage(pause_state: dict[str, Any]) -> bool:
    if not pause_state.get("paused"):
        return False
    return not _pause_state_targets_detail_page(pause_state)


def _notify_auth_probe_passed(api_base_url: str, target_url: str) -> dict[str, Any]:
    if not str(api_base_url or "").strip():
        return {"ok": False, "skipped": True, "reason": "api_base_url_missing"}
    endpoint = api_base_url.rstrip("/") + "/collection/auth/complete"
    payload = post_json(
        endpoint,
        {
            "source": "seed_auth_probe",
            "refresh_cookie_snapshot": False,
            "target_url": target_url,
        },
        timeout=10,
    )
    return payload if isinstance(payload, dict) else {"ok": False, "payload": payload}


def _probe_seed_auth_state(
    config: SeedCollectorConfig,
    pause_state: dict[str, Any],
    *,
    http_session: Any,
    browserless_seed_probe: Any,
) -> dict[str, Any]:
    target_url = _pause_state_seed_probe_target_url(
        pause_state,
        allow_default=bool(str(config.api_base_url or "").strip()),
    )
    if not target_url:
        return {"attempted": False, "authenticated": False, "reason": "no_seed_list_target_url"}

    try:
        runtime_user_agent = resolve_runtime_user_agent(config.cdp_endpoint)
        html, final_url, status_code, fetch_method = fetch_list_page(
            http_session,
            cdp_endpoint=config.cdp_endpoint,
            target_url=target_url,
            user_agent=runtime_user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
            solver_enabled=False,
            api_base_url=config.api_base_url,
        )
        items, list_summary, has_challenge = _extract_seed_items(browserless_seed_probe, html, final_url=final_url)
        payload_missing = _browser_page_payload_missing_without_challenge(fetch_method, list_summary)
        authenticated = not has_challenge and not payload_missing
        result: dict[str, Any] = {
            "attempted": True,
            "authenticated": authenticated,
            "target_url": target_url,
            "final_url": final_url,
            "status_code": status_code,
            "method": fetch_method,
            "item_count": len(items),
            "list_summary": list_summary,
        }
        if not authenticated and payload_missing:
            result["reason"] = "probe_not_authenticated"
        if authenticated:
            result["auth_complete"] = _notify_auth_probe_passed(config.api_base_url, target_url)
        return result
    except Exception as exc:
        return {
            "attempted": True,
            "authenticated": False,
            "target_url": target_url,
            "reason": "probe_exception",
            "error": repr(exc),
        }


def _build_cdp_unreachable_auth_probe(config: SeedCollectorConfig, target_url: str) -> dict[str, Any]:
    from tools import taobao_login_health

    effective_target_url = str(target_url or "").strip() or "https://sf.taobao.com/list/50025969__2.htm"
    return {
        "attempted": True,
        "authenticated": False,
        "status": taobao_login_health.CDP_UNREACHABLE,
        "cdp_endpoint": config.cdp_endpoint,
        "target_url": effective_target_url,
        "operator_hint": taobao_login_health.build_operator_hint(
            status=taobao_login_health.CDP_UNREACHABLE,
            cdp_endpoint=config.cdp_endpoint,
            check_url=effective_target_url,
        ),
    }


def _build_runtime_context(config: SeedCollectorConfig) -> Any:
    cookies = export_cookies(config.cdp_endpoint)
    return build_http(cookies)


def _emit_progress_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _summary_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _seed_cycle_summary(run_results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    decision_counts: dict[str, int] = {}
    for result in run_results:
        decision = str(result.get("decision") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1

    collected = [result for result in run_results if result.get("decision") == "seed_page_collected"]
    retryable_failures = [result for result in run_results if result.get("decision") == "seed_page_retryable_failure"]
    upserts = [result.get("upsert") for result in collected if isinstance(result.get("upsert"), dict)]
    return {
        "pages_attempted": sum(1 for result in run_results if _is_page_attempt_result(result)),
        "pages_collected": len(collected),
        "retryable_failures": len(retryable_failures),
        "paused_count": decision_counts.get("seed_collection_paused", 0),
        "queue_empty_count": decision_counts.get("seed_scan_queue_empty", 0),
        "items_seen": sum(_summary_int(upsert.get("seen")) for upsert in upserts),
        "items_collected": sum(_summary_int(result.get("item_count")) for result in collected),
        "new_items": sum(_summary_int(upsert.get("new_items")) for upsert in upserts),
        "existing_items": sum(_summary_int(upsert.get("existing_items")) for upsert in upserts),
        "new_occurrences": sum(_summary_int(upsert.get("new_occurrences")) for upsert in upserts),
        "decision_counts": decision_counts,
    }


def _seed_run_progress_event(run: int, run_results: list[dict[str, Any]]) -> dict[str, Any]:
    last_result = run_results[-1] if run_results else {}
    cycle_summary = _seed_cycle_summary(run_results)
    last_auth_probe = next(
        (
            result.get("auth_probe")
            for result in reversed(run_results)
            if isinstance(result.get("auth_probe"), dict)
        ),
        None,
    )
    event = {
        "event": "seed_collector_run",
        "run": run,
        "pages_attempted": cycle_summary["pages_attempted"],
        "pages_collected": cycle_summary["pages_collected"],
        "retryable_failures": cycle_summary["retryable_failures"],
        "new_occurrences": cycle_summary["new_occurrences"],
        "last_decision": last_result.get("decision"),
        "last_reason": last_result.get("reason"),
        "last_item_count": last_result.get("item_count"),
        "counts": last_result.get("counts"),
        "cycle_summary": cycle_summary,
    }
    if last_auth_probe is not None:
        event["last_auth_probe"] = last_auth_probe
        event["auth_probe_attempted"] = bool(last_auth_probe.get("attempted"))
    return event


def _is_page_attempt_result(result: dict[str, Any]) -> bool:
    return result.get("decision") not in {"seed_scan_queue_empty", "seed_collection_paused"}


def _seed_run_collected_page(run_results: Sequence[dict[str, Any]]) -> bool:
    return any(result.get("decision") == "seed_page_collected" for result in run_results)


def _seed_run_attempted_auth_probe(run_results: Sequence[dict[str, Any]]) -> bool:
    for result in run_results:
        auth_probe = result.get("auth_probe")
        if isinstance(auth_probe, dict) and auth_probe.get("attempted"):
            return True
    return False


def _seed_run_hit_challenge_page(run_results: Sequence[dict[str, Any]]) -> bool:
    return any(
        result.get("decision") == "seed_page_retryable_failure"
        and result.get("reason") == "list_challenge_page"
        for result in run_results
    )


def _seed_loop_sleep_seconds(config: SeedCollectorConfig, run_results: Sequence[dict[str, Any]]) -> int:
    if _seed_run_collected_page(run_results):
        interval = config.active_loop_interval_seconds
        if interval is None:
            interval = config.loop_interval_seconds
        return max(int(interval), 0)
    if _seed_run_attempted_auth_probe(run_results) or _seed_run_hit_challenge_page(run_results):
        return max(int(config.auth_probe_interval_seconds), 0)
    return max(config.loop_interval_seconds, 0)


def _summary_optional_non_negative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _seed_page_has_next(
    *,
    task_page: Any,
    task_max_page: Any,
    list_summary: dict[str, Any],
    filtered_items: Sequence[dict[str, Any]],
) -> bool:
    try:
        current_page = int(task_page)
    except (TypeError, ValueError):
        current_page = 1
    try:
        max_page = int(task_max_page)
    except (TypeError, ValueError):
        max_page = current_page
    if current_page >= max_page:
        return False
    raw_item_count = _summary_optional_non_negative_int(list_summary.get("item_count"))
    if raw_item_count is not None:
        return raw_item_count > 0
    return bool(filtered_items)


def _report_manual_seed_challenge(config: SeedCollectorConfig, target_url: str) -> dict[str, Any] | None:
    if (
        not config.manual_challenge_reporting
        or config.solver_enabled
        or not str(config.api_base_url or "").strip()
    ):
        return None

    from tools.taobao_login_health import report_captcha_via_api

    try:
        return dict(
            report_captcha_via_api(
                config.api_base_url,
                config.cdp_endpoint,
                _normalize_seed_challenge_target_url(target_url, allow_default=True),
                manual_only=True,
            )
        )
    except Exception as exc:
        return {"status": "report_failed", "error": repr(exc)}


def run_seed_collector_once(
    config: SeedCollectorConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browserless_seed_probe: Any,
    ensure_jobs: bool = True,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pause_state = _collection_pause_state_with_retry(config.api_base_url)
    auth_probe_summary = None
    if _pause_state_blocks_seed_stage(pause_state):
        if pause_state.get("reason") != "captcha_solver_manual_required":
            summary = {
                "decision": "seed_collection_paused",
                "reason": pause_state.get("reason") or "collection_paused",
                "captcha_solver": pause_state.get("captcha_solver") or {},
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary
        auth_probe = _probe_seed_auth_state(
            config,
            pause_state,
            http_session=http_session,
            browserless_seed_probe=browserless_seed_probe,
        )
        if auth_probe.get("authenticated"):
            auth_probe_summary = auth_probe
            pause_state = {"paused": False, "reason": "auth_probe_passed", "captcha_solver": pause_state.get("captcha_solver") or {}}
        else:
            summary = {
                "decision": "seed_collection_paused",
                "reason": pause_state.get("reason") or "collection_paused",
                "captcha_solver": pause_state.get("captcha_solver") or {},
                "auth_probe": auth_probe,
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary

    if ensure_jobs:
        _ensure_seed_scan_jobs(config, repository)
    task = repository.claim_seed_scan_page(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        parallel_sorts=config.parallel_sorts,
        failure_cooldown_threshold=config.failure_cooldown_threshold,
        failure_cooldown_seconds=config.failure_cooldown_seconds,
    )
    if task is None:
        summary = {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}
        if auth_probe_summary is not None:
            summary["auth_probe"] = auth_probe_summary
        _write_runtime_summary(config.output_dir, summary)
        return summary

    claimed_summary = {
        "decision": "seed_page_claimed",
        "task": task,
        "counts": repository.seed_queue_counts(),
    }
    if auth_probe_summary is not None:
        claimed_summary["auth_probe"] = auth_probe_summary
    _write_runtime_summary(config.output_dir, claimed_summary)

    try:
        runtime_user_agent = resolve_runtime_user_agent(config.cdp_endpoint)
        html, final_url, status_code, fetch_method = fetch_list_page(
            http_session,
            cdp_endpoint=config.cdp_endpoint,
            target_url=str(task["url"]),
            user_agent=runtime_user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
            solver_enabled=config.solver_enabled,
            api_base_url=config.api_base_url,
        )
        items, list_summary, has_challenge = _extract_seed_items(browserless_seed_probe, html, final_url=final_url)
        if has_challenge:
            captcha_solver_report = (
                None
                if config.solver_enabled
                else _report_manual_seed_challenge(config, str(task["url"]))
            )
            repository.fail_seed_scan_page(str(task["progress_key"]), "list_payload_missing", retryable=True)
            post_challenge_pause_state = _collection_pause_state_with_retry(config.api_base_url)
            if _pause_state_blocks_seed_stage(post_challenge_pause_state):
                summary = {
                    "decision": "seed_collection_paused",
                    "reason": post_challenge_pause_state.get("reason") or "collection_paused",
                    "captcha_solver": post_challenge_pause_state.get("captcha_solver") or {},
                    "task": task,
                    "list_summary": list_summary,
                    "fetch": {
                        "status_code": status_code,
                        "final_url": final_url,
                        "method": fetch_method,
                    },
                    "counts": repository.seed_queue_counts(),
                }
                if auth_probe_summary is not None:
                    summary["auth_probe"] = auth_probe_summary
                if captcha_solver_report is not None:
                    summary["captcha_solver_report"] = captcha_solver_report
                _write_runtime_summary(config.output_dir, summary)
                return summary
            summary = {
                "decision": "seed_page_retryable_failure",
                "reason": "list_challenge_page",
                "task": task,
                "list_summary": list_summary,
                "fetch": {
                    "status_code": status_code,
                    "final_url": final_url,
                    "method": fetch_method,
                },
                "counts": repository.seed_queue_counts(),
            }
            if auth_probe_summary is not None:
                summary["auth_probe"] = auth_probe_summary
            if captcha_solver_report is not None:
                summary["captcha_solver_report"] = captcha_solver_report
            _write_runtime_summary(config.output_dir, summary)
            return summary
        if _browser_page_payload_missing_without_challenge(fetch_method, list_summary):
            repository.fail_seed_scan_page(str(task["progress_key"]), "browser_list_payload_missing", retryable=True)
            summary = {
                "decision": "seed_page_retryable_failure",
                "reason": "browser_list_payload_missing",
                "task": task,
                "list_summary": list_summary,
                "fetch": {
                    "status_code": status_code,
                    "final_url": final_url,
                    "method": fetch_method,
                },
                "counts": repository.seed_queue_counts(),
            }
            if auth_probe_summary is not None:
                summary["auth_probe"] = auth_probe_summary
            _write_runtime_summary(config.output_dir, summary)
            return summary

        for item in items:
            item.setdefault("source_page_url", final_url)
            item.setdefault("list_location_code", task.get("location_code"))
            item.setdefault("list_category", task.get("category"))
            item.setdefault("list_st_param", task.get("st_param"))
            item.setdefault("list_page", task.get("page"))
            item.setdefault("list_sort_key", task.get("sort_key"))
            item.setdefault("list_sort_name", task.get("sort_name"))

        upsert = repository.upsert_seed_items(
            job_key=str(task["job_key"]),
            progress_key=str(task["progress_key"]),
            sort_key=str(task["sort_key"]),
            sort_name=str(task.get("sort_name") or ""),
            st_param=str(task["st_param"]),
            page=int(task["page"]),
            source_page_url=str(task["url"]),
            source_final_url=final_url,
            items=items,
        )
        has_next = _seed_page_has_next(
            task_page=task.get("page"),
            task_max_page=task.get("max_page", config.max_page),
            list_summary=list_summary,
            filtered_items=items,
        )
        repository.complete_seed_scan_page(
            progress_key=str(task["progress_key"]),
            page=int(task["page"]),
            item_count=len(items),
            has_next=has_next,
            source_url=final_url,
        )
        summary = {
            "decision": "seed_page_collected",
            "task": task,
            "fetch": {
                "status_code": status_code,
                "final_url": final_url,
                "method": fetch_method,
            },
            "list_summary": list_summary,
            "item_count": len(items),
            "has_next": has_next,
            "upsert": upsert,
            "counts": repository.seed_queue_counts(),
        }
        if auth_probe_summary is not None:
            summary["auth_probe"] = auth_probe_summary
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        repository.fail_seed_scan_page(str(task["progress_key"]), repr(exc), retryable=True)
        if isinstance(exc, CdpEndpointUnavailableError):
            summary = {
                "decision": "seed_collection_paused",
                "reason": "cdp_unreachable",
                "task": task,
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "auth_probe": _build_cdp_unreachable_auth_probe(config, str(task.get("url") or "")),
                "counts": repository.seed_queue_counts(),
            }
            if auth_probe_summary is not None:
                summary["previous_auth_probe"] = auth_probe_summary
            _write_runtime_summary(config.output_dir, summary)
            return summary
        summary = {
            "decision": "seed_page_retryable_failure",
            "reason": "exception",
            "task": task,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "counts": repository.seed_queue_counts(),
        }
        if auth_probe_summary is not None:
            summary["auth_probe"] = auth_probe_summary
        _write_runtime_summary(config.output_dir, summary)
        return summary


def run_seed_collector_loop(
    config: SeedCollectorConfig,
    *,
    repository: PropertyRepository,
    http_session: Any | None = None,
    browserless_seed_probe: Any,
    runtime_context_factory: SeedRuntimeContextFactory | None = None,
    progress_emit_func: SeedProgressEmitFunc | None = None,
) -> dict[str, Any]:
    if runtime_context_factory is None:
        if http_session is None:
            runtime_context_factory = lambda: _build_runtime_context(config)
        else:
            runtime_context_factory = lambda: http_session
    emit_progress = progress_emit_func or _emit_progress_event
    results: list[dict[str, Any]] = []
    last_runtime_context: Any | None = None
    runs = 0
    pages_attempted = 0
    cycle_summaries: list[dict[str, Any]] = []
    release_worker_leases = getattr(repository, "release_seed_scan_worker_leases", None)
    if callable(release_worker_leases):
        release_summary = release_worker_leases(config.worker_id)
        if int((release_summary or {}).get("released") or 0) > 0:
            release_event = {
                "decision": "seed_scan_worker_leases_released",
                "worker_id": config.worker_id,
                "release_summary": release_summary,
                "counts": repository.seed_queue_counts(),
            }
            emit_progress({"event": "seed_collector_worker_leases_released", **release_event})
            _write_runtime_summary(config.output_dir, release_event)
    initial_counts = repository.seed_queue_counts()
    if _should_ensure_seed_jobs(config, initial_counts):
        _write_runtime_summary(
            config.output_dir,
            {
                "decision": "seed_scan_jobs_ensure_started",
                "worker_id": config.worker_id,
                "job_count": len(_seed_jobs(config)),
                "counts": initial_counts,
            },
        )
        archive_summary = None
        if _should_archive_stale_seed_jobs(config):
            archive_summary = _archive_stale_seed_jobs(config, repository)
            _write_runtime_summary(
                config.output_dir,
                {
                    "decision": "seed_scan_jobs_archive_stale_completed",
                    "worker_id": config.worker_id,
                    "archive_summary": archive_summary,
                    "counts": repository.seed_queue_counts(),
                },
            )
        ensured_jobs = _ensure_seed_scan_jobs(config, repository)
        _write_runtime_summary(
            config.output_dir,
            {
                "decision": "seed_scan_jobs_ensure_completed",
                "worker_id": config.worker_id,
                "ensured_jobs": len(ensured_jobs),
                "ensure_results": ensured_jobs[-20:],
                "archive_summary": archive_summary,
                "counts": repository.seed_queue_counts(),
            },
        )
    else:
        _write_runtime_summary(
            config.output_dir,
            {
                "decision": "seed_scan_jobs_ensure_skipped",
                "reason": "existing_seed_scan_queue",
                "worker_id": config.worker_id,
                "counts": initial_counts,
            },
        )
    while True:
        runs += 1
        has_work, queue_counts = _has_seed_scan_work(repository)
        if not has_work:
            result = {"decision": "seed_scan_queue_empty", "counts": queue_counts}
            _write_runtime_summary(config.output_dir, result)
            results.append(result)
            run_event = _seed_run_progress_event(runs, [result])
            cycle_summaries.append(dict(run_event.get("cycle_summary") or {}))
            emit_progress(run_event)
            _write_runtime_summary(config.output_dir, run_event)
            if config.max_runs is not None and runs >= config.max_runs:
                break
            sleep_seconds = max(config.loop_interval_seconds, 0)
            emit_progress(
                {
                    "event": "seed_collector_sleep",
                    "run": runs,
                    "sleep_seconds": sleep_seconds,
                    "counts": run_event.get("counts"),
                }
            )
            time.sleep(sleep_seconds)
            continue
        try:
            current_http_session = runtime_context_factory()
            last_runtime_context = current_http_session
        except Exception as exc:
            if last_runtime_context is not None:
                current_http_session = last_runtime_context
                reuse_event = {
                    "event": "seed_collector_runtime_refresh_reused_last_context",
                    "run": runs,
                    "decision": "seed_runtime_refresh_reused_last_context",
                    "error": repr(exc),
                    "counts": repository.seed_queue_counts(),
                }
                emit_progress(reuse_event)
                _write_runtime_summary(config.output_dir, reuse_event)
            else:
                failure_event = {
                    "event": "seed_collector_runtime_refresh_failed",
                    "run": runs,
                    "decision": "seed_runtime_refresh_failed",
                    "error": repr(exc),
                    "counts": repository.seed_queue_counts(),
                }
                emit_progress(failure_event)
                _write_runtime_summary(config.output_dir, failure_event)
                if config.max_runs is not None and runs >= config.max_runs:
                    break
                sleep_seconds = max(config.loop_interval_seconds, 0)
                emit_progress(
                    {
                        "event": "seed_collector_sleep",
                        "run": runs,
                        "sleep_seconds": sleep_seconds,
                        "counts": failure_event.get("counts"),
                    }
                )
                time.sleep(sleep_seconds)
                continue
        run_results: list[dict[str, Any]] = []
        for _page_index in range(max(int(config.pages_per_run or 1), 1)):
            result = run_seed_collector_once(
                config,
                repository=repository,
                http_session=current_http_session,
                browserless_seed_probe=browserless_seed_probe,
                ensure_jobs=False,
            )
            results.append(result)
            run_results.append(result)
            if _is_page_attempt_result(result):
                pages_attempted += 1
            partial_run_event = _seed_run_progress_event(runs, run_results)
            partial_run_event["event"] = "seed_collector_run_in_progress"
            _write_runtime_summary(config.output_dir, partial_run_event)
            if result.get("decision") == "seed_scan_queue_empty":
                break
            if (
                result.get("decision") == "seed_page_retryable_failure"
                and result.get("reason") == "list_challenge_page"
            ):
                break
            if result.get("decision") == "seed_collection_paused":
                break
        run_event = _seed_run_progress_event(runs, run_results)
        cycle_summaries.append(dict(run_event.get("cycle_summary") or {}))
        emit_progress(run_event)
        _write_runtime_summary(config.output_dir, run_event)
        if config.max_runs is not None and runs >= config.max_runs:
            break
        sleep_seconds = _seed_loop_sleep_seconds(config, run_results)
        emit_progress(
            {
                "event": "seed_collector_sleep",
                "run": runs,
                "sleep_seconds": sleep_seconds,
                "counts": run_event.get("counts"),
            }
        )
        time.sleep(sleep_seconds)
    summary = {
        "decision": "seed_collector_loop_finished",
        "runs": runs,
        "pages_attempted": pages_attempted,
        "pages_per_run": max(int(config.pages_per_run or 1), 1),
        "last_decision": results[-1].get("decision") if results else None,
        "last_cycle_summary": cycle_summaries[-1] if cycle_summaries else {},
        "cycle_summaries": cycle_summaries[-20:],
        "results": results[-20:],
        "counts": repository.seed_queue_counts(),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


def config_from_env_and_args(argv: Sequence[str] | None = None) -> tuple[SeedCollectorConfig, bool]:
    loop_interval_default = _safe_non_negative_int(os.getenv("FAPAI_SEED_LOOP_INTERVAL_SECONDS"), 1800)
    active_loop_interval_default = _safe_non_negative_int(
        os.getenv("FAPAI_SEED_ACTIVE_LOOP_INTERVAL_SECONDS"),
        loop_interval_default,
    )
    auth_probe_interval_default = _safe_non_negative_int(
        os.getenv("FAPAI_SEED_AUTH_PROBE_INTERVAL_SECONDS"),
        DEFAULT_AUTH_PROBE_INTERVAL_SECONDS,
    )
    parser = argparse.ArgumentParser(description="DB backed seed URL collector for Taobao legal auction pages.")
    parser.add_argument("--job-key", default=os.getenv("FAPAI_SEED_JOB_KEY", DEFAULT_SEED_JOB_KEY))
    parser.add_argument("--province", default=os.getenv("FAPAI_SEED_PROVINCE", "广东省"))
    parser.add_argument("--city", default=os.getenv("FAPAI_SEED_CITY", "广州市"))
    parser.add_argument("--district", default=os.getenv("FAPAI_SEED_DISTRICT", "南沙区"))
    parser.add_argument("--location-code", default=os.getenv("FAPAI_SEED_LOCATION_CODE", DEFAULT_SEED_LOCATION_CODE))
    parser.add_argument("--category", default=os.getenv("FAPAI_SEED_CATEGORY", DEFAULT_SEED_CATEGORY))
    parser.add_argument("--sorts", default=os.getenv("FAPAI_SEED_SORTS", DEFAULT_SEED_SORTS))
    parser.add_argument("--max-page", type=int, default=_safe_int(os.getenv("FAPAI_SEED_MAX_PAGE"), 83))
    parser.add_argument("--cdp-endpoint", default=os.getenv("FAPAI_CDP_ENDPOINT", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("FAPAI_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR / "seed_collector"))))
    parser.add_argument("--worker-id", default=os.getenv("FAPAI_SEED_WORKER_ID", f"seed-{os.getpid()}"))
    parser.add_argument("--lease-seconds", type=int, default=_safe_int(os.getenv("FAPAI_SEED_LEASE_SECONDS"), 120))
    parser.add_argument("--loop", action="store_true", default=os.getenv("FAPAI_SEED_LOOP", "").lower() in {"1", "true", "yes", "on"})
    parser.add_argument("--loop-interval-seconds", type=int, default=loop_interval_default)
    parser.add_argument("--active-loop-interval-seconds", type=int, default=active_loop_interval_default)
    parser.add_argument("--auth-probe-interval-seconds", type=int, default=auth_probe_interval_default)
    parser.add_argument("--pages-per-run", type=int, default=_safe_int(os.getenv("FAPAI_SEED_PAGES_PER_RUN"), 10))
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--api-base-url", default=os.getenv("FAPAI_API_BASE_URL", ""))
    parser.add_argument("--jobs-file", default=os.getenv("FAPAI_SEED_JOBS_FILE", ""))
    parser.add_argument("--jobs-json", default=os.getenv("FAPAI_SEED_JOBS_JSON", ""))
    parser.add_argument(
        "--failure-cooldown-threshold",
        type=int,
        default=_safe_non_negative_int(os.getenv("FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD"), 0),
    )
    parser.add_argument(
        "--failure-cooldown-seconds",
        type=int,
        default=_safe_non_negative_int(os.getenv("FAPAI_SEED_FAILURE_COOLDOWN_SECONDS"), 0),
    )
    parser.add_argument(
        "--parallel-sorts",
        action="store_true",
        default=os.getenv("FAPAI_SEED_PARALLEL_SORTS", "").lower() in {"1", "true", "yes", "on"},
    )
    parser.add_argument(
        "--solver-enabled",
        "--captcha-solver-enabled",
        action="store_true",
        default=captcha_solver_enabled(default=False),
        help="Report Taobao list challenge pages to the configured captcha solver queue.",
    )
    parser.add_argument(
        "--manual-challenge-reporting",
        action="store_true",
        default=os.getenv("FAPAI_MANUAL_CHALLENGE_REPORTING", "").lower() in {"1", "true", "yes", "on"},
        help="Pause collection and request PC1 manual authentication without starting the automatic solver.",
    )
    args = parser.parse_args(argv)
    if args.max_runs is None and os.getenv("FAPAI_SEED_MAX_RUNS"):
        args.max_runs = _safe_int(os.getenv("FAPAI_SEED_MAX_RUNS"), 1)
    sort_specs = parse_seed_sort_specs(args.sorts)
    max_page = max(int(args.max_page), 1)
    jobs_source = ""
    if _clean_text(args.jobs_file):
        jobs_source = Path(args.jobs_file).read_text(encoding="utf-8")
    elif _clean_text(args.jobs_json):
        jobs_source = str(args.jobs_json)
    seed_jobs = parse_seed_job_specs(
        jobs_source,
        fallback_sort_specs=sort_specs,
        fallback_max_page=max_page,
    )

    return (
        SeedCollectorConfig(
            job_key=_clean_text(args.job_key, DEFAULT_SEED_JOB_KEY),
            province=_clean_text(args.province),
            city=_clean_text(args.city),
            district=_clean_text(args.district),
            location_code=_clean_text(args.location_code, DEFAULT_SEED_LOCATION_CODE),
            category=_clean_text(args.category, DEFAULT_SEED_CATEGORY),
            sort_specs=sort_specs,
            max_page=max_page,
            cdp_endpoint=_clean_text(args.cdp_endpoint, DEFAULT_CDP_ENDPOINT),
            output_dir=args.output_dir,
            worker_id=_clean_text(args.worker_id, f"seed-{os.getpid()}"),
            lease_seconds=max(int(args.lease_seconds), 1),
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            active_loop_interval_seconds=max(int(args.active_loop_interval_seconds), 0),
            auth_probe_interval_seconds=max(int(args.auth_probe_interval_seconds), 0),
            max_runs=args.max_runs,
            pages_per_run=max(int(args.pages_per_run), 1),
            solver_enabled=bool(args.solver_enabled),
            manual_challenge_reporting=bool(args.manual_challenge_reporting),
            api_base_url=_clean_text(args.api_base_url),
            seed_jobs=seed_jobs,
            parallel_sorts=bool(args.parallel_sorts),
            failure_cooldown_threshold=max(int(args.failure_cooldown_threshold), 0),
            failure_cooldown_seconds=max(int(args.failure_cooldown_seconds), 0),
        ),
        bool(args.loop),
    )


def main(argv: Sequence[str] | None = None) -> int:
    config, loop = config_from_env_and_args(argv)
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for seed-collector mode")
    from tools import browserless_seed_probe

    if loop:
        summary = run_seed_collector_loop(
            config,
            repository=repository,
            browserless_seed_probe=browserless_seed_probe,
            runtime_context_factory=lambda: _build_runtime_context(config),
        )
    else:
        http_session = _build_runtime_context(config)
        summary = run_seed_collector_once(
            config,
            repository=repository,
            http_session=http_session,
            browserless_seed_probe=browserless_seed_probe,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
