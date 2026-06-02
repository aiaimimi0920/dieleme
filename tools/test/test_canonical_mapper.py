import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json
from src.avm.canonical_mapper import map_raw_to_canonical
from tools import build_canonical_dataset as canonical_dataset_module
from tools.build_canonical_dataset import build_canonical_dataset


def test_map_raw_to_canonical_core_fields():
    raw = {
        "id": 123,
        "原始网站": " https://example.com/item/123 ",
        "成交价格": "123.5万",
        "起拍价格": "1000000元",
        "建筑面积": "89.7㎡",
        "交易时间": "2024年01月02日 03:04:05",
    }
    mapped = map_raw_to_canonical(raw)

    assert mapped["item_id"] == "123"
    assert mapped["source_item_id"] == "123"
    assert mapped["source_url"] == "https://example.com/item/123"
    assert mapped["transaction_price"] == 1235000.0
    assert mapped["starting_price"] == 1000000.0
    assert mapped["area_sqm"] == 89.7
    assert mapped["auction_date"] == "2024-01-02 03:04:05"


def test_map_raw_to_canonical_timestamp_and_invalid_values():
    raw = {
        "item_id": "abc",
        "source_item_id": "origin-abc",
        "source_url": "u",
        "transaction_price": -1,
        "starting_price": "2亿",
        "area_sqm": "0",
        "auction_date": "1704067200",  # 2024-01-01 00:00:00 UTC
    }
    mapped = map_raw_to_canonical(raw)

    assert mapped["item_id"] == "abc"
    assert mapped["source_item_id"] == "origin-abc"
    assert mapped["transaction_price"] is None
    assert mapped["starting_price"] == 200000000.0
    assert mapped["area_sqm"] is None
    assert mapped["auction_date"] == "2024-01-01 08:00:00"


def test_build_canonical_dataset_custom_dirs(tmp_path: Path):
    datas = tmp_path / "datas"
    datas.mkdir()
    raw_file = datas / "raw.json"
    raw_file.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "url": "https://x/1",
                    "成交价格": "1万",
                    "起拍价格": "9000元",
                    "建筑面积": "66.6平",
                    "交易时间": "2024-01-01",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out_dir = datas / "canonical"
    result = build_canonical_dataset(datas_dir=datas, output_dir=out_dir)

    assert result["processed_files"] == 1
    assert result["records_total"] == 1
    assert (out_dir / "dataset.jsonl").exists()
    report = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert report["file_error_count"] == 0
    assert report["fields"]["transaction_price"]["non_null"] == 1


def test_build_canonical_dataset_prefers_database_analysis_ready_rows_when_enabled(tmp_path: Path, monkeypatch):
    class _FakeRepo:
        enabled = True

        def count_listings(self):
            return 1

        def count_analysis_ready_items(self):
            return 1

        def yield_analysis_ready_flat_items(self):
            return [
                {
                    "item_id": "ready-1",
                    "source_url": "https://example.com/ready-1",
                    "transaction_price": 1000000.0,
                    "starting_price": 900000.0,
                    "area_sqm": 80.0,
                    "auction_date": "2024-01-01 10:00:00",
                    "city": "上海市",
                    "district": "浦东新区",
                }
            ]

        def yield_flat_items(self):
            return [
                {
                    "item_id": "db-fallback-1",
                    "source_url": "https://example.com/db-fallback-1",
                    "transaction_price": 888000.0,
                    "starting_price": 777000.0,
                    "area_sqm": 70.0,
                    "auction_date": "2024-01-02 10:00:00",
                    "city": "北京市",
                    "district": "海淀区",
                }
            ]

    datas = tmp_path / "datas"
    datas.mkdir()
    out_dir = datas / "canonical"

    monkeypatch.setattr(canonical_dataset_module, "create_repository_from_env", lambda: _FakeRepo())

    result = build_canonical_dataset(datas_dir=datas, output_dir=out_dir, prefer_db=True)

    assert result["source_mode"] == "database"
    assert result["source_scope"] == "analysis_ready"
    assert result["processed_files"] == 0
    assert result["records_total"] == 1
    report = json.loads((out_dir / "quality_report.json").read_text(encoding="utf-8"))
    assert report["source_mode"] == "database"
    assert report["source_scope"] == "analysis_ready"
    assert report["fields"]["transaction_price"]["non_null"] == 1
    lines = (out_dir / "canonical.jsonl").read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    assert row["item_id"] == "ready-1"


