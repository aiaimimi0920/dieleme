from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.storage.repository import PropertyRepository, create_repository_from_env
from tools.internal_api_http import fetch_json
from tools.live_batch_smoke import (
    CdpEndpointUnavailableError,
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    LiveSmokeConfig,
    analyze_raw_item,
    build_http,
    captcha_solver_enabled,
    export_cookies,
    is_challenge_page,
    load_open_browser_pages,
    load_json,
    preflight_llm_backend,
    process_item,
    write_json,
)


@dataclass(frozen=True)
class DetailWorkerConfig:
    output_dir: Path
    cdp_endpoint: str
    target_success: int
    max_attempts: int
    worker_id: str
    do_risk: bool
    lease_seconds: int = 900
    item_max_attempts: int = 3
    failure_cooldown_seconds: int = 0
    success_delay_seconds: float = 0.0
    failure_delay_seconds: float = 1.0
    loop_interval_seconds: int = 900
    active_loop_interval_seconds: int | None = None
    max_runs: int | None = None
    llm_preflight_enabled: bool = False
    llm_preflight_timeout_seconds: float = 15.0
    llm_preflight_attempts: int = 3
    llm_preflight_retry_delay_seconds: float = 2.0
    solver_enabled: bool = False
    api_base_url: str = ""
    raw_only: bool = False
    analysis_only: bool = False
    manual_challenge_reporting: bool = False
    detail_archive_root: Path | None = None


ProcessItemFunc = Callable[[Any, dict[str, Any], dict[str, tuple[str, str]], Any], dict[str, Any]]
AnalyzeItemFunc = Callable[..., dict[str, Any]]
RuntimeContext = tuple[Any, dict[str, tuple[str, str]]]
RuntimeContextFactory = Callable[[], RuntimeContext]
ProgressEmitFunc = Callable[[dict[str, Any]], None]
STATUS_UNAVAILABLE_RETRY_ATTEMPTS = 3
STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS = 1.0
DETAIL_ITEM_ID_RE = re.compile(r"/sf_item/(\d+)\.htm", re.IGNORECASE)


def _llm_preflight_is_unavailable(preflight: dict[str, Any] | None) -> bool:
    if not preflight or not preflight.get("enabled"):
        return False
    status_code = preflight.get("status_code")
    chat_status_code = preflight.get("chat_status_code")
    if status_code == 0 or chat_status_code == 0:
        return True
    if isinstance(chat_status_code, int) and chat_status_code < 400:
        return False
    if isinstance(chat_status_code, int) and chat_status_code >= 400:
        return True
    if isinstance(status_code, int) and status_code >= 400:
        return True
    return False


def _llm_preflight_is_retryable(preflight: dict[str, Any] | None) -> bool:
    if not preflight or not preflight.get("enabled"):
        return False
    if preflight.get("error"):
        return True
    chat_status_code = preflight.get("chat_status_code")
    status_code = preflight.get("status_code")
    probe_status = chat_status_code if isinstance(chat_status_code, int) else status_code
    return isinstance(probe_status, int) and (
        probe_status == 0 or probe_status in {408, 425, 429} or probe_status >= 500
    )


def _run_llm_preflight(config: DetailWorkerConfig) -> dict[str, Any] | None:
    max_attempts = max(int(config.llm_preflight_attempts), 1)
    retry_delay_seconds = max(float(config.llm_preflight_retry_delay_seconds), 0.0)
    for attempt in range(1, max_attempts + 1):
        try:
            preflight = preflight_llm_backend(
                timeout=config.llm_preflight_timeout_seconds,
                check_chat=True,
            )
        except Exception as exc:
            preflight = {
                "enabled": True,
                "error": repr(exc),
            }
        if preflight is None:
            return None
        preflight = dict(preflight)
        preflight["attempt"] = attempt
        preflight["max_attempts"] = max_attempts
        unavailable = _llm_preflight_is_unavailable(preflight) or bool(preflight.get("error"))
        if not unavailable:
            return preflight
        if attempt >= max_attempts or not _llm_preflight_is_retryable(preflight):
            return preflight
        time.sleep(retry_delay_seconds * attempt)
    return None


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


def _safe_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _safe_non_negative_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _live_config(config: DetailWorkerConfig, *, target_url: str) -> LiveSmokeConfig:
    return LiveSmokeConfig(
        output_dir=config.output_dir,
        cdp_endpoint=config.cdp_endpoint,
        target_url=target_url,
        target_success=config.target_success,
        max_attempts=config.max_attempts,
        do_risk=config.do_risk,
        resume_enabled=False,
        llm_preflight_enabled=False,
        raw_only=config.raw_only,
    )


def _write_runtime_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "detail_worker_summary.json", summary)


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

    return _normalize_collection_pause_state(payload, scope="detail")


