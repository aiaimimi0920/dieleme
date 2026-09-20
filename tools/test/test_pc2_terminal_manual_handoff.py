import pytest

from tools import pc2_local_solver as solver
from tools.pc2_solver_manual_handoff import ManualChallengeRequired, retry_terminal_manual_report


def test_terminal_reason_survives_local_execution_and_child_ipc(monkeypatch):
    class FakeSolver:
        last_failure_reason = "manual_required"

        def __init__(self, **_kwargs):
            pass

        def solve(self, **_kwargs):
            return False

    class Pipe:
        result = None

        def send(self, result):
            self.result = result

        def close(self):
            pass

    monkeypatch.setattr(solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(solver, "log_event", lambda _event: None)
    with pytest.raises(ManualChallengeRequired):
        solver.run_solver_local("http://127.0.0.1:1", "https://example.test/")
    pipe = Pipe()
    solver._run_solver_process_entry(pipe, "http://127.0.0.1:1", "https://example.test/", 1, None, 0)
    assert pipe.result == {"success": False, "failure_reason": "manual_required"}


def test_failed_report_latches_and_retries_without_restarting_solver():
    state = {"terminal_manual_pending": True}
    saved, calls = [], []

    def report():
        calls.append(1)
        return {"error": "network unavailable"}

    save = lambda value: saved.append(dict(value))
    assert retry_terminal_manual_report(state, {}, report, save, now=100)
    assert saved[0]["terminal_manual_pending"]
    assert retry_terminal_manual_report(state, {}, report, save, now=110)
    assert len(calls) == 1
    assert retry_terminal_manual_report(state, {}, report, save, now=131)
    assert len(calls) == 2
    assert retry_terminal_manual_report(state, {"manual_required": True}, report, save, now=132)
    assert not state["terminal_manual_pending"] and state["manual_pushed"]


def test_successful_manual_completion_clears_pending_report():
    state = {"terminal_manual_pending": True}
    status = {"paused": False, "last_status": "manual_auth_completed"}
    assert not retry_terminal_manual_report(state, status, lambda: pytest.fail("must not re-report"), lambda _: None)
    assert not state["terminal_manual_pending"]


def test_manual_report_carries_scope_and_challenge_identity(monkeypatch):
    captured = []
    monkeypatch.setattr(solver, "post_json", lambda _url, payload, **_kw: captured.append(payload) or {})
    solver.notify_manual_challenge("http://api.example.test/api", {
        "scope": "seed", "challenge_id": "seed-123",
        "last_request": {"target_url": "https://sf.taobao.com/list/example.htm", "node_id": "pc2"},
    })
    assert captured[0]["challenge_id"] == "seed-123"
    assert captured[0]["scope"] == "seed"


def test_loop_terminal_result_never_rotates_or_sends_second_attempt(monkeypatch):
    state = solver._default_fallback_state()
    status = {"paused": True, "running": False, "manual_required": False,
              "challenge_id": "seed-one", "scope": "seed",
              "last_request": {"target_url": "https://example.test/list"}}
    calls = []
    monkeypatch.setattr(solver, "check_cdp_healthy", lambda _: True)
    monkeypatch.setattr(solver, "process_pending_control_actions", lambda **kw: {
        "handled": False, "last_probe_target": None, "last_auth_confirmed_at": 0})
    monkeypatch.setattr(solver, "read_solver_status", lambda _: status)
    monkeypatch.setattr(solver, "compact_active_challenge_pages", lambda *_: {})
    monkeypatch.setattr(solver, "reset_forced_solver_scopes", lambda _a, _b, value, _d: value)
    monkeypatch.setattr(solver, "_load_fallback_state", lambda: state)
    monkeypatch.setattr(solver, "_save_fallback_state", lambda _: None)
    monkeypatch.setattr(solver, "node_owns_last_request", lambda *_a, **_kw: True)
    monkeypatch.setattr(solver, "node_solver_execution_block_reason", lambda *_a: None)
    monkeypatch.setattr(solver, "check_cdp_browser_for_slider", lambda *_a, **_kw: {"_target_id": "challenge"})
    monkeypatch.setattr(solver, "run_solver_local_with_deadline", lambda *_a, **_kw: (_ for _ in ()).throw(ManualChallengeRequired()))
    monkeypatch.setattr(solver, "rotate_failed_challenge_target", lambda *_a, **_kw: pytest.fail("terminal failure must not rotate"))
    monkeypatch.setattr(solver, "notify_manual_challenge", lambda *_a: calls.append(1) or {"status": "manual_required"})
    monkeypatch.setattr(solver, "write_solver_heartbeat", lambda *_a, **_kw: None)
    monkeypatch.setattr(solver.time, "sleep", lambda _: (_ for _ in ()).throw(SystemExit()))
    with pytest.raises(SystemExit):
        solver.local_solver_loop(poll_seconds=1)
    assert calls == [1]
    assert state["manual_pushed"] and not state["terminal_manual_pending"]
