from __future__ import annotations

import time

import pytest

from src import server
from src.nas_auth_recovery import NasAuthRecoveryCoordinator


@pytest.mark.parametrize(
    "scope,pending,paused,age,operator_paused,manual_required,expected",
    [
        ("seed", 20, True, 301, False, False, True),
        ("seed", 0, True, 301, False, False, True),
        ("seed", 20, True, 301, False, True, True),
        ("detail", 20, True, 301, False, False, True),
        ("detail", 0, True, 301, False, False, False),
        ("seed", 20, True, 299, False, False, False),
        ("seed", 20, False, 301, False, False, False),
        ("seed", 20, True, 301, True, False, False),
    ],
)
def test_scoped_challenge_recovery_is_independent_of_detail_progress(
    monkeypatch, tmp_path, scope, pending, paused, age, operator_paused, manual_required, expected
):
    coordinator = NasAuthRecoveryCoordinator(tmp_path / "recovery.json")
    coordinator.sample(100, pending, now=time.time() - 10)
    stages = {
        stage: {
            "paused": paused if stage == scope else False,
            "challenge_id": "challenge-1" if paused and stage == scope else None,
            "challenge_age_seconds": age if stage == scope else 0,
        }
        for stage in ("seed", "detail")
    }
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY", coordinator)
    monkeypatch.setattr(server, "NAS_AUTH_RECOVERY_BLOCKED_STALL_SECONDS", 300)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "operator" if operator_paused else "")
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 101)
    monkeypatch.setattr(server, "_nas_auth_recovery_pending_detail_count", lambda: pending)
    monkeypatch.setattr(server, "_solver_scope_runtime_status", lambda stage: stages[stage])
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {
        "paused": paused, "scopes": stages, "manual_required": manual_required,
    })
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", lambda: {"status": "idle"})

    result = server._sample_nas_auth_recovery()

    assert result["last_captured_count"] == 101
    if expected:
        assert result["active"]["status"] == "requested"
        assert result["active"]["trigger_reason"] == f"{scope}_challenge_stalled"
        assert result["active"]["baseline_captured_count"] == 101
    else:
        assert result["active"] is None


def test_scoped_stall_keeps_cooldown_and_single_flight(tmp_path):
    coordinator = NasAuthRecoveryCoordinator(
        tmp_path / "recovery.json", stall_seconds=1, cooldown_seconds=300,
    )
    coordinator.sample(100, 20, now=100)
    first = coordinator.sample(100, 20, now=102)["active"]["recovery_id"]
    coordinator.sample(101, 20, now=103)

    cooling = coordinator.sample(
        101, 20, now=200, blocked_scopes=("seed",),
        recovery_signal="seed_challenge_stalled", recovery_signal_stall_seconds=300,
    )
    assert cooling["active"] is None

    retried = coordinator.sample(
        102, 20, now=404, blocked_scopes=("seed",),
        recovery_signal="seed_challenge_stalled", recovery_signal_stall_seconds=300,
    )
    active = retried["active"]
    assert active["recovery_id"] != first
    same = coordinator.sample(
        103, 20, now=405, blocked_scopes=("seed",),
        recovery_signal="seed_challenge_stalled", recovery_signal_stall_seconds=300,
    )
    assert same["active"]["recovery_id"] == active["recovery_id"]
