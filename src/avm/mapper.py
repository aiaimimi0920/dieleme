"""AVM 原始字段到标准字段的映射逻辑。"""

from __future__ import annotations

from typing import Any

from .normalize import parse_area_sqm, parse_money_to_yuan, safe_float, safe_int


PRICE_KEYS = ("成交价格", "起拍价格", "市场评估价")
AREA_KEYS = ("建筑面积", "面积")


def map_avm_record(raw: dict[str, Any]) -> dict[str, Any]:
    """将原始记录映射为标准化结构。"""
    return {
        "id": safe_int(raw.get("id")),
        "deal_price_yuan": parse_money_to_yuan(raw.get("成交价格")),
        "start_price_yuan": parse_money_to_yuan(raw.get("起拍价格")),
        "market_price_yuan": parse_money_to_yuan(raw.get("市场评估价")),
        "area_sqm": parse_area_sqm(raw.get("建筑面积") or raw.get("面积")),
        "bid_count": safe_int(raw.get("出价人数") or raw.get("竞拍人数")),
        "unit_price_yuan_per_sqm": safe_float(raw.get("单价")),
    }
