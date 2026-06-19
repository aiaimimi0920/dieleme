from __future__ import annotations

from pathlib import Path


def test_worker_artifact_sync_script_syncs_only_critical_directories() -> None:
    script = Path("scripts/sync-worker-artifacts-to-nas.ps1").read_text(encoding="utf-8")

    assert '"output", "datas", "jobs", "secrets"' in script
    assert "robocopy" in script
    assert "/XJ" in script
    assert "chrome-cdp-profile" not in script
    assert "edge-cdp-profile" not in script
    assert "LoopIntervalSeconds" in script
