from __future__ import annotations

import argparse
import json
import os
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
from tools.live_batch_smoke import (
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    LiveSmokeConfig,
    analyze_raw_item,
    build_http,
    captcha_solver_enabled,
    export_cookies,
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
    loop_interval_seconds: int = 900
    active_loop_interval_seconds: int | None = None
    max_runs: int | None = None
    llm_preflight_enabled: bool = False
    llm_preflight_timeout_seconds: float = 15.0
    solver_enabled: bool = False
    api_base_url: str = ""
    raw_only: bool = False
    analysis_only: bool = False


ProcessItemFunc = Callable[[Any, dict[str, Any], dict[str, tuple[str, str]], Any], dict[str, Any]]
AnalyzeItemFunc = Callable[..., dict[str, Any]]
RuntimeContext = tuple[Any, dict[str, tuple[str, str]]]
RuntimeContextFactory = Callable[[], RuntimeContext]
ProgressEmitFunc = Callable[[dict[str, Any]], None]
STATUS_UNAVAILABLE_RETRY_ATTEMPTS = 3
STATUS_UNAVAILABLE_RETRY_SLEEP_SECONDS = 1.0


def _llm_preflight_is_unavailable(preflight: dict[str, Any] | None) -> bool:
    if not preflight or not preflight.get("enabled"):
        return False
    status_code = preflight.get("status_code")
    chat_status_code = preflight.get("chat_status_code")
    if isinstance(chat_status_code, int) and chat_status_code < 400:
        return False
    if isinstance(chat_status_code, int) and chat_status_code >= 400:
        return True
    if isinstance(status_code, int) and status_code >= 400:
        return True
    return False


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
        with urlopen(endpoint, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"paused": False, "reason": "status_unavailable", "error": repr(exc)}

    if not isinstance(payload, dict):
        return {"paused": False, "reason": "status_unavailable", "error": "non_object_status"}

    captcha_solver = payload.get("captcha_solver")
    if not isinstance(captcha_solver, dict):
        captcha_solver = {}
    manual_required = bool(captcha_solver.get("manual_required"))
    paused = bool(payload.get("paused")) or manual_required
    reason = "captcha_solver_manual_required" if manual_required else "collection_paused" if paused else None
    return {
        "paused": paused,
        "reason": reason,
        "captcha_solver": captcha_solver,
    }


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


def _report_captcha_solver(api_base_url: str, cdp_endpoint: str, target_url: str) -> dict[str, Any]:
    from tools.taobao_login_health import build_captcha_solver_target_url, report_captcha_via_api

    return dict(
        report_captcha_via_api(
            api_base_url,
            cdp_endpoint,
            build_captcha_solver_target_url(target_url),
        )
    )


def _build_runtime_context(config: DetailWorkerConfig) -> RuntimeContext:
    cookies = export_cookies(config.cdp_endpoint)
    return build_http(cookies), load_open_browser_pages(config.cdp_endpoint)


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
    if pause_state.get("paused"):
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
    try:
        selected = process_item_func(
            http_session,
            seed,
            browser_pages,
            config=_live_config(config, target_url=str(seed.get("source_page_url") or seed.get("url") or "")),
        )
        final_json_path = config.output_dir / item_id / "final.json"
        selected_json_path = config.output_dir / item_id / "selected.json"
        if config.raw_only:
            detail_html_path = config.output_dir / item_id / "detail.html"
            description_json_path = config.output_dir / item_id / "description-data.json"
            repository.mark_seed_raw_detail_captured(
                item_id,
                detail_html_path=str(detail_html_path),
                description_json_path=str(description_json_path),
                selected_json_path=str(selected_json_path),
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
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        is_challenge_error = _is_detail_challenge_error(exc)
        captcha_solver_report: dict[str, Any] | None = None
        if is_challenge_error and config.solver_enabled and str(config.api_base_url or "").strip():
            try:
                captcha_solver_report = _report_captcha_solver(
                    config.api_base_url,
                    config.cdp_endpoint,
                    str(seed.get("url") or seed.get("source_page_url") or ""),
                )
            except Exception as solver_exc:
                captcha_solver_report = {"status": "report_failed", "error": repr(solver_exc)}
        repository.mark_seed_detail_failed(item_id, repr(exc), retryable=True)
        summary = {
            "decision": "detail_item_retryable_failure",
            "reason": "detail_challenge_page" if is_challenge_error else "exception",
            "item_id": item_id,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "counts": repository.seed_queue_counts(),
        }
        if captcha_solver_report is not None:
            summary["captcha_solver_report"] = captcha_solver_report
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
        try:
            preflight = preflight_llm_backend(timeout=config.llm_preflight_timeout_seconds, check_chat=True)
        except Exception as exc:
            preflight = {
                "enabled": True,
                "error": repr(exc),
            }
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
        if result.get("decision") in {"detail_item_completed", "detail_item_raw_captured", "detail_analysis_completed"}:
            completed += 1
        if (
            config.solver_enabled
            and result.get("decision") == "detail_item_retryable_failure"
            and result.get("reason") == "detail_challenge_page"
        ):
            break
        time.sleep(1)
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
        return max(int(interval), 0)
    return max(config.loop_interval_seconds, 0)


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
        "--solver-enabled",
        "--captcha-solver-enabled",
        action="store_true",
        default=captcha_solver_enabled(default=False),
        help="Report Taobao detail challenge pages to the configured captcha solver queue.",
    )
    parser.add_argument(
        "--llm-preflight-timeout-seconds",
        type=float,
        default=_safe_float(os.getenv("FAPAI_LLM_PREFLIGHT_TIMEOUT_SECONDS"), 15.0),
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
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            active_loop_interval_seconds=max(int(args.active_loop_interval_seconds), 0),
            max_runs=args.max_runs,
            llm_preflight_enabled=bool(args.llm_preflight),
            llm_preflight_timeout_seconds=max(float(args.llm_preflight_timeout_seconds), 1.0),
            solver_enabled=bool(args.solver_enabled),
            api_base_url=_clean_text(args.api_base_url),
            raw_only=False if analysis_only else bool(args.raw_only),
            analysis_only=analysis_only,
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