def _normalize_collection_pause_state(payload: dict[str, Any], scope: str = "detail") -> dict[str, Any]:
    captcha_solver = payload.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        captcha_solver = {}
    scope_statuses = payload.get("collection_scopes")
    if not isinstance(scope_statuses, dict):
        scope_statuses = captcha_solver.get("collection_scopes")
    if not isinstance(scope_statuses, dict):
        scope_statuses = captcha_solver.get("scopes")
    scoped = scope_statuses.get(scope) if isinstance(scope_statuses, dict) else None
    if isinstance(scoped, dict):
        scoped_solver = dict(captcha_solver)
        scoped_solver.update(scoped)
        scoped_solver["last_request"] = scoped.get("last_request") or captcha_solver.get("last_request") or {}
        scoped_solver["running"] = bool(scoped.get("last_status") == "running")
        scoped_solver["paused"] = bool(scoped.get("paused"))
        scoped_solver["manual_required"] = bool(scoped.get("manual_required"))
        scoped_solver["force_unlock_flag_exists"] = False
        return {
            "paused": bool(scoped.get("paused") or scoped.get("manual_required")),
            "reason": "captcha_solver_manual_required" if scoped.get("manual_required") else "captcha_solver_running" if scoped.get("paused") else None,
            "captcha_solver": scoped_solver,
            "scope": scope,
        }
    manual_required = bool(captcha_solver.get("manual_required"))
    solver_running_for_current_node = _captcha_solver_targets_current_node(captcha_solver)
    solver_running_only = (
        bool(payload.get("paused"))
        and bool(captcha_solver.get("running"))
        and bool(captcha_solver.get("paused"))
        and not manual_required
    )
    paused = bool(payload.get("paused")) or manual_required or solver_running_for_current_node
    if solver_running_only and not solver_running_for_current_node:
        paused = False
    reason = "captcha_solver_manual_required" if manual_required else "collection_paused" if paused else None
    if solver_running_for_current_node and not manual_required:
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


def _pause_state_detail_target_item_id(pause_state: dict[str, Any]) -> str | None:
    captcha_solver = pause_state.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        return None
    last_request = captcha_solver.get("last_request")
    if not isinstance(last_request, dict):
        return None
    target_url = str(last_request.get("target_url") or last_request.get("url") or "").strip()
    if not target_url:
        return None
    match = DETAIL_ITEM_ID_RE.search(target_url)
    if match is None:
        return None
    return str(match.group(1) or "").strip() or None


def _pause_state_has_resolved_open_detail_page(
    pause_state: dict[str, Any],
    browser_pages: dict[str, tuple[str, str]],
) -> bool:
    item_id = _pause_state_detail_target_item_id(pause_state)
    if not item_id:
        return False
    browser_page = browser_pages.get(item_id)
    if not browser_page:
        return False
    html, final_url = browser_page
    return bool(html) and not is_challenge_page(str(html), str(final_url))


def _is_detail_challenge_error(exc: BaseException) -> bool:
    text = repr(exc).lower()
    return any(
        marker in text
        for marker in (
            "anti-bot challenge",
            "captcha",
            "punish",
            "x5secdata",
            "rgv587",
            "验证码",
            "security verification",
        )
    )


def _is_transient_dns_error(exc: BaseException) -> bool:
    text = repr(exc).lower()
    return any(
        marker in text
        for marker in (
            "nameresolutionerror",
            "temporary failure in name resolution",
            "failed to resolve",
            "name or service not known",
            "getaddrinfo failed",
            "no address associated with hostname",
            "nodename nor servname provided",
        )
    )


def _is_llm_backend_unavailable_error(exc: BaseException) -> bool:
    from src import llm_helper

    if isinstance(exc, llm_helper.LLMBackendUnavailableError):
        return True
    text = repr(exc).lower()
    return any(
        marker in text
        for marker in (
            "llm backend unavailable",
            "appidnoautherror",
            "empty response from ai",
            "all configured models are disabled",
        )
    )


def _report_captcha_solver(
    api_base_url: str,
    cdp_endpoint: str,
    target_url: str,
    *,
    manual_only: bool = False,
) -> dict[str, Any]:
    from tools.taobao_login_health import build_captcha_solver_target_url, report_captcha_via_api

    normalized_target_url = build_captcha_solver_target_url(target_url)
    report_kwargs: dict[str, Any] = {"scope": "detail"}
    if manual_only:
        report_kwargs["manual_only"] = True
    return dict(report_captcha_via_api(api_base_url, cdp_endpoint, normalized_target_url, **report_kwargs))


def _detail_seed_target_url(seed: dict[str, Any], item_id: str) -> str:
    """Return a canonical detail URL; list provenance must never own detail challenge state."""
    for key in ("url", "source_url"):
        candidate = str(seed.get(key) or "").strip()
        if DETAIL_ITEM_ID_RE.search(candidate):
            return PropertyRepository._seed_item_url(item_id, candidate)
    return PropertyRepository._seed_item_url(item_id)


def _challenge_retry_budget_preserved(*, is_challenge_error: bool, is_transient_dns: bool) -> bool:
    return bool(is_challenge_error or is_transient_dns)


