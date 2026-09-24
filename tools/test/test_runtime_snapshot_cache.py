"""Read-only snapshot caching retains source data and cannot leak mutable results."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.runtime_snapshot_cache import SnapshotCache


def test_cache_reuses_reads_and_invalidates_changed_or_corrupt_snapshots(
    tmp_path, monkeypatch
):
    file = tmp_path / "status.json"
    file.write_text('{"nested":{"count":1}}', encoding="utf-8")
    cache = SnapshotCache()
    reads = []
    original = Path.read_text

    def read(path, **kwargs):
        reads.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    first = cache.read(file)
    first["nested"]["count"] = 999
    assert cache.read(file) == {"nested": {"count": 1}}
    assert len(reads) == 1
    file.write_text('{"nested":{"count":20}}', encoding="utf-8")
    assert cache.read(file)["nested"]["count"] == 20
    file.write_text('{"unfinished":', encoding="utf-8")
    assert cache.read(file) == {}
    assert file.read_text(encoding="utf-8") == '{"unfinished":'
    file.write_text('{"recovered":true}', encoding="utf-8")
    assert cache.read(file) == {"recovered": True}


def test_jsonl_and_json_have_distinct_keys_and_lru_never_deletes_files(tmp_path):
    cache = SnapshotCache(max_entries=1, max_bytes=128)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    first.write_text('{"id":1}\n', encoding="utf-8")
    second.write_text('{"id":2}\n42\n\n{"id":3}\n', encoding="utf-8")
    assert cache.read(first) == {"id": 1}
    assert cache.read(first, lines=True) == [{"id": 1}]
    assert cache.read(second, lines=True) == [{"id": 2}, {"id": 3}]
    assert len(cache._entries) == 1
    assert first.is_file() and second.is_file()
    assert cache.read(first) == {"id": 1}


def test_concurrent_callers_receive_independent_snapshots(tmp_path):
    file = tmp_path / "status.json"
    file.write_text('{"values":[]}', encoding="utf-8")
    cache = SnapshotCache()

    def change(index):
        value = cache.read(file)
        value["values"].append(index)
        return value

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(change, range(40)))
    assert results == [{"values": [index]} for index in range(40)]
    assert cache.read(file) == {"values": []}


def test_large_snapshot_is_read_without_retaining_unbounded_cache(tmp_path):
    file = tmp_path / "status.json"
    file.write_text('{"id":123}', encoding="utf-8")
    cache = SnapshotCache(max_bytes=2)
    assert cache.read(file) == {"id": 123}
    assert len(cache._entries) == 0


def test_excessive_json_nesting_is_unavailable_without_modifying_source(tmp_path):
    file = tmp_path / "nested.json"
    raw = '{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}"
    file.write_text(raw, encoding="utf-8")
    assert SnapshotCache().read(file) == {}
    assert file.read_text(encoding="utf-8") == raw

    jsonl = tmp_path / "nested.jsonl"
    jsonl.write_text(raw + "\n", encoding="utf-8")
    assert SnapshotCache().read(jsonl, lines=True) == []
    assert jsonl.read_text(encoding="utf-8") == raw + "\n"
