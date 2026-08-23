from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_OUTPUT_DIR = Path("output/live_batch_smoke")
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_CDP_CONNECT_TIMEOUT_MS = 120000
DEFAULT_LIST_BROWSER_NAV_TIMEOUT_MS = 10000
DEFAULT_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS = 2
DEFAULT_LIST_BROWSER_RECOVERY_WAIT_SECONDS = 2.0
DEFAULT_DETAIL_BROWSER_READY_TIMEOUT_MS = 8000
DEFAULT_DETAIL_BROWSER_POLL_INTERVAL_MS = 250
DEFAULT_RESUME_STATE_FILENAME = "resume_state.json"
DEFAULT_LIST_ST_PARAMS = ("2", "1", "0", "3", "4", "5")
DEFAULT_TARGET_URL = (
    "https://sf.taobao.com/list/50025969__2.htm"
    "?location_code=110101&st_param=2&auction_start_seg=-1&page=1"
)
DEFAULT_API_BASE_URL = os.environ.get("FAPAI_API_BASE_URL", "http://127.0.0.1:8001/api")
DEFAULT_CDP_PAGE_TARGET_LIMIT = 12
DEFAULT_CDP_HTTP_TIMEOUT_SECONDS = 3.0
DEFAULT_CDP_RECONNECT_ATTEMPTS = 3
DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS = 0.5
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)

AREA_FOLLOWUP_NEXT_ATTEMPTS = [
    "announcement_attachment",
    "appraisal_report_attachment",
    "detail_page_images_ocr",
    "external_property_or_community_index",
]
RESUME_SCHEMA_VERSION = "live_batch_resume_state_v1"
RESUME_COMPLETED_STATUS = "completed"
TRUE_VALUES = {"1", "true", "yes", "y", "on"}
CAPTCHA_SOLVER_ENV_NAMES = (
    "FAPAI_CAPTCHA_SOLVER_ENABLED",
    "FAPAI_SOLVER_ENABLED",
    "SOLVER_ENABLED",
    "solver_enabled",
)
MOBILE_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
SERVICE_PHONE_RE = re.compile(r"(?<!\d)400[-\s]?\d{3}[-\s]?\d{4}(?!\d)")
LANDLINE_PHONE_RE = re.compile(r"(?<!\d)0\d{2,3}[-\s]?\d{7,8}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
CONTACT_FIELD_RE = re.compile(r"(联系方式|联系人|咨询电话|电话|手机)[:：]?\s*[^\s<]{1,32}")


class CdpEndpointUnavailableError(RuntimeError):
    def __init__(self, cdp_endpoint: str, operation: str, cause: BaseException):
        self.cdp_endpoint = str(cdp_endpoint or "")
        self.operation = str(operation or "")
        self.cause = cause
        super().__init__(
            f"CDP endpoint unavailable during {self.operation} on {self.cdp_endpoint}: {cause!r}"
        )


@dataclass(frozen=True)
class LiveSmokeConfig:
    output_dir: Path
    cdp_endpoint: str
    target_url: str
    target_success: int
    max_attempts: int
    do_risk: bool
    resume_state_path: Path | None = None
    resume_enabled: bool = True
    list_st_params: tuple[str, ...] = ()
    list_location_codes: tuple[str, ...] = ()
    list_categories: tuple[str, ...] = ()
    list_max_pages: int = 1
    list_stop_on_empty: bool = True
    llm_preflight_enabled: bool = False
    llm_preflight_timeout_seconds: float = 15.0
    raw_only: bool = False


def _browserless_seed_probe():
    from tools import browserless_seed_probe

    return browserless_seed_probe


def preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, Any]:
    from src import llm_helper

    return llm_helper.preflight_llm_backend(timeout=timeout, check_chat=check_chat)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_resume_state() -> dict[str, Any]:
    return {
        "schema_version": RESUME_SCHEMA_VERSION,
        "updated_at": utc_now_iso(),
        "items": {},
    }


def load_resume_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return new_resume_state()
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return new_resume_state()
    if not isinstance(payload, dict):
        return new_resume_state()
    items = payload.get("items")
    if not isinstance(items, dict):
        items = {}
    state = dict(payload)
    state["schema_version"] = str(state.get("schema_version") or RESUME_SCHEMA_VERSION)
    state["items"] = items
    state.setdefault("updated_at", utc_now_iso())
    return state


def save_resume_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["schema_version"] = str(payload.get("schema_version") or RESUME_SCHEMA_VERSION)
    payload["updated_at"] = utc_now_iso()
    if not isinstance(payload.get("items"), dict):
        payload["items"] = {}
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    state.clear()
    state.update(payload)