def _captcha_report_suppresses_challenge(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
    status = str(report.get("status") or "").strip().lower()
    return status in {
        "recent_auth_complete",
        "recent_force_reset",
        "stale_auth_report",
        "stale_challenge",
    }


def _detail_challenge_should_break_batch(config: DetailWorkerConfig, result: dict[str, Any]) -> bool:
    if result.get("decision") != "detail_item_retryable_failure":
        return False
    if result.get("reason") == "detail_cdp_unreachable":
        return True
    captcha_solver_report = result.get("captcha_solver_report")
    report_status = (
        str(captcha_solver_report.get("status") or "").strip().lower()
        if isinstance(captcha_solver_report, dict)
        else ""
    )
    # A force reset means "try collection again once", not "hammer the same
    # blocked scope for the whole batch". Keep recent-auth suppression separate:
    # after a real solve, short-lived stale challenge reports may still continue.
    if report_status == "recent_force_reset":
        return True
    if not (config.solver_enabled or config.manual_challenge_reporting):
        return False
    if result.get("reason") != "detail_challenge_page":
        return False
    if isinstance(captcha_solver_report, dict):
        solver_status = str(captcha_solver_report.get("status") or "").strip().lower()
        if solver_status == "already_running" or _captcha_report_suppresses_challenge(
            captcha_solver_report
        ):
            return False
    return True


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_cdp_unreachable_health(config: DetailWorkerConfig, target_url: str) -> dict[str, Any]:
    from tools import taobao_login_health

    effective_target_url = str(target_url or "").strip() or "https://sf.taobao.com/list/50025969__2.htm"
    return {
        "status": taobao_login_health.CDP_UNREACHABLE,
        "cdp_endpoint": config.cdp_endpoint,
        "target_url": effective_target_url,
        "operator_hint": taobao_login_health.build_operator_hint(
            status=taobao_login_health.CDP_UNREACHABLE,
            cdp_endpoint=config.cdp_endpoint,
            check_url=effective_target_url,
        ),
    }


def _build_runtime_context(config: DetailWorkerConfig) -> RuntimeContext:
    cookies = export_cookies(config.cdp_endpoint)
    browser_pages = (
        {}
        if not _env_bool("FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES", True)
        else load_open_browser_pages(config.cdp_endpoint)
    )
    return build_http(cookies), browser_pages


def _emit_progress_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)


def _detail_batch_progress_event(run: int, result: dict[str, Any]) -> dict[str, Any]:
    results = result.get("results") if isinstance(result.get("results"), list) else []
    last_result = results[-1] if results and isinstance(results[-1], dict) else {}
    return {
        "event": "detail_worker_batch",
        "run": run,
        "decision": result.get("decision"),
        "attempts": result.get("attempts"),
        "completed": result.get("completed"),
        "target_success": result.get("target_success"),
        "max_attempts": result.get("max_attempts"),
        "last_result_decision": last_result.get("decision"),
        "last_item_id": last_result.get("item_id"),
        "counts": result.get("counts"),
    }


def _load_final_item(output_dir: Path, item_id: str) -> dict[str, Any] | None:
    path = output_dir / item_id / "final.json"
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _record_analysis_module_b_receipt(
    repository: PropertyRepository,
    *,
    item_id: str,
    receipt: Any,
) -> None:
    if not isinstance(receipt, dict) or not receipt.get("run_id"):
        return
    record_run = getattr(repository, "record_analysis_ensemble_run", None)
    if not callable(record_run):
        return
    try:
        record_run(item_id, receipt)
    except Exception as persistence_error:
        print(
            "[ANALYSIS-MODULE-B] unable to persist run receipt "
            f"for {item_id}: {type(persistence_error).__name__}: {persistence_error}"
        )


def _load_analysis_module_b_latest(output_dir: Path, item_id: str) -> dict[str, Any] | None:
    path = output_dir / item_id / "analysis-b" / "latest.json"
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _copy_raw_artifact(source_value: Any, target_path: Path) -> str | None:
    source_text = str(source_value or "").strip()
    if not source_text:
        return None
    source_path = Path(source_text)
    if not source_path.exists():
        return None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_path.resolve() == target_path.resolve():
            return str(target_path)
    except OSError:
        pass
    shutil.copyfile(source_path, target_path)
    return str(target_path)


def _write_durable_detail_archive(
    *,
    archive_root: Path,
    detail_html_path: Path,
    item_id: str,
    captured_at: datetime.datetime | None = None,
) -> str:
    """把 raw detail HTML 复制到日期分区的持久归档，返回归档路径。

    `output_dir/{item_id}/detail.html` 是分析阶段用的临时工作副本，会被后续任务
    覆盖或清掉；线上 228,959 行的 detail_archive_path 全空、磁盘不留 HTML 就是
    因为生产路径从来没有落过持久副本。抽取逻辑将来改进时，回填需要这份原料。

    路径是确定性的：`{archive_root}/html_archive/{YYYY}/{YYYY-MM-DD}/item-{id}.html`，
    回填工具可以按 item_id 直接 glob，不依赖 DB 里记的路径。
    """
    moment = captured_at or datetime.datetime.now()
    target_dir = archive_root / "html_archive" / moment.strftime("%Y") / moment.strftime("%Y-%m-%d")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"item-{item_id}.html"
    shutil.copyfile(detail_html_path, target_path)
    return str(target_path)


