from src import server


def test_idle_legacy_solver_preserves_persisted_stage_challenge(monkeypatch):
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_exists", lambda: False)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_runtime_status", lambda: {})
    stage = {
        "challenge_id": "seed-persisted-before-api-restart",
        "paused": True,
        "manual_required": True,
        "force_reset_required": True,
    }
    monkeypatch.setattr(
        server, "_solver_scope_runtime_status",
        lambda scope, now=None: dict(stage) if scope == "seed" else {},
    )
    status = server._captcha_solver_runtime_status(now=100)
    assert status["scopes"]["seed"] == stage
    assert status["collection_scopes"]["seed"] == stage
    assert status["collection_pause_markers"]["seed"] == "paused"
    assert status["manual_required"] is True
