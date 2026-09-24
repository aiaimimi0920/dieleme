"""Status readers share file snapshots, without caching database results."""
import json
from pathlib import Path

from src.runtime_snapshot_cache import SnapshotCache
from tools.analysis_stage_snapshots import (
    load_action_effectiveness_snapshot,
    load_manual_review_receipt_snapshot,
    load_optimization_loop_progress_snapshot,
    load_recent_gap_audit_snapshot,
)


def test_status_helpers_reuse_reads_and_refresh_changed_files(tmp_path, monkeypatch):
    path = tmp_path / "loop.json"
    path.write_text(json.dumps({"total_progress": {"action_effectiveness": {"ready": 1}}}), encoding="utf-8")
    calls = []
    original = Path.read_text

    def read(file, **kwargs):
        if file == path:
            calls.append(file)
        return original(file, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert load_action_effectiveness_snapshot(path) == {"ready": 1}
    assert load_optimization_loop_progress_snapshot(path)["action_effectiveness"] == {"ready": 1}
    assert len(calls) == 1
    path.write_text('{"total_progress":{"action_effectiveness":{"ready":22}}}', encoding="utf-8")
    assert load_action_effectiveness_snapshot(path) == {"ready": 22}
    assert len(calls) == 2
    path.write_text('{"incomplete":', encoding="utf-8")
    assert load_recent_gap_audit_snapshot(path) == {}
    assert path.read_bytes() == b'{"incomplete":'


def test_receipt_snapshots_are_isolated_and_refresh_after_atomic_replacement(tmp_path):
    path = tmp_path / "receipts.json"
    path.write_text('{"receipts":[{"action":"retain","nested":{"count":1}}]}', encoding="utf-8")
    first = load_manual_review_receipt_snapshot(path)
    first["receipts"][0]["nested"]["count"] = 99
    assert load_manual_review_receipt_snapshot(path)["receipts"][0]["nested"]["count"] == 1
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"receipts":[{"action":"retain"},{"action":"new"}]}', encoding="utf-8")
    replacement.replace(path)
    assert len(load_manual_review_receipt_snapshot(path)["receipts"]) == 2


def test_database_receipts_are_never_cached(tmp_path, monkeypatch):
    from tools import manual_review_receipt_store

    monkeypatch.setattr(manual_review_receipt_store, "ensure_manual_review_control_plane_backfilled", lambda *a, **k: None)

    class Repository:
        enabled = True
        calls = 0

        def list_manual_review_receipts(self):
            self.calls += 1
            return {"receipts": [{"revision": self.calls}]}

    repo = Repository()
    path = tmp_path / "unread.json"
    assert load_manual_review_receipt_snapshot(path, repo)["receipts"][0]["revision"] == 1
    assert load_manual_review_receipt_snapshot(path, repo)["receipts"][0]["revision"] == 2
    assert not path.exists()


def test_object_validation_distinguishes_empty_object_from_invalid_json(tmp_path):
    cache = SnapshotCache()
    path = tmp_path / "object.json"
    for content, expected in [('{}', {}), ('[]', None), ('broken', None)]:
        path.write_text(content, encoding="utf-8")
        assert cache.read(path, invalid=None) == expected


def test_collection_runtime_snapshot_captures_solver_and_recovery_once(monkeypatch):
    from src import server

    solver_calls = []
    recovery_calls = []
    solver = {
        "paused": True,
        "last_status": "manual_required",
        "collection_scopes": {"seed": {"paused": True}},
    }
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: solver_calls.append(1) or solver)
    monkeypatch.setattr(
        server.NAS_AUTH_RECOVERY,
        "snapshot",
        lambda: recovery_calls.append(1) or {"active": None, "last_result": None},
    )

    snapshot = server._collection_runtime_snapshot()

    assert snapshot == {
        "paused": True,
        "captcha_solver": solver,
        "auth_recovery": {"active": None, "last_result": None},
        "collection_scopes": {"seed": {"paused": True}},
    }
    assert solver_calls == [1]
    assert recovery_calls == [1]
