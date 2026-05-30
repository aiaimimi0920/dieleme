from __future__ import annotations

from pathlib import Path

from tools import avm_data_loader


class _FakeRepo:
    enabled = True

    def yield_flat_items(self, limit: int | None = None, chunk_size: int = 1000):
        rows = [{"item_id": "db-1", "source_title": "DB Row"}]
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            yield row

    def yield_recent_flat_items(self, window_days: int, limit: int | None = None, chunk_size: int = 1000):
        rows = [{"item_id": f"recent-{window_days}", "auction_date": "2026-03-05 10:00:00"}]
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            yield row

    def yield_analysis_ready_flat_items(self, limit: int | None = None, chunk_size: int = 1000):
        rows = [{"item_id": "ready-1", "source_title": "Ready Row"}]
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            yield row


def test_iter_raw_record_rows_prefers_database_stream_when_enabled(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text(
        "[{\"id\": \"file-1\", \"title\": \"File Row\"}]",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_ANALYTICS_SOURCE", "1")
    monkeypatch.setattr(avm_data_loader, "create_repository_from_env", lambda: _FakeRepo())

    rows = list(avm_data_loader.iter_raw_record_rows(data_root))

    assert rows == [{"item_id": "db-1", "source_title": "DB Row"}]


def test_load_raw_record_rows_prefers_database_rows_when_enabled(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text(
        "[{\"id\": \"file-1\", \"title\": \"File Row\"}]",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_ANALYTICS_SOURCE", "1")
    monkeypatch.setattr(avm_data_loader, "create_repository_from_env", lambda: _FakeRepo())

    rows = avm_data_loader.load_raw_record_rows(data_root)

    assert rows == [{"item_id": "db-1", "source_title": "DB Row"}]


def test_load_raw_record_rows_does_not_switch_to_db_just_because_control_plane_flag_is_enabled(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text(
        "[{\"id\": \"file-1\", \"title\": \"File Row\"}]",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE", "1")
    monkeypatch.setattr(avm_data_loader, "create_repository_from_env", lambda: _FakeRepo())

    rows = avm_data_loader.load_raw_record_rows(data_root)

    assert rows == [{"id": "file-1", "title": "File Row"}]


def test_load_recent_and_sample_rows_can_prefer_database_when_control_plane_flag_is_enabled(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text(
        "[{\"id\": \"file-1\", \"交易时间\": \"2026-03-01 10:00:00\"}]",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_CONTROL_PLANE_SOURCE", "1")
    monkeypatch.setattr(avm_data_loader, "create_repository_from_env", lambda: _FakeRepo())

    recent_rows = avm_data_loader.load_recent_raw_record_rows(data_root, 7)
    sample_rows = avm_data_loader.load_sample_raw_record_rows(data_root, 1)

    assert recent_rows == [{"item_id": "recent-7", "auction_date": "2026-03-05 10:00:00"}]
    assert sample_rows == [{"item_id": "db-1", "source_title": "DB Row"}]


def test_iter_analysis_ready_rows_prefers_database_analysis_ready_stream(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text(
        "[{\"id\": \"file-1\", \"title\": \"File Row\"}]",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_ANALYTICS_SOURCE", "1")
    monkeypatch.setattr(avm_data_loader, "create_repository_from_env", lambda: _FakeRepo())

    rows = list(avm_data_loader.iter_analysis_ready_rows(data_root))

    assert rows == [{"item_id": "ready-1", "source_title": "Ready Row"}]


def test_load_recent_and_sample_analysis_ready_rows_can_prefer_database_when_enabled(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-01.json").write_text(
        "[{\"id\": \"file-1\", \"交易时间\": \"2026-03-01 10:00:00\"}]",
        encoding="utf-8",
    )

    monkeypatch.setenv("FAPAI_DB_PREFER_ANALYTICS_SOURCE", "1")
    monkeypatch.setattr(avm_data_loader, "create_repository_from_env", lambda: _FakeRepo())

    recent_rows = avm_data_loader.load_recent_analysis_ready_rows(data_root, 7)
    sample_rows = avm_data_loader.load_sample_analysis_ready_rows(data_root, 1)

    assert recent_rows == [{"item_id": "ready-1", "source_title": "Ready Row"}]
    assert sample_rows == [{"item_id": "ready-1", "source_title": "Ready Row"}]
