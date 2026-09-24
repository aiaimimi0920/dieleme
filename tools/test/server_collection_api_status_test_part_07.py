from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_probe_solver_cdp_endpoint_treats_missing_endpoint_as_healthy() -> None:
    from src import server

    # 没有 cdp_endpoint 的请求（例如纯 target_url 重试）不应被探测拦住
    assert server._probe_solver_cdp_endpoint("") is True

def test_manual_required_auto_retry_uses_default_target_when_last_request_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("legacy manual flag without json", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS", "https://sf.taobao.com/list/50025969__2.htm")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert queued == [
        {
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        }
    ]

def test_manual_required_auto_retry_keeps_pc2_delegated_when_seed_stage_has_remaining_work(
    monkeypatch,
    tmp_path,
) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS", "https://sf.taobao.com/list/50025969__2.htm")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: True)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "required_epoch", 0, raising=False)
    monkeypatch.setattr(
        server.RUNTIME.recovery,
        "last_request",
        {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "node_id": "pc2",
            "target_url": "https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1",
        },
    )
    monkeypatch.setattr(server.RUNTIME.recovery, "retry_last_epoch", 0, raising=False)
    monkeypatch.setattr(
        server,
        "_collection_api_lightweight_status_payload",
        lambda: {
            "seed_scan_job_pending": 10,
            "seed_scan_job_in_progress": 1,
            "seed_scan_progress_pending": 20,
            "seed_scan_progress_in_progress": 0,
        },
    )

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert result["solver_request"] == {
        "cdp_endpoint": "http://192.168.15.104:9224",
        "node_id": "pc2",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    assert queued == []

def test_manual_retry_monitor_marks_running_solver_manual_required_after_timeout(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MAX_RUNTIME_SECONDS", "120")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: 221.0)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "captcha_solver")
    monkeypatch.setattr(server.RUNTIME.solver, "running", True)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 100.0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "running")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.recovery, "cancel_epoch", 0, raising=False)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {"target_url": "https://sf.taobao.com/list/50025969__2.htm"})

    result = server._trigger_manual_solver_retry_if_due(
        now=221.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "running_solver_timed_out"
    assert result["elapsed_seconds"] == 121
    assert queued == []
    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.control.reason == "manual_required"
    assert server.RUNTIME.solver.last_status == "manual_required"
    assert server.RUNTIME.solver.failure_reason == "manual_required"
    assert server.RUNTIME.recovery.cancel_epoch == 221.0
    assert flag_path.exists()

def test_send_json_ignores_client_disconnect() -> None:
    from src import server

    class BrokenWriter:
        def write(self, _body):
            raise BrokenPipeError("client disconnected")

    handler = object.__new__(server.DataHandler)
    handler.path = "/api/test"
    handler.headers = {}
    handler.wfile = BrokenWriter()
    handler.send_response = lambda *_args, **_kwargs: None
    handler.send_header = lambda *_args, **_kwargs: None
    handler.end_headers = lambda: None

    handler.send_json({"ok": True})

def test_send_error_json_ignores_client_disconnect() -> None:
    from src import server

    class BrokenWriter:
        def write(self, _body):
            raise ConnectionResetError("connection reset")

    handler = object.__new__(server.DataHandler)
    handler.path = "/api/test"
    handler.headers = {}
    handler.wfile = BrokenWriter()
    handler.send_response = lambda *_args, **_kwargs: None
    handler.send_header = lambda *_args, **_kwargs: None
    handler.end_headers = lambda: None

    handler.send_error_json(500, "TEST_ERROR", "test", {"x": 1})

def test_run_solver_marks_not_running_while_waiting_for_manual_verification(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"
    snapshots: list[dict[str, object]] = []

    def fake_manual_poll(_execution, _deadline) -> bool:
        snapshots.append(server._captcha_solver_runtime_status())
        if flag_path.exists():
            flag_path.unlink()
        return True

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_wait_for_solver_manual_poll", fake_manual_poll)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert snapshots
    assert snapshots[0]["manual_required"] is True
    assert snapshots[0]["running"] is False
    assert server.RUNTIME.solver.running is False
    assert server.RUNTIME.solver.last_status == "resumed"

def test_run_solver_manual_required_flag_preserves_retry_request(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"
    snapshots: list[dict[str, object]] = []

    def fake_manual_poll(_execution, _deadline) -> bool:
        snapshots.append(json.loads(flag_path.read_text(encoding="utf-8")))
        flag_path.unlink()
        return True

    solver_request = {
        "cdp_endpoint": "http://host.docker.internal:9223",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
    }

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_wait_for_solver_manual_poll", fake_manual_poll)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})

    handler = object.__new__(server.DataHandler)
    handler.run_solver(solver_request)

    assert snapshots
    assert snapshots[0]["manual_required"] is True
    assert snapshots[0]["last_request"] == solver_request

def test_run_solver_success_clears_manual_auth_lock(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"

    class FakeSolver:
        last_failure_reason = None

        def solve(self):
            flag_path.write_text('{"manual_required": true}', encoding="utf-8")
            return True

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda _request, **_options: True)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "manual_only", False)
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert flag_path.exists() is False
    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.control.reason is None
    assert server.RUNTIME.solver.last_status == "solved"
    assert server.RUNTIME.solver.failure_reason is None
    assert server._captcha_solver_runtime_status()["manual_required"] is False

def test_run_solver_clears_stale_lock_when_page_already_authenticated(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text('{"manual_required": true}', encoding="utf-8")

    class FakeSolver:
        last_failure_reason = None
        solve_called = False

        def _preflight_current_challenge(self):
            return {
                "connected": False,
                "manual_required": False,
                "has_slider": False,
                "already_authenticated": True,
            }

        def solve(self):
            self.solve_called = True
            return False

    fake = FakeSolver()
    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: fake)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.RUNTIME.control, "paused", True)
    monkeypatch.setattr(server.RUNTIME.control, "reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", "manual_required")
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "manual_only", False)
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "pending_token", None)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://sf.taobao.com/list/1.htm"})

    assert fake.solve_called is False
    assert flag_path.exists() is False
    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.control.reason is None
    assert server.RUNTIME.solver.last_status == "solved"
    assert server.RUNTIME.solver.failure_reason is None
    assert server._captcha_solver_runtime_status()["manual_required"] is False

