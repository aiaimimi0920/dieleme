import json
from pathlib import Path

from tools.backfill_json_to_db import (
    backfill_json_to_db,
    build_db_row,
    iter_source_files,
    load_contract_meta,
    should_skip_root_file,
    SourceRow,
)


def test_iter_source_files_only_keeps_archive_and_dated_root_json(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text("[]", encoding="utf-8")
    (data_root / "2026-03-02.json").write_text("[]", encoding="utf-8")
    (data_root / "model_config.json").write_text("{}", encoding="utf-8")
    (data_root / "mock_data.json").write_text("[]", encoding="utf-8")

    paths = [path.relative_to(data_root).as_posix() for path in iter_source_files(data_root, include_root=True)]

    assert paths == ["archive/2026/2026-03-01.json", "2026-03-02.json"]
    assert should_skip_root_file(data_root / "model_config.json") is True
    assert should_skip_root_file(data_root / "2026-03-02.json") is False


def test_build_db_row_uses_frozen_collection_contract_shape(tmp_path: Path):
    contract_meta = load_contract_meta()
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    source_path = archive_dir / "2026-03-01.json"
    source_path.write_text("[]", encoding="utf-8")

    source_row = SourceRow(
        path=source_path,
        row_index=0,
        item={
            "id": 1001,
            "原始网站": "https://example.com/item/1001",
            "title": "上海市浦东新区测试小区101室",
            "成交价格": "123万",
            "起拍价格": "100万",
            "交易时间": "2026-03-01 10:00:00",
            "地点": "上海市浦东新区测试路100号101室",
            "省份": "上海市",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "最靠近商圈": "张江",
            "建筑面积": "88.8㎡",
            "纬度": 31.2,
            "经度": 121.5,
            "detail_archive_path": "html_archive/2026/2026-03-01/item-1001.html",
            "avm_risk_features": {
                "is_occupied": True,
                "has_long_lease": False,
                "evaluation_price": 1500000,
                "extraction_version": "avm_risk_v2",
            },
        },
    )

    row = build_db_row(
        source_row,
        contract_version=contract_meta["version"],
        expected_sections=contract_meta["sections"],
    )

    assert row["item_id"] == "1001"
    assert row["contract_version"] == "avm_collection_contract_v1_frozen"
    assert row["source_date"] == "2026-03-01"
    assert row["community_name"] == "测试小区"
    assert row["latitude"] == 31.2
    assert row["longitude"] == 121.5
    assert row["detail_archive_path"] == "html_archive/2026/2026-03-01/item-1001.html"
    assert row["is_occupied"] is True

    collection_record = json.loads(row["collection_record_json"])
    assert set(collection_record.keys()) == set(contract_meta["sections"])
    assert collection_record["source"]["item_id"] == "1001"
    assert collection_record["auction"]["transaction_price"] == 1230000.0
    assert collection_record["location"]["community_name"] == "测试小区"
    assert collection_record["property"]["area_sqm"] == 88.8


def test_backfill_json_to_db_dry_run_writes_report_and_skips_bad_rows(tmp_path: Path):
    contract_meta = load_contract_meta()
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    data_file = archive_dir / "2026-03-01.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "原始网站": "https://example.com/item/1",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "交易时间": "2026-03-01 10:00:00",
                },
                {
                    "title": "missing-id",
                    "成交价格": "50万",
                    "起拍价格": "40万",
                    "交易时间": "2026-03-01 11:00:00",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report_path = tmp_path / "db_backfill_report.json"
    result = backfill_json_to_db(
        data_root=data_root,
        contract_version=contract_meta["version"],
        expected_sections=contract_meta["sections"],
        include_root=False,
        dry_run=True,
        limit_records=10,
        report_path=report_path,
    )

    assert result["processed_file_count"] == 1
    assert result["row_seen_count"] == 2
    assert result["candidate_row_count"] == 1
    assert result["row_error_count"] == 1
    assert result["db_write_row_count"] == 0
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["sample_item_ids"] == ["1"]
    assert report["row_errors"][0]["row_index"] == 1
