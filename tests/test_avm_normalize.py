import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.avm.mapper import map_avm_record
from src.avm.normalize import parse_area_sqm, parse_money_to_yuan, safe_float, safe_int


def test_parse_money_to_yuan_mixed_formats():
    assert parse_money_to_yuan("¥1,234,567") == 1234567
    assert parse_money_to_yuan("123.5万") == 1235000
    assert parse_money_to_yuan("￥2.1亿") == 210000000


def test_parse_area_sqm_mixed_formats():
    assert parse_area_sqm("89.6平方米") == 89.6
    assert parse_area_sqm("120㎡") == 120
    assert parse_area_sqm("150.5 m²") == 150.5


def test_safe_number_helpers():
    assert safe_float("¥3,210.5") == 3210.5
    assert safe_int(" 98人 ") == 98
    assert safe_int(None, default=-1) == -1


def test_mapper_uses_normalized_values():
    row = {
        "id": "1001",
        "成交价格": "¥1,200,000",
        "起拍价格": "95万",
        "市场评估价": "120万",
        "建筑面积": "89㎡",
        "出价人数": "12人",
        "单价": "13,483.2 元/㎡",
    }
    mapped = map_avm_record(row)

    assert mapped["id"] == 1001
    assert mapped["deal_price_yuan"] == 1200000
    assert mapped["start_price_yuan"] == 950000
    assert mapped["market_price_yuan"] == 1200000
    assert mapped["area_sqm"] == 89
    assert mapped["bid_count"] == 12
    assert mapped["unit_price_yuan_per_sqm"] == 13483.2
