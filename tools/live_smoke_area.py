from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403


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

__all__ = ('as_dict', 'parse_positive_number', 'is_positive_number', 'result_area_value', 'result_description_area_value', 'compute_area_stats', '_missing_fields_for_area_job', '_artifact_path_if_exists', '_load_artifact_json_if_exists', '_area_followup_priority', '_build_area_followup_job', 'build_area_followup_queue', 'attach_area_artifacts')
