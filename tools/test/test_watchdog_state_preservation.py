"""Unreadable watchdog state must not reset durable restart limits."""
import json

import pytest

from tools.pc2_collection_watchdog import CollectionWatchdog
from tools.test.test_pc2_collection_watchdog import BrowserDocker


@pytest.mark.parametrize("contents", [
    b'{"truncated":', b'[]', b'null', b'\xff',
    b'{"consecutive_attempts": "bad"}', b'{"consecutive_attempts": -1}',
    b'{"consecutive_attempts": true}', b'{"attempted_at": "bad"}',
    b'{"attempted_at": NaN}', b'{"attempted_at": Infinity}',
])
def test_unreadable_state_preserved_without_restart(tmp_path, caplog, contents):
    path = tmp_path / "watchdog.json"
    path.write_bytes(contents)
    docker = BrowserDocker()
    watcher = CollectionWatchdog(tmp_path, runner=docker, grace=0)
    assert watcher.step() == "state_unavailable"
    assert path.read_bytes() == contents
    assert not docker.restarts
    assert "automatic restart suspended" in caplog.text


def test_failed_restart_retains_attempt_count_across_controller_restart(tmp_path):
    docker = BrowserDocker()

    def failed_restart(args, **kwargs):
        if args[0] == "restart":
            raise OSError("docker unavailable")
        return docker(args, **kwargs)

    watcher = CollectionWatchdog(tmp_path, runner=failed_restart, grace=0, max_attempts=1)
    with pytest.raises(OSError, match="docker unavailable"):
        watcher.step()
    state = json.loads(watcher.path.read_text(encoding="utf-8"))
    assert state["consecutive_attempts"] == 1
    assert state["result"] == "restart_failed"
    assert state["alert"] == "restart_command_failed"
    restarted = CollectionWatchdog(tmp_path, runner=docker, grace=0, max_attempts=1)
    assert restarted.step() == "restart_limit_reached"
    assert not docker.restarts
