import datetime as datetime_module
import logging
from types import SimpleNamespace

import pytest

from src import server


def test_load_data_logs_corrupt_file_and_continues(tmp_path, monkeypatch, caplog):
    (tmp_path / "broken.json").write_text('{"id":', encoding="utf-8")
    (tmp_path / "valid.json").write_text(
        '{"id": "valid-item", "status": "pending"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(server.RUNTIME.collection, "seen_ids", {})
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", [])
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=False))
    monkeypatch.setattr(server, "sync_collection_record", lambda _item: None)

    with caplog.at_level(logging.ERROR):
        server.load_data(tmp_path)

    assert "Failed to load collection data file" in caplog.text
    assert str(tmp_path / "broken.json") in caplog.text
    assert "valid-item" in server.RUNTIME.collection.seen_ids


def test_date_path_helpers_do_not_swallow_unexpected_parser_errors(monkeypatch):
    class ExplodingDateTime:
        @classmethod
        def strptime(cls, *_args):
            raise RuntimeError("parser bug")

    monkeypatch.setattr(
        server,
        "datetime",
        SimpleNamespace(datetime=ExplodingDateTime, date=datetime_module.date),
    )

    with pytest.raises(RuntimeError, match="parser bug"):
        server.get_data_path("invalid")
    with pytest.raises(RuntimeError, match="parser bug"):
        server.get_list_payload_archive_path("invalid")


def test_load_data_propagates_unexpected_item_processing_errors(tmp_path, monkeypatch):
    (tmp_path / "valid.json").write_text(
        '{"id": "broken-item", "status": "pending"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(server.RUNTIME.collection, "seen_ids", {})
    monkeypatch.setattr(server.RUNTIME.collection, "pending_tasks", [])
    monkeypatch.setattr(server, "DB_REPOSITORY", SimpleNamespace(enabled=False))

    def explode(_item):
        raise RuntimeError("record parser bug")

    monkeypatch.setattr(server, "sync_collection_record", explode)

    with pytest.raises(RuntimeError, match="record parser bug"):
        server.load_data(tmp_path)
