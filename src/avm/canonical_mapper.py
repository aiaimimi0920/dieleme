"""Raw -> canonical field mapper based on AVM schema contract."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from .normalizers import parse_area_sqm, parse_price_to_yuan


FIELD_CANDIDATES = {
    "item_id": ["item_id", "id", "source_item_id"],
    "source_item_id": ["source_item_id", "id", "item_id"],
    "source_url": ["source_url", "url", "原始网站"],
    "transaction_price": ["transaction_price", "成交价格"],
    "starting_price": ["starting_price", "起拍价格"],
    "area_sqm": ["area_sqm", "建筑面积"],
    "auction_date": ["auction_date", "交易时间"],
}

CN_TIMEZONE = timezone(timedelta(hours=8))


def _first_present(raw_item: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in raw_item and raw_item[key] not in (None, ""):
            return raw_item[key]
    return None


def _normalize_datetime(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    # Unix timestamp (seconds / milliseconds)
    try:
        ts = float(text)
        if ts > 10**12:
            ts /= 1000
        if ts > 0 and ts < 10**11:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(CN_TIMEZONE)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    text = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("T", " ")
        .replace("Z", "")
    )

    known_formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ]
    for fmt in known_formats:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt in {"%Y-%m-%d", "%Y/%m/%d"}:
                dt = dt.replace(hour=0, minute=0, second=0)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return None


def map_raw_to_canonical(raw_item: dict) -> dict:
    """Map one raw item into AVM canonical schema fields."""
    item_id = _first_present(raw_item, FIELD_CANDIDATES["item_id"])
    source_item_id = _first_present(raw_item, FIELD_CANDIDATES["source_item_id"])
    source_url = _first_present(raw_item, FIELD_CANDIDATES["source_url"])

    canonical = {
        "item_id": str(item_id) if item_id is not None else None,
        "source_item_id": str(source_item_id) if source_item_id is not None else None,
        "source_url": str(source_url).strip() if source_url is not None else None,
        "transaction_price": parse_price_to_yuan(
            _first_present(raw_item, FIELD_CANDIDATES["transaction_price"])
        ),
        "starting_price": parse_price_to_yuan(
            _first_present(raw_item, FIELD_CANDIDATES["starting_price"])
        ),
        "area_sqm": parse_area_sqm(_first_present(raw_item, FIELD_CANDIDATES["area_sqm"])),
        "auction_date": _normalize_datetime(
            _first_present(raw_item, FIELD_CANDIDATES["auction_date"])
        ),
    }
    return canonical
