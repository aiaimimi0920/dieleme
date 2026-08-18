from __future__ import annotations

import json

import pytest

from tools import pc2_local_solver


def test_manual_fallback_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", raising=False)

    assert pc2_local_solver.manual_fallback_enabled() is False
    assert pc2_local_solver._manual_fallback_latch_active(
        {"manual_pushed": True},
        manual_required=True,
    ) is False


def test_manual_fallback_latch_requires_explicit_enable(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", "1")

    assert pc2_local_solver.manual_fallback_enabled() is True
    assert pc2_local_solver._manual_fallback_latch_active(
        {"manual_pushed": True},
        manual_required=True,
    ) is True
    assert pc2_local_solver._manual_fallback_latch_active(
        {"manual_pushed": True},
        manual_required=False,
    ) is False


def test_solver_cooldown_is_active_until_persisted_deadline(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state.update({
        "consecutive_failures": 3,
        "window_started_at": 900.0,
        "solver_cooldown_until": 1100.0,
        "solver_cooldown_reason": "repeated_solver_failures",
    })

    assert pc2_local_solver._solver_cooldown_active(state, now=1099.0) is True
    assert pc2_local_solver._solver_cooldown_active(state, now=1100.0) is False
    assert state["solver_cooldown_until"] == 1100.0
    assert state["solver_cooldown_reason"] == "repeated_solver_failures"
    assert state["consecutive_failures"] == 3
    assert state["window_started_at"] == 900.0


def test_solver_cooldown_starts_after_configured_failures(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state["slider_attempts"] = 3
    monkeypatch.setattr(pc2_local_solver, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 3)
    monkeypatch.setattr(pc2_local_solver, "SOLVER_COOLDOWN_SECONDS", 600.0)

    assert pc2_local_solver._begin_solver_cooldown_if_needed(state, now=1000.0) is True
    assert state["solver_cooldown_until"] == 1600.0
    assert state["solver_cooldown_reason"] == "repeated_solver_failures"


def test_default_slider_rule_is_ten_attempts_with_twenty_second_spacing(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    monkeypatch.setattr(pc2_local_solver, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(pc2_local_solver, "SOLVER_COOLDOWN_SECONDS", 600.0)
    monkeypatch.setattr(pc2_local_solver, "SLIDER_RETRY_INTERVAL_SECONDS", 20.0)

    for attempt in range(1, 10):
        result = pc2_local_solver._record_slider_attempt_failure(state, now=1000.0 + (attempt - 1) * 20)
        assert result["attempts"] == attempt
        assert result["cooldown_started"] is False
        assert state["slider_next_attempt_at"] == 1000.0 + attempt * 20
        assert state["solver_cooldown_until"] is None

    tenth = pc2_local_solver._record_slider_attempt_failure(state, now=1180.0)
    assert tenth["attempts"] == 10
    assert tenth["cooldown_started"] is True
    assert state["slider_next_attempt_at"] is None
    assert state["solver_cooldown_until"] == 1780.0


def test_slider_retry_does_not_run_before_twenty_second_deadline() -> None:
    state = pc2_local_solver._default_fallback_state()
    state["slider_next_attempt_at"] = 1020.0

    assert pc2_local_solver._slider_retry_due(state, now=1019.9) is False
    assert pc2_local_solver._slider_retry_due(state, now=1020.0) is True


def test_new_challenge_id_resets_previous_retry_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", tmp_path / "state.json")
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "challenge-a",
            "slider_attempts": 9,
            "consecutive_failures": 9,
            "slider_next_attempt_at": 2000.0,
        }
    )

    synced, reset = pc2_local_solver._sync_challenge_state(state, "challenge-b")

    assert reset is True
    assert synced["challenge_id"] == "challenge-b"
    assert synced["slider_attempts"] == 0
    assert synced["consecutive_failures"] == 0
    assert synced["slider_next_attempt_at"] is None


def test_run_solver_local_forces_one_drag_without_nc_replay(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeSolver:
        last_failure_reason = None

        def __init__(self, **kwargs) -> None:
            calls.append({"init": kwargs})

        def solve(self, **kwargs) -> bool:
            calls.append({"solve": kwargs})
            return True

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)

    assert pc2_local_solver.run_solver_local("http://127.0.0.1:9223", "https://example.test", max_attempts=50) is True
    assert calls[-1] == {
        "solve": {
            "max_attempts": 1,
            "nc_retry_replay_limit": 0,
            "slider_find_max_retries": 1,
        }
    }


def test_success_pending_state_keeps_attempt_window_until_nas_confirmation(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update({
        "consecutive_failures": 10,
        "slider_attempts": 10,
        "solver_cooldown_until": 2000.0,
        "solver_cooldown_reason": "repeated_solver_failures",
    })
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)

    pending = pc2_local_solver._mark_auth_complete_pending("https://example.test/list")

    assert pending["auth_complete_pending"] is True
    assert pending["consecutive_failures"] == 10
    assert pending["slider_attempts"] == 10
    assert pending["solver_cooldown_until"] == 2000.0
    assert pending["solver_cooldown_reason"] == "repeated_solver_failures"


def _confirmed_auth_payload(completion_id: str) -> dict[str, object]:
    return {
        "ok": True,
        "auth_state_confirmed": True,
        "completion_id": completion_id,
        "paused": False,
        "captcha_solver": {
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "paused": False,
        },
    }


def _confirmed_resume_payload(request_id: str) -> dict[str, object]:
    return {
        "ok": True,
        "action": "resume_after_cooldown",
        "auth_state_confirmed": True,
        "resume_request_id": request_id,
        "paused": False,
        "captcha_solver": {
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "paused": False,
        },
    }


def test_notify_auth_complete_retries_with_same_completion_id(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    completion_id = "pc2-completion-1"

    def fake_post(_url, payload, *, timeout):
        calls.append({"payload": dict(payload), "timeout": timeout})
        if len(calls) == 1:
            raise TimeoutError("NAS response timeout")
        return _confirmed_auth_payload(completion_id)

    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_REQUEST_ATTEMPTS", 3)
    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_REQUEST_BACKOFF_SECONDS", 0)
    monkeypatch.setattr(pc2_local_solver, "post_json", fake_post)

    result = pc2_local_solver.notify_auth_complete("http://nas/api", completion_id=completion_id)

    assert result["request_attempts"] == 2
    assert result["auth_state_confirmed"] is True
    assert [call["payload"]["completion_id"] for call in calls] == [completion_id, completion_id]


def test_auth_complete_requires_explicit_matching_nas_confirmation() -> None:
    completion_id = "pc2-completion-2"

    assert pc2_local_solver._auth_complete_response_confirmed(
        {"ok": True, "completion_id": completion_id},
        completion_id,
    ) is False
    assert pc2_local_solver._auth_complete_response_confirmed(
        _confirmed_auth_payload("different-id"),
        completion_id,
    ) is False
    assert pc2_local_solver._auth_complete_response_confirmed(
        _confirmed_auth_payload(completion_id),
        completion_id,
    ) is True


def test_pending_auth_confirmation_survives_timeout(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "auth_complete_pending": True,
            "auth_completion_id": "pc2-completion-3",
            "auth_complete_next_retry_at": 1000.0,
        }
    )

    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_RETRY_BASE_SECONDS", 5.0)
    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_RETRY_MAX_SECONDS", 60.0)
    monkeypatch.setattr(
        pc2_local_solver,
        "notify_auth_complete",
        lambda *_args, **_kwargs: {"ok": False, "error": "read timeout", "request_attempts": 3},
    )

    result = pc2_local_solver._retry_pending_auth_confirmation("http://nas/api", state=state, now=1000.0)
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["pending"] is True
    assert result["confirmed"] is False
    assert persisted["auth_complete_pending"] is True
    assert persisted["auth_completion_id"] == "pc2-completion-3"
    assert persisted["auth_complete_attempts"] == 3
    assert persisted["auth_complete_next_retry_at"] == 1020.0


def test_pending_auth_confirmation_clears_only_after_explicit_confirmation(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    completion_id = "pc2-completion-4"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "auth_complete_pending": True,
            "auth_completion_id": completion_id,
            "auth_complete_next_retry_at": 1000.0,
        }
    )

    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(
        pc2_local_solver,
        "notify_auth_complete",
        lambda *_args, **_kwargs: {**_confirmed_auth_payload(completion_id), "request_attempts": 1},
    )

    result = pc2_local_solver._retry_pending_auth_confirmation("http://nas/api", state=state, now=1000.0)
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["confirmed"] is True
    assert result["pending"] is False
    assert persisted["auth_complete_pending"] is False
    assert persisted["auth_completion_id"] is None


def test_pending_confirmation_is_processed_before_another_solver_run(monkeypatch) -> None:
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(
        pc2_local_solver,
        "_retry_pending_auth_confirmation",
        lambda _api: {"pending": True, "attempted": False, "confirmed": False},
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: (_ for _ in ()).throw(AssertionError("status must not be read while confirmation is pending")),
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "run_solver_local",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("solver must not run while confirmation is pending")),
    )
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_resume_after_cooldown_timeout_keeps_same_request_id(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_RETRY_BASE_SECONDS", 5.0)
    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_RETRY_MAX_SECONDS", 60.0)

    pending = pc2_local_solver._mark_collection_resume_pending(state, now=1000.0)
    request_id = pending["collection_resume_request_id"]
    monkeypatch.setattr(
        pc2_local_solver,
        "notify_collection_resume_after_cooldown",
        lambda *_args, **_kwargs: {"ok": False, "error": "read timeout", "request_attempts": 2},
    )

    result = pc2_local_solver._retry_pending_collection_resume(
        "http://nas/api",
        state=pending,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["pending"] is True
    assert result["confirmed"] is False
    assert persisted["collection_resume_request_id"] == request_id
    assert persisted["collection_resume_attempts"] == 2
    assert persisted["collection_resume_next_retry_at"] == 1010.0
    assert persisted["slider_attempts"] == 10
    assert persisted["solver_cooldown_until"] == 1000.0


def test_resume_after_cooldown_clears_state_only_after_nas_confirmation(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    pending = pc2_local_solver._mark_collection_resume_pending(state, now=1000.0)
    request_id = pending["collection_resume_request_id"]
    monkeypatch.setattr(
        pc2_local_solver,
        "notify_collection_resume_after_cooldown",
        lambda *_args, **_kwargs: {**_confirmed_resume_payload(request_id), "request_attempts": 1},
    )

    result = pc2_local_solver._retry_pending_collection_resume(
        "http://nas/api",
        state=pending,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["confirmed"] is True
    assert result["pending"] is False
    assert persisted["collection_resume_pending"] is False
    assert persisted["collection_resume_request_id"] is None
    assert persisted["slider_attempts"] == 0
    assert persisted["solver_cooldown_until"] is None


def test_stale_auth_completion_is_abandoned_for_new_challenge(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "challenge-a",
            "slider_attempts": 4,
            "auth_complete_pending": True,
            "auth_completion_id": "completion-a",
            "auth_complete_next_retry_at": 1000.0,
        }
    )
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(
        pc2_local_solver,
        "notify_auth_complete",
        lambda *_args, **_kwargs: {
            "ok": False,
            "stale_challenge": True,
            "challenge_id": "challenge-b",
            "request_attempts": 1,
        },
    )

    result = pc2_local_solver._retry_pending_auth_confirmation(
        "http://nas/api",
        state=state,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["superseded"] is True
    assert result["pending"] is False
    assert persisted["auth_complete_pending"] is False
    assert persisted["slider_attempts"] == 0
    assert persisted["challenge_id"] is None


def test_local_loop_does_not_run_solver_during_persisted_cooldown(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1100.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {"paused": True, "manual_required": True, "running": False},
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "run_solver_local",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("solver must not run during cooldown")),
    )
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_local_loop_resumes_collection_after_cooldown_without_running_solver(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "slider_attempts": 10,
            "consecutive_failures": 10,
            "solver_cooldown_until": 1000.0,
            "solver_cooldown_reason": "repeated_solver_failures",
        }
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    resume_ids: list[str] = []
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {"paused": True, "manual_required": True, "running": False},
    )

    def fake_resume(_api, request_id, challenge_id=None):
        resume_ids.append(request_id)
        return {**_confirmed_resume_payload(request_id), "request_attempts": 1}

    monkeypatch.setattr(pc2_local_solver, "notify_collection_resume_after_cooldown", fake_resume)
    monkeypatch.setattr(
        pc2_local_solver,
        "run_solver_local",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cooldown expiry must not run solver")),
    )
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(resume_ids) == 1
    assert persisted["collection_resume_pending"] is False
    assert persisted["slider_attempts"] == 0
