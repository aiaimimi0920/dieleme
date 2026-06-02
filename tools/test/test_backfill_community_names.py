import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.backfill_community_names import backfill_community_names


def test_backfill_community_names_updates_files_when_not_dry_run(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive = data_root / "archive" / "2026"
    archive.mkdir(parents=True)
    source_file = archive / "2026-06-01.json"
    source_file.write_text(
        json.dumps(
            [
                {
                    "id": "item-1",
                    "城市": "北京市",
                    "区": "朝阳区",
                    "所属小区": "远洋天地小区",
                    "地点": "北京市朝阳区八里庄远洋天地小区7号楼",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    index_file = tmp_path / "beike_communities.json"
    index_file.write_text(
        json.dumps(
            [
                {
                    "city": "北京市",
                    "district": "朝阳区",
                    "canonical_name": "远洋天地",
                    "aliases": ["远洋天地小区"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = backfill_community_names(
        data_root=data_root,
        index_path=index_file,
        dry_run=False,
        prefer_db=False,
    )

    assert report["candidate_count"] == 1
    assert report["updated_count"] == 1
    payload = json.loads(source_file.read_text(encoding="utf-8"))
    assert payload[0]["所属小区"] == "远洋天地"
    assert payload[0]["community_name_source"] == "beike_alias"
    assert payload[0]["community_stable_key"] == "beike::北京市::朝阳区::远洋天地"


def test_backfill_community_names_dry_run_reports_without_mutating_files(tmp_path: Path):
    data_root = tmp_path / "datas"
    data_root.mkdir()
    source_file = data_root / "2026-06-01.json"
    original_payload = [
        {
            "id": "item-1",
            "城市": "温州市",
            "区": "瑞安市",
            "最靠近商圈": "陶山镇",
            "地点": "浙江省温州市瑞安市陶山镇石坑村201室房地产",
        }
    ]
    source_file.write_text(json.dumps(original_payload, ensure_ascii=False), encoding="utf-8")

    report = backfill_community_names(
        data_root=data_root,
        index_path=None,
        dry_run=True,
        prefer_db=False,
    )

    assert report["candidate_count"] == 1
    assert report["updated_count"] == 1
    assert report["updated_records"][0]["source"] == "geo_fallback"
    assert json.loads(source_file.read_text(encoding="utf-8")) == original_payload
