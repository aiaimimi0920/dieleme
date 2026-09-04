from __future__ import annotations

import json

import sys

import types

from pathlib import Path

from urllib.parse import parse_qs, urlparse

import pytest

from src import llm_helper

from tools import live_batch_smoke

from tools import taobao_login_health

def _result(
    item_id: str,
    *,
    area_sqm,
    unit_price,
    desc_area,
    community_name: str = "贡院西街片区",
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "fetch": {
            "detail_final_url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
            "detail_html_bytes": 102950,
            "html_has_description_data": True,
        },
        "trusted_seed": {
            "title": f"标的 {item_id}",
            "currentPrice": 11632000,
            "initialPrice": 8200000,
            "auction_date": "2026-01-01 10:00:00",
            "bidCount": 421,
            "applyCount": 9,
        },
        "final_core": {
            "source_url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
            "title": f"标的 {item_id}",
        },
        "location_and_stable_index": {
            "full_address": "北京市东城区贡院西街某号",
            "city": "北京市",
            "district": "东城区",
            "business_area": "建国门",
            "community_name": community_name,
            "community_stable_key": f"collector::北京市::东城区::{community_name}",
        },
        "auction_and_property": {
            "transaction_price": 11632000,
            "starting_price": 8200000,
            "auction_date": "2026-01-01 10:00:00",
            "bid_count": 421,
            "apply_count": 9,
            "area_sqm": area_sqm,
            "gross_area_sqm": area_sqm,
            "unit_price": unit_price,
        },
        "ai_extracted_raw_core": {
            "建筑面积": desc_area,
            "单价": unit_price,
        },
        "description_data": {
            "area_sqm": desc_area,
            "text_len": 48 if desc_area is None else 300,
            "has_area_marker": desc_area is not None,
        },
    }

__all__ = [name for name in globals() if not name.startswith("__")]