def test_run_solver_wait_clears_lock_when_page_becomes_authenticated(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

        def _preflight_current_challenge(self):
            return {
                "connected": False,
                "manual_required": False,
                "has_slider": False,
                "already_authenticated": True,
            }

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda _request, **_options: True)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.control, "reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "manual_only", False)
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "pending_token", None)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://sf.taobao.com/list/1.htm"})

    assert flag_path.exists() is False
    assert server.RUNTIME.control.paused is False
    assert server.RUNTIME.control.reason is None
    assert server.RUNTIME.solver.last_status == "solved"
    assert server._captcha_solver_runtime_status()["manual_required"] is False

def test_stale_manual_solver_wait_does_not_clear_new_solver_state(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = [1000.0]

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"

    def fake_manual_poll(_execution, _deadline) -> bool:
        flag_path.unlink()
        fake_now[0] = 2000.0
        server.RUNTIME.solver.begin(
            2000.0,
            resume_epoch=server.RUNTIME.recovery.resume_epoch,
            cancel_epoch=server.RUNTIME.recovery.cancel_epoch,
        )
        server._set_collection_pause_state(True, "captcha_solver")
        return True

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server, "_wait_for_solver_manual_poll", fake_manual_poll)
    monkeypatch.setattr(server.RUNTIME.control, "paused", False)
    monkeypatch.setattr(server.RUNTIME.solver, "running", False)
    monkeypatch.setattr(server.RUNTIME.solver, "started_at", 0)
    monkeypatch.setattr(server.RUNTIME.solver, "last_status", "idle")
    monkeypatch.setattr(server.RUNTIME.solver, "failure_reason", None)
    monkeypatch.setattr(server.RUNTIME.solver, "finished_at", 0)
    monkeypatch.setattr(server.RUNTIME.recovery, "last_request", {})
    monkeypatch.setattr(server.RUNTIME.recovery, "resume_epoch", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.RUNTIME.control.paused is True
    assert server.RUNTIME.control.reason == "captcha_solver"
    assert server.RUNTIME.solver.running is True
    assert server.RUNTIME.solver.started_at == 2000.0
    assert server.RUNTIME.solver.last_status == "running"
