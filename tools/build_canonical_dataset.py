#!/usr/bin/env python3
"""Build canonical JSONL dataset from datas/**/*.json."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DATAS_DIR = BASE_DIR / "datas"
CANONICAL_DIR = DATAS_DIR / "canonical"
CANONICAL_FILE = CANONICAL_DIR / "canonical.jsonl"
FAILED_FILE = CANONICAL_DIR / "failed_records.jsonl"

# Canonical output keys and their source aliases.
FIELD_ALIASES = {
    "id": ["id", "唯一id"],
    "market_price": ["市场评估价", "market_price"],
    "start_price": ["起拍价格", "起拍价", "initialPrice", "start_price"],
    "deal_price": ["成交价格", "成交价", "deal_price", "currentPrice"],
    "auction_date": ["交易时间", "auction_date"],
    "url": ["原始网站", "url"],
    "is_deal": ["是否成交", "status", "is_deal"],
    "apply_count": ["竞拍人数", "applyCount", "apply_count"],
    "bid_count": ["出价人数", "bidCount", "bid_count"],
    "address": ["地点", "item_address", "address"],
    "community": ["所属小区", "community_name", "community"],
    "province": ["省份", "province"],
    "city": ["城市", "city"],
    "district": ["区", "district"],
    "business_area": ["最靠近商圈", "business_area"],
    "building_area": ["建筑面积", "building_area"],
    "unit_price": ["单价", "unit_price"],
}


class MapperError(ValueError):
    """Record mapping errors for failed_records output."""


def _pick_first(record: dict[str, Any], aliases: list[str]) -> Any:
    for key in aliases:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _to_number(value: Any, *, integer: bool = False) -> float | int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return int(value) if integer else float(value)
    if isinstance(value, (int, float)):
        return int(value) if integer else float(value)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        for token in [",", "¥", "￥", "元", "平方米", "㎡", "m²"]:
            text = text.replace(token, "")
        try:
            num = Decimal(text)
        except InvalidOperation as exc:
            raise MapperError(f"数值格式错误: {value!r}") from exc
        return int(num) if integer else float(num)

    raise MapperError(f"不支持的数值类型: {type(value).__name__}")


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "done", "成交", "已成交"}:
            return True
        if normalized in {"false", "0", "no", "n", "todo", "未成交", "流拍"}:
            return False
    return False


def mapper(record: dict[str, Any]) -> dict[str, Any]:
    """Map raw record to canonical schema."""
    if not isinstance(record, dict):
        raise MapperError("记录不是 JSON object")

    mapped: dict[str, Any] = {}
    for field, aliases in FIELD_ALIASES.items():
        mapped[field] = _pick_first(record, aliases)

    mapped["id"] = _to_number(mapped["id"], integer=True)
    if mapped["id"] is None:
        raise MapperError("缺少 id")

    mapped["market_price"] = _to_number(mapped["market_price"])
    mapped["start_price"] = _to_number(mapped["start_price"])
    mapped["deal_price"] = _to_number(mapped["deal_price"])
    mapped["apply_count"] = _to_number(mapped["apply_count"], integer=True)
    mapped["bid_count"] = _to_number(mapped["bid_count"], integer=True)
    mapped["building_area"] = _to_number(mapped["building_area"])
    mapped["is_deal"] = _to_bool(mapped["is_deal"])

    if mapped["unit_price"] is not None:
        mapped["unit_price"] = _to_number(mapped["unit_price"])
    elif mapped["deal_price"] and mapped["building_area"] and mapped["building_area"] > 0:
        mapped["unit_price"] = round(mapped["deal_price"] / mapped["building_area"], 2)
    else:
        mapped["unit_price"] = 0

    if mapped["url"] is None:
        raise MapperError("缺少 url")

    mapped["source_timestamp"] = datetime.now(timezone.utc).isoformat()
    return mapped


def iter_json_records(file_path: Path) -> Iterable[dict[str, Any]]:
    with file_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            yield item
    else:
        raise MapperError(f"JSON 顶层类型无效: {type(payload).__name__}")


def build_dataset(datas_dir: Path, canonical_file: Path, failed_file: Path) -> tuple[int, int]:
    canonical_file.parent.mkdir(parents=True, exist_ok=True)
    total_success = 0
    total_failed = 0

    json_files = sorted(datas_dir.glob("**/*.json"))

    with canonical_file.open("w", encoding="utf-8") as okf, failed_file.open("w", encoding="utf-8") as failf:
        for file_path in json_files:
            if file_path.parent == canonical_file.parent:
                continue

            relative_path = file_path.relative_to(BASE_DIR).as_posix()
            try:
                records = iter_json_records(file_path)
                for idx, raw_record in enumerate(records):
                    try:
                        canonical_record = mapper(raw_record)
                        canonical_record["_source"] = {
                            "file": relative_path,
                            "index": idx,
                        }
                        okf.write(json.dumps(canonical_record, ensure_ascii=False) + "\n")
                        total_success += 1
                    except Exception as exc:
                        fail_payload = {
                            "source_file": relative_path,
                            "index": idx,
                            "error": str(exc),
                            "raw_record": raw_record,
                        }
                        failf.write(json.dumps(fail_payload, ensure_ascii=False) + "\n")
                        total_failed += 1
            except Exception as exc:
                fail_payload = {
                    "source_file": relative_path,
                    "index": None,
                    "error": f"文件读取失败: {exc}",
                }
                failf.write(json.dumps(fail_payload, ensure_ascii=False) + "\n")
                total_failed += 1

    return total_success, total_failed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build datas/canonical/canonical.jsonl")
    parser.add_argument("--datas-dir", default=str(DATAS_DIR), help="Input datas root directory")
    parser.add_argument("--output", default=str(CANONICAL_FILE), help="Canonical JSONL output path")
    parser.add_argument("--failed-output", default=str(FAILED_FILE), help="Failed records JSONL output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    success, failed = build_dataset(Path(args.datas_dir), Path(args.output), Path(args.failed_output))
    print(f"Done. success={success}, failed={failed}")


if __name__ == "__main__":
    main()