def _archive_raw_detail_if_configured(
    *,
    config: DetailWorkerConfig,
    detail_html_path: Path,
    item_id: str,
) -> str:
    """按配置归档，且不让归档失败影响已经成功的抓取。

    抓取成本远高于归档：抓取成功后因为磁盘满或权限问题把整条判失败，会让 item
    重新排队再抓一次，这比丢一份归档更糟。所以这里吞掉异常只记日志。
    """
    archive_root = config.detail_archive_root
    if archive_root is None:
        return ""
    if not detail_html_path.is_file():
        return ""
    try:
        return _write_durable_detail_archive(
            archive_root=Path(archive_root),
            detail_html_path=detail_html_path,
            item_id=item_id,
        )
    except Exception as archive_error:
        print(f"[DETAIL-ARCHIVE] durable archive failed for {item_id}: {archive_error}")
        return ""


def _stage_raw_detail_artifacts_for_analysis(seed: dict[str, Any], *, output_dir: Path, item_id: str) -> dict[str, Any]:
    item_dir = output_dir / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    seed_payload = dict(seed)
    write_json(item_dir / "seed.json", seed_payload)

    artifacts = seed.get("_raw_detail_artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    staged = {
        "detail_html_path": _copy_raw_artifact(artifacts.get("detail_html_path"), item_dir / "detail.html"),
        "description_json_path": _copy_raw_artifact(artifacts.get("description_json_path"), item_dir / "description-data.json"),
        "selected_json_path": _copy_raw_artifact(artifacts.get("selected_json_path"), item_dir / "selected.json"),
    }
    return {key: value for key, value in staged.items() if value}


def _raw_detail_final_url(selected_json_path: Path) -> str:
    if not selected_json_path.exists():
        return ""
    try:
        selected = load_json(selected_json_path)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(selected, dict):
        return ""
    fetch = selected.get("fetch")
    if not isinstance(fetch, dict):
        return ""
    return str(fetch.get("detail_final_url") or "")


def _assert_raw_detail_artifact_is_not_challenge(*, detail_html_path: Path, selected_json_path: Path) -> None:
    try:
        html = detail_html_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"raw detail artifact missing or unreadable: {detail_html_path}") from exc
    final_url = _raw_detail_final_url(selected_json_path)
    if is_challenge_page(html, final_url):
        raise RuntimeError(f"raw detail artifact returned anti-bot challenge: {final_url}")

