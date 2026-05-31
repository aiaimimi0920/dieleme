#!/usr/bin/env python3
"""Export auction records to Excel.

Prefer the PostgreSQL fact store when available, but keep file-based fallback for
standalone usage.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.avm_data_loader import iter_analysis_ready_rows

DATAS_DIR = REPO_ROOT / "datas"
OUTPUT_FILE = REPO_ROOT / f"fapaifang_data_{datetime.now().strftime('%Y%m%d')}.xlsx"

COLUMNS = [
    "id",
    "title",
    "评估价",
    "起拍价",
    "成交价",
    "面积",
    "单价",
    "省份",
    "城市",
    "区",
    "地点",
    "所属小区",
    "最靠近商圈",
    "交易时间",
    "竞拍人数",
    "出价人数",
    "url",
    "json_file",
]

SKIP_FILE_NAMES = {
    "model_config.json",
    "monitor_state.json",
    "all_locations.json",
    "collected_locations.json",
    "mock_data.json",
}


def _parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _source_reference(item: dict[str, Any]) -> str:
    source = (
        str(item.get("__file_path") or "").strip()
        or str(item.get("json_file") or "").strip()
        or str(item.get("list_payload_path") or "").strip()
        or str(item.get("detail_archive_path") or "").strip()
    )
    if source:
        return source
    return "db://property_listing"


def _should_skip_row(item: dict[str, Any]) -> bool:
    source_ref = _source_reference(item)
    return any(skip_name in source_ref for skip_name in SKIP_FILE_NAMES)


def _normalize_export_row(item: dict[str, Any]) -> dict[str, Any] | None:
    item_id = item.get("id") or item.get("唯一id") or item.get("item_id")
    if not item_id:
        return None

    price = _parse_number(item.get("成交价格") or item.get("transaction_price") or item.get("起拍价格") or item.get("starting_price"))
    area = _parse_number(item.get("建筑面积") or item.get("area_sqm"))
    location = item.get("地点") or item.get("full_address")
    if not location or not price or not area or area <= 0:
        return None

    return {
        "id": str(item_id),
        "title": item.get("title") or item.get("source_title") or location,
        "评估价": item.get("市场评估价") or item.get("evaluation_price"),
        "起拍价": item.get("起拍价格") or item.get("starting_price"),
        "成交价": item.get("成交价格") or item.get("transaction_price"),
        "面积": item.get("建筑面积") or item.get("area_sqm"),
        "单价": round(price / area, 2),
        "省份": item.get("省份") or item.get("province"),
        "城市": item.get("城市") or item.get("city"),
        "区": item.get("区") or item.get("district"),
        "地点": location,
        "所属小区": item.get("所属小区") or item.get("community_name"),
        "最靠近商圈": item.get("最靠近商圈") or item.get("business_area"),
        "交易时间": item.get("交易时间") or item.get("auction_date"),
        "竞拍人数": item.get("竞拍人数") or item.get("apply_count"),
        "出价人数": item.get("出价人数") or item.get("bidder_count"),
        "url": item.get("原始网站") or item.get("url") or item.get("source_url"),
        "json_file": _source_reference(item),
    }


def load_data(data_dir: str | Path = DATAS_DIR) -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    scanned_rows = 0
    for item in iter_analysis_ready_rows(Path(data_dir), prefer_db=True):
        scanned_rows += 1
        if not isinstance(item, dict) or _should_skip_row(item):
            continue

        normalized = _normalize_export_row(item)
        if normalized is None:
            continue

        item_id = normalized["id"]
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        all_items.append(normalized)

    print(f"[INFO] Loaded {scanned_rows} raw rows from preferred source.")
    return all_items


def main() -> None:
    print("Starting data export...")
    data = load_data()
    print(f"[INFO] Loaded {len(data)} unique items.")

    if not data:
        print("[WARN] No data found to export.")
        return

    df = pd.DataFrame(data)
    final_cols = [column for column in COLUMNS if column in df.columns]
    missing_cols = set(COLUMNS) - set(final_cols)
    if missing_cols:
        print(f"[INFO] Skipped missing columns: {missing_cols}")
    df = df[final_cols]

    try:
        print(f"[INFO] Saving to {OUTPUT_FILE}...")
        df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
        print(f"[SUCCESS] Export complete! File saved at: {OUTPUT_FILE}")
    except ImportError:
        print("[ERROR] 'openpyxl' or 'pandas' library missing.")
        print("Please install them using: pip install pandas openpyxl")
    except Exception as exc:
        print(f"[ERROR] Export failed: {exc}")


if __name__ == "__main__":
    main()
