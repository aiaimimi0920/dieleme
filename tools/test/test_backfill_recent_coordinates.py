import json
from pathlib import Path

import pytest

from src.avm.service import AVMService
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import backfill_recent_coordinates as coordinate_module
from tools.backfill_recent_coordinates import backfill_recent_coordinates


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "recent-coordinate.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_backfill_recent_coordinates_updates_missing_recent_rows(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_2026 = data_root / "archive" / "2026"
    archive_2026.mkdir(parents=True, exist_ok=True)

    (archive_2026 / "2026-03-01.json").write_text(
        json.dumps(
            [
                {
                    "id": "hist-1",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "交易时间": "2026-03-01 10:00:00",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "所属小区": "测试小区",
                    "纬度": 31.2,
                    "经度": 121.5,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    recent_file = archive_2026 / "2026-03-05.json"
    recent_file.write_text(
        json.dumps(
            [
                {
                    "id": "recent-1",
                    "成交价格": "110万",
                    "起拍价格": "90万",
                    "建筑面积": "100㎡",
                    "交易时间": "2026-03-05 10:00:00",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "所属小区": "测试小区",
                    "detail_captured": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        {
            "id": "hist-1",
            "交易时间": "2026-03-01 10:00:00",
            "成交价格": "100万",
            "起拍价格": "80万",
            "建筑面积": "100㎡",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "纬度": 31.2,
            "经度": 121.5,
        },
        event_type="seed",
        event_payload={"source_file": str(archive_2026 / "2026-03-01.json")},
    )
    repo.upsert_flat_item(
        {
            "id": "recent-1",
            "交易时间": "2026-03-05 10:00:00",
            "成交价格": "110万",
            "起拍价格": "90万",
            "建筑面积": "100㎡",
            "城市": "上海市",
            "区": "浦东新区",
            "所属小区": "测试小区",
            "detail_captured": True,
        },
        event_type="seed",
        event_payload={"source_file": str(recent_file)},
    )

    from tools import backfill_recent_coordinates as coordinate_module
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(coordinate_module, "create_repository_from_env", lambda: repo)
    try:
        report = backfill_recent_coordinates(data_root, window_days=7, dry_run=False)
    finally:
        monkeypatch.undo()

    assert report["updated_count"] == 1
    updated_payload = json.loads(recent_file.read_text(encoding="utf-8"))
    assert updated_payload[0]["latitude"] == 31.2
    assert updated_payload[0]["longitude"] == 121.5
    assert updated_payload[0]["coordinate_backfill_strategy"] == "community_centroid"
    db_item = repo.get_flat_item("recent-1")
    assert db_item is not None
    assert db_item["latitude"] == 31.2
    assert db_item["longitude"] == 121.5


def test_backfill_recent_coordinates_uses_coordinate_cache_without_full_feature_dataset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_root = tmp_path / "datas"
    archive_2026 = data_root / "archive" / "2026"
    archive_2026.mkdir(parents=True, exist_ok=True)

    (archive_2026 / "2026-03-01.json").write_text(
        json.dumps(
            [
                {
                    "id": "hist-1",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "交易时间": "2026-03-01 10:00:00",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "所属小区": "测试小区",
                    "纬度": 31.2,
                    "经度": 121.5,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    recent_file = archive_2026 / "2026-03-05.json"
    recent_file.write_text(
        json.dumps(
            [
                {
                    "id": "recent-1",
                    "成交价格": "110万",
                    "起拍价格": "90万",
                    "建筑面积": "100㎡",
                    "交易时间": "2026-03-05 10:00:00",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "所属小区": "测试小区",
                    "detail_captured": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    build_calls = {"count": 0}
    ensure_calls = {"count": 0}
    original_ensure = AVMService.ensure_coordinate_cache

    def _counted_build(self):
        build_calls["count"] += 1
        return []

    def _counted_ensure(self, *args, **kwargs):
        ensure_calls["count"] += 1
        return original_ensure(self, *args, **kwargs)

    monkeypatch.setattr(AVMService, "_build_feature_dataset", _counted_build)
    monkeypatch.setattr(AVMService, "ensure_coordinate_cache", _counted_ensure)

    report = backfill_recent_coordinates(data_root, window_days=7, dry_run=True)

    assert report["updated_count"] == 1
    assert ensure_calls["count"] == 1
    assert build_calls["count"] == 0
