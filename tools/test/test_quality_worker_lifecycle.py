"""Offline progress and shutdown tests, without production Docker or databases."""
import json
import signal
import time
from types import SimpleNamespace

import pytest

from tools import docker_entrypoint, pc2_linux_healthcheck
from tools.worker_lifecycle import WorkerLifecycle, checkpoint, wait


def test_signal_finishes_current_item_then_releases_lease_and_interrupts_wait(tmp_path):
    events = []
    heartbeat = tmp_path / "heartbeat.json"
    previous = signal.getsignal(signal.SIGTERM)
    with WorkerLifecycle("worker", lambda worker: events.append(("release", worker)), heartbeat):
        assert checkpoint("item")
        signal.raise_signal(signal.SIGTERM)
        events.append(("committed", "item"))
        started = time.monotonic()
        wait(600)
        assert time.monotonic() - started < 1
        assert not checkpoint("next_item")
    assert events == [("committed", "item"), ("release", "worker")]
    assert json.loads(heartbeat.read_text())["stage"] == "stopped"
    assert signal.getsignal(signal.SIGTERM) == previous


def test_failed_start_restores_signal_handlers(tmp_path, monkeypatch):
    previous = signal.getsignal(signal.SIGTERM)
    lifecycle = WorkerLifecycle("worker", lambda _: None, tmp_path / "heartbeat.json")
    monkeypatch.setattr(lifecycle, "heartbeat", lambda _: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError):
        with lifecycle:
            pytest.fail("failed heartbeat accepted")
    assert signal.getsignal(signal.SIGTERM) == previous
    assert checkpoint("outside_worker")


def test_worker_health_uses_own_progress_without_contacting_nas(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    path.write_text(json.dumps({"updated_at_epoch": time.time(), "pid": 42, "stage": "waiting"}))
    monkeypatch.setenv("FAPAI_WORKER_HEARTBEAT_PATH", str(path))
    monkeypatch.setenv("FAPAI_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(pc2_linux_healthcheck, "_read_json", lambda _: pytest.fail("NAS connectivity is not worker liveness"))
    calls = []
    monkeypatch.setattr(pc2_linux_healthcheck.os, "kill", lambda *args: calls.append(args))
    pc2_linux_healthcheck.check_worker()
    assert calls == [(42, 0)]
    for update in ({"updated_at_epoch": time.time() - 2000}, {"stage": "stopped"}):
        path.write_text(json.dumps({"updated_at_epoch": time.time(), "pid": 42, "stage": "item", **update}))
        with pytest.raises(RuntimeError, match="stale or stopped"):
            pc2_linux_healthcheck.check_worker()
    assert calls == [(42, 0)]


def test_entrypoint_replaces_itself_after_checks(monkeypatch):
    class ReplacedProcess(Exception):
        pass

    events = []
    monkeypatch.setattr(docker_entrypoint, "run_startup_checks", lambda _: events.append("checked"))
    monkeypatch.setattr(docker_entrypoint, "build_command", lambda _: ["python", "worker.py"])

    def replace(executable, arguments):
        events.append((executable, arguments))
        raise ReplacedProcess

    monkeypatch.setattr(docker_entrypoint.os, "execvp", replace)
    with pytest.raises(ReplacedProcess):
        docker_entrypoint.main()
    assert events == ["checked", ("python", ["python", "worker.py"])]
