from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_run_solver_waits_for_configured_worker_quiescence(monkeypatch, tmp_path) -> None:
    from src import server

    events: list[object] = []

    class FakeSolver:
        last_failure_reason = None

        def solve(self):
            events.append("solve")
            return True

    def build_solver(_request):
        events.append("build")
        return FakeSolver()

    def wait_for_cdp(_request):
        events.append("cdp_ready")
        return True

    monkeypatch.setenv("FAPAI_SOLVER_WORKER_QUIESCE_SECONDS", "7")
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", wait_for_cdp, raising=False)
    monkeypatch.setattr(server, "_build_solver_for_request", build_solver)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(tmp_path / "force_unlock.flag"))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
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

    assert events[:4] == [("sleep", 7), "cdp_ready", "build", "solve"]
    assert server.SOLVER_LAST_STATUS == "solved"

def test_wait_for_solver_cdp_ready_requires_consecutive_healthy_probes(monkeypatch) -> None:
    from src import server

    calls: list[str] = []
    sleep_calls: list[float] = []
    monotonic_values = iter([0.0, 0.0, 1.0, 2.0])

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(request, *, timeout):
        calls.append(request.full_url)
        assert timeout == 3
        if len(calls) == 1:
            raise OSError("browser restarting")
        return FakeResponse()

    monkeypatch.setenv("FAPAI_SOLVER_CDP_READY_TIMEOUT_SECONDS", "10")
    monkeypatch.setattr(server, "urlopen", fake_urlopen, raising=False)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    assert server._wait_for_solver_cdp_ready({"cdp_endpoint": "http://192.168.15.104:9224"}) is True
    assert calls == [
        "http://192.168.15.104:9224/json/list",
        "http://192.168.15.104:9224/json/list",
        "http://192.168.15.104:9224/json/list",
    ]
    assert sleep_calls == [2, 2]

def test_mark_manual_required_requests_running_solver_cancel(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = 1234.0
    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_CANCEL_EPOCH", 0, raising=False)

    flag_error = server._mark_solver_manual_required()

    assert flag_error is None
    assert server.PAUSED is True
    assert server.SOLVER_CANCEL_EPOCH == fake_now
    assert flag_path.exists()

def test_manual_only_captcha_report_preserves_detail_target_and_disables_auto_retry(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    challenge_state_path = tmp_path / "solver-challenge-state.json"
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_solver_challenge_state_path", lambda: challenge_state_path)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False, raising=False)
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)

    payload = server._manual_only_captcha_report_payload(
        {
            "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "manual_only": True,
        }
    )

    assert payload["status"] == "manual_required"
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["manual_only"] is True
    assert payload["captcha_solver"]["manual_retry_enabled"] is False
    assert str(payload["captcha_solver"]["challenge_id"]).startswith("captcha-")
    assert payload["captcha_solver"]["last_request"]["target_url"] == (
        "https://sf-item.taobao.com/sf_item/3001.htm"
    )
    assert flag_path.exists()
    assert challenge_state_path.exists()

    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    assert server._manual_solver_retry_enabled() is False

def test_manual_only_status_survives_restart_from_persisted_flag(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text(
        json.dumps(
            {
                "manual_only": True,
                "last_request": {
                    "node_id": "pc2",
                    "cdp_endpoint": "http://192.168.15.104:9224",
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False, raising=False)

    status = server._captcha_solver_runtime_status()

    assert status["manual_required"] is True
    assert status["manual_only"] is True
    assert status["manual_retry_enabled"] is False
    assert status["last_request"]["node_id"] == "pc2"
    assert status["last_request"]["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert status["execution_mode"] == "manual"
    assert status["request_owner"] == "pc2"
    assert status["delegated_to_node_solver"] is True
    assert status["nas_solver_active"] is False
    assert status["node_solver_expected"] is False

def test_solver_cancel_for_manual_required_preserves_manual_pause(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = [1000.0]
    flag_path = tmp_path / "force_unlock.flag"
    sleep_calls: list[float] = []

    class FakeSolver:
        last_failure_reason = "cancelled"
        cancel_checker = None

        def solve(self):
            fake_now[0] = 1001.0
            server._mark_solver_manual_required()
            return False

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if flag_path.exists():
            flag_path.unlink()

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
    monkeypatch.setattr(server, "SOLVER_CANCEL_EPOCH", 0, raising=False)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.PAUSED is True
    assert server.SOLVER_RUNNING is False
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()
    assert sleep_calls == []

def test_manual_required_auto_retry_queues_solver_after_cooldown(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: True)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_ATTEMPTS", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert result["attempt"] == 1
    assert queued == [
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        }
    ]
    assert server.PAUSED is False
    assert server.SOLVER_LAST_STATUS == "manual_retry_queued"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server.SOLVER_MANUAL_RETRY_LAST_EPOCH == 900.0
    assert not flag_path.exists()

def test_manual_required_auto_retry_delegates_pc2_without_clearing_pause(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert queued == []
    assert server.PAUSED is True
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()

def test_manual_required_auto_retry_respects_cooldown(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115"},
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=799.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "cooldown_active"
    assert result["next_retry_epoch"] == 800.0
    assert queued == []
    assert server.PAUSED is True
    assert flag_path.exists()

def test_manual_required_auto_retry_delegates_remote_pc2_even_when_cdp_is_unreachable(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: False)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_ATTEMPTS", 7, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert result["solver_request"]["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert queued == []
    # manual_required 状态必须原样保留，不能被清成“可继续采集”
    assert server.PAUSED is True
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()
    # PC2 owns the retry clock; the NAS monitor must not consume its cooldown.
    assert server.SOLVER_MANUAL_RETRY_ATTEMPTS == 7
    assert server.SOLVER_MANUAL_RETRY_LAST_EPOCH == 500.0

def test_manual_required_auto_retry_queues_when_cdp_endpoint_is_reachable(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []
    probed: list[str] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(
        server,
        "_probe_solver_cdp_endpoint",
        lambda endpoint: probed.append(endpoint) is None,
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_ATTEMPTS", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert result["attempt"] == 1
    assert probed == ["http://host.docker.internal:9223"]
    assert len(queued) == 1
    assert server.PAUSED is False
    assert not flag_path.exists()

def test_probe_solver_cdp_endpoint_reports_unreachable_endpoint_as_unhealthy() -> None:
    from src import server

    # 端口 1 上不会有 CDP 监听，探测必须返回 False 而不是抛异常
    assert server._probe_solver_cdp_endpoint("http://127.0.0.1:1") is False
