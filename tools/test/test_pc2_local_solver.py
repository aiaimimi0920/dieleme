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
