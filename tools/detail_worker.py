from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.storage.repository import PropertyRepository, create_repository_from_env
from tools.live_batch_smoke import (
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    LiveSmokeConfig,
    build_http,
    export_cookies,
    fetch_open_browser_pages,
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
    loop_interval_seconds: int = 900
    max_runs: int | None = None
    llm_preflight_enabled: bool = False
    llm_preflight_timeout_seconds: float = 15.0


ProcessItemFunc = Callable[[Any, dict[str, Any], dict[str, tuple[str, str]], Any], dict[str, Any]]
RuntimeContext = tuple[Any, dict[str, tuple[str, str]]]
RuntimeContextFactory = Callable[[], RuntimeContext]
ProgressEmitFunc = Callable[[dict[str, Any]], None]


def _llm_preflight_is_unavailable(preflight: dict[str, Any] | None) -> bool:
    if not preflight or not preflight.get("enabled"):
        return False
    status_code = preflight.get("status_code")
    chat_status_code = preflight.get("chat_status_code")
    if isinstance(status_code, int) and status_code >= 500:
        return True
    if isinstance(chat_status_code, int) and chat_status_code >= 500:
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
    )


def _write_runtime_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "detail_worker_summary.json", summary)


def _build_runtime_context(config: DetailWorkerConfig) -> RuntimeContext:
    cookies = export_cookies(config.cdp_endpoint)
    return build_http(cookies), fetch_open_browser_pages(config.cdp_endpoint)


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
    seed = repository.claim_seed_detail_item(
        config.worker_id,
        lease_seconds=config.lease_seconds,
        exclude_item_ids=exclude_item_ids,
        max_item_attempts=config.item_max_attempts,
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
        repository.mark_seed_detail_failed(item_id, repr(exc), retryable=True)
        summary = {
            "decision": "detail_item_retryable_failure",
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
) -> dict[str, Any]:
    if config.llm_preflight_enabled:
        preflight = preflight_llm_backend(timeout=config.llm_preflight_timeout_seconds, check_chat=True)
    else:
        preflight = None
    if _llm_preflight_is_unavailable(preflight):
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
        if result.get("decision") == "detail_queue_empty":
            break
        if result.get("decision") == "detail_item_completed":
            completed += 1
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
    runs = 0
    while True:
        runs += 1
        try:
            current_http_session, current_browser_pages = runtime_context_factory()
        except Exception as exc:
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
        sleep_seconds = max(config.loop_interval_seconds, 0)
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
    parser = argparse.ArgumentParser(description="DB backed detail worker for legal auction seed URLs.")
    parser.add_argument("--output-dir", type=Path, default=Path(os.getenv("FAPAI_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR / "detail_worker"))))
    parser.add_argument("--cdp-endpoint", default=os.getenv("FAPAI_CDP_ENDPOINT", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--target-success", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_TARGET_SUCCESS"), 5))
    parser.add_argument("--max-attempts", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_MAX_ATTEMPTS"), 20))
    parser.add_argument("--item-max-attempts", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_ITEM_MAX_ATTEMPTS"), 3))
    parser.add_argument("--worker-id", default=os.getenv("FAPAI_DETAIL_WORKER_ID", f"detail-{os.getpid()}"))
    parser.add_argument("--lease-seconds", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_LEASE_SECONDS"), 900))
    parser.add_argument("--loop", action="store_true", default=_env_flag("FAPAI_DETAIL_LOOP", False))
    parser.add_argument("--loop-interval-seconds", type=int, default=_safe_int(os.getenv("FAPAI_DETAIL_LOOP_INTERVAL_SECONDS"), 900))
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--risk", action="store_true", default=_env_flag("FAPAI_ENABLE_RISK", False))
    parser.add_argument("--llm-preflight", action="store_true", default=_env_flag("FAPAI_LLM_PREFLIGHT", False))
    parser.add_argument(
        "--llm-preflight-timeout-seconds",
        type=float,
        default=_safe_float(os.getenv("FAPAI_LLM_PREFLIGHT_TIMEOUT_SECONDS"), 15.0),
    )
    args = parser.parse_args(argv)
    if args.max_runs is None and os.getenv("FAPAI_DETAIL_MAX_RUNS"):
        args.max_runs = _safe_int(os.getenv("FAPAI_DETAIL_MAX_RUNS"), 1)
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
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            max_runs=args.max_runs,
            llm_preflight_enabled=bool(args.llm_preflight),
            llm_preflight_timeout_seconds=max(float(args.llm_preflight_timeout_seconds), 1.0),
        ),
        bool(args.loop),
    )


def main(argv: Sequence[str] | None = None) -> int:
    config, loop = config_from_env_and_args(argv)
    if not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_BASE_URL/OPENAI_API_KEY must be set for detail-worker mode")
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for detail-worker mode")

    if loop:
        summary = run_detail_worker_loop(
            config,
            repository=repository,
            runtime_context_factory=lambda: _build_runtime_context(config),
        )
    else:
        http_session, browser_pages = _build_runtime_context(config)
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
