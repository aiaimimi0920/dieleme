from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.storage.repository import PropertyRepository, create_repository_from_env
from tools.live_batch_smoke import (
    DEFAULT_CDP_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_USER_AGENT,
    build_http,
    export_cookies,
    fetch_list_page,
    write_json,
)


DEFAULT_SEED_SORTS = (
    "bid_desc:2:出价次数由高到低,"
    "end_time_soon:1:结拍时间由近到远,"
    "sort_0:0:排序0,"
    "sort_3:3:排序3,"
    "sort_4:4:排序4,"
    "sort_5:5:排序5"
)
DEFAULT_SEED_JOB_KEY = "guangdong-guangzhou-nansha-50025969"
DEFAULT_SEED_LOCATION_CODE = "440115"
DEFAULT_SEED_CATEGORY = "50025969"


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
    max_runs: int | None = None
    pages_per_run: int = 10


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _safe_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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


def _job_payload(config: SeedCollectorConfig) -> dict[str, Any]:
    return {
        "job_key": config.job_key,
        "province": config.province,
        "city": config.city,
        "district": config.district,
        "location_code": config.location_code,
        "category": config.category,
    }


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


def _write_runtime_summary(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "seed_collector_summary.json", summary)


def run_seed_collector_once(
    config: SeedCollectorConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browserless_seed_probe: Any,
) -> dict[str, Any]:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    repository.ensure_seed_scan_job(
        _job_payload(config),
        sort_specs=[spec.as_dict() for spec in config.sort_specs],
        max_page=config.max_page,
    )
    task = repository.claim_seed_scan_page(config.worker_id, lease_seconds=config.lease_seconds)
    if task is None:
        summary = {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}
        _write_runtime_summary(config.output_dir, summary)
        return summary

    try:
        html, final_url, status_code, fetch_method = fetch_list_page(
            http_session,
            cdp_endpoint=config.cdp_endpoint,
            target_url=str(task["url"]),
            user_agent=getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
        )
        items, list_summary, has_challenge = _extract_seed_items(browserless_seed_probe, html, final_url=final_url)
        if has_challenge:
            repository.fail_seed_scan_page(str(task["progress_key"]), "list_payload_missing", retryable=True)
            summary = {
                "decision": "seed_page_retryable_failure",
                "reason": "list_payload_missing",
                "task": task,
                "list_summary": list_summary,
                "fetch": {
                    "status_code": status_code,
                    "final_url": final_url,
                    "method": fetch_method,
                },
                "counts": repository.seed_queue_counts(),
            }
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
        has_next = bool(items) and int(task["page"]) < int(config.max_page)
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
        _write_runtime_summary(config.output_dir, summary)
        return summary
    except Exception as exc:
        repository.fail_seed_scan_page(str(task["progress_key"]), repr(exc), retryable=True)
        summary = {
            "decision": "seed_page_retryable_failure",
            "reason": "exception",
            "task": task,
            "error": repr(exc),
            "traceback": traceback.format_exc(),
            "counts": repository.seed_queue_counts(),
        }
        _write_runtime_summary(config.output_dir, summary)
        return summary


def run_seed_collector_loop(
    config: SeedCollectorConfig,
    *,
    repository: PropertyRepository,
    http_session: Any,
    browserless_seed_probe: Any,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    runs = 0
    pages_attempted = 0
    stop_loop = False
    while True:
        runs += 1
        for _page_index in range(max(int(config.pages_per_run or 1), 1)):
            result = run_seed_collector_once(
                config,
                repository=repository,
                http_session=http_session,
                browserless_seed_probe=browserless_seed_probe,
            )
            results.append(result)
            if result.get("decision") != "seed_scan_queue_empty":
                pages_attempted += 1
            if result.get("decision") == "seed_scan_queue_empty":
                stop_loop = True
                break
        if config.max_runs is not None and runs >= config.max_runs:
            break
        if stop_loop:
            break
        time.sleep(max(config.loop_interval_seconds, 0))
    summary = {
        "decision": "seed_collector_loop_finished",
        "runs": runs,
        "pages_attempted": pages_attempted,
        "pages_per_run": max(int(config.pages_per_run or 1), 1),
        "last_decision": results[-1].get("decision") if results else None,
        "results": results[-20:],
        "counts": repository.seed_queue_counts(),
    }
    _write_runtime_summary(config.output_dir, summary)
    return summary


def config_from_env_and_args(argv: Sequence[str] | None = None) -> tuple[SeedCollectorConfig, bool]:
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
    parser.add_argument("--loop-interval-seconds", type=int, default=_safe_int(os.getenv("FAPAI_SEED_LOOP_INTERVAL_SECONDS"), 1800))
    parser.add_argument("--pages-per-run", type=int, default=_safe_int(os.getenv("FAPAI_SEED_PAGES_PER_RUN"), 10))
    parser.add_argument("--max-runs", type=int, default=None)
    args = parser.parse_args(argv)
    if args.max_runs is None and os.getenv("FAPAI_SEED_MAX_RUNS"):
        args.max_runs = _safe_int(os.getenv("FAPAI_SEED_MAX_RUNS"), 1)

    return (
        SeedCollectorConfig(
            job_key=_clean_text(args.job_key, DEFAULT_SEED_JOB_KEY),
            province=_clean_text(args.province),
            city=_clean_text(args.city),
            district=_clean_text(args.district),
            location_code=_clean_text(args.location_code, DEFAULT_SEED_LOCATION_CODE),
            category=_clean_text(args.category, DEFAULT_SEED_CATEGORY),
            sort_specs=parse_seed_sort_specs(args.sorts),
            max_page=max(int(args.max_page), 1),
            cdp_endpoint=_clean_text(args.cdp_endpoint, DEFAULT_CDP_ENDPOINT),
            output_dir=args.output_dir,
            worker_id=_clean_text(args.worker_id, f"seed-{os.getpid()}"),
            lease_seconds=max(int(args.lease_seconds), 1),
            loop_interval_seconds=max(int(args.loop_interval_seconds), 0),
            max_runs=args.max_runs,
            pages_per_run=max(int(args.pages_per_run), 1),
        ),
        bool(args.loop),
    )


def main(argv: Sequence[str] | None = None) -> int:
    config, loop = config_from_env_and_args(argv)
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for seed-collector mode")
    from tools import browserless_seed_probe

    cookies = export_cookies(config.cdp_endpoint)
    http_session = build_http(cookies)
    if loop:
        summary = run_seed_collector_loop(
            config,
            repository=repository,
            http_session=http_session,
            browserless_seed_probe=browserless_seed_probe,
        )
    else:
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
