"""A failed progress write must preserve disk evidence and fail the caller."""
import json

import pytest

from jobs.job_manager import JobManager


pytestmark = pytest.mark.security


def test_cached_job_is_not_mutated_before_durable_save(tmp_path):
    path = tmp_path / "4401.json"
    path.write_text('{"all_done": false, "pages": [1]}', encoding="utf-8")
    manager = JobManager(str(tmp_path))
    loaded = manager._load_job_file(str(path))
    loaded["pages"].append(2)
    assert manager._load_job_file(str(path))["pages"] == [1]


@pytest.mark.parametrize("failure", ["replace", "fsync"])
def test_write_failure_preserves_archive_and_pending_snapshot(tmp_path, monkeypatch, failure):
    path = tmp_path / "4401.json"
    original = b'{"all_done": false, "pages": [1]}'
    path.write_bytes(original)
    manager = JobManager(str(tmp_path))
    pending = manager._load_job_file(str(path))
    pending["pages"].append(2)

    def fail(*_args):
        raise OSError("storage unavailable")

    monkeypatch.setattr("jobs.job_manager.os." + failure, fail)
    with pytest.raises(OSError, match="storage unavailable"):
        manager._save_job_file(str(path), pending)
    assert path.read_bytes() == original
    assert manager._load_job_file(str(path))["pages"] == [1]
    snapshots = list(tmp_path.glob("4401.json.*.tmp"))
    assert len(snapshots) == 1
    assert json.loads(snapshots[0].read_text(encoding="utf-8"))["pages"] == [1, 2]


def test_public_progress_update_propagates_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "4401.json"
    original = b'{"all_done": false}'
    path.write_bytes(original)
    manager = JobManager(str(tmp_path))

    def fail(*_args):
        raise OSError("cannot replace progress")

    monkeypatch.setattr("jobs.job_manager.os.replace", fail)
    with pytest.raises(OSError, match="cannot replace progress"):
        manager.update_progress(
            "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2", 3,
        )
    assert path.read_bytes() == original