def test_map_raw_to_canonical_merges_nested_risk_features_and_bool_status():
    raw = {
        "id": "x-1",
        "url": "https://example.com/item/x-1",
        "成交价格": "200万",
        "起拍价格": "150万",
        "建筑面积": "100㎡",
        "交易时间": "2024-02-01 10:00:00",
        "是否成交": True,
        "applyCount": 12,
        "bidCount": 18,
        "avm_risk_features": {
            "community_name": "测试花园",
            "is_occupied": True,
            "clear_delivery": False,
            "housing_type": "住宅",
            "evidence_source": "公告",
            "extraction_version": "avm_risk_v1",
        },
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["status"] == "done"
    assert mapped["community_name"] == "测试花园"
    assert mapped["is_occupied"] is True
    assert mapped["clear_delivery"] is False
    assert mapped["housing_type"] == "住宅"
    assert mapped["apply_count"] == 12
    assert mapped["bid_count"] == 18


def test_map_raw_to_canonical_normalizes_evaluation_price_from_v1_wan():
    raw = {
        "id": "ev-1",
        "成交价格": "200万",
        "起拍价格": "150万",
        "建筑面积": "100㎡",
        "交易时间": "2024-02-01 10:00:00",
        "avm_risk_features": {
            "evaluation_price": 230,
            "extraction_version": "avm_risk_v1",
        },
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["evaluation_price"] == 2300000.0


def test_map_raw_to_canonical_normalizes_evaluation_price_from_v2_yuan():
    raw = {
        "id": "ev-2",
        "成交价格": "200万",
        "起拍价格": "150万",
        "建筑面积": "100㎡",
        "交易时间": "2024-02-01 10:00:00",
        "avm_risk_features": {
            "evaluation_price": 2300000,
            "extraction_version": "avm_risk_v2",
        },
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["evaluation_price"] == 2300000.0


def test_map_raw_to_canonical_normalizes_explicit_housing_type_synonyms():
    raw = {
        "id": "house-1",
        "成交价格": "200万",
        "起拍价格": "150万",
        "建筑面积": "100㎡",
        "交易时间": "2024-02-01 10:00:00",
        "housing_type": "成套住宅",
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["housing_type"] == "住宅"


def test_map_raw_to_canonical_infers_housing_type_from_title_and_location():
    raw_parking = {
        "id": "park-1",
        "成交价格": "20万",
        "起拍价格": "15万",
        "建筑面积": "12㎡",
        "交易时间": "2024-02-01 10:00:00",
        "title": "二拍 广州市黄埔区黄埔东路633号大院地下38号车位",
    }
    raw_residential = {
        "id": "res-1",
        "成交价格": "120万",
        "起拍价格": "100万",
        "建筑面积": "88㎡",
        "交易时间": "2024-02-01 10:00:00",
        "地点": "黑龙江省齐齐哈尔市铁锋区千禧名仕小镇13号楼1单元302室",
    }

    mapped_parking = map_raw_to_canonical(raw_parking)
    mapped_residential = map_raw_to_canonical(raw_residential)

    assert mapped_parking["housing_type"] == "车位"
    assert mapped_residential["housing_type"] == "住宅"


def test_map_raw_to_canonical_normalizes_large_market_evaluation_price_scale():
    raw = {
        "id": "eval-scale-1",
        "成交价格": 630066.08,
        "起拍价格": 630066.08,
        "建筑面积": 73.59,
        "交易时间": "2024-02-06 10:00:00",
        "市场评估价": 11251180000,
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["evaluation_price"] == 1125118.0


def test_map_raw_to_canonical_accepts_bidder_count_alias_for_bid_count():
    raw = {
        "id": "bidder-alias-1",
        "成交价格": "20万",
        "起拍价格": "18万",
        "建筑面积": "30㎡",
        "交易时间": "2024-02-01 10:00:00",
        "出价人数": 1,
        "竞拍人数": 1,
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["bid_count"] == 1
    assert mapped["apply_count"] == 1


def test_map_raw_to_canonical_keeps_standardized_community_audit_fields():
    raw = {
        "id": "community-audit-1",
        "成交价格": "20万",
        "起拍价格": "18万",
        "建筑面积": "30㎡",
        "交易时间": "2024-02-01 10:00:00",
        "所属小区": "远洋天地",
        "community_name_source": "beike_alias",
        "community_name_confidence": 0.98,
        "community_stable_key": "beike::北京市::朝阳区::远洋天地",
        "community_raw_name": "远洋天地小区",
        "beike_community_id": "bj-test-002",
    }

    mapped = map_raw_to_canonical(raw)

    assert mapped["community_name"] == "远洋天地"
    assert mapped["community_name_source"] == "beike_alias"
    assert mapped["community_name_confidence"] == 0.98
    assert mapped["community_stable_key"] == "beike::北京市::朝阳区::远洋天地"
    assert mapped["community_raw_name"] == "远洋天地小区"
    assert mapped["beike_community_id"] == "bj-test-002"