def _resume_item_id(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def resume_item_id(item: dict[str, Any]) -> str | None:
    return _resume_item_id(item.get("id") or item.get("item_id") or item.get("source_item_id"))


def mark_resume_item(
    state: dict[str, Any],
    item_id: Any,
    *,
    status: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_id = _resume_item_id(item_id)
    if normalized_id is None:
        raise ValueError("resume item id is required")
    items = state.setdefault("items", {})
    if not isinstance(items, dict):
        items = {}
        state["items"] = items
    previous = items.get(normalized_id)
    if not isinstance(previous, dict):
        previous = {}
    attempts = int(previous.get("attempts") or 0)
    if status == "in_progress":
        attempts += 1
    entry = dict(previous)
    entry.update(metadata or {})
    entry["status"] = status
    entry["updated_at"] = utc_now_iso()
    entry["attempts"] = attempts
    if status == RESUME_COMPLETED_STATUS:
        entry.setdefault("completed_at", entry["updated_at"])
    items[normalized_id] = entry
    state["updated_at"] = entry["updated_at"]
    return entry


def is_resume_completed(state: dict[str, Any], item_id: Any) -> bool:
    normalized_id = _resume_item_id(item_id)
    if normalized_id is None:
        return False
    items = state.get("items")
    if not isinstance(items, dict):
        return False
    entry = items.get(normalized_id)
    return isinstance(entry, dict) and entry.get("status") == RESUME_COMPLETED_STATUS


def select_resume_candidates(
    items: Iterable[dict[str, Any]],
    state: dict[str, Any],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    candidates: list[dict[str, Any]] = []
    skipped_completed: list[str] = []
    for item in items:
        item_id = resume_item_id(item)
        if item_id and is_resume_completed(state, item_id):
            skipped_completed.append(item_id)
            continue
        if len(candidates) >= limit:
            break
        candidates.append(item)
    return candidates, skipped_completed


def hydrate_resume_state_from_artifacts(
    state: dict[str, Any],
    items: Iterable[dict[str, Any]],
    *,
    output_dir: Path,
) -> list[str]:
    hydrated: list[str] = []
    for item in items:
        item_id = resume_item_id(item)
        if not item_id or is_resume_completed(state, item_id):
            continue
        if not has_completed_item_artifacts(output_dir, item_id):
            continue
        mark_resume_item(
            state,
            item_id,
            status=RESUME_COMPLETED_STATUS,
            metadata={
                "source_url": item.get("url"),
                "title": item.get("title"),
                "selected_json_path": str(output_dir / item_id / "selected.json"),
                "final_json_path": str(output_dir / item_id / "final.json"),
                "recovered_from_artifacts": True,
            },
        )
        hydrated.append(item_id)
    return hydrated


def has_completed_item_artifacts(output_dir: Path, item_id: str) -> bool:
    item_dir = output_dir / item_id
    return (item_dir / "final.json").exists() and (item_dir / "selected.json").exists()


def has_value(value: Any) -> bool:
    return value not in (None, "", [])


def pick_first(*values: Any) -> Any:
    for value in values:
        if has_value(value):
            return value
    return None


def parse_csv_values(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    values: list[str] = []
    for chunk in str(raw).replace(";", ",").split(","):
        value = chunk.strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def replace_list_url_params(
    url: str,
    *,
    location_code: str | None = None,
    category: str | None = None,
    st_param: str | None = None,
    page: int | None = None,
) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if location_code:
        query["location_code"] = [str(location_code)]
    if st_param:
        query["st_param"] = [str(st_param)]
    if page is not None:
        query["page"] = [str(int(page))]
    if category:
        path_parts = parsed.path.split("/")
        for index, part in enumerate(path_parts):
            if part.startswith("50025969") or part.startswith("200782003") or "__" in part:
                suffix = ""
                if "__" in part:
                    suffix = "__" + part.split("__", 1)[1]
                elif part.endswith(".htm"):
                    suffix = ".htm"
                path_parts[index] = f"{category}{suffix or '__2.htm'}"
                break
        else:
            path_parts.append(f"{category}__2.htm")
        parsed = parsed._replace(path="/".join(path_parts))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def expand_list_urls(config: LiveSmokeConfig) -> list[dict[str, Any]]:
    parsed = urlparse(config.target_url)
    query = parse_qs(parsed.query)
    default_location = (query.get("location_code") or [""])[0]
    default_st_param = (query.get("st_param") or ["2"])[0]
    path_category: str | None = None
    for part in parsed.path.split("/"):
        if part.startswith("50025969") or part.startswith("200782003"):
            path_category = part.split("__", 1)[0].split(".", 1)[0]
            break
    location_codes = config.list_location_codes or ((default_location,) if default_location else ("",))
    categories = config.list_categories or ((path_category,) if path_category else ("",))
    st_params = config.list_st_params or (default_st_param,)
    max_pages = max(1, int(config.list_max_pages or 1))
    specs: list[dict[str, Any]] = []
    for location_code in location_codes:
        for category in categories:
            for st_param in st_params:
                for page in range(1, max_pages + 1):
                    specs.append(
                        {
                            "url": replace_list_url_params(
                                config.target_url,
                                location_code=location_code,
                                category=category,
                                st_param=st_param,
                                page=page,
                            ),
                            "location_code": location_code,
                            "category": category,
                            "st_param": st_param,
                            "page": page,
                        }
                    )
    return specs


def deduplicate_list_items(items: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    deduped: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for item in items:
        item_id = resume_item_id(item)
        if not item_id:
            deduped.append(dict(item))
            continue
        source_page_url = str(item.get("source_page_url") or item.get("page_url") or item.get("url") or "")
        existing = by_id.get(item_id)
        if existing is None:
            cloned = dict(item)
            if source_page_url:
                cloned["list_union_sources"] = [source_page_url]
            by_id[item_id] = cloned
            deduped.append(cloned)
            continue
        duplicate_count += 1
        if source_page_url:
            sources = existing.setdefault("list_union_sources", [])
            if isinstance(sources, list) and source_page_url not in sources:
                sources.append(source_page_url)
    return deduped, duplicate_count


def collect_list_union(
    browserless_seed_probe: Any,
    http: requests.Session,
    config: LiveSmokeConfig,
) -> dict[str, Any]:
    specs = expand_list_urls(config)
    list_fetches: list[dict[str, Any]] = []
    raw_items: list[dict[str, Any]] = []
    stopped_keys: set[tuple[str, str, str]] = set()
    first_fetch: dict[str, Any] | None = None
    successful_payload_count = 0

    for spec in specs:
        key = (
            str(spec.get("location_code") or ""),
            str(spec.get("category") or ""),
            str(spec.get("st_param") or ""),
        )
        record: dict[str, Any] = {
            "url": spec["url"],
            "location_code": spec.get("location_code"),
            "category": spec.get("category"),
            "st_param": spec.get("st_param"),
            "page": spec.get("page"),
        }
        if key in stopped_keys:
            record["skipped"] = True
            record["skip_reason"] = "previous_empty_page"
            list_fetches.append(record)
            continue

        try:
            list_html, list_final_url, list_status, list_fetch_method = fetch_list_page(
                http,
                cdp_endpoint=config.cdp_endpoint,
                target_url=str(spec["url"]),
                user_agent=getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
            )
            list_summary = browserless_seed_probe.summarize_list_page(list_html, final_url=list_final_url)
            payload = browserless_seed_probe.extract_list_payload(list_html)
            record.update(
                {
                    "list_status": list_status,
                    "list_final_url": list_final_url,
                    "list_fetch_method": list_fetch_method,
                    "list_item_count": list_summary.get("item_count") if isinstance(list_summary, dict) else None,
                    "body_has_challenge": list_summary.get("body_has_challenge") if isinstance(list_summary, dict) else None,
                    "body_has_login": list_summary.get("body_has_login") if isinstance(list_summary, dict) else None,
                    "body_has_punish": list_summary.get("body_has_punish") if isinstance(list_summary, dict) else None,
                    "payload_present": payload is not None,
                }
            )
            if first_fetch is None:
                first_fetch = dict(record)
            if payload is None:
                record["error"] = f"list payload missing: {list_summary}"
                list_fetches.append(record)
                if isinstance(list_summary, dict) and list_summary.get("body_has_challenge"):
                    stopped_keys.add(key)
                continue

            successful_payload_count += 1
            batch = browserless_seed_probe.build_userscript_like_batch_payload(payload, source_page_url=list_final_url)
            batch_items = [item for item in (batch.get("items") or []) if isinstance(item, dict)]
            for item in batch_items:
                enriched_item = dict(item)
                enriched_item.setdefault("source_page_url", list_final_url)
                enriched_item["list_location_code"] = spec.get("location_code")
                enriched_item["list_category"] = spec.get("category")
                enriched_item["list_st_param"] = spec.get("st_param")
                enriched_item["list_page"] = spec.get("page")
                raw_items.append(enriched_item)

            record["eligible_item_count"] = len(batch_items)
            list_fetches.append(record)
            if config.list_stop_on_empty and int(spec.get("page") or 1) > 1 and not batch_items:
                stopped_keys.add(key)
        except Exception as exc:
            record["error"] = repr(exc)
            record["traceback"] = traceback.format_exc()
            list_fetches.append(record)
            if config.list_stop_on_empty and int(spec.get("page") or 1) > 1:
                stopped_keys.add(key)

    if successful_payload_count == 0:
        raise RuntimeError(f"list payload missing for all list sources: {list_fetches[:5]}")

    all_items, duplicate_item_count = deduplicate_list_items(raw_items)
    source_count = len(specs)
    fetched_source_count = sum(1 for record in list_fetches if not record.get("skipped"))
    return {
        "items": all_items,
        "first_fetch": first_fetch or {},
        "list_union": {
            "source_count": source_count,
            "fetched_source_count": fetched_source_count,
            "successful_payload_count": successful_payload_count,
            "raw_item_count": len(raw_items),
            "unique_item_count": len(all_items),
            "duplicate_item_count": duplicate_item_count,
            "list_stop_on_empty": bool(config.list_stop_on_empty),
            "sources": list_fetches,
        },
    }


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_positive_number(value: Any) -> float | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number > 0 else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    number_chars = []
    seen_digit = False
    seen_dot = False
    for char in text:
        if char.isdigit():
            seen_digit = True
            number_chars.append(char)
            continue
        if char == "." and not seen_dot:
            seen_dot = True
            number_chars.append(char)
            continue
        if seen_digit:
            break
    if not number_chars or not seen_digit:
        return None
    try:
        number = float("".join(number_chars))
    except ValueError:
        return None
    return number if number > 0 else None


def is_positive_number(value: Any) -> bool:
    return parse_positive_number(value) is not None


def result_area_value(result: dict[str, Any]) -> Any:
    auction = as_dict(result.get("auction_and_property"))
    prop_area = pick_first(auction.get("area_sqm"), auction.get("gross_area_sqm"))
    if has_value(prop_area):
        return prop_area
    raw = as_dict(result.get("ai_extracted_raw_core"))
    return pick_first(raw.get("建筑面积"), raw.get("产权建筑面积"))


def result_description_area_value(result: dict[str, Any]) -> Any:
    description = as_dict(result.get("description_data"))
    raw = as_dict(result.get("ai_extracted_raw_core"))
    return pick_first(description.get("area_sqm"), description.get("gross_area_sqm"), raw.get("建筑面积"))


def compute_area_stats(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in results if isinstance(row, dict)]
    total = len(rows)
    area_present = sum(1 for row in rows if is_positive_number(result_area_value(row)))
    unit_present = sum(
        1
        for row in rows
        if is_positive_number(as_dict(row.get("auction_and_property")).get("unit_price"))
    )
    description_area_present = sum(1 for row in rows if is_positive_number(result_description_area_value(row)))
    return {
        "total": total,
        "area_present_count": area_present,
        "area_missing_count": total - area_present,
        "unit_price_present_count": unit_present,
        "unit_price_missing_count": total - unit_present,
        "description_area_present_count": description_area_present,
        "description_area_missing_count": total - description_area_present,
        "area_present_ratio": round(area_present / total, 4) if total else 0,
    }


def _missing_fields_for_area_job(result: dict[str, Any]) -> list[str]:
    auction = as_dict(result.get("auction_and_property"))
    missing: list[str] = []
    if not is_positive_number(auction.get("area_sqm")):
        missing.append("area_sqm")
    if not is_positive_number(auction.get("gross_area_sqm")):
        missing.append("gross_area_sqm")
    if not is_positive_number(auction.get("unit_price")):
        missing.append("unit_price")
    return missing


def _artifact_path_if_exists(artifact_root: Path | None, item_id: str, filename: str) -> str | None:
    if artifact_root is None:
        return None
    path = artifact_root / item_id / filename
    return str(path) if path.exists() else None


def _load_artifact_json_if_exists(artifact_root: Path | None, item_id: str, filename: str) -> dict[str, Any]:
    if artifact_root is None:
        return {}
    path = artifact_root / item_id / filename
    if not path.exists():
        return {}
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _area_followup_priority(result: dict[str, Any]) -> str:
    auction = as_dict(result.get("auction_and_property"))
    if is_positive_number(auction.get("transaction_price")):
        return "P1"
    return "P2"


def _build_area_followup_job(result: dict[str, Any], *, artifact_root: Path | None) -> dict[str, Any]:
    item_id = str(result.get("item_id") or "")
    fetch = as_dict(result.get("fetch"))
    trusted_seed = as_dict(result.get("trusted_seed"))
    final_core = as_dict(result.get("final_core"))
    location = as_dict(result.get("location_and_stable_index"))
    auction = as_dict(result.get("auction_and_property"))
    description = as_dict(result.get("description_data"))
    description_artifact = _load_artifact_json_if_exists(artifact_root, item_id, "description-data.json")
    if description_artifact:
        description = {**description, **description_artifact}
    raw_core = as_dict(result.get("ai_extracted_raw_core"))
    return {
        "item_id": item_id,
        "priority": _area_followup_priority(result),
        "reason": "area_missing_after_detail_and_description_data",
        "missing_fields": _missing_fields_for_area_job(result),
        "next_attempts": list(AREA_FOLLOWUP_NEXT_ATTEMPTS),
        "source_url": pick_first(final_core.get("source_url"), fetch.get("detail_final_url"), trusted_seed.get("url")),
        "title": pick_first(final_core.get("title"), trusted_seed.get("title")),
        "full_address": location.get("full_address"),
        "city": location.get("city"),
        "district": location.get("district"),
        "business_area": location.get("business_area"),
        "community_name": location.get("community_name"),
        "community_stable_key": location.get("community_stable_key"),
        "community_name_source": location.get("community_name_source"),
        "community_name_confidence": location.get("community_name_confidence"),
        "transaction_price": auction.get("transaction_price"),
        "starting_price": auction.get("starting_price"),
        "auction_date": pick_first(auction.get("auction_date"), trusted_seed.get("auction_date")),
        "bid_count": pick_first(auction.get("bid_count"), trusted_seed.get("bidCount")),
        "apply_count": pick_first(auction.get("apply_count"), trusted_seed.get("applyCount")),
        "current_area_sqm": auction.get("area_sqm"),
        "current_gross_area_sqm": auction.get("gross_area_sqm"),
        "current_unit_price": auction.get("unit_price"),
        "desc_area": pick_first(description.get("area_sqm"), raw_core.get("建筑面积")),
        "desc_text_len": description.get("text_len"),
        "desc_has_area_marker": description.get("has_area_marker"),
        "fetch_method": fetch.get("method"),
        "detail_html_bytes": fetch.get("detail_html_bytes"),
        "detail_html_path": _artifact_path_if_exists(artifact_root, item_id, "detail.html"),
        "description_data_path": _artifact_path_if_exists(artifact_root, item_id, "description-data.json"),
        "selected_json_path": _artifact_path_if_exists(artifact_root, item_id, "selected.json"),
        "final_json_path": _artifact_path_if_exists(artifact_root, item_id, "final.json"),
    }


def build_area_followup_queue(summary: dict[str, Any], *, artifact_root: str | Path | None = None) -> dict[str, Any]:
    root = Path(artifact_root) if artifact_root is not None else None
    results = [row for row in summary.get("results", []) if isinstance(row, dict)]
    jobs = [
        _build_area_followup_job(row, artifact_root=root)
        for row in results
        if not is_positive_number(result_area_value(row))
    ]
    source_summary = summary.get("summary_path")
    if not source_summary and root is not None:
        source_summary = str(root / "summary.json")
    return {
        "schema_version": "area_followup_queue_v1",
        "source_summary": source_summary,
        "target_url": summary.get("target_url"),
        "area_stats": compute_area_stats(results),
        "job_count": len(jobs),
        "jobs": jobs,
    }


def attach_area_artifacts(summary: dict[str, Any], *, output_dir: str | Path) -> dict[str, Any]:
    output_path = Path(output_dir)
    enriched = dict(summary)
    results = [row for row in enriched.get("results", []) if isinstance(row, dict)]
    enriched["area_stats"] = compute_area_stats(results)
    enriched["area_followup_queue_path"] = str(output_path / "area_followup_queue.json")
    enriched["area_followup_job_count"] = enriched["area_stats"]["area_missing_count"]
    return enriched


def is_challenge_page(html: str, final_url: str) -> bool:
    browserless_seed_probe = _browserless_seed_probe()
    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    if summary.get("body_has_challenge") or summary.get("body_has_login"):
        return True
    text = html or ""
    lowered_final_url = str(final_url or "").lower()
    return "challenge" in lowered_final_url or any(
        marker in text for marker in ("霸下通用 web 页面-验证码", "_____tmd_____/punish", "x5secdata=")
    )


def is_login_page(html: str, final_url: str) -> bool:
    browserless_seed_probe = _browserless_seed_probe()
    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    lowered_final_url = str(final_url or "").lower()
    return bool(summary.get("body_has_login")) or any(
        marker in lowered_final_url
        for marker in ("login.taobao.com", "login.m.taobao.com", "havanaone/login")
    )


def _configured_cookie_snapshot_path() -> Path | None:
    explicit = (os.environ.get("FAPAI_COOKIE_SNAPSHOT") or "").strip()
    if explicit:
        return Path(explicit)
    shared_root = (
        (os.environ.get("FAPAI_SHARED_DATA_ROOT_HOST") or "").strip()
        or (os.environ.get("FAPAI_DATA_ROOT_HOST") or "").strip()
    )
    node_id = (os.environ.get("FAPAI_NODE_ID") or "").strip()
    if not shared_root or not node_id:
        return None
    return Path(shared_root) / "secrets" / "nodes" / node_id / "taobao-cookies.json"


def _write_cookie_snapshot_best_effort(browserless_seed_probe: Any, cookies: list[dict[str, Any]], snapshot_path: Path | None) -> None:
    if snapshot_path is None:
        return
    try:
        browserless_seed_probe.write_cookie_snapshot(cookies, snapshot_path)
    except Exception:
        return


def export_cookies(cdp_endpoint: str) -> list[dict[str, Any]]:
    browserless_seed_probe = _browserless_seed_probe()
    snapshot = _configured_cookie_snapshot_path()
    prefer_snapshot = (os.environ.get("FAPAI_COOKIE_SNAPSHOT_PREFER") or "").strip().lower() in TRUE_VALUES
    if prefer_snapshot and snapshot is not None:
        try:
            return browserless_seed_probe.load_cookie_snapshot(snapshot)
        except FileNotFoundError:
            cookies = browserless_seed_probe.export_cdp_cookies(cdp_endpoint)
            _write_cookie_snapshot_best_effort(browserless_seed_probe, cookies, snapshot)
            return cookies
    try:
        cookies = browserless_seed_probe.export_cdp_cookies(cdp_endpoint)
        _write_cookie_snapshot_best_effort(browserless_seed_probe, cookies, snapshot)
        return cookies
    except Exception as export_exc:
        if snapshot is None:
            raise
        try:
            return browserless_seed_probe.load_cookie_snapshot(snapshot)
        except Exception as snapshot_exc:
            raise RuntimeError(
                f"cdp cookie export failed: {export_exc!r}; "
                f"snapshot fallback failed: {snapshot_exc!r}"
            ) from snapshot_exc


def list_browser_fallback_enabled() -> bool:
    raw = os.environ.get("FAPAI_LIST_BROWSER_FALLBACK")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def detail_browser_fallback_enabled() -> bool:
    raw = os.environ.get("FAPAI_DETAIL_BROWSER_FALLBACK")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def captcha_solver_enabled(*, default: bool = False) -> bool:
    for name in CAPTCHA_SOLVER_ENV_NAMES:
        raw = os.environ.get(name)
        if raw is None:
            continue
        text = raw.strip()
        if text:
            return text.lower() in TRUE_VALUES
    return default


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def detail_browser_ready_timeout_ms() -> int:
    return _positive_int_env(
        "FAPAI_DETAIL_BROWSER_READY_TIMEOUT_MS",
        DEFAULT_DETAIL_BROWSER_READY_TIMEOUT_MS,
    )


def detail_browser_poll_interval_ms() -> int:
    return _positive_int_env(
        "FAPAI_DETAIL_BROWSER_POLL_INTERVAL_MS",
        DEFAULT_DETAIL_BROWSER_POLL_INTERVAL_MS,
    )


def _detail_page_has_ready_marker(html: str) -> bool:
    lowered = str(html or "").lower()
    return any(
        marker in lowered
        for marker in (
            'id="j_startprice',
            "id='j_startprice",
            'id="itemaddress',
            "id='itemaddress",
            'id="description-data',
            "id='description-data",
            'class="countdown',
            "class='countdown",
        )
    )


def _wait_for_detail_ready(
    page: Any,
    *,
    timeout_ms: int | None = None,
    poll_interval_ms: int | None = None,
) -> str:
    """Poll detail DOM readiness while preserving immediate challenge detection."""
    timeout = max(int(timeout_ms or detail_browser_ready_timeout_ms()), 1)
    poll_interval = max(int(poll_interval_ms or detail_browser_poll_interval_ms()), 1)
    deadline = time.monotonic() + timeout / 1000.0
    max_polls = max((timeout + poll_interval - 1) // poll_interval, 1)
    last_html = ""
    for poll_index in range(max_polls + 1):
        last_html = read_page_content_with_retries(page, attempts=1)
        final_url = str(getattr(page, "url", "") or "")
        if is_challenge_page(last_html, final_url) or _detail_page_has_ready_marker(last_html):
            return last_html
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if poll_index >= max_polls or remaining_ms <= 0:
            break
        page.wait_for_timeout(min(poll_interval, max(1, remaining_ms)))
    return last_html


def list_browser_recovery_max_attempts() -> int:
    return _positive_int_env(
        "FAPAI_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS",
        DEFAULT_LIST_BROWSER_RECOVERY_MAX_ATTEMPTS,
    )


def list_browser_recovery_wait_seconds() -> float:
    return _positive_float_env(
        "FAPAI_LIST_BROWSER_RECOVERY_WAIT_SECONDS",
        DEFAULT_LIST_BROWSER_RECOVERY_WAIT_SECONDS,
    )


def list_http_timeout_seconds() -> float:
    return _positive_float_env(
        "FAPAI_LIST_HTTP_TIMEOUT_SECONDS",
        40.0,
    )


def build_http(cookies: list[dict[str, Any]]) -> requests.Session:
    browserless_seed_probe = _browserless_seed_probe()
    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    session.trust_env = False
    explicit_proxy = os.environ.get("FAPAI_HTTP_PROXY") or os.environ.get("FAPAI_PROXY")
    explicit_https_proxy = os.environ.get("FAPAI_HTTPS_PROXY") or explicit_proxy
    session.proxies = {
        "http": explicit_proxy,
        "https": explicit_https_proxy,
    }
    return session


def resolve_runtime_user_agent(cdp_endpoint: str) -> str:
    browserless_seed_probe = _browserless_seed_probe()
    resolver = getattr(browserless_seed_probe, "resolve_cdp_user_agent", None)
    if callable(resolver):
        try:
            return str(resolver(cdp_endpoint, default=getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)) or "")
        except Exception:
            pass
    return getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)


def build_navigation_headers(*, target_url: str, user_agent: str, referer_url: str) -> dict[str, str]:
    browserless_seed_probe = _browserless_seed_probe()
    builder = getattr(browserless_seed_probe, "build_navigation_headers", None)
    if callable(builder):
        try:
            return dict(
                builder(
                    target_url=target_url,
                    user_agent=user_agent,
                    referer_url=referer_url,
                )
            )
        except Exception:
            pass
    return {
        "User-Agent": str(user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "max-age=0",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-site" if str(referer_url or "").strip() else "none",
        "Sec-Fetch-User": "?1",
        "Referer": str(referer_url or ""),
    }


def _default_list_referer_url(target_url: str) -> str:
    normalized_target = str(target_url or "").strip()
    if not normalized_target:
        return "https://sf.taobao.com/"
    try:
        parsed = urlparse(normalized_target)
    except ValueError:
        return "https://sf.taobao.com/"
    hostname = str(parsed.hostname or "").lower()
    if hostname != "sf.taobao.com":
        return "https://sf.taobao.com/"
    if "/list/" not in str(parsed.path or "").lower():
        return "https://sf.taobao.com/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("__captcha_solver_bg", None)
    page_values = query.get("page") or []
    try:
        current_page = int(page_values[-1]) if page_values else 1
    except (TypeError, ValueError):
        current_page = 1
    if current_page <= 1:
        return "https://sf.taobao.com/"
    query["page"] = [str(current_page - 1)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _cdp_page_target_limit() -> int:
    raw = os.environ.get("FAPAI_CDP_MAX_PAGE_TARGETS")
    if raw is None or not raw.strip():
        return DEFAULT_CDP_PAGE_TARGET_LIMIT
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_CDP_PAGE_TARGET_LIMIT
    return parsed if parsed > 0 else DEFAULT_CDP_PAGE_TARGET_LIMIT


def _cdp_url(cdp_endpoint: str, path: str) -> str:
    return f"{str(cdp_endpoint or '').rstrip('/')}/{path.lstrip('/')}"


def _cdp_http_get(cdp_endpoint: str, path: str, *, timeout_seconds: float) -> Any:
    session = requests.Session()
    session.trust_env = False
    return session.get(_cdp_url(cdp_endpoint, path), timeout=timeout_seconds)


def _cdp_http_put(cdp_endpoint: str, path: str, *, timeout_seconds: float) -> Any:
    session = requests.Session()
    session.trust_env = False
    return session.put(_cdp_url(cdp_endpoint, path), timeout=timeout_seconds)


def _fallback_cached_playwright_cdp_endpoint(cdp_endpoint: str) -> str:
    try:
        probe = _browserless_seed_probe()
    except Exception:
        return ""

    cached_loader = getattr(probe, "_load_cached_cdp_websocket", None)
    if callable(cached_loader):
        try:
            cached = str(cached_loader(cdp_endpoint) or "").strip()
        except Exception:
            cached = ""
        if cached.startswith(("ws://", "wss://")):
            return cached

    resolver = getattr(probe, "_resolve_cdp_endpoint", None)
    if callable(resolver):
        try:
            resolved = str(resolver(cdp_endpoint) or "").strip()
        except Exception:
            resolved = ""
        if resolved.startswith(("ws://", "wss://")):
            return resolved

    return ""


def resolve_playwright_cdp_endpoint(
    cdp_endpoint: str,
    *,
    timeout_seconds: float = DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
) -> str:
    normalized = str(cdp_endpoint or "").strip()
    if not normalized:
        return normalized
    if normalized.startswith(("ws://", "wss://")):
        return normalized
    try:
        response = _cdp_http_get(normalized, "/json/version", timeout_seconds=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return _fallback_cached_playwright_cdp_endpoint(normalized) or normalized
    if not isinstance(payload, dict):
        return _fallback_cached_playwright_cdp_endpoint(normalized) or normalized
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    return websocket_url or normalized


def open_cdp_keepalive_target(
    cdp_endpoint: str,
    *,
    timeout_seconds: float = DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
) -> str:
    response = _cdp_http_put(cdp_endpoint, "/json/new?about:blank", timeout_seconds=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("id") or "").strip()


def compact_cdp_page_targets_if_needed(
    cdp_endpoint: str,
    *,
    limit: int | None = None,
    timeout_seconds: float = DEFAULT_CDP_HTTP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    effective_limit = int(limit or _cdp_page_target_limit())
    summary: dict[str, Any] = {"triggered": False, "page_count": 0, "closed": 0, "errors": []}
    if not str(cdp_endpoint or "").strip() or effective_limit <= 0:
        return summary
    try:
        response = _cdp_http_get(cdp_endpoint, "/json/list", timeout_seconds=timeout_seconds)
        response.raise_for_status()
        targets = response.json()
    except Exception as error:
        summary["errors"].append(repr(error))
        return summary
    if not isinstance(targets, list):
        summary["errors"].append("CDP /json/list response is not a list")
        return summary
    page_targets = [
        target
        for target in targets
        if isinstance(target, dict) and str(target.get("type") or "").lower() == "page"
    ]
    summary["page_count"] = len(page_targets)
    if len(page_targets) < effective_limit:
        return summary
    summary["triggered"] = True
    keepalive_target_id = ""
    try:
        keepalive_target_id = open_cdp_keepalive_target(cdp_endpoint, timeout_seconds=timeout_seconds)
    except Exception as error:
        summary["errors"].append(f"keepalive: {error!r}")
    if keepalive_target_id:
        summary["keepalive_target_id"] = keepalive_target_id
    preserve_target_id = keepalive_target_id or str(page_targets[0].get("id") or "").strip()
    if preserve_target_id and not keepalive_target_id:
        summary["preserved_target_id"] = preserve_target_id
    for target in page_targets:
        target_id = str(target.get("id") or "").strip()
        if not target_id:
            continue
        if target_id == preserve_target_id:
            continue
        try:
            close_response = _cdp_http_get(
                cdp_endpoint,
                f"/json/close/{quote(target_id, safe='')}",
                timeout_seconds=timeout_seconds,
            )
            close_response.raise_for_status()
            summary["closed"] += 1
        except Exception as error:
            summary["errors"].append(f"{target_id}: {error!r}")
    return summary


def _cdp_reconnect_attempts() -> int:
    raw = os.environ.get("FAPAI_CDP_RECONNECT_ATTEMPTS", str(DEFAULT_CDP_RECONNECT_ATTEMPTS))
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = DEFAULT_CDP_RECONNECT_ATTEMPTS
    return max(1, min(value, 10))


def _cdp_reconnect_backoff_seconds() -> float:
    raw = os.environ.get("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", str(DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS))
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS
    return max(0.0, min(value, 30.0))


def _cdp_endpoint_healthy_for_reconnect(cdp_endpoint: str) -> bool:
    try:
        probe = _browserless_seed_probe()
        health_check = getattr(probe, "cdp_endpoint_is_healthy", None)
        if callable(health_check):
            return bool(health_check(cdp_endpoint, timeout_seconds=DEFAULT_CDP_HTTP_TIMEOUT_SECONDS))
    except Exception:
        return False
    return bool(resolve_playwright_cdp_endpoint(cdp_endpoint))


def connect_browser_over_cdp(playwright: Any, cdp_endpoint: str, *, timeout_ms: int = DEFAULT_CDP_CONNECT_TIMEOUT_MS) -> Any:
    try:
        compaction = compact_cdp_page_targets_if_needed(cdp_endpoint)
    except Exception as error:
        _raise_cdp_endpoint_unavailable(cdp_endpoint, "compact_cdp_page_targets", error)
    if compaction.get("triggered"):
        print(json.dumps({"event": "cdp_page_target_compaction", **compaction}, ensure_ascii=False))
    attempts = _cdp_reconnect_attempts()
    backoff = _cdp_reconnect_backoff_seconds()
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1 and not _cdp_endpoint_healthy_for_reconnect(cdp_endpoint):
            last_error = RuntimeError(f"CDP health check failed before reconnect attempt {attempt}")
            if attempt < attempts and backoff > 0:
                time.sleep(backoff * attempt)
            continue
        try:
            resolved_endpoint = resolve_playwright_cdp_endpoint(cdp_endpoint)
            return playwright.chromium.connect_over_cdp(resolved_endpoint, timeout=timeout_ms)
        except Exception as error:
            last_error = error
        if attempt < attempts and backoff > 0:
            time.sleep(backoff * attempt)
    _raise_cdp_endpoint_unavailable(
        cdp_endpoint,
        "connect_over_cdp_bounded_reconnect",
        last_error or RuntimeError("CDP connection failed without an explicit error"),
    )


def detach_attached_cdp_browser(browser: Any) -> None:
    """Detach from an externally managed CDP browser without closing the host process."""
    disconnect = getattr(browser, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            pass


def read_page_content_with_retries(
    page: Any,
    *,
    attempts: int = 5,
    wait_timeout_ms: int = 500,
) -> str:
    last_error: Exception | None = None
    for attempt_index in range(max(int(attempts), 1)):
        try:
            return str(page.content() or "")
        except Exception as error:
            last_error = error
            if attempt_index >= max(int(attempts), 1) - 1:
                break
            try:
                page.wait_for_timeout(wait_timeout_ms)
            except Exception:
                break
    if last_error is not None:
        raise last_error
    return ""


def request_captcha_solver(
    cdp_endpoint: str,
    target_url: str,
    *,
    api_base_url: str | None = None,
    manual_only: bool = False,
) -> dict[str, Any]:
    from tools.taobao_login_health import build_captcha_solver_target_url, report_captcha_via_api

    solver_target_url = build_captcha_solver_target_url(target_url)
    report_kwargs = {"manual_only": True} if manual_only else {}
    response = report_captcha_via_api(
        str(api_base_url or DEFAULT_API_BASE_URL),
        cdp_endpoint,
        solver_target_url,
        **report_kwargs,
    )
    return dict(response) if isinstance(response, dict) else {"status": "unknown_response", "raw": response}


def fetch_open_browser_pages(cdp_endpoint: str) -> dict[str, tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    pages: dict[str, tuple[str, str]] = {}
    with sync_playwright() as p:
        browser = connect_browser_over_cdp(p, cdp_endpoint)
        try:
            for context in browser.contexts:
                for page in context.pages:
                    url = page.url or ""
                    if "/sf_item/" not in url:
                        continue
                    item_id = url.split("/sf_item/", 1)[1].split(".htm", 1)[0]
                    page.wait_for_timeout(1000)
                    pages[item_id] = (read_page_content_with_retries(page), url)
        finally:
            detach_attached_cdp_browser(browser)
    return pages


def load_open_browser_pages(cdp_endpoint: str) -> dict[str, tuple[str, str]]:
    try:
        return fetch_open_browser_pages(cdp_endpoint)
    except Exception:
        return {}


def _normalize_browser_match_url(
    url: str,
    *,
    drop_params: Iterable[str] = ("__captcha_solver_bg", "x5secdata", "x5step"),
) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    query = parse_qs(parsed.query, keep_blank_values=True)
    path = parsed.path or ""
    if "/_____tmd_____/punish" in path:
        path = path.split("/_____tmd_____/punish", 1)[0]
    while "//" in path:
        path = path.replace("//", "/")
    for param in drop_params:
        query.pop(str(param), None)
    normalized_query = urlencode(
        sorted((key, value) for key, values in query.items() for value in values),
        doseq=True,
    )
    return urlunparse(parsed._replace(path=path, query=normalized_query, fragment=""))


def _cdp_runtime_value(response: Mapping[str, Any] | dict[str, Any]) -> Any:
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    inner = result.get("result")
    if not isinstance(inner, dict):
        return None
    return inner.get("value")


def _raise_cdp_endpoint_unavailable(cdp_endpoint: str, operation: str, error: BaseException) -> None:
    if isinstance(error, CdpEndpointUnavailableError):
        raise error
    raise CdpEndpointUnavailableError(cdp_endpoint, operation, error) from error


def _read_cdp_list_target_html(
    cdp_endpoint: str,
    target: Mapping[str, Any] | dict[str, Any],
    *,
    polls: int = 5,
    wait_seconds: float = 1.0,
) -> tuple[str, str]:
    from tools import taobao_login_health

    taobao_login_health.activate_cdp_target(cdp_endpoint, target)
    websocket_url = str(target.get("webSocketDebuggerUrl") or "").strip()
    if not websocket_url:
        raise RuntimeError(f"CDP target missing webSocketDebuggerUrl: {target!r}")

    expression = (
        "(() => {"
        "return {"
        "html: document.documentElement ? document.documentElement.outerHTML : '',"
        "url: window.location.href || ''"
        "};"
        "})()"
    )
    last_html = ""
    last_url = str(target.get("url") or "").strip()
    for attempt_index in range(max(int(polls), 1)):
        response = taobao_login_health.evaluate_cdp_expression(websocket_url, expression)
        value = _cdp_runtime_value(response)
        if isinstance(value, dict):
            html = str(value.get("html") or "")
            url = str(value.get("url") or last_url or "")
        else:
            html = ""
            url = last_url
        if html:
            last_html = html
        if url:
            last_url = url
        if last_html and ("sf-item-list-data" in last_html or is_challenge_page(last_html, last_url)):
            break
        if attempt_index < max(int(polls), 1) - 1 and wait_seconds > 0:
            time.sleep(wait_seconds)
    return last_html, last_url


def _find_matching_cdp_list_targets(cdp_endpoint: str, target_url: str) -> list[dict[str, Any]]:
    from tools import taobao_login_health

    normalized_target = _normalize_browser_match_url(target_url)
    matches: list[dict[str, Any]] = []
    for target in taobao_login_health.list_cdp_targets(cdp_endpoint):
        if not isinstance(target, dict):
            continue
        if str(target.get("type") or "").lower() != "page":
            continue
        page_url = str(target.get("url") or "")
        if "/list/" not in page_url:
            continue
        if normalized_target and _normalize_browser_match_url(page_url) != normalized_target:
            continue
        matches.append(dict(target))
    return matches


def fetch_open_browser_list_page(
    cdp_endpoint: str,
    target_url: str,
    *,
    include_challenge: bool = False,
) -> tuple[str, str] | None:
    challenge_page: tuple[str, str] | None = None
    for target in _find_matching_cdp_list_targets(cdp_endpoint, target_url):
        html, page_url = _read_cdp_list_target_html(cdp_endpoint, target)
        if not html:
            continue
        if is_challenge_page(html, page_url):
            if include_challenge and challenge_page is None:
                challenge_page = (html, page_url)
            continue
        return html, page_url
    return challenge_page


def _read_text_if_exists(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ""


def _redact_detail_analysis_text(text: str) -> str:
    sanitized = str(text or "")
    sanitized = CONTACT_FIELD_RE.sub(lambda match: f"{match.group(1)}: [REDACTED]", sanitized)
    sanitized = MOBILE_PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = SERVICE_PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = LANDLINE_PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    sanitized = EMAIL_RE.sub("[REDACTED_EMAIL]", sanitized)
    return sanitized


def _detail_input_value(soup: BeautifulSoup, element_id: str) -> str:
    node = soup.find(id=element_id)
    if node is None:
        return ""
    return str(node.get("value") or "").strip()


def _detail_node_text(soup: BeautifulSoup, element_id: str) -> str:
    node = soup.find(id=element_id)
    if node is None:
        return ""
    return node.get_text(" ", strip=True)


def _detail_countdown_text(soup: BeautifulSoup) -> str:
    node = soup.find(class_="countdown")
    if node is None:
        return ""
    return node.get_text(" ", strip=True)


def _build_detail_analysis_input(
    *,
    item_id: str,
    item_dir: Path,
    seed: dict[str, Any],
    html: str,
    selected: dict[str, Any],
    description_data: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    effective_seed = dict(seed)
    selected = as_dict(selected)
    trusted_seed = as_dict(selected.get("trusted_seed"))
    fetch = as_dict(selected.get("fetch"))
    final_core = as_dict(selected.get("final_core"))
    soup = BeautifulSoup(html or "", "html.parser")

    title = pick_first(
        final_core.get("title"),
        trusted_seed.get("title"),
        effective_seed.get("title"),
        soup.title.string.strip() if soup.title and soup.title.string else None,
    )
    final_url = pick_first(
        fetch.get("detail_final_url"),
        final_core.get("source_url"),
        effective_seed.get("url"),
        effective_seed.get("source_url"),
    )
    address = " ".join(
        part
        for part in (
            _detail_node_text(soup, "itemAddress"),
            _detail_node_text(soup, "itemAddressDetail"),
        )
        if part
    ).strip()
    page_end_time = _detail_countdown_text(soup)
    page_start_price = parse_positive_number(_detail_input_value(soup, "J_StartPrice"))
    page_status_code = _detail_input_value(soup, "J_Status")
    if page_start_price is not None:
        effective_seed["initialPrice"] = page_start_price
        effective_seed["起拍价格"] = page_start_price
    if address:
        effective_seed.setdefault("地点", address)
        effective_seed.setdefault("完整地址", address)

    description_text_path = Path(str(description_data.get("text_path") or item_dir / "description-data.txt"))
    description_text = _read_text_if_exists(description_text_path).strip()
    if not description_text and description_data:
        description_text = json.dumps(description_data, ensure_ascii=False, indent=2)

    lines = [
        "【可信种子】",
        f"id: {item_id}",
    ]
    if final_url:
        lines.append(f"url: {final_url}")
    if title:
        lines.append(f"title: {title}")
    for key in ("status", "currentPrice", "initialPrice", "auction_date", "bidCount", "applyCount"):
        value = pick_first(effective_seed.get(key), trusted_seed.get(key))
        if has_value(value):
            lines.append(f"{key}: {value}")

    lines.extend(["", "【详情页摘要】"])
    if address:
        lines.append(f"address: {address}")
    if page_end_time:
        lines.append(f"auction_end_time: {page_end_time}")
    if page_start_price is not None:
        lines.append(f"起拍价_html: {page_start_price}")
    if page_status_code:
        lines.append(f"status_code_html: {page_status_code}")
    if has_value(description_data.get("area_sqm")):
        lines.append(f"description_area_sqm: {description_data.get('area_sqm')}")

    if description_text:
        lines.extend(["", "【异步标的物描述】", description_text])

    analysis_text = "\n".join(lines).strip()
    return effective_seed, _redact_detail_analysis_text(analysis_text)


def fetch_browser_navigation_list_page(cdp_endpoint: str, target_url: str) -> tuple[str, str]:
    from tools import taobao_login_health

    try:
        taobao_login_health.compact_cdp_pages_if_needed(cdp_endpoint, reserve_for_new_page=True)
        opened = taobao_login_health.read_cdp_json(
            cdp_endpoint,
            "/json/new?" + quote(target_url, safe=""),
            method="PUT",
        )
    except Exception as error:
        _raise_cdp_endpoint_unavailable(cdp_endpoint, "open_list_page_target", error)
    target: dict[str, Any] | None = dict(opened) if isinstance(opened, dict) else None
    if target is None or not str(target.get("webSocketDebuggerUrl") or "").strip():
        try:
            matches = _find_matching_cdp_list_targets(cdp_endpoint, target_url)
        except Exception as error:
            _raise_cdp_endpoint_unavailable(cdp_endpoint, "find_list_page_target", error)
        target = matches[0] if matches else None
    if target is None:
        raise RuntimeError(f"unable to open CDP list page target: {target_url}")

    target_id = str(target.get("id") or "").strip()
    preserve_challenge_target = False
    try:
        try:
            html, final_url = _read_cdp_list_target_html(cdp_endpoint, target)
            preserve_challenge_target = is_challenge_page(html, final_url)
            return html, final_url
        except Exception as error:
            _raise_cdp_endpoint_unavailable(cdp_endpoint, "read_list_page_target_html", error)
    finally:
        # The node solver can only act on a challenge that remains attached to
        # CDP. Normal transient pages are still closed immediately.
        if target_id and not preserve_challenge_target:
            try:
                taobao_login_health.close_cdp_target(cdp_endpoint, target_id)
            except Exception:
                pass


def fetch_browser_list_page(cdp_endpoint: str, target_url: str) -> tuple[str, str] | None:
    try:
        browser_page = fetch_open_browser_list_page(
            cdp_endpoint,
            target_url,
            include_challenge=True,
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "event": "open_browser_list_page_probe_failed",
                    "target_url": target_url,
                    "error": repr(error),
                },
                ensure_ascii=False,
            )
        )
        browser_page = None
    if browser_page is not None:
        return browser_page
    return fetch_browser_navigation_list_page(cdp_endpoint, target_url)


def recover_browser_list_page_after_challenge(
    cdp_endpoint: str,
    target_url: str,
    initial_page: tuple[str, str] | None,
    *,
    max_attempts: int | None = None,
    wait_seconds: float | None = None,
    solver_enabled: bool = True,
    api_base_url: str | None = None,
) -> tuple[str, str] | None:
    effective_max_attempts = max_attempts if max_attempts is not None else list_browser_recovery_max_attempts()
    effective_wait_seconds = wait_seconds if wait_seconds is not None else list_browser_recovery_wait_seconds()
    browser_page = initial_page
    attempts = 0
    while browser_page is not None and attempts < effective_max_attempts:
        html, final_url = browser_page
        if not is_challenge_page(html, final_url):
            return browser_page
        if attempts == 0 and solver_enabled:
            try:
                login_required = is_login_page(html, final_url)
                request_captcha_solver(
                    cdp_endpoint,
                    target_url if login_required else (final_url or target_url),
                    api_base_url=api_base_url,
                    manual_only=login_required,
                )
            except Exception:
                pass
        attempts += 1
        if attempts >= effective_max_attempts:
            return browser_page
        time.sleep(effective_wait_seconds)
        browser_page = fetch_browser_list_page(cdp_endpoint, target_url)
    return browser_page


def fetch_list_page(
    http: requests.Session,
    *,
    cdp_endpoint: str,
    target_url: str,
    user_agent: str,
    referer_url: str | None = None,
    solver_enabled: bool | None = None,
    api_base_url: str | None = None,
) -> tuple[str, str, int | None, str]:
    browser_fallback_enabled = list_browser_fallback_enabled()
    solver_requested = (
        captcha_solver_enabled(default=browser_fallback_enabled)
        if solver_enabled is None
        else bool(solver_enabled)
    )
    effective_referer_url = str(referer_url or "").strip() or _default_list_referer_url(target_url)
    try:
        response = http.get(
            target_url,
            headers=build_navigation_headers(
                target_url=target_url,
                user_agent=user_agent,
                referer_url=effective_referer_url,
            ),
            timeout=list_http_timeout_seconds(),
            allow_redirects=True,
        )
        response.raise_for_status()
        if is_challenge_page(response.text, response.url):
            if not browser_fallback_enabled:
                if solver_requested:
                    try:
                        login_required = is_login_page(response.text, response.url)
                        request_captcha_solver(
                            cdp_endpoint,
                            target_url if login_required else (response.url or target_url),
                            api_base_url=api_base_url,
                            manual_only=login_required,
                        )
                    except Exception:
                        pass
                return response.text, response.url, response.status_code, "http_cookie_challenge"
            browser_page = recover_browser_list_page_after_challenge(
                cdp_endpoint,
                target_url,
                fetch_browser_list_page(cdp_endpoint, target_url),
                solver_enabled=solver_requested,
                api_base_url=api_base_url,
            )
            if browser_page is not None:
                html, final_url = browser_page
                return html, final_url, None, "browser_page_after_http_challenge"
        return response.text, response.url, response.status_code, "http_cookie"
    except requests.RequestException:
        if not browser_fallback_enabled:
            raise
        browser_page = recover_browser_list_page_after_challenge(
            cdp_endpoint,
            target_url,
            fetch_browser_list_page(cdp_endpoint, target_url),
            solver_enabled=solver_requested,
            api_base_url=api_base_url,
        )
        if browser_page is None:
            raise
        html, final_url = browser_page
        return html, final_url, None, "browser_page"


def fetch_detail_with_browser(seed: dict[str, Any], *, cdp_endpoint: str) -> tuple[str, str, int, str]:
    from playwright.sync_api import sync_playwright

    detail_url = seed.get("url")
    if not detail_url:
        raise RuntimeError("seed missing detail url")
    with sync_playwright() as p:
        browser = connect_browser_over_cdp(p, cdp_endpoint)
        try:
            if not browser.contexts:
                raise RuntimeError("attached browser has no contexts")
            context = browser.contexts[0]
            page = context.new_page()
            preserve_challenge_page = False
            try:
                response = page.goto(detail_url, wait_until="domcontentloaded", timeout=90000)
                html = _wait_for_detail_ready(page)
                final_url = page.url
                if response and response.status >= 400:
                    raise RuntimeError(f"browser detail request returned HTTP {response.status}")
                if is_challenge_page(html, final_url):
                    preserve_challenge_page = True
                    raise RuntimeError("browser detail request returned anti-bot challenge")
                return html, final_url, len(html.encode("utf-8")), "browser_navigation"
            finally:
                if not preserve_challenge_page:
                    page.close()
        finally:
            detach_attached_cdp_browser(browser)


def fetch_detail_html(
    http: requests.Session,
    seed: dict[str, Any],
    browser_pages: dict[str, tuple[str, str]],
    *,
    cdp_endpoint: str,
    referer_url: str,
    user_agent: str | None = None,
) -> tuple[str, str, int, str]:
    browserless_seed_probe = _browserless_seed_probe()
    seed_id = str(seed.get("id"))
    if seed_id in browser_pages:
        html, final_url = browser_pages[seed_id]
        return html, final_url, len(html.encode("utf-8")), "open_browser_page"

    detail_url = seed.get("url")
    response = http.get(
        detail_url,
        headers=build_navigation_headers(
            target_url=str(detail_url),
            user_agent=str(user_agent or getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT)),
            referer_url=referer_url,
        ),
        timeout=60,
        allow_redirects=True,
    )
    response.raise_for_status()
    html = response.text
    if is_challenge_page(html, response.url):
        if not detail_browser_fallback_enabled():
            raise RuntimeError(f"HTTP detail request returned anti-bot challenge: {response.url}")
        return fetch_detail_with_browser(seed, cdp_endpoint=cdp_endpoint)
    return html, response.url, len(response.content), "http_cookie"


def risk_aliases(item: dict[str, Any]) -> None:
    risk_payload = item.get("avm_risk_features")
    if not isinstance(risk_payload, dict):
        return
    for key, value in risk_payload.items():
        if has_value(value):
            item.setdefault(key, value)
    if risk_payload.get("community_name") and not item.get("所属小区"):
        item["所属小区"] = risk_payload["community_name"]


def build_description_audit(html: str, item_dir: Path) -> dict[str, Any]:
    from src import llm_helper

    audit: dict[str, Any] = {
        "area_sqm": None,
        "text_len": 0,
        "has_area_marker": False,
        "text_path": None,
    }
    desc_text = llm_helper.fetch_description_data_text(html)
    if not desc_text:
        return audit
    desc_path = item_dir / "description-data.txt"
    desc_path.write_text(desc_text, encoding="utf-8")
    area = llm_helper.extract_area_from_text(desc_text)
    audit["area_sqm"] = area
    audit["text_len"] = len(desc_text)
    audit["has_area_marker"] = area is not None
    audit["text_path"] = str(desc_path)
    return audit


def selected_summary(
    *,
    seed: dict[str, Any],
    html: str,
    final_url: str,
    detail_bytes: int,
    fetch_method: str,
    extracted: dict[str, Any],
    final_item: dict[str, Any],
    description_data: dict[str, Any],
) -> dict[str, Any]:
    location = as_dict(final_item.get("location"))
    source = as_dict(final_item.get("source"))
    auction = as_dict(final_item.get("auction"))
    prop = as_dict(final_item.get("property"))
    risk_features = as_dict(final_item.get("avm_risk_features"))
    return {
        "item_id": str(seed.get("id")),
        "fetch": {
            "method": fetch_method,
            "detail_final_url": final_url,
            "detail_html_bytes": detail_bytes,
            "html_has_description_data": "description-data" in html,
            "html_has_challenge": is_challenge_page(html, final_url),
        },
        "trusted_seed": {
            "title": seed.get("title"),
            "currentPrice": seed.get("currentPrice"),
            "initialPrice": seed.get("initialPrice"),
            "auction_date": seed.get("auction_date"),
            "status": seed.get("status"),
            "bidCount": seed.get("bidCount"),
            "applyCount": seed.get("applyCount"),
        },
        "final_core": {
            "id": final_item.get("id"),
            "source_item_id": pick_first(final_item.get("source_item_id"), source.get("source_item_id")),
            "source_url": pick_first(final_item.get("source_url"), source.get("source_url"), final_item.get("原始网站")),
            "title": pick_first(final_item.get("title"), final_item.get("标题"), source.get("source_title")),
            "is_processed": final_item.get("is_processed"),
            "detail_captured": final_item.get("detail_captured"),
        },
        "location_and_stable_index": {
            "full_address": pick_first(final_item.get("完整地址"), final_item.get("full_address"), location.get("full_address"), final_item.get("地点")),
            "city": pick_first(final_item.get("城市"), final_item.get("city"), location.get("city")),
            "district": pick_first(final_item.get("区"), final_item.get("district"), location.get("district")),
            "business_area": pick_first(final_item.get("最靠近商圈"), final_item.get("business_area"), location.get("business_area")),
            "community_name": pick_first(location.get("community_name"), final_item.get("所属小区"), final_item.get("community_name")),
            "community_name_source": pick_first(location.get("community_name_source"), final_item.get("community_name_source")),
            "community_name_confidence": pick_first(location.get("community_name_confidence"), final_item.get("community_name_confidence")),
            "community_stable_key": pick_first(location.get("community_stable_key"), final_item.get("community_stable_key")),
        },
        "auction_and_property": {
            "transaction_price": pick_first(final_item.get("成交价格"), final_item.get("transaction_price"), auction.get("transaction_price")),
            "starting_price": pick_first(final_item.get("起拍价格"), final_item.get("starting_price"), auction.get("starting_price")),
            "evaluation_price": pick_first(final_item.get("市场评估价"), auction.get("evaluation_price")),
            "deposit": pick_first(final_item.get("保证金"), final_item.get("deposit"), auction.get("deposit")),
            "auction_date": pick_first(final_item.get("交易时间"), final_item.get("auction_date"), auction.get("auction_date")),
            "bid_count": pick_first(final_item.get("出价次数"), final_item.get("bid_count"), auction.get("bid_count")),
            "apply_count": pick_first(final_item.get("竞拍人数"), final_item.get("apply_count"), auction.get("apply_count")),
            "area_sqm": pick_first(final_item.get("建筑面积"), final_item.get("area_sqm"), prop.get("area_sqm")),
            "gross_area_sqm": prop.get("gross_area_sqm"),
            "ownership_share_ratio": pick_first(final_item.get("产权份额比例"), prop.get("ownership_share_ratio")),
            "unit_price": pick_first(final_item.get("单价"), prop.get("unit_price")),
        },
        "description_data": description_data,
        "ai_extracted_raw_core": {
            "id": extracted.get("id"),
            "标题": extracted.get("标题"),
            "完整地址": extracted.get("完整地址"),
            "所属小区": extracted.get("所属小区"),
            "城市": extracted.get("城市"),
            "区": extracted.get("区"),
            "最靠近商圈": extracted.get("最靠近商圈"),
            "建筑面积": extracted.get("建筑面积"),
            "成交价格": extracted.get("成交价格"),
            "单价": extracted.get("单价"),
        },
        "risk_sample": {
            "community_name": risk_features.get("community_name"),
            "housing_type": risk_features.get("housing_type"),
            "floor_level": risk_features.get("floor_level"),
            "evidence_source": risk_features.get("evidence_source"),
            "extraction_confidence": risk_features.get("extraction_confidence"),
        },
    }


def raw_detail_summary(
    *,
    seed: dict[str, Any],
    html: str,
    final_url: str,
    detail_bytes: int,
    fetch_method: str,
    description_data: dict[str, Any],
    item_dir: Path,
) -> dict[str, Any]:
    return {
        "item_id": str(seed.get("id")),
        "detail_capture_mode": "raw",
        "fetch": {
            "method": fetch_method,
            "detail_final_url": final_url,
            "detail_html_bytes": detail_bytes,
            "html_has_description_data": "description-data" in html,
            "html_has_challenge": is_challenge_page(html, final_url),
        },
        "trusted_seed": {
            "title": seed.get("title"),
            "currentPrice": seed.get("currentPrice"),
            "initialPrice": seed.get("initialPrice"),
            "auction_date": seed.get("auction_date"),
            "status": seed.get("status"),
            "bidCount": seed.get("bidCount"),
            "applyCount": seed.get("applyCount"),
        },
        "final_core": {
            "id": seed.get("id"),
            "source_item_id": pick_first(seed.get("source_item_id"), seed.get("item_id"), seed.get("id")),
            "source_url": pick_first(final_url, seed.get("url"), seed.get("source_url")),
            "title": seed.get("title"),
            "is_processed": False,
            "detail_captured": True,
        },
        "description_data": description_data,
        "artifacts": {
            "seed_json_path": str(item_dir / "seed.json"),
            "detail_html_path": str(item_dir / "detail.html"),
            "description_json_path": str(item_dir / "description-data.json"),
            "description_text_path": description_data.get("text_path"),
            "selected_json_path": str(item_dir / "selected.json"),
        },
    }


def analyze_raw_item(
    item_id: str,
    *,
    output_dir: Path,
    do_risk: bool = False,
) -> dict[str, Any]:
    from src import llm_helper
    from src.avm.collection_template import sync_collection_record
    from src.collection.detail_service import DetailCollectionService

    seed_id = str(item_id)
    item_dir = output_dir / seed_id
    seed_path = item_dir / "seed.json"
    detail_html_path = item_dir / "detail.html"
    description_json_path = item_dir / "description-data.json"
    selected_json_path = item_dir / "selected.json"

    if not detail_html_path.exists():
        raise FileNotFoundError(f"raw detail html not found: {detail_html_path}")

    seed = load_json(seed_path) if seed_path.exists() else {"id": seed_id, "item_id": seed_id, "source_item_id": seed_id}
    html = detail_html_path.read_text(encoding="utf-8")
    if description_json_path.exists():
        description_data = load_json(description_json_path)
    else:
        description_data = build_description_audit(html, item_dir)
        write_json(description_json_path, description_data)

    raw_selected = load_json(selected_json_path) if selected_json_path.exists() else {}
    effective_seed, analysis_text = _build_detail_analysis_input(
        item_id=seed_id,
        item_dir=item_dir,
        seed=seed,
        html=html,
        selected=raw_selected,
        description_data=description_data,
    )
    fetch = as_dict(raw_selected.get("fetch"))
    final_url = pick_first(
        fetch.get("detail_final_url"),
        effective_seed.get("url"),
        effective_seed.get("source_url"),
        effective_seed.get("原始网站"),
        "",
    )
    detail_bytes = fetch.get("detail_html_bytes")
    if not isinstance(detail_bytes, int):
        detail_bytes = len(html.encode("utf-8"))
    fetch_method = str(fetch.get("method") or "raw_artifact")

    extracted = json.loads(llm_helper.extract_auction_data(analysis_text, item_id=seed_id))
    extracted["id"] = int(seed_id) if seed_id.isdigit() else seed_id
    extracted["source_item_id"] = seed_id
    DetailCollectionService._preserve_seed_values(extracted, effective_seed)
    write_json(item_dir / "extracted.json", extracted)

    risk = {}
    if do_risk:
        risk = llm_helper.extract_avm_risk_features(html, item_id=seed_id) or {}
        write_json(item_dir / "risk.json", risk)

    combined = dict(effective_seed)
    combined.update(extracted)
    DetailCollectionService._preserve_seed_values(combined, effective_seed)
    combined["id"] = int(seed_id) if seed_id.isdigit() else seed_id
    combined["source_item_id"] = seed_id
    combined["source_url"] = final_url
    combined["原始网站"] = final_url
    combined.setdefault("source_platform", "taobao_sf")
    combined["detail_captured"] = True
    combined["is_processed"] = True
    if risk:
        combined["avm_risk_features"] = risk
        risk_aliases(combined)

    final_item = sync_collection_record(combined)
    write_json(item_dir / "final.json", final_item)
    selected = selected_summary(
        seed=seed,
        html=html,
        final_url=final_url,
        detail_bytes=detail_bytes,
        fetch_method=fetch_method,
        extracted=extracted,
        final_item=final_item,
        description_data=description_data,
    )
    selected["detail_capture_mode"] = "ai_finalized_from_raw"
    selected["raw_selected_json_path"] = str(selected_json_path) if selected_json_path.exists() else None
    write_json(selected_json_path, selected)
    return selected


def process_item(
    http: requests.Session,
    seed: dict[str, Any],
    browser_pages: dict[str, tuple[str, str]],
    *,
    config: LiveSmokeConfig,
) -> dict[str, Any]:
    from src.avm.collection_template import sync_collection_record
    from src.collection.detail_service import DetailCollectionService

    seed_id = str(seed.get("id"))
    item_dir = config.output_dir / seed_id
    item_dir.mkdir(parents=True, exist_ok=True)
    write_json(item_dir / "seed.json", seed)

    html, final_url, detail_bytes, fetch_method = fetch_detail_html(
        http,
        seed,
        browser_pages,
        cdp_endpoint=config.cdp_endpoint,
        referer_url=str(seed.get("source_page_url") or config.target_url),
        user_agent=resolve_runtime_user_agent(config.cdp_endpoint),
    )
    (item_dir / "detail.html").write_text(html, encoding="utf-8")
    description_data = build_description_audit(html, item_dir)
    write_json(item_dir / "description-data.json", description_data)

    if config.raw_only:
        selected = raw_detail_summary(
            seed=seed,
            html=html,
            final_url=final_url,
            detail_bytes=detail_bytes,
            fetch_method=fetch_method,
            description_data=description_data,
            item_dir=item_dir,
        )
        write_json(item_dir / "selected.json", selected)
        return selected

    from src import llm_helper

    extracted = json.loads(llm_helper.extract_auction_data(html, item_id=seed_id))
    extracted["id"] = int(seed_id) if seed_id.isdigit() else seed_id
    extracted["source_item_id"] = seed_id
    DetailCollectionService._preserve_seed_values(extracted, seed)
    write_json(item_dir / "extracted.json", extracted)

    risk = {}
    if config.do_risk:
        risk = llm_helper.extract_avm_risk_features(html, item_id=seed_id) or {}
        write_json(item_dir / "risk.json", risk)

    combined = dict(seed)
    combined.update(extracted)
    DetailCollectionService._preserve_seed_values(combined, seed)
    combined["id"] = int(seed_id) if seed_id.isdigit() else seed_id
    combined["source_item_id"] = seed_id
    combined["source_url"] = final_url
    combined["原始网站"] = final_url
    combined.setdefault("source_platform", "taobao_sf")
    combined["detail_captured"] = True
    combined["is_processed"] = True
    if risk:
        combined["avm_risk_features"] = risk
        risk_aliases(combined)

    final_item = sync_collection_record(combined)
    write_json(item_dir / "final.json", final_item)
    selected = selected_summary(
        seed=seed,
        html=html,
        final_url=final_url,
        detail_bytes=detail_bytes,
        fetch_method=fetch_method,
        extracted=extracted,
        final_item=final_item,
        description_data=description_data,
    )
    write_json(item_dir / "selected.json", selected)
    return selected


def run_live_smoke(config: LiveSmokeConfig) -> int:
    if not config.raw_only and (not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY")):
        raise RuntimeError("OPENAI_BASE_URL/OPENAI_API_KEY must be set in this subprocess")

    browserless_seed_probe = _browserless_seed_probe()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    llm_preflight_result = None
    if config.llm_preflight_enabled and not config.raw_only:
        llm_preflight_result = preflight_llm_backend(timeout=config.llm_preflight_timeout_seconds)
        print(f"[SMOKE] LLM preflight ok: {json.dumps(llm_preflight_result, ensure_ascii=False)}")

    resume_state_path = config.resume_state_path or (config.output_dir / DEFAULT_RESUME_STATE_FILENAME)
    resume_state = load_resume_state(resume_state_path) if config.resume_enabled else new_resume_state()
    started_at = time.time()
    cookies = export_cookies(config.cdp_endpoint)
    http = build_http(cookies)
    list_collection = collect_list_union(browserless_seed_probe, http, config)
    all_items = list_collection["items"]
    list_union = list_collection["list_union"]
    first_fetch = list_collection["first_fetch"]
    list_status = first_fetch.get("list_status")
    list_final_url = first_fetch.get("list_final_url") or config.target_url
    list_fetch_method = first_fetch.get("list_fetch_method")
    list_item_count = first_fetch.get("list_item_count")
    artifact_completed_ids: list[str] = []
    if config.resume_enabled:
        artifact_completed_ids = hydrate_resume_state_from_artifacts(
            resume_state,
            all_items,
            output_dir=config.output_dir,
        )
        if artifact_completed_ids:
            save_resume_state(resume_state_path, resume_state)
        items, skipped_completed_ids = select_resume_candidates(
            all_items,
            resume_state,
            limit=config.max_attempts,
        )
    else:
        items = all_items[: config.max_attempts]
        skipped_completed_ids = []
    if not items:
        summary_path = config.output_dir / "summary.json"
        summary = {
            "summary_path": str(summary_path),
            "target_url": config.target_url,
            "list_status": list_status,
            "list_final_url": list_final_url,
            "list_fetch_method": list_fetch_method,
            "list_item_count": list_item_count,
            "list_union": list_union,
            "eligible_done_item_count": len(all_items),
            "target_success": config.target_success,
            "max_attempts": config.max_attempts,
            "attempted_items": 0,
            "processed_items": 0,
            "error_count": 0,
            "cookie_count": len(cookies),
            "duration_seconds": round(time.time() - started_at, 2),
            "resume_enabled": bool(config.resume_enabled),
            "resume_state_path": str(resume_state_path) if config.resume_enabled else None,
            "skipped_completed_items": len(skipped_completed_ids),
            "skipped_completed_item_ids": skipped_completed_ids[:50],
            "artifact_completed_items": len(artifact_completed_ids),
            "artifact_completed_item_ids": artifact_completed_ids[:50],
            "llm_preflight": llm_preflight_result,
            "no_candidate_reason": "all_candidates_already_completed" if skipped_completed_ids else "no_eligible_done_items",
            "results": [],
            "errors": [],
        }
        enriched = attach_area_artifacts(summary, output_dir=config.output_dir)
        queue = build_area_followup_queue(enriched, artifact_root=config.output_dir)
        write_json(config.output_dir / "area_followup_queue.json", queue)
        write_json(summary_path, enriched)
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
        return 0 if skipped_completed_ids else 1

    browser_pages = load_open_browser_pages(config.cdp_endpoint)
    results = []
    errors = []
    for index, seed in enumerate(items, start=1):
        if len(results) >= config.target_success:
            break
        seed_id = str(seed.get("id"))
        try:
            print(f"[SMOKE] {index}/{len(items)} item={seed_id}")
            if config.resume_enabled:
                mark_resume_item(
                    resume_state,
                    seed_id,
                    status="in_progress",
                    metadata={
                        "source_url": seed.get("url"),
                        "source_page_url": seed.get("source_page_url"),
                        "title": seed.get("title"),
                        "target_url": config.target_url,
                        "list_location_code": seed.get("list_location_code"),
                        "list_category": seed.get("list_category"),
                        "list_st_param": seed.get("list_st_param"),
                        "list_page": seed.get("list_page"),
                    },
                )
                save_resume_state(resume_state_path, resume_state)
            selected = process_item(http, seed, browser_pages, config=config)
            results.append(selected)
            if config.resume_enabled:
                mark_resume_item(
                    resume_state,
                    seed_id,
                    status=RESUME_COMPLETED_STATUS,
                    metadata={
                        "source_url": pick_first(selected.get("final_core", {}).get("source_url"), seed.get("url")),
                        "source_page_url": seed.get("source_page_url"),
                        "title": pick_first(selected.get("final_core", {}).get("title"), seed.get("title")),
                        "selected_json_path": str(config.output_dir / seed_id / "selected.json"),
                        "final_json_path": str(config.output_dir / seed_id / "final.json"),
                        "has_completed_artifacts": has_completed_item_artifacts(config.output_dir, seed_id),
                        "list_location_code": seed.get("list_location_code"),
                        "list_category": seed.get("list_category"),
                        "list_st_param": seed.get("list_st_param"),
                        "list_page": seed.get("list_page"),
                    },
                )
                save_resume_state(resume_state_path, resume_state)
        except Exception as exc:
            errors.append({"item_id": seed_id, "error": repr(exc), "traceback": traceback.format_exc()})
            write_json(config.output_dir / f"{seed_id}.error.json", errors[-1])
            if config.resume_enabled:
                mark_resume_item(
                    resume_state,
                    seed_id,
                    status="failed",
                    metadata={
                        "source_url": seed.get("url"),
                        "source_page_url": seed.get("source_page_url"),
                        "title": seed.get("title"),
                        "target_url": config.target_url,
                        "list_location_code": seed.get("list_location_code"),
                        "list_category": seed.get("list_category"),
                        "list_st_param": seed.get("list_st_param"),
                        "list_page": seed.get("list_page"),
                        "error": repr(exc),
                    },
                )
                save_resume_state(resume_state_path, resume_state)
            print(f"[SMOKE][ERROR] item={seed_id}: {exc}")
        time.sleep(1)

    summary_path = config.output_dir / "summary.json"
    summary = {
        "summary_path": str(summary_path),
        "target_url": config.target_url,
        "list_status": list_status,
        "list_final_url": list_final_url,
        "list_fetch_method": list_fetch_method,
        "list_item_count": list_item_count,
        "list_union": list_union,
        "eligible_done_item_count": len(all_items),
        "target_success": config.target_success,
        "max_attempts": config.max_attempts,
        "attempted_items": len(results) + len(errors),
        "processed_items": len(results),
        "error_count": len(errors),
        "cookie_count": len(cookies),
        "duration_seconds": round(time.time() - started_at, 2),
        "resume_enabled": bool(config.resume_enabled),
        "resume_state_path": str(resume_state_path) if config.resume_enabled else None,
        "skipped_completed_items": len(skipped_completed_ids),
        "skipped_completed_item_ids": skipped_completed_ids[:50],
        "artifact_completed_items": len(artifact_completed_ids),
        "artifact_completed_item_ids": artifact_completed_ids[:50],
        "llm_preflight": llm_preflight_result,
        "results": results,
        "errors": errors,
    }
    enriched = attach_area_artifacts(summary, output_dir=config.output_dir)
    queue = build_area_followup_queue(enriched, artifact_root=config.output_dir)
    write_json(config.output_dir / "area_followup_queue.json", queue)
    write_json(summary_path, enriched)
    print(json.dumps(enriched, ensure_ascii=False, indent=2))
    return 0 if len(results) >= min(config.target_success, len(items)) else 1


def run_loop(
    config: LiveSmokeConfig,
    *,
    max_runs: int | None,
    interval_seconds: float,
) -> dict[str, Any]:
    run_count = 0
    exit_codes: list[int] = []
    errors: list[dict[str, Any]] = []
    started_at = time.time()
    while max_runs is None or run_count < max_runs:
        run_count += 1
        try:
            exit_codes.append(run_live_smoke(config))
        except Exception as exc:
            exit_codes.append(1)
            error = {
                "run": run_count,
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "timestamp": utc_now_iso(),
            }
            errors.append(error)
            if len(errors) > 50:
                errors = errors[-50:]
            print(json.dumps({"loop_error": error}, ensure_ascii=False, indent=2), flush=True)
        if max_runs is not None and run_count >= max_runs:
            break
        if interval_seconds > 0:
            time.sleep(interval_seconds)
    return {
        "run_count": run_count,
        "exit_codes": exit_codes,
        "ok": all(code == 0 for code in exit_codes),
        "duration_seconds": round(time.time() - started_at, 2),
        "resume_enabled": bool(config.resume_enabled),
        "resume_state_path": str(config.resume_state_path or (config.output_dir / DEFAULT_RESUME_STATE_FILENAME))
        if config.resume_enabled
        else None,
        "errors": errors,
    }


def write_followup_from_summary(summary_path: Path, *, output_dir: Path, write_followup_only: bool) -> int:
    summary = load_json(summary_path)
    if isinstance(summary, dict):
        summary.setdefault("summary_path", str(summary_path))
    else:
        raise RuntimeError(f"summary must be a JSON object: {summary_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    enriched = attach_area_artifacts(summary, output_dir=output_dir)
    queue = build_area_followup_queue(enriched, artifact_root=output_dir)
    queue_path = output_dir / "area_followup_queue.json"
    write_json(queue_path, queue)
    if not write_followup_only:
        write_json(output_dir / "summary.json", enriched)
    print(
        json.dumps(
            {
                "summary_path": str(summary_path),
                "area_stats": enriched["area_stats"],
                "area_followup_queue_path": str(queue_path),
                "area_followup_job_count": queue["job_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a real Taobao judicial-auction detail live smoke.")
    parser.add_argument("--from-summary", type=Path, help="Generate area follow-up artifacts from an existing summary.json without live network crawling.")
    parser.add_argument("--write-followup-only", action="store_true", help="With --from-summary, only write area_followup_queue.json and leave summary.json unchanged.")
    parser.add_argument("--output-dir", type=Path, help="Artifact directory. Defaults to output/live_batch_smoke, or the --from-summary parent.")
    parser.add_argument("--cdp-endpoint", default=os.environ.get("LIVE_BATCH_SMOKE_CDP", DEFAULT_CDP_ENDPOINT))
    parser.add_argument("--url", default=os.environ.get("LIVE_BATCH_SMOKE_URL", DEFAULT_TARGET_URL))
    parser.add_argument(
        "--target-success",
        type=positive_int,
        default=int(os.environ.get("LIVE_BATCH_SMOKE_TARGET", os.environ.get("LIVE_BATCH_SMOKE_LIMIT", "5"))),
    )
    parser.add_argument("--max-attempts", type=positive_int, default=None)
    parser.add_argument("--risk", action="store_true", default=os.environ.get("LIVE_BATCH_SMOKE_RISK", "0") == "1")
    parser.add_argument(
        "--resume-state",
        type=Path,
        default=os.environ.get("LIVE_BATCH_RESUME_STATE"),
        help="Persistent JSON state used to skip already completed item ids.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_NO_RESUME", "0") == "1",
        help="Disable persistent resume/deduplication state for this run.",
    )
    parser.add_argument("--loop", action="store_true", help="Run batches repeatedly with the same resume state.")
    parser.add_argument("--max-runs", type=positive_int, default=None, help="Stop loop after this many batch runs.")
    parser.add_argument(
        "--loop-interval-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_LOOP_INTERVAL_SECONDS", "300")),
        help="Sleep interval between looped batch runs.",
    )
    parser.add_argument(
        "--list-st-params",
        default=os.environ.get("LIVE_BATCH_LIST_ST_PARAMS"),
        help="Comma-separated Taobao list sort parameters to union before detail collection, e.g. 2,1,0,3,4,5.",
    )
    parser.add_argument(
        "--list-location-codes",
        default=os.environ.get("LIVE_BATCH_LIST_LOCATION_CODES"),
        help="Comma-separated Taobao location_code values to crawl. Defaults to the --url location_code.",
    )
    parser.add_argument(
        "--list-categories",
        default=os.environ.get("LIVE_BATCH_LIST_CATEGORIES"),
        help="Comma-separated Taobao list category path ids. Defaults to the --url category.",
    )
    parser.add_argument(
        "--list-max-pages",
        type=positive_int,
        default=int(os.environ.get("LIVE_BATCH_LIST_MAX_PAGES", "1")),
        help="Maximum page number to fetch for each location/category/sort combination.",
    )
    parser.add_argument(
        "--no-list-stop-on-empty",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_LIST_STOP_ON_EMPTY", "1").strip().lower() in {"0", "false", "no", "off"},
        help="Do not stop later pages for a location/category/sort after an empty page is seen.",
    )
    parser.add_argument(
        "--llm-preflight",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_LLM_PREFLIGHT", "0").strip().lower() in {"1", "true", "yes", "on"},
        help="Probe the OpenAI-compatible backend before processing detail items; aborts the batch on connection/TLS/proxy errors.",
    )
    parser.add_argument(
        "--llm-preflight-timeout-seconds",
        type=float,
        default=float(os.environ.get("LIVE_BATCH_LLM_PREFLIGHT_TIMEOUT_SECONDS", "15")),
        help="Timeout for --llm-preflight /models connectivity probe.",
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        default=os.environ.get("LIVE_BATCH_RAW_ONLY", os.environ.get("FAPAI_DETAIL_RAW_ONLY", "0")).strip().lower() in TRUE_VALUES,
        help="Fetch and archive raw detail artifacts without invoking the LLM extraction stage.",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> LiveSmokeConfig:
    output_dir = args.output_dir or DEFAULT_OUTPUT_DIR
    max_attempts = args.max_attempts or int(
        os.environ.get("LIVE_BATCH_SMOKE_MAX_ATTEMPTS", str(max(args.target_success * 3, args.target_success)))
    )
    return LiveSmokeConfig(
        output_dir=output_dir,
        cdp_endpoint=args.cdp_endpoint,
        target_url=args.url,
        target_success=args.target_success,
        max_attempts=max_attempts,
        do_risk=bool(args.risk),
        resume_state_path=args.resume_state,
        resume_enabled=not bool(args.no_resume),
        list_st_params=parse_csv_values(args.list_st_params),
        list_location_codes=parse_csv_values(args.list_location_codes),
        list_categories=parse_csv_values(args.list_categories),
        list_max_pages=int(args.list_max_pages),
        list_stop_on_empty=not bool(args.no_list_stop_on_empty),
        llm_preflight_enabled=bool(args.llm_preflight),
        llm_preflight_timeout_seconds=float(args.llm_preflight_timeout_seconds),
        raw_only=bool(args.raw_only),
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.from_summary:
        output_dir = args.output_dir or args.from_summary.parent
        return write_followup_from_summary(
            args.from_summary,
            output_dir=output_dir,
            write_followup_only=bool(args.write_followup_only),
        )
    config = config_from_args(args)
    if args.loop:
        loop_summary = run_loop(
            config,
            max_runs=args.max_runs,
            interval_seconds=max(0.0, float(args.loop_interval_seconds)),
        )
        print(json.dumps(loop_summary, ensure_ascii=False, indent=2))
        return 0 if loop_summary["ok"] else 1
    return run_live_smoke(config)


if __name__ == "__main__":
    raise SystemExit(main())
