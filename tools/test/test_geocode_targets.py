"""geocoding 目标的归一化与优先级排序。

线上 228,959 行 latitude/longitude 全为 NULL，空间维度整体失效，是
`eval_report.json` 里 mape 943% 的主要来源之一。既有的
`tools/backfill_recent_coordinates.py` 走 centroid 兜底——从已有坐标池推导，
而坐标池是空的，所以它必然无效。真正需要的是从地址反查坐标。

按「城市+区+小区」编码只需 77,764 次调用（按 full_address 是 206,643 次），
且小区级精度正好是 AVM 同小区比价需要的粒度。按出现频次降序编码时，
Top 5,000 覆盖 39.5% 的行，Top 20,000 覆盖 65.4%，所以增量编码很划算。

这一层不依赖任何 geocoding 服务商，可以先做完再决定用哪家。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_query_joins_city_district_and_community() -> None:
    from tools.geocode_targets import build_geocode_query

    query = build_geocode_query(city="泸州市", district="合江县", community_name="荔城华府")

    assert query == "泸州市合江县荔城华府"


def test_query_tolerates_missing_district() -> None:
    from tools.geocode_targets import build_geocode_query

    query = build_geocode_query(city="宁波市", district="", community_name="清水绿园")

    assert query == "宁波市清水绿园"


def test_query_strips_decorative_separators_from_community_name() -> None:
    """“隆鑫·印象城邦”这类中点分隔符会干扰地理编码匹配。"""
    from tools.geocode_targets import build_geocode_query

    query = build_geocode_query(city="成都市", district="新津区", community_name="隆鑫·印象城邦")

    assert "·" not in query
    assert query == "成都市新津区隆鑫印象城邦"


def test_query_is_empty_when_community_is_missing() -> None:
    from tools.geocode_targets import build_geocode_query

    assert build_geocode_query(city="广州市", district="从化区", community_name="") == ""
    assert build_geocode_query(city="", district="", community_name="某小区") == ""


def test_query_collapses_whitespace() -> None:
    from tools.geocode_targets import build_geocode_query

    query = build_geocode_query(city=" 苏州市 ", district="相城区", community_name=" 宝地 商务广场 ")

    assert query == "苏州市相城区宝地商务广场"


def test_target_key_is_stable_and_case_insensitive_for_dedup() -> None:
    from tools.geocode_targets import build_target_key

    a = build_target_key(city="苏州市", district="相城区", community_name="宝地商务广场")
    b = build_target_key(city="苏州市 ", district="相城区", community_name="宝地商务广场 ")

    assert a == b
    assert a


def test_targets_are_ordered_by_row_count_descending() -> None:
    """按频次降序，让有限的免费额度先覆盖最多的行。"""
    from tools.geocode_targets import prioritize_targets

    rows = [
        {"city": "A市", "district": "X区", "community_name": "小区1", "row_count": 10},
        {"city": "B市", "district": "Y区", "community_name": "小区2", "row_count": 592},
        {"city": "C市", "district": "Z区", "community_name": "小区3", "row_count": 100},
    ]

    ordered = prioritize_targets(rows)

    assert [t["row_count"] for t in ordered] == [592, 100, 10]
    assert ordered[0]["query"] == "B市Y区小区2"


def test_prioritize_drops_targets_without_usable_query() -> None:
    from tools.geocode_targets import prioritize_targets

    rows = [
        {"city": "A市", "district": "X区", "community_name": "", "row_count": 999},
        {"city": "B市", "district": "Y区", "community_name": "小区2", "row_count": 5},
    ]

    ordered = prioritize_targets(rows)

    assert len(ordered) == 1
    assert ordered[0]["community_name"] == "小区2"


def test_prioritize_deduplicates_repeated_targets_and_sums_rows() -> None:
    """同一小区可能因为区字段有无而重复出现，额度不该浪费在重复调用上。"""
    from tools.geocode_targets import prioritize_targets

    rows = [
        {"city": "苏州市", "district": "相城区", "community_name": "宝地商务广场", "row_count": 200},
        {"city": "苏州市", "district": "相城区", "community_name": "宝地商务广场 ", "row_count": 31},
    ]

    ordered = prioritize_targets(rows)

    assert len(ordered) == 1
    assert ordered[0]["row_count"] == 231


def test_cumulative_coverage_is_reported_for_quota_planning() -> None:
    """要能回答“调用 N 次覆盖多少行”，这是选服务商和排期的依据。"""
    from tools.geocode_targets import prioritize_targets, summarize_coverage

    rows = [
        {"city": "A市", "district": "", "community_name": "c1", "row_count": 60},
        {"city": "B市", "district": "", "community_name": "c2", "row_count": 30},
        {"city": "C市", "district": "", "community_name": "c3", "row_count": 10},
    ]

    summary = summarize_coverage(prioritize_targets(rows), limits=[1, 2, 3])

    assert summary["total_targets"] == 3
    assert summary["total_rows"] == 100
    assert summary["coverage"][1]["rows"] == 60
    assert summary["coverage"][1]["pct"] == 60.0
    assert summary["coverage"][2]["rows"] == 90
    assert summary["coverage"][3]["pct"] == 100.0


def test_coverage_limit_beyond_target_count_is_clamped() -> None:
    from tools.geocode_targets import prioritize_targets, summarize_coverage

    rows = [{"city": "A市", "district": "", "community_name": "c1", "row_count": 7}]

    summary = summarize_coverage(prioritize_targets(rows), limits=[100])

    assert summary["coverage"][100]["rows"] == 7
    assert summary["coverage"][100]["pct"] == 100.0
