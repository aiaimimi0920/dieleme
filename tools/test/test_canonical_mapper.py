import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import json
from src.avm.canonical_mapper import map_raw_to_canonical
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
