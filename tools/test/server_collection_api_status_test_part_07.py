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
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 0, raising=False)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 0, raising=False)

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
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "node_id": "pc2",
            "target_url": "https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 0, raising=False)
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
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 100.0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "running")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_CANCEL_EPOCH", 0, raising=False)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {"target_url": "https://sf.taobao.com/list/50025969__2.htm"})

    result = server._trigger_manual_solver_retry_if_due(
        now=221.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "running_solver_timed_out"
    assert result["elapsed_seconds"] == 121
    assert queued == []
    assert server.PAUSED is True
    assert server.COLLECTION_PAUSE_REASON == "manual_required"
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert server.SOLVER_CANCEL_EPOCH == 221.0
    assert flag_path.exists()

def test_send_json_ignores_client_disconnect() -> None:
    from src import server

    class BrokenWriter:
        def write(self, _body):
            raise BrokenPipeError("client disconnected")

    handler = object.__new__(server.DataHandler)
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

    def fake_sleep(_seconds: float) -> None:
        snapshots.append(server._captcha_solver_runtime_status())
        if flag_path.exists():
            flag_path.unlink()

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert snapshots
    assert snapshots[0]["manual_required"] is True
    assert snapshots[0]["running"] is False
    assert server.SOLVER_RUNNING is False
    assert server.SOLVER_LAST_STATUS == "resumed"

def test_run_solver_manual_required_flag_preserves_retry_request(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"
    snapshots: list[dict[str, object]] = []

    def fake_sleep(_seconds: float) -> None:
        snapshots.append(json.loads(flag_path.read_text(encoding="utf-8")))
        flag_path.unlink()

    solver_request = {
        "cdp_endpoint": "http://host.docker.internal:9223",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
    }

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})

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
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda _request: True)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert flag_path.exists() is False
    assert server.PAUSED is False
    assert server.COLLECTION_PAUSE_REASON is None
    assert server.SOLVER_LAST_STATUS == "solved"
    assert server.SOLVER_LAST_FAILURE_REASON is None
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
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://sf.taobao.com/list/1.htm"})

    assert fake.solve_called is False
    assert flag_path.exists() is False
    assert server.PAUSED is False
    assert server.COLLECTION_PAUSE_REASON is None
    assert server.SOLVER_LAST_STATUS == "solved"
    assert server.SOLVER_LAST_FAILURE_REASON is None
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
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda _request: True)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://sf.taobao.com/list/1.htm"})

    assert flag_path.exists() is False
    assert server.PAUSED is False
    assert server.COLLECTION_PAUSE_REASON is None
    assert server.SOLVER_LAST_STATUS == "solved"
    assert server._captcha_solver_runtime_status()["manual_required"] is False

def test_stale_manual_solver_wait_does_not_clear_new_solver_state(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = [1000.0]

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"

    def fake_sleep(_seconds: float) -> None:
        flag_path.unlink()
        fake_now[0] = 2000.0
        server.SOLVER_RUNNING = True
        server.SOLVER_START_TIME = 2000.0
        server.SOLVER_LAST_STATUS = "running"
        server.SOLVER_LAST_FAILURE_REASON = None
        server._set_collection_pause_state(True, "captcha_solver")

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.PAUSED is True
    assert server.COLLECTION_PAUSE_REASON == "captcha_solver"
    assert server.SOLVER_RUNNING is True
    assert server.SOLVER_START_TIME == 2000.0
    assert server.SOLVER_LAST_STATUS == "running"