def run_detail_worker_once(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browser_pages: dict[str, tuple[str, str]],
    process_item_func: Callable[..., dict[str, Any]] = process_item,
    exclude_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    pause_state = _collection_pause_state_with_retry(config.api_base_url)
    pause_override = False
    if pause_state.get("paused"):
        if _pause_state_has_resolved_open_detail_page(pause_state, browser_pages):
            pause_override = True
        else:
            summary = {
                "decision": "detail_collection_paused",
                "reason": pause_state.get("reason") or "collection_paused",
                "captcha_solver": pause_state.get("captcha_solver") or {},
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary

    seed = repository.claim_seed_detail_item(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        exclude_item_ids=exclude_item_ids,
        max_item_attempts=config.item_max_attempts,
        failure_cooldown_seconds=config.failure_cooldown_seconds,
    )
    if seed is None:
        summary = {"decision": "detail_queue_empty"}
        _write_runtime_summary(config.output_dir, summary)
        return summary

    item_id = str(seed.get("id") or seed.get("item_id") or seed.get("source_item_id"))
    detail_target_url = _detail_seed_target_url(seed, item_id)
    try:
        selected = process_item_func(
            http_session,
            seed,
            browser_pages,
            config=_live_config(config, target_url=detail_target_url),
        )
        final_json_path = config.output_dir / item_id / "final.json"
        selected_json_path = config.output_dir / item_id / "selected.json"
        if config.raw_only:
            detail_html_path = config.output_dir / item_id / "detail.html"
            description_json_path = config.output_dir / item_id / "description-data.json"
            _assert_raw_detail_artifact_is_not_challenge(
                detail_html_path=detail_html_path,
                selected_json_path=selected_json_path,
            )
            repository.mark_seed_raw_detail_captured(
                item_id,
                detail_html_path=str(detail_html_path),
                description_json_path=str(description_json_path),
                selected_json_path=str(selected_json_path),
            )
            archived_path = _archive_raw_detail_if_configured(
                config=config,
                detail_html_path=detail_html_path,
                item_id=item_id,
            )
            summary = {
                "decision": "detail_item_raw_captured",
                "item_id": item_id,
                "selected": selected,
                "detail_html_path": str(detail_html_path),
                "description_json_path": str(description_json_path),
                "selected_json_path": str(selected_json_path),
                "counts": repository.seed_queue_counts(),
            }
            if archived_path:
                summary["detail_archive_path"] = archived_path
            if pause_override:
                summary["pause_override"] = "resolved_open_detail_page"
            _write_runtime_summary(config.output_dir, summary)
            return summary
        final_item = _load_final_item(config.output_dir, item_id)
        if final_item is not None:
            repository.upsert_flat_item(
                final_item,
                event_type="detail_worker_completed",
                event_payload={
                    "source": "detail_worker",
                    "item_id": item_id,
                    "seed_url": seed.get("url"),
                    "source_page_url": seed.get("source_page_url"),
                    "final_json_path": str(final_json_path),
                    "selected_json_path": str(selected_json_path),
                },
            )
        repository.mark_seed_detail_completed(
            item_id,
            final_json_path=str(final_json_path),
            selected_json_path=str(selected_json_path),
        )
        summary = {
            "decision": "detail_item_completed",
            "item_id": item_id,
            "selected": selected,
            "final_json_path": str(final_json_path),
            "selected_json_path": str(selected_json_path),
            "counts": repository.seed_queue_counts(),
        }
        if pause_override:
            summary["pause_override"] = "resolved_open_detail_page"
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        is_challenge_error = _is_detail_challenge_error(exc)
        is_transient_dns = _is_transient_dns_error(exc)
        is_cdp_unreachable = isinstance(exc, CdpEndpointUnavailableError)
        preserve_retry_budget = _challenge_retry_budget_preserved(
            is_challenge_error=is_challenge_error,
            is_transient_dns=is_transient_dns,
        ) or is_cdp_unreachable
        captcha_solver_report: dict[str, Any] | None = None
        if (
            is_challenge_error
            and (config.solver_enabled or config.manual_challenge_reporting)
            and str(config.api_base_url or "").strip()
        ):
            try:
                report_args = (
                    config.api_base_url,
                    config.cdp_endpoint,
                    detail_target_url,
                )
                if config.solver_enabled:
                    captcha_solver_report = _report_captcha_solver(*report_args)
                else:
                    captcha_solver_report = _report_captcha_solver(*report_args, manual_only=True)
            except Exception as solver_exc:
                captcha_solver_report = {"status": "report_failed", "error": repr(solver_exc)}
        repository.mark_seed_detail_failed(
            item_id,
            repr(exc),
            retryable=True,
            revert_attempt=preserve_retry_budget,
            restore_pending=preserve_retry_budget,
        )
        stale_challenge_suppressed = bool(
            is_challenge_error and _captcha_report_suppresses_challenge(captcha_solver_report)
        )
        summary = {
            "decision": "detail_item_retryable_failure",
            "reason": (
                "detail_stale_challenge_ignored"
                if stale_challenge_suppressed
                else "detail_challenge_page"
                if is_challenge_error
                else "transient_dns_error"
                if is_transient_dns
                else "detail_cdp_unreachable"
                if is_cdp_unreachable
                else "exception"
            ),
            "item_id": item_id,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "counts": repository.seed_queue_counts(),
        }
        if pause_override:
            summary["pause_override"] = "resolved_open_detail_page"
        if preserve_retry_budget:
            summary["retry_budget_preserved"] = True
        if is_cdp_unreachable:
            summary["cdp_health"] = _build_cdp_unreachable_health(
                config,
                detail_target_url,
            )
        if captcha_solver_report is not None:
            summary["captcha_solver_report"] = captcha_solver_report
        if stale_challenge_suppressed:
            summary["challenge_suppressed"] = True
        _write_runtime_summary(config.output_dir, summary)
        return summary


def run_detail_analysis_once(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    analyze_item_func: AnalyzeItemFunc = analyze_raw_item,
    exclude_item_ids: set[str] | None = None,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    seed = repository.claim_seed_raw_detail_item(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        exclude_item_ids=exclude_item_ids,
        max_analysis_attempts=config.item_max_attempts,
    )
    if seed is None:
        summary = {"decision": "detail_analysis_queue_empty"}
        _write_runtime_summary(config.output_dir, summary)
        return summary

    item_id = str(seed.get("id") or seed.get("item_id") or seed.get("source_item_id"))
    try:
        staged_artifacts = _stage_raw_detail_artifacts_for_analysis(seed, output_dir=config.output_dir, item_id=item_id)
        selected = analyze_item_func(item_id, output_dir=config.output_dir, do_risk=config.do_risk)
        module_b_receipt = selected.get("analysis_module_b") if isinstance(selected, dict) else None
        _record_analysis_module_b_receipt(repository, item_id=item_id, receipt=module_b_receipt)
        final_json_path = config.output_dir / item_id / "final.json"
        selected_json_path = config.output_dir / item_id / "selected.json"
        final_item = _load_final_item(config.output_dir, item_id)
        if final_item is not None:
            repository.upsert_flat_item(
                final_item,
                event_type="detail_analysis_completed",
                event_payload={
                    "source": "detail_analysis_worker",
                    "item_id": item_id,
                    "final_json_path": str(final_json_path),
                    "selected_json_path": str(selected_json_path),
                    "raw_artifacts": seed.get("_raw_detail_artifacts"),
                    "analysis_module_b": module_b_receipt,
                },
            )
        repository.mark_seed_detail_completed(
            item_id,
            final_json_path=str(final_json_path),
            selected_json_path=str(selected_json_path),
        )
        summary = {
            "decision": "detail_analysis_completed",
            "item_id": item_id,
            "selected": selected,
            "final_json_path": str(final_json_path),
            "selected_json_path": str(selected_json_path),
            "staged_raw_artifacts": staged_artifacts,
            "counts": repository.seed_queue_counts(),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        _record_analysis_module_b_receipt(
            repository,
            item_id=item_id,
            receipt=_load_analysis_module_b_latest(config.output_dir, item_id),
        )
        if _is_llm_backend_unavailable_error(exc):
            repository.mark_seed_detail_analysis_failed(
                item_id,
                repr(exc),
                retryable=True,
                revert_attempt=True,
                restore_raw=True,
            )
            summary = {
                "decision": "detail_analysis_backend_unavailable",
                "item_id": item_id,
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "counts": repository.seed_queue_counts(),
            }
            _write_runtime_summary(config.output_dir, summary)
            return summary
        repository.mark_seed_detail_analysis_failed(item_id, repr(exc), retryable=True)
        summary = {
            "decision": "detail_analysis_retryable_failure",
            "item_id": item_id,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "counts": repository.seed_queue_counts(),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary


def run_detail_worker_batch(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browser_pages: dict[str, tuple[str, str]],
    process_item_func: Callable[..., dict[str, Any]] = process_item,
    analyze_item_func: AnalyzeItemFunc = analyze_raw_item,
) -> dict[str, Any]:
    if config.llm_preflight_enabled and not config.raw_only:
        preflight = _run_llm_preflight(config)
    else:
        preflight = None
    if _llm_preflight_is_unavailable(preflight) or (preflight and preflight.get("error")):
        summary = {
            "decision": "detail_worker_llm_unavailable",
            "attempts": 0,
            "completed": 0,
            "target_success": config.target_success,
            "max_attempts": config.max_attempts,
            "llm_preflight": preflight,
            "results": [],
            "counts": repository.seed_queue_counts(),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary
    results: list[dict[str, Any]] = []
    attempted_item_ids: set[str] = set()
    completed = 0
    attempts = 0
    while attempts < config.max_attempts and completed < config.target_success:
        attempts += 1
        if config.analysis_only:
            result = run_detail_analysis_once(
                config,
                repository=repository,
                analyze_item_func=analyze_item_func,
                exclude_item_ids=attempted_item_ids,
            )
        else:
            result = run_detail_worker_once(
                config,
                repository=repository,
                http_session=http_session,
                browser_pages=browser_pages,
                process_item_func=process_item_func,
                exclude_item_ids=attempted_item_ids,
            )
        results.append(result)
        item_id = result.get("item_id")
        if item_id:
            attempted_item_ids.add(str(item_id))
        if result.get("decision") in {"detail_queue_empty", "detail_analysis_queue_empty"}:
            break
        item_completed = result.get("decision") in {
            "detail_item_completed",
            "detail_item_raw_captured",
            "detail_analysis_completed",
        }
        if item_completed:
            completed += 1
        if result.get("decision") == "detail_analysis_backend_unavailable":
            break
        if _detail_challenge_should_break_batch(config, result):
            break
        if attempts < config.max_attempts and completed < config.target_success:
            delay_seconds = config.success_delay_seconds if item_completed else config.failure_delay_seconds
            if delay_seconds > 0:
                time.sleep(delay_seconds)
    summary = {
        "decision": "detail_worker_batch_finished",
        "attempts": attempts,
        "completed": completed,
        "target_success": config.target_success,
        "max_attempts": config.max_attempts,
        "llm_preflight": preflight,
        "results": results,
        "counts": repository.seed_queue_counts(),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


def _detail_batch_sleep_seconds(config: DetailWorkerConfig, result: dict[str, Any]) -> int:
    completed = result.get("completed")
    try:
        completed_count = int(completed)
    except (TypeError, ValueError):
        completed_count = 0
    if completed_count > 0:
        interval = config.active_loop_interval_seconds
        if interval is None:
            interval = config.loop_interval_seconds
        base_sleep = max(int(interval), 0)
    else:
        base_sleep = max(config.loop_interval_seconds, 0)

    force_reset_retry_after = 0
    for item_result in result.get("results") or []:
        if not isinstance(item_result, dict):
            continue
        report = item_result.get("captcha_solver_report")
        if not isinstance(report, dict):
            continue
        if str(report.get("status") or "").strip().lower() != "recent_force_reset":
            continue
        try:
            force_reset_retry_after = max(
                force_reset_retry_after,
                int(math.ceil(max(float(report.get("retry_after_seconds") or 0), 0.0))),
            )
        except (TypeError, ValueError):
            continue
    return max(base_sleep, force_reset_retry_after)


def run_detail_worker_loop(
    config: DetailWorkerConfig,
    *,
    repository: PropertyRepository,
    http_session: Any | None = None,
    browser_pages: dict[str, tuple[str, str]] | None = None,
    runtime_context_factory: RuntimeContextFactory | None = None,
    progress_emit_func: ProgressEmitFunc | None = None,
) -> dict[str, Any]:
    if runtime_context_factory is None:
        if http_session is None or browser_pages is None:
            runtime_context_factory = lambda: _build_runtime_context(config)
        else:
            runtime_context_factory = lambda: (http_session, browser_pages)
    emit_progress = progress_emit_func or _emit_progress_event
    results: list[dict[str, Any]] = []
    last_runtime_context: RuntimeContext | None = None
    runs = 0
    release_worker_leases = getattr(repository, "release_seed_detail_worker_leases", None)
    if callable(release_worker_leases):
        release_summary = release_worker_leases(config.worker_id)
        if int((release_summary or {}).get("released") or 0) > 0:
            release_event = {
                "decision": "detail_worker_leases_released",
                "worker_id": config.worker_id,
                "release_summary": release_summary,
                "counts": repository.seed_queue_counts(),
            }
            emit_progress({"event": "detail_worker_leases_released", **release_event})
            _write_runtime_summary(config.output_dir, release_event)
    while True:
        runs += 1
        try:
            current_http_session, current_browser_pages = runtime_context_factory()
            last_runtime_context = (current_http_session, current_browser_pages)
        except Exception as exc:
            if last_runtime_context is not None:
                current_http_session, current_browser_pages = last_runtime_context
                reuse_event = {
                    "event": "detail_worker_runtime_refresh_reused_last_context",
                    "run": runs,
                    "decision": "detail_runtime_refresh_reused_last_context",
                    "error": repr(exc),
                    "counts": repository.seed_queue_counts(),
                }
                emit_progress(reuse_event)
                _write_runtime_summary(config.output_dir, reuse_event)
            else:
                failure_event = {
                    "event": "detail_worker_runtime_refresh_failed",
                    "run": runs,
                    "decision": "detail_runtime_refresh_failed",
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
                        "event": "detail_worker_sleep",
                        "run": runs,
                        "sleep_seconds": sleep_seconds,
                        "counts": failure_event.get("counts"),
                    }
                )
                time.sleep(sleep_seconds)
                continue
        result = run_detail_worker_batch(
            config,
            repository=repository,
            http_session=current_http_session,
            browser_pages=current_browser_pages,
        )
        results.append(result)
        emit_progress(_detail_batch_progress_event(runs, result))
        if config.max_runs is not None and runs >= config.max_runs:
            break
        sleep_seconds = _detail_batch_sleep_seconds(config, result)
        emit_progress(
            {
                "event": "detail_worker_sleep",
                "run": runs,
                "sleep_seconds": sleep_seconds,
                "counts": result.get("counts"),
            }
        )
        time.sleep(sleep_seconds)
    summary = {
        "decision": "detail_worker_loop_finished",
        "runs": runs,
        "last_decision": results[-1].get("decision") if results else None,
        "results": results[-20:],
        "counts": repository.seed_queue_counts(),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def config_from_env_and_args(argv: Sequence[str] | None = None) -> tuple[DetailWorkerConfig, bool]:
    loop_interval_default = _safe_non_negative_int(os.getenv("FAPAI_DETAIL_LOOP_INTERVAL_SECONDS"), 900)
    active_loop_interval_default = _safe_non_negative_int(
        os.getenv("FAPAI_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS"),
        loop_interval_default,
    )
    parser = argparse.ArgumentParser(description="DB backed detail worker for legal auction seed URLs.")
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("FAPAI_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR / "detail_worker"))))
    parser.add_argument("--cdp-endpoint", default=os.getenv("FAPAI_CDP_ENDPOINT", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--target-success", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_TARGET_SUCCESS"), 5))
    parser.add_argument("--max-attempts", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_MAX_ATTEMPTS"), 20))
    parser.add_argument("--item-max-attempts", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_ITEM_MAX_ATTEMPTS"), 3))
    parser.add_argument(
        "--failure-cooldown-seconds",
        type=int,
        default=_safe_int(os.getenv("FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS"), 0),
        help="Skip recently failed detail items for this many seconds before retrying them.",
    )
    parser.add_argument(
        "--success-delay-seconds",
        type=float,
        default=_safe_non_negative_float(os.getenv("FAPAI_DETAIL_SUCCESS_DELAY_SECONDS"), 0.0),
        help="Delay between successful items in the same batch.",
    )
    parser.add_argument(
        "--failure-delay-seconds",
        type=float,
        default=_safe_non_negative_float(os.getenv("FAPAI_DETAIL_FAILURE_DELAY_SECONDS"), 1.0),
        help="Backoff between failed items in the same batch.",
    )
    parser.add_argument("--worker-id", default=os.getenv("FAPAI_DETAIL_WORKER_ID", f"detail-{os.getpid()}"))
    parser.add_argument("--lease-seconds", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_LEASE_SECONDS"), 900))
    parser.add_argument("--loop", action="store_true", default=_env_flag("FAPAI_DETAIL_LOOP", False))
    parser.add_argument("--loop-interval-seconds", type=int, default=loop_interval_default)
    parser.add_argument("--active-loop-interval-seconds", type=int, default=active_loop_interval_default)
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--risk", action="store_true", default=_env_flag("FAPAI_ENABLE_RISK", False))
    parser.add_argument("--llm-preflight", action="store_true", default=_env_flag("FAPAI_LLM_PREFLIGHT", False))
    parser.add_argument(
        "--raw-only",
        action="store_true",
        default=_env_flag("FAPAI_DETAIL_RAW_ONLY", False),
        help="Archive raw detail artifacts without running AI extraction or finalizing flat items.",
    )
    parser.add_argument(
        "--analysis-only",
        action="store_true",
        default=_env_flag("FAPAI_DETAIL_ANALYSIS_ONLY", False)
        or (os.getenv("FAPAI_RUN_MODE", "").strip().lower() in {"detail-analysis-worker", "detail-analysis-batch"}),
        help="Consume previously captured raw detail artifacts and run only the AI finalization stage.",
    )
    parser.add_argument("--api-base-url", default=os.getenv("FAPAI_API_BASE_URL", ""))
    parser.add_argument(
        "--detail-archive-root",
        type=Path,
        default=(Path(os.environ["FAPAI_DETAIL_ARCHIVE_ROOT"]) if os.getenv("FAPAI_DETAIL_ARCHIVE_ROOT") else None),
        help="raw detail HTML 持久归档根目录；不设则不归档",
    )
    parser.add_argument(
        "--solver-enabled",
        "--captcha-solver-enabled",
        action="store_true",
        default=captcha_solver_enabled(default=False),
        help="Report Taobao detail challenge pages to the configured captcha solver queue.",
    )
    parser.add_argument(
        "--manual-challenge-reporting",
        action="store_true",
        default=_env_flag("FAPAI_MANUAL_CHALLENGE_REPORTING", False),
        help="Pause collection and request PC1 manual authentication without starting the automatic solver.",
    )
    parser.add_argument(
        "--llm-preflight-timeout-seconds",
        type=float,
        default=_safe_float(os.getenv("FAPAI_LLM_PREFLIGHT_TIMEOUT_SECONDS"), 15.0),
    )
    parser.add_argument(
        "--llm-preflight-attempts",
        type=int,
        default=_safe_int(os.getenv("FAPAI_LLM_PREFLIGHT_ATTEMPTS"), 3),
    )
    parser.add_argument(
        "--llm-preflight-retry-delay-seconds",
        type=float,
        default=_safe_non_negative_float(os.getenv("FAPAI_LLM_PREFLIGHT_RETRY_DELAY_SECONDS"), 2.0),
    )
    args = parser.parse_args(argv)
    if args.max_runs is None and os.getenv("FAPAI_DETAIL_MAX_RUNS"):
        args.max_runs = _safe_int(os.getenv("FAPAI_DETAIL_MAX_RUNS"), 1)
    analysis_only = bool(args.analysis_only)
    return (
        DetailWorkerConfig(
            output_dir=args.output_dir,
            cdp_endpoint=_clean_text(args.cdp_endpoint, DEFAULT_CDP_ENDPOINT),
            target_success=max(int(args.target_success), 1),
            max_attempts=max(int(args.max_attempts), 1),
            worker_id=_clean_text(args.worker_id, f"detail-{os.getpid()}"),
            do_risk=bool(args.risk),
            lease_seconds=max(int(args.lease_seconds), 1),
            item_max_attempts=max(int(args.item_max_attempts), 1),
            failure_cooldown_seconds=max(int(args.failure_cooldown_seconds), 0),
            success_delay_seconds=max(float(args.success_delay_seconds), 0.0),
            failure_delay_seconds=max(float(args.failure_delay_seconds), 0.0),
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            active_loop_interval_seconds=max(int(args.active_loop_interval_seconds), 0),
            max_runs=args.max_runs,
            llm_preflight_enabled=bool(args.llm_preflight),
            llm_preflight_timeout_seconds=max(float(args.llm_preflight_timeout_seconds), 1.0),
            llm_preflight_attempts=max(int(args.llm_preflight_attempts), 1),
            llm_preflight_retry_delay_seconds=max(float(args.llm_preflight_retry_delay_seconds), 0.0),
            solver_enabled=bool(args.solver_enabled),
            api_base_url=_clean_text(args.api_base_url),
            raw_only=False if analysis_only else bool(args.raw_only),
            analysis_only=analysis_only,
            manual_challenge_reporting=bool(args.manual_challenge_reporting),
            detail_archive_root=args.detail_archive_root,
        ),
        bool(args.loop),
    )


def main(argv: Sequence[str] | None = None) -> int:
    config, loop = config_from_env_and_args(argv)
    # Allow running without LLM for raw data collection
    # if not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY"):
    #     raise RuntimeError("OPENAI_BASE_URL/OPENAI_API_KEY must be set for detail-worker mode")
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for detail-worker mode")

    if loop:
        summary = run_detail_worker_loop(
            config,
            repository=repository,
            runtime_context_factory=lambda: (None, {}) if config.analysis_only else _build_runtime_context(config),
        )
    else:
        http_session, browser_pages = (None, {}) if config.analysis_only else _build_runtime_context(config)
        summary = run_detail_worker_batch(
            config,
            repository=repository,
            http_session=http_session,
            browser_pages=browser_pages,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
