"""坐标回填逻辑：批量把 geocoding 结果写回 property_listing。

这是 geocoding 链路的最后一段，把 geocode_client.AmapGeocoder 的结果
落到 property_listing.latitude/longitude 和 geom（PostGIS）列。

设计取舍：
- 按「城市+区+小区」聚合，把同一小区的所有 item_id 批量写回，而不是逐行调用
  geocoding——76,718 次调用覆盖 182,325 行，比 228,959 次少 66%。
- 全程 dry-run 可预览，不提交任何数据库修改。
- progress_path 写入每个 key 的编码结果，中断后可从断点续跑，不会重复烧额度。
- 额度耗尽（GeocodeQuotaExceeded）立刻停止批次而不是静默跳过，避免把整批
  目标误标成无坐标。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_fake_geocoder(results: dict[str, dict[str, Any] | None]):
    """为测试生成一个可控的 geocoder stub。"""
    from tools.geocode_client import AmapGeocoder

    calls: list[str] = []

    def _fake_fetch(url: str, *, timeout: float) -> str:
        q = url.split("address=")[1].split("&")[0]
        import urllib.parse
        q = urllib.parse.unquote(q)
        calls.append(q)
        result = results.get(q)
        if result is None:
            return json.dumps({"status": "1", "info": "OK", "count": "0", "geocodes": []})
        lat = result["raw_lat"]
        lon = result["raw_lon"]
        return json.dumps({
            "status": "1", "info": "OK", "count": "1",
            "geocodes": [{"location": f"{lon},{lat}", "level": "住宅区", "formatted_address": q}],
        })

    geocoder = AmapGeocoder(api_key="TESTKEY", fetch=_fake_fetch)
    return geocoder, calls


def test_backfill_writes_wgs84_coordinates_to_db(tmp_path: Path) -> None:
    from tools.geocode_targets import build_geocode_query
    from tools.backfill_coordinates import backfill_coordinates_from_geocoder
    from tools.test.test_detail_worker import _make_repo, _seed_one_item

    repo = _make_repo(tmp_path)

    # 插入两条同小区的 property_listing
    repo.upsert_flat_item(
        {"item_id": "3001", "city": "泸州市", "district": "合江县", "community_name": "荔城华府",
         "transaction_price": 500000, "area_sqm": 80},
        event_type="test",
    )
    repo.upsert_flat_item(
        {"item_id": "3002", "city": "泸州市", "district": "合江县", "community_name": "荔城华府",
         "transaction_price": 520000, "area_sqm": 82},
        event_type="test",
    )

    query = build_geocode_query(city="泸州市", district="合江县", community_name="荔城华府")
    # GCJ-02 坐标，geocoder 会转成 WGS-84 再返回
    geocoder, calls = _make_fake_geocoder({query: {"raw_lat": 28.8691, "raw_lon": 105.8558}})

    result = backfill_coordinates_from_geocoder(repo, geocoder, dry_run=False)

    assert result["targets_attempted"] == 1
    assert result["targets_written"] == 1
    assert result["rows_written"] == 2
    assert result["targets_not_found"] == 0
    assert calls == [query]

    # 确认坐标已写入 DB（latitude 必须是转换后的 WGS-84，不是 GCJ-02 原值）
    items = [repo.get_item("3001"), repo.get_item("3002")]
    for item in items:
        assert item is not None
        lat = item.get("latitude")
        assert lat is not None
        assert lat != 28.8691  # 不能是 GCJ-02 原值
        assert abs(lat - 28.8691) < 0.01  # 但量级应接近


def test_backfill_dry_run_does_not_modify_db(tmp_path: Path) -> None:
    from tools.geocode_targets import build_geocode_query
    from tools.backfill_coordinates import backfill_coordinates_from_geocoder
    from tools.test.test_detail_worker import _make_repo

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {"item_id": "4001", "city": "宁波市", "district": "北仑区", "community_name": "清水绿园",
         "transaction_price": 600000, "area_sqm": 90},
        event_type="test",
    )

    query = build_geocode_query(city="宁波市", district="北仑区", community_name="清水绿园")
    geocoder, _ = _make_fake_geocoder({query: {"raw_lat": 29.889, "raw_lon": 121.844}})

    result = backfill_coordinates_from_geocoder(repo, geocoder, dry_run=True)

    assert result["targets_attempted"] == 1
    assert result["targets_written"] == 0
    assert result["dry_run"] is True

    item = repo.get_item("4001")
    assert item is not None
    assert item.get("latitude") is None


def test_backfill_skips_items_that_already_have_coordinates(tmp_path: Path) -> None:
    from tools.geocode_targets import build_geocode_query
    from tools.backfill_coordinates import backfill_coordinates_from_geocoder
    from tools.test.test_detail_worker import _make_repo

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {"item_id": "5001", "city": "成都市", "district": "新津区", "community_name": "隆鑫印象城邦",
         "latitude": 30.41, "longitude": 103.81, "transaction_price": 400000, "area_sqm": 75},
        event_type="test",
    )

    query = build_geocode_query(city="成都市", district="新津区", community_name="隆鑫印象城邦")
    geocoder, calls = _make_fake_geocoder({query: {"raw_lat": 30.42, "raw_lon": 103.82}})

    result = backfill_coordinates_from_geocoder(repo, geocoder, dry_run=False)

    assert result["targets_attempted"] == 0, "已有坐标的 item 不该触发 geocoding"
    assert calls == []


def test_backfill_records_not_found_separately(tmp_path: Path) -> None:
    from tools.backfill_coordinates import backfill_coordinates_from_geocoder
    from tools.test.test_detail_worker import _make_repo

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {"item_id": "6001", "city": "某市", "district": "某区", "community_name": "找不到的小区",
         "transaction_price": 300000, "area_sqm": 60},
        event_type="test",
    )

    geocoder, _ = _make_fake_geocoder({})  # 所有查询都返回空

    result = backfill_coordinates_from_geocoder(repo, geocoder, dry_run=False)

    assert result["targets_not_found"] == 1
    assert result["targets_written"] == 0


def test_backfill_stops_on_quota_exhaustion(tmp_path: Path) -> None:
    """额度耗尽必须立刻停止，不能把后续目标误标为无坐标。"""
    from tools.geocode_client import GeocodeQuotaExceeded
    from tools.backfill_coordinates import backfill_coordinates_from_geocoder
    from tools.test.test_detail_worker import _make_repo

    repo = _make_repo(tmp_path)
    for i, comm in enumerate(["小区A", "小区B", "小区C"]):
        repo.upsert_flat_item(
            {"item_id": str(7000 + i), "city": "A市", "district": "X区", "community_name": comm,
             "transaction_price": 200000 + i, "area_sqm": 50},
            event_type="test",
        )

    def _quota_fetch(url: str, *, timeout: float) -> str:
        import json
        return json.dumps({"status": "0", "info": "DAILY_QUERY_OVER_LIMIT", "infocode": "10003"})

    from tools.geocode_client import AmapGeocoder
    geocoder = AmapGeocoder(api_key="K", fetch=_quota_fetch)

    result = backfill_coordinates_from_geocoder(repo, geocoder, dry_run=False)

    assert result["stopped_by_quota"] is True
    assert result["targets_attempted"] == 1  # 第一次就触发了配额耗尽


def test_backfill_resumes_from_progress_file(tmp_path: Path) -> None:
    """中断后续跑时，已完成的 key 不应重复调用 geocoding。"""
    from tools.geocode_targets import build_geocode_query
    from tools.backfill_coordinates import backfill_coordinates_from_geocoder
    from tools.test.test_detail_worker import _make_repo

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {"item_id": "8001", "city": "福州市", "district": "福清市", "community_name": "侨荣花园",
         "transaction_price": 450000, "area_sqm": 85},
        event_type="test",
    )
    repo.upsert_flat_item(
        {"item_id": "8002", "city": "广州市", "district": "从化区", "community_name": "欣荣宏国际商贸城",
         "transaction_price": 380000, "area_sqm": 65},
        event_type="test",
    )

    q1 = build_geocode_query(city="福州市", district="福清市", community_name="侨荣花园")
    q2 = build_geocode_query(city="广州市", district="从化区", community_name="欣荣宏国际商贸城")

    progress_file = tmp_path / "progress.json"
    # 模拟 q1 在上次运行中已完成
    progress_file.write_text(json.dumps({q1: {"latitude": 25.84, "longitude": 119.37,
                                               "raw_latitude": 25.84, "raw_longitude": 119.37,
                                               "provider": "amap", "source_crs": "GCJ-02",
                                               "level": "住宅区", "formatted_address": q1}}),
                              encoding="utf-8")

    geocoder, calls = _make_fake_geocoder({q2: {"raw_lat": 23.55, "raw_lon": 113.58}})

    result = backfill_coordinates_from_geocoder(
        repo, geocoder, dry_run=False, progress_path=progress_file
    )

    assert q1 not in calls, "已有进度的 key 不应再调用 geocoding"
    assert q2 in calls
    assert result["targets_written"] == 2
    assert result["targets_from_progress"] == 1
