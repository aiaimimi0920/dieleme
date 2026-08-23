from __future__ import annotations

import json

import pytest

from tools import pc2_local_solver


def test_manual_challenge_report_uses_canonical_taobao_target(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url, payload, timeout):
        captured.update({"url": url, "payload": payload, "timeout": timeout})
        return {"status": "manual_required", "captcha_solver": {"challenge_id": "captcha-1"}}

    monkeypatch.setattr(pc2_local_solver, "post_json", fake_post)
    result = pc2_local_solver.notify_manual_challenge(
        "http://192.168.15.200:8001/api",
        {
            "last_request": {
                "node_id": "pc2",
                "cdp_endpoint": "http://192.168.15.104:9224",
                "target_url": (
                    "https://sf-item.taobao.com//sf_item/747890132583.htm/_____tmd_____/punish"
                    "?x5secdata=secret"
                ),
            }
        },
        "pc2",
    )

    assert result["status"] == "manual_required"
    assert captured["url"] == "http://192.168.15.200:8001/api/report_manual_captcha"
    assert captured["timeout"] == 10
    assert captured["payload"] == {
        "target_url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
        "url": "https://sf-item.taobao.com/sf_item/747890132583.htm",
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "manual_only": True,
        "timestamp": captured["payload"]["timestamp"],
    }


def test_manual_challenge_registration_repairs_legacy_pause_without_challenge_id() -> None:
    status = {
        "manual_only": True,
        "manual_required": True,
        "challenge_id": None,
        "last_request": {"target_url": "https://sf.taobao.com/list/50025969__2.htm"},
    }

    assert pc2_local_solver.manual_challenge_registration_needed(status) is True
    assert pc2_local_solver.manual_challenge_registration_needed(
        {**status, "challenge_id": "captcha-current"}
    ) is False


def test_node_solver_execution_gate_requires_fresh_exclusive_ownership(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", raising=False)
    owned = {
        "running": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
        },
    }

    assert pc2_local_solver.node_solver_execution_block_reason(
        owned,
        "http://127.0.0.1:9223",
        "pc2",
    ) is None
    assert pc2_local_solver.node_solver_execution_block_reason(
        {**owned, "running": True},
        "http://127.0.0.1:9223",
        "pc2",
    ) == "nas_solver_running"
    assert pc2_local_solver.node_solver_execution_block_reason(
        {**owned, "manual_only": True},
        "http://127.0.0.1:9223",
        "pc2",
    ) == "manual_only"
    assert pc2_local_solver.node_solver_execution_block_reason(
        {
            **owned,
            "manual_only": False,
            "last_request": {
                **owned["last_request"],
                "target_url": "https://sf.taobao.com/list/50025969__2.htm",
            },
        },
        "http://127.0.0.1:9223",
        "pc2",
    ) == "manual_only"
    assert pc2_local_solver.node_solver_execution_block_reason(
        {"error": "status unavailable"},
        "http://127.0.0.1:9223",
        "pc2",
    ) == "status_unavailable"
    assert pc2_local_solver.node_solver_execution_block_reason(
        {"running": False, "last_request": {"node_id": "pc3"}},
        "http://127.0.0.1:9223",
        "pc2",
    ) == "request_owned_elsewhere"


def test_node_solver_execution_gate_allows_explicit_real_taobao_auto_mode(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    owned = {
        "running": False,
        "manual_only": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    }

    assert pc2_local_solver.node_solver_execution_block_reason(
        owned,
        "http://127.0.0.1:9223",
        "pc2",
    ) is None
    assert pc2_local_solver.node_solver_execution_block_reason(
        {**owned, "manual_only": True},
        "http://127.0.0.1:9223",
        "pc2",
    ) == "manual_only"


def test_completion_challenge_id_follows_same_owned_request_rotation(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    target_url = "https://sf.taobao.com/list/200782003__2.htm?__captcha_solver_bg=1"
    started = {
        "challenge_id": "captcha-old",
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": target_url,
        },
    }
    latest = {
        **started,
        "challenge_id": "captcha-current",
        "manual_only": False,
    }

    assert pc2_local_solver._completion_challenge_id(
        started,
        latest,
        target_url,
        "http://127.0.0.1:9223",
        "pc2",
    ) == "captcha-current"


def test_completion_challenge_id_rejects_different_request_rotation(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    target_url = "https://sf.taobao.com/list/200782003__2.htm?__captcha_solver_bg=1"
    started = {
        "challenge_id": "captcha-old",
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": target_url,
        },
    }
    latest = {
        "challenge_id": "captcha-other",
        "manual_only": False,
        "last_request": {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        },
    }

    assert pc2_local_solver._completion_challenge_id(
        started,
        latest,
        target_url,
        "http://127.0.0.1:9223",
        "pc2",
    ) == "captcha-old"


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


def test_slider_rule_supports_ten_attempts_five_second_spacing_and_180_second_cooldown(
    monkeypatch,
) -> None:
    state = pc2_local_solver._default_fallback_state()
    monkeypatch.setattr(pc2_local_solver, "SOLVER_COOLDOWN_FAIL_THRESHOLD", 10)
    monkeypatch.setattr(pc2_local_solver, "SOLVER_COOLDOWN_SECONDS", 180.0)
    monkeypatch.setattr(pc2_local_solver, "SLIDER_RETRY_INTERVAL_SECONDS", 5.0)

    for attempt in range(1, 10):
        result = pc2_local_solver._record_slider_attempt_failure(state, now=1000.0 + (attempt - 1) * 5)
        assert result["attempts"] == attempt
        assert result["cooldown_started"] is False
        assert state["slider_next_attempt_at"] == 1000.0 + attempt * 5
        assert state["solver_cooldown_until"] is None

    tenth = pc2_local_solver._record_slider_attempt_failure(state, now=1045.0)
    assert tenth["attempts"] == 10
    assert tenth["cooldown_started"] is True
    assert state["slider_next_attempt_at"] is None
    assert state["solver_cooldown_until"] == 1225.0


def test_solver_attempt_progress_is_persisted_and_completed_on_failure(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    saved: list[dict[str, object]] = []
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda value: saved.append(dict(value)))

    pc2_local_solver._record_slider_attempt_started(state, now=1000.0)

    assert state["slider_attempt_started_at"] == 1000.0
    assert state["slider_last_progress_at"] == 1000.0
    assert saved[-1]["slider_attempt_started_at"] == 1000.0

    pc2_local_solver._record_slider_attempt_failure(state, now=1075.0)

    assert state["slider_attempt_started_at"] is None
    assert state["slider_last_progress_at"] == 1075.0


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


def test_run_solver_local_allows_two_profile_replays_within_one_attempt(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeSolver:
        last_failure_reason = None

        def __init__(self, **kwargs) -> None:
            calls.append({"init": kwargs})

        def _remember_target_tab(self, tab: dict[str, object]) -> None:
            calls.append({"remember": tab})

        def solve(self, **kwargs) -> bool:
            calls.append({"solve": kwargs})
            return True

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)

    probe_target = {
        "_target_id": "slider-target",
        "_target_url": "https://example.test/visible-slider",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/slider-target",
    }

    assert pc2_local_solver.run_solver_local(
        "http://127.0.0.1:9223",
        "https://example.test/requested-page-3",
        max_attempts=50,
        probe_target=probe_target,
        drag_profile_offset=2,
    ) is True
    assert calls[1] == {
        "remember": {
            "id": "slider-target",
            "url": "https://example.test/visible-slider",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/slider-target",
        }
    }
    assert calls[-1] == {
        "solve": {
            "max_attempts": 1,
            "nc_retry_replay_limit": 2,
            "slider_find_max_retries": 1,
            "drag_profile_offset": 2,
        }
    }


def test_cdp_slider_probe_scans_pages_and_returns_target_identity(monkeypatch) -> None:
    sockets: list[FakeWebSocket] = []

    class FakeWebSocket:
        def __init__(self, ws_url: str) -> None:
            self.ws_url = ws_url
            self.last_message: dict[str, object] = {}
            self.closed = False

        def settimeout(self, _timeout: int) -> None:
            return None

        def send(self, payload: str) -> None:
            self.last_message = json.loads(payload)

        def recv(self) -> str:
            message_id = self.last_message["id"]
            if self.last_message["method"] == "Runtime.evaluate":
                found = self.ws_url.endswith("/slider-target")
                value = {
                    "found": found,
                    "x": 10,
                    "y": 20,
                    "width": 42,
                    "height": 30,
                    "selector": "#nc_1_n1z",
                }
                return json.dumps({"id": message_id, "result": {"result": {"value": value}}})
            return json.dumps({"id": message_id, "result": {}})

        def close(self) -> None:
            self.closed = True

    tabs = [
        {
            "id": "worker-target",
            "type": "worker",
            "url": "https://example.test/background-worker.js",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/worker-target",
        },
        {
            "id": "plain-target",
            "type": "page",
            "url": "https://example.test/plain",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/plain-target",
        },
        {
            "id": "slider-target",
            "type": "page",
            "url": "https://example.test/visible-slider?__captcha_solver_bg=1",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/slider-target",
        },
    ]
    monkeypatch.setattr(pc2_local_solver, "fetch_json", lambda *_args, **_kwargs: tabs)

    def fake_create_connection(ws_url: str, **_kwargs: object) -> FakeWebSocket:
        socket = FakeWebSocket(ws_url)
        sockets.append(socket)
        return socket

    import websocket

    monkeypatch.setattr(websocket, "create_connection", fake_create_connection)

    result = pc2_local_solver.check_cdp_browser_for_slider("http://127.0.0.1:9223")

    assert result is not None
    assert result["selector"] == "#nc_1_n1z"
    assert result["_target_id"] == "slider-target"
    assert result["_target_url"] == "https://example.test/visible-slider?__captcha_solver_bg=1"
    assert result["_target_ws_url"] == "ws://127.0.0.1:9223/devtools/page/slider-target"
    assert [socket.ws_url for socket in sockets] == [
        "ws://127.0.0.1:9223/devtools/page/plain-target",
        "ws://127.0.0.1:9223/devtools/page/slider-target",
    ]
    assert all(socket.closed for socket in sockets)


def test_cdp_challenge_probe_returns_existing_target_identity(monkeypatch) -> None:
    challenge = {
        "id": "punish-target",
        "type": "page",
        "title": "验证码拦截",
        "url": "https://sf.taobao.com/list/50025969__2.htm",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/punish-target",
    }
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda *_args, **_kwargs: [
            {"id": "blank", "type": "page", "url": "about:blank"},
            challenge,
        ],
    )

    result = pc2_local_solver.check_cdp_browser_for_challenge_page("http://127.0.0.1:9223")

    assert result == {
        "_target_id": "punish-target",
        "_target_url": challenge["url"],
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/punish-target",
    }


def test_cdp_challenge_probe_prefers_requested_route_over_unrelated_detail(monkeypatch) -> None:
    unrelated = {
        "id": "detail-challenge",
        "type": "page",
        "title": "验证码拦截",
        "url": "https://sf-item.taobao.com//sf_item/601294677898.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/detail-challenge",
    }
    requested = {
        "id": "list-challenge",
        "type": "page",
        "title": "验证码拦截",
        "url": "https://sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/page/list-challenge",
    }
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda *_args, **_kwargs: [unrelated, requested],
    )

    result = pc2_local_solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223",
        target_url=(
            "https://sf.taobao.com/list/50025969__2.htm"
            "?auction_start_seg=-1&location_code=110114&page=4&st_param=5"
        ),
    )

    assert result["_target_id"] == "list-challenge"


@pytest.mark.parametrize("evidence_key", ["challengePresent", "explicitFailure", "hardBlock", "hasSlider"])
def test_cdp_challenge_probe_uses_route_scoped_dom_evidence(monkeypatch, evidence_key) -> None:
    closed_targets: list[str | None] = []

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.current_target = None

        def _solver_target_route(self, value):
            return str(value or "").split("?", 1)[0]

        def _remember_target_tab(self, tab):
            self.current_target = tab.get("id")

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            assert self.current_target == "requested"
            return {evidence_key: True}

        def _close_solver_ws(self):
            closed_targets.append(self.current_target)

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "unrelated",
                "type": "page",
                "title": "normal",
                "url": "https://example.test/unrelated",
                "webSocketDebuggerUrl": "ws://example.test/unrelated",
            },
            {
                "id": "requested",
                "type": "page",
                "title": "normal",
                "url": "https://example.test/requested?state=normal",
                "webSocketDebuggerUrl": "ws://example.test/requested",
            },
        ],
    )

    result = pc2_local_solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223",
        target_url="https://example.test/requested?from=api",
    )

    assert result == {
        "_target_id": "requested",
        "_target_url": "https://example.test/requested?state=normal",
        "_target_ws_url": "ws://example.test/requested",
        "_challenge_evidence": [evidence_key],
    }
    assert "requested" in closed_targets


def test_cdp_challenge_probe_stays_fail_closed_without_dom_evidence(monkeypatch) -> None:
    close_calls = 0

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            pass

        def _solver_target_route(self, value):
            return str(value or "").split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            pass

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return {"authenticatedPage": False, "challengePresent": False}

        def _close_solver_ws(self):
            nonlocal close_calls
            close_calls += 1

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "requested",
                "type": "page",
                "title": "normal",
                "url": "https://example.test/requested",
                "webSocketDebuggerUrl": "ws://example.test/requested",
            }
        ],
    )

    assert pc2_local_solver.check_cdp_browser_for_challenge_page(
        "http://127.0.0.1:9223",
        target_url="https://example.test/requested",
    ) is None
    assert close_calls >= 1


def test_paused_api_trigger_probes_and_passes_existing_slider_target(monkeypatch) -> None:
    probe_target = {
        "found": True,
        "_target_id": "slider-target",
        "_target_url": "https://example.test/visible-slider",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/slider-target",
    }
    captured: list[dict[str, object]] = []
    probed_urls: list[str] = []
    solved_urls: list[str] = []
    state = pc2_local_solver._default_fallback_state()
    state["slider_attempts"] = 4

    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_auth_confirmation", lambda _api: {})
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_collection_resume", lambda _api: {})
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "challenge_id": "challenge-1",
            "last_request": {
                "target_url": "https://seed.example.test/list",
                "challenge_target_url": "https://detail.example.test/item",
            },
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(pc2_local_solver, "_sync_challenge_state", lambda value, _challenge: (value, False))
    monkeypatch.setattr(pc2_local_solver, "node_owns_last_request", lambda *_args, **_kwargs: True)
    def fake_slider_probe(_endpoint, *, target_url=None):
        probed_urls.append(target_url)
        return probe_target

    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_slider", fake_slider_probe)

    def fake_run_solver(_endpoint, target_url, **kwargs) -> bool:
        solved_urls.append(target_url)
        captured.append(kwargs)
        raise SystemExit

    monkeypatch.setattr(pc2_local_solver, "run_solver_local", fake_run_solver)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert captured[0]["probe_target"] == probe_target
    assert captured[0]["drag_profile_offset"] == 1
    assert probed_urls == ["https://detail.example.test/item"]
    assert solved_urls == ["https://detail.example.test/item"]


def test_solver_request_target_urls_preserve_priority_and_remove_duplicates() -> None:
    last_request = {
        "challenge_target_url": "https://detail.example.test/item",
        "target_url": "https://seed.example.test/list",
        "url": "https://seed.example.test/list",
    }

    assert pc2_local_solver.solver_request_target_urls(last_request) == [
        "https://detail.example.test/item",
        "https://seed.example.test/list",
    ]
    assert pc2_local_solver.solver_request_target_url(last_request) == (
        "https://detail.example.test/item"
    )


def test_paused_api_trigger_falls_back_to_active_seed_request_route(monkeypatch) -> None:
    detail_target_url = "https://detail.example.test/item"
    seed_target_url = "https://seed.example.test/list"
    challenge_target = {
        "_target_id": "seed-punish-target",
        "_target_url": seed_target_url + "/_____tmd_____/punish",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/seed-punish-target",
    }
    slider_probes: list[str | None] = []
    challenge_probes: list[str | None] = []
    solver_calls: list[dict[str, object]] = []
    state = pc2_local_solver._default_fallback_state()

    solver_status = {
        "paused": True,
        "running": False,
        "manual_required": False,
        "challenge_id": "challenge-mixed-route",
        "last_request": {
            "target_url": seed_target_url,
            "challenge_target_url": detail_target_url,
        },
    }
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_auth_confirmation", lambda _api: {})
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_collection_resume", lambda _api: {})
    monkeypatch.setattr(pc2_local_solver, "read_solver_status", lambda _api: solver_status)
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(pc2_local_solver, "_sync_challenge_state", lambda value, _challenge: (value, False))
    monkeypatch.setattr(pc2_local_solver, "node_owns_last_request", lambda *_args, **_kwargs: True)

    def fake_slider_probe(_endpoint, *, target_url=None):
        slider_probes.append(target_url)
        return None

    def fake_challenge_probe(_endpoint, *, target_url=None):
        challenge_probes.append(target_url)
        return challenge_target if target_url == seed_target_url else None

    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_slider", fake_slider_probe)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_challenge_page", fake_challenge_probe)

    def fake_run_solver(_endpoint, target_url, **kwargs) -> bool:
        solver_calls.append({"target_url": target_url, **kwargs})
        raise SystemExit

    monkeypatch.setattr(pc2_local_solver, "run_solver_local", fake_run_solver)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert slider_probes == [detail_target_url, seed_target_url]
    assert challenge_probes == [detail_target_url, seed_target_url]
    assert solver_calls == [
        {
            "target_url": seed_target_url,
            "max_attempts": pc2_local_solver.DEFAULT_MAX_ATTEMPTS,
            "probe_target": challenge_target,
            "drag_profile_offset": 0,
        }
    ]


def test_paused_api_trigger_passes_existing_hard_block_target(monkeypatch) -> None:
    challenge_target = {
        "_target_id": "punish-target",
        "_target_url": "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?x5step=1",
        "_target_ws_url": "ws://127.0.0.1:9223/devtools/page/punish-target",
    }
    captured: list[dict[str, object] | None] = []
    state = pc2_local_solver._default_fallback_state()

    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_auth_confirmation", lambda _api: {})
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_collection_resume", lambda _api: {})
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "challenge_id": "challenge-1",
            "last_request": {"target_url": "https://example.test/requested-page-14"},
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(pc2_local_solver, "_sync_challenge_state", lambda value, _challenge: (value, False))
    monkeypatch.setattr(pc2_local_solver, "node_owns_last_request", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_slider", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(
        pc2_local_solver,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, **_kwargs: challenge_target,
    )

    def fake_run_solver(*_args, **kwargs) -> bool:
        captured.append(kwargs.get("probe_target"))
        raise SystemExit

    monkeypatch.setattr(pc2_local_solver, "run_solver_local", fake_run_solver)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert captured == [challenge_target]


def test_paused_api_without_current_cdp_challenge_does_not_run_solver(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()

    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_auth_confirmation", lambda _api, **_kwargs: {})
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_collection_resume", lambda _api, **_kwargs: {})
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "challenge_id": "challenge-1",
            "last_status": "failed",
            "last_request": {"target_url": "https://example.test/requested-page"},
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(pc2_local_solver, "_sync_challenge_state", lambda value, _challenge: (value, False))
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_slider", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_challenge_page", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(
        pc2_local_solver,
        "run_solver_local",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("solver must not run without CDP evidence")),
    )
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_recent_healthy_auth_snapshot_requires_fresh_completed_health(monkeypatch) -> None:
    monkeypatch.setattr(pc2_local_solver, "RECENT_HEALTHY_AUTH_MAX_AGE_SECONDS", 300.0)
    status = {
        "last_status": "manual_auth_completed",
        "running": False,
        "manual_required": False,
        "force_unlock_flag_exists": False,
        "cookie_snapshot_refresh": {
            "status": "completed",
            "refreshed": True,
            "last_finished_at_epoch": 1000.0,
            "result": {"health": {"healthy": True}},
        },
    }

    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1299.0) is True
    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1301.0) is False
    status["last_status"] = "resumed_after_cooldown"
    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1299.0) is True
    status["cookie_snapshot_refresh"]["result"]["health"]["healthy"] = False
    assert pc2_local_solver._recent_healthy_auth_snapshot(status, now=1100.0) is False


def test_post_auth_cdp_probe_grace_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(pc2_local_solver, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 90.0)

    assert pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1090.0) is True
    assert pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1090.1) is False
    assert pc2_local_solver._post_auth_cdp_probe_grace_active(None, now=1000.0) is False


def test_post_auth_cdp_probe_default_window_is_three_minutes(monkeypatch) -> None:
    monkeypatch.setattr(pc2_local_solver, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 180.0)

    assert pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1180.0) is True
    assert pc2_local_solver._post_auth_cdp_probe_grace_active(1000.0, now=1180.1) is False


def test_stale_api_pause_after_recent_healthy_auth_is_reconfirmed(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    state["challenge_id"] = "challenge-late-report"
    pending_states: list[dict[str, object]] = []

    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)

    def fake_retry_auth(_api, state=None, **_kwargs):
        if state is None:
            return {}
        pending_states.append(state)
        return {"confirmed": True, "pending": False}

    monkeypatch.setattr(pc2_local_solver, "_retry_pending_auth_confirmation", fake_retry_auth)
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_collection_resume", lambda _api, **_kwargs: {})
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "challenge_id": "challenge-late-report",
            "last_status": "manual_auth_completed",
            "last_request": {"target_url": "https://example.test/requested-page"},
            "cookie_snapshot_refresh": {
                "status": "completed",
                "refreshed": True,
                "last_finished_at_epoch": 1000.0,
                "result": {"health": {"healthy": True}},
            },
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(pc2_local_solver, "_sync_challenge_state", lambda value, _challenge: (value, False))
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_slider", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_challenge_page", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(
        pc2_local_solver,
        "check_cdp_browser_for_authenticated_target",
        lambda _endpoint, _target_url: None,
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "_mark_auth_complete_pending",
        lambda target_url, challenge_id=None: {
            **state,
            "auth_complete_pending": True,
            "target_url": target_url,
            "challenge_id": challenge_id,
        },
    )
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1100.0)
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert len(pending_states) == 1
    assert pending_states[0]["challenge_id"] == "challenge-late-report"
    assert pending_states[0]["target_url"] == "https://example.test/requested-page"


def test_existing_authenticated_target_reconfirms_pause_without_cookie_snapshot(monkeypatch) -> None:
    state = pc2_local_solver._default_fallback_state()
    pending_states: list[dict[str, object]] = []
    marked: list[tuple[str, str | None]] = []

    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)

    def fake_retry_auth(_api, state=None, **_kwargs):
        if state is None:
            return {}
        pending_states.append(state)
        return {"confirmed": True, "pending": False}

    monkeypatch.setattr(pc2_local_solver, "_retry_pending_auth_confirmation", fake_retry_auth)
    monkeypatch.setattr(pc2_local_solver, "_retry_pending_collection_resume", lambda _api, **_kwargs: {})
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "running": False,
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "challenge_id": "challenge-healthy-page",
            "last_status": "manual_auth_completed",
            "last_request": {"target_url": "https://example.test/requested-page"},
            "cookie_snapshot_refresh": {"status": "skipped", "refreshed": False},
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(pc2_local_solver, "_sync_challenge_state", lambda value, _challenge: (value, False))
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_slider", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_challenge_page", lambda _endpoint, **_kwargs: None)
    monkeypatch.setattr(
        pc2_local_solver,
        "check_cdp_browser_for_authenticated_target",
        lambda _endpoint, _target_url: {"_target_id": "healthy-target"},
    )

    def fake_mark(target_url, challenge_id=None):
        marked.append((target_url, challenge_id))
        return {
            **state,
            "auth_complete_pending": True,
            "target_url": target_url,
            "challenge_id": challenge_id,
        }

    monkeypatch.setattr(pc2_local_solver, "_mark_auth_complete_pending", fake_mark)
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)

    assert marked == [("https://example.test/requested-page", "challenge-healthy-page")]
    assert len(pending_states) == 1
    assert pending_states[0]["challenge_id"] == "challenge-healthy-page"


def test_authenticated_target_probe_requires_every_matching_page_to_be_healthy(monkeypatch) -> None:
    summaries = iter(
        [
            {"authenticatedPage": True, "challengePresent": False, "loginRequired": False},
            {"authenticatedPage": False, "challengePresent": True, "loginRequired": False},
        ]
    )

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.target_url = target_url

        def _normalize_target_url(self, value):
            return str(value)

        def _solver_target_route(self, value):
            return str(value).split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            return None

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return next(summaries)

        def _close_solver_ws(self):
            return None

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "healthy",
                "type": "page",
                "url": "https://example.test/list?marker=1",
                "webSocketDebuggerUrl": "ws://example.test/healthy",
            },
            {
                "id": "challenge",
                "type": "page",
                "url": "https://example.test/list?marker=1",
                "webSocketDebuggerUrl": "ws://example.test/challenge",
            },
        ],
    )

    assert pc2_local_solver.check_cdp_browser_for_authenticated_target(
        "http://127.0.0.1:9223",
        "https://example.test/list?marker=1",
    ) is None


def test_authenticated_target_probe_rejects_route_challenge_beside_exact_healthy_page(monkeypatch) -> None:
    summaries = iter(
        [
            {"authenticatedPage": True, "challengePresent": False, "loginRequired": False},
            {"authenticatedPage": False, "challengePresent": True, "loginRequired": False},
        ]
    )

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.target_url = target_url

        def _normalize_target_url(self, value):
            return str(value)

        def _solver_target_route(self, value):
            return str(value).split("/_____tmd_____/", 1)[0].split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            return None

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return next(summaries)

        def _close_solver_ws(self):
            return None

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "healthy",
                "type": "page",
                "url": "https://example.test/list?marker=1",
                "webSocketDebuggerUrl": "ws://example.test/healthy",
            },
            {
                "id": "challenge",
                "type": "page",
                "url": "https://example.test/list/_____tmd_____/punish?x5secdata=redacted",
                "webSocketDebuggerUrl": "ws://example.test/challenge",
            },
        ],
    )

    assert pc2_local_solver.check_cdp_browser_for_authenticated_target(
        "http://127.0.0.1:9223",
        "https://example.test/list?marker=1",
    ) is None


def test_authenticated_target_probe_accepts_healthy_session_after_target_tab_is_gone(monkeypatch) -> None:
    summaries = iter(
        [
            {"authenticatedPage": True, "challengePresent": False, "loginRequired": False},
            {"authenticatedPage": False, "challengePresent": False, "loginRequired": False},
        ]
    )

    class FakeSolver:
        def __init__(self, *, cdp_endpoint, target_url):
            self.target_url = target_url

        def _normalize_target_url(self, value):
            return str(value)

        def _solver_target_route(self, value):
            return str(value).split("?", 1)[0]

        def _remember_target_tab(self, _tab):
            return None

        def _connect_to_target(self, _ws_url, _title):
            return True

        def _page_challenge_summary(self):
            return next(summaries)

        def _close_solver_ws(self):
            return None

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda _url, timeout: [
            {
                "id": "healthy-auction",
                "type": "page",
                "url": "https://example.test/another-list",
                "webSocketDebuggerUrl": "ws://example.test/healthy",
            },
            {
                "id": "neutral-page",
                "type": "page",
                "url": "about:blank",
                "webSocketDebuggerUrl": "ws://example.test/blank",
            },
        ],
    )

    result = pc2_local_solver.check_cdp_browser_for_authenticated_target(
        "http://127.0.0.1:9223",
        "https://example.test/requested-list",
    )

    assert result is not None
    assert result["_target_id"] == "healthy-auction"


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


def _confirmed_resume_payload(
    request_id: str,
    *,
    target_url: str | None = None,
) -> dict[str, object]:
    captcha_solver: dict[str, object] = {
        "manual_required": False,
        "force_unlock_flag_exists": False,
        "paused": False,
    }
    if target_url:
        captcha_solver["last_request"] = {"target_url": target_url}
    return {
        "ok": True,
        "action": "resume_after_cooldown",
        "auth_state_confirmed": True,
        "resume_request_id": request_id,
        "paused": False,
        "captcha_solver": captcha_solver,
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


def test_expired_auth_confirmation_yields_to_active_challenge(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "solver-fallback-state.json"
    state = pc2_local_solver._default_fallback_state()
    state.update(
        {
            "challenge_id": "challenge-current",
            "slider_attempts": 2,
            "last_success_at": 800.0,
            "auth_complete_pending": True,
            "auth_completion_id": "pc2-completion-stale",
            "auth_complete_next_retry_at": 1100.0,
        }
    )
    monkeypatch.setattr(pc2_local_solver, "FALLBACK_STATE_PATH", state_path)
    monkeypatch.setattr(pc2_local_solver, "AUTH_COMPLETE_PENDING_MAX_SECONDS", 120.0)
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": True,
            "manual_required": True,
            "challenge_id": "challenge-current",
        },
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "notify_auth_complete",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("expired confirmation must yield before another completion request")
        ),
    )

    result = pc2_local_solver._retry_pending_auth_confirmation(
        "http://nas/api",
        state=state,
        now=1000.0,
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["superseded"] is True
    assert result["reason"] == "active_challenge_after_auth_confirmation_timeout"
    assert result["pending"] is False
    assert persisted["auth_complete_pending"] is False
    assert persisted["auth_completion_id"] is None
    assert persisted["last_success_at"] is None
    assert persisted["challenge_id"] == "challenge-current"
    assert persisted["slider_attempts"] == 2


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


def test_confirmed_auth_completion_reloads_status_before_solver_decision(monkeypatch) -> None:
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(
        pc2_local_solver,
        "_retry_pending_auth_confirmation",
        lambda _api: {"pending": False, "attempted": True, "confirmed": True},
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: (_ for _ in ()).throw(AssertionError("status must be read on the next loop")),
    )
    monkeypatch.setattr(pc2_local_solver.time, "sleep", lambda _seconds: (_ for _ in ()).throw(SystemExit()))

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=1)


def test_confirmed_auth_completion_suppresses_immediate_periodic_cdp_probe(monkeypatch) -> None:
    confirmation_results = iter(
        [
            {"pending": False, "attempted": True, "confirmed": True},
            {"pending": False, "attempted": False, "confirmed": False},
        ]
    )
    state = pc2_local_solver._default_fallback_state()
    monkeypatch.setattr(pc2_local_solver, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(
        pc2_local_solver,
        "_retry_pending_auth_confirmation",
        lambda _api: next(confirmation_results),
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "_retry_pending_collection_resume",
        lambda _api: {"pending": False, "attempted": False, "confirmed": False},
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": False,
            "running": False,
            "manual_required": False,
            "challenge_id": None,
            "last_request": {
                "node_id": "pc2",
                "target_url": "https://example.test/requested-page",
            },
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(
        pc2_local_solver,
        "_sync_challenge_state",
        lambda value, _challenge: (value, False),
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: (_ for _ in ()).throw(
            AssertionError("periodic probe must be suppressed during post-auth grace")
        ),
    )

    def stop_after_next_poll(seconds: float) -> None:
        if seconds > 0:
            raise SystemExit

    monkeypatch.setattr(pc2_local_solver.time, "sleep", stop_after_next_poll)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=30)


def test_close_stale_challenge_probe_target_preserves_keepalive(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeSolver:
        @staticmethod
        def _is_manual_challenge_url(value):
            return "/_____tmd_____/punish" in str(value or "")

        def __init__(self, *, cdp_endpoint, target_url):
            calls.append(("init", f"{cdp_endpoint}|{target_url}"))

        def _open_keepalive_tab(self):
            calls.append(("open", None))
            return "keepalive-1"

        def _close_cdp_target(self, target_id):
            calls.append(("close", target_id))
            return True

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(pc2_local_solver, "fetch_json", lambda *_args, **_kwargs: [])

    result = pc2_local_solver.close_stale_challenge_probe_target(
        "http://127.0.0.1:9223",
        {
            "_target_id": "challenge-1",
            "_target_url": "https://sf.taobao.com/list/page/_____tmd_____/punish?x5step=1",
        },
    )

    assert result == {
        "attempted": True,
        "closed": True,
        "target_id": "challenge-1",
        "keepalive_opened": True,
        "keepalive_reused": False,
    }
    assert calls == [
        ("init", "http://127.0.0.1:9223|https://sf.taobao.com/list/page/_____tmd_____/punish?x5step=1"),
        ("open", None),
        ("close", "challenge-1"),
    ]


def test_close_stale_challenge_probe_target_reuses_existing_keepalive(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    class FakeSolver:
        @staticmethod
        def _is_manual_challenge_url(value):
            return "/_____tmd_____/punish" in str(value or "")

        def __init__(self, *, cdp_endpoint, target_url):
            calls.append(("init", f"{cdp_endpoint}|{target_url}"))

        def _open_keepalive_tab(self):
            raise AssertionError("an existing keepalive must be reused")

        def _close_cdp_target(self, target_id):
            calls.append(("close", target_id))
            return True

    monkeypatch.setattr(pc2_local_solver, "CaptchaSolver", FakeSolver)
    monkeypatch.setattr(
        pc2_local_solver,
        "fetch_json",
        lambda *_args, **_kwargs: [
            {"id": "blank-1", "type": "page", "url": "about:blank"},
            {"id": "challenge-1", "type": "page", "url": "https://example.test/punish"},
        ],
    )

    result = pc2_local_solver.close_stale_challenge_probe_target(
        "http://127.0.0.1:9223",
        {
            "_target_id": "challenge-1",
            "_target_url": "https://sf.taobao.com/list/_____tmd_____/punish?x5step=1",
        },
    )

    assert result == {
        "attempted": True,
        "closed": True,
        "target_id": "challenge-1",
        "keepalive_opened": False,
        "keepalive_reused": True,
    }
    assert calls[-1] == ("close", "challenge-1")


def test_close_stale_challenge_probe_target_does_not_close_normal_page(monkeypatch) -> None:
    monkeypatch.setattr(
        pc2_local_solver.CaptchaSolver,
        "_is_manual_challenge_url",
        lambda _value: False,
    )
    monkeypatch.setattr(
        pc2_local_solver.CaptchaSolver,
        "_close_cdp_target",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("normal target must stay open")),
    )

    result = pc2_local_solver.close_stale_challenge_probe_target(
        "http://127.0.0.1:9223",
        {
            "_target_id": "normal-1",
            "_target_url": "https://sf.taobao.com/list/page=1",
        },
    )

    assert result == {"attempted": False, "closed": False, "reason": "target_not_challenge"}


def test_resolve_stale_challenge_probe_target_after_resume_rebuilds_lost_target(monkeypatch) -> None:
    requested_url = "https://sf.taobao.com/list/page=1"
    recovered_target = {
        "_target_id": "challenge-after-restart",
        "_target_url": "https://sf.taobao.com/list/_____tmd_____/punish?x5step=1",
    }
    calls: list[str] = []

    def fake_check(_endpoint, *, target_url=None):
        calls.append(target_url)
        return recovered_target

    monkeypatch.setattr(pc2_local_solver, "check_cdp_browser_for_challenge_page", fake_check)

    result = pc2_local_solver.resolve_stale_challenge_probe_target_after_resume(
        "http://127.0.0.1:9223",
        None,
        {
            "confirmed": True,
            "result": _confirmed_resume_payload("pc2-resume-restart", target_url=requested_url),
        },
    )

    assert result == recovered_target
    assert calls == [requested_url]


def test_confirmed_cooldown_resume_suppresses_immediate_periodic_cdp_probe(monkeypatch) -> None:
    requested_url = "https://sf.taobao.com/list/page=1"
    recovered_target = {
        "_target_id": "challenge-after-restart",
        "_target_url": "https://sf.taobao.com/list/_____tmd_____/punish?x5step=1",
    }
    resume_results = iter(
        [
            {
                "pending": False,
                "attempted": True,
                "confirmed": True,
                "result": _confirmed_resume_payload(
                    "pc2-resume-restart",
                    target_url=requested_url,
                ),
            },
            {"pending": False, "attempted": False, "confirmed": False},
        ]
    )
    cleanup_targets: list[dict[str, object] | None] = []
    state = pc2_local_solver._default_fallback_state()
    monkeypatch.setattr(pc2_local_solver, "POST_AUTH_CDP_PROBE_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(pc2_local_solver.time, "time", lambda: 1000.0)
    monkeypatch.setattr(pc2_local_solver, "check_cdp_healthy", lambda _endpoint: True)
    monkeypatch.setattr(
        pc2_local_solver,
        "_retry_pending_auth_confirmation",
        lambda _api: {"pending": False, "attempted": False, "confirmed": False},
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "_retry_pending_collection_resume",
        lambda _api: next(resume_results),
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "check_cdp_browser_for_challenge_page",
        lambda _endpoint, *, target_url=None: recovered_target if target_url == requested_url else None,
    )

    def fake_close(_endpoint, target):
        cleanup_targets.append(target)
        return {"attempted": True, "closed": True}

    monkeypatch.setattr(pc2_local_solver, "close_stale_challenge_probe_target", fake_close)
    monkeypatch.setattr(
        pc2_local_solver,
        "read_solver_status",
        lambda _api: {
            "paused": False,
            "running": False,
            "manual_required": False,
            "challenge_id": None,
            "last_request": {
                "node_id": "pc2",
                "target_url": "https://example.test/requested-page",
            },
        },
    )
    monkeypatch.setattr(pc2_local_solver, "_load_fallback_state", lambda: dict(state))
    monkeypatch.setattr(pc2_local_solver, "_save_fallback_state", lambda _state: None)
    monkeypatch.setattr(
        pc2_local_solver,
        "_sync_challenge_state",
        lambda value, _challenge: (value, False),
    )
    monkeypatch.setattr(
        pc2_local_solver,
        "check_cdp_browser_for_slider",
        lambda _endpoint, **_kwargs: (_ for _ in ()).throw(
            AssertionError("periodic probe must be suppressed after cooldown resume")
        ),
    )

    def stop_after_next_poll(seconds: float) -> None:
        if seconds > 0:
            raise SystemExit

    monkeypatch.setattr(pc2_local_solver.time, "sleep", stop_after_next_poll)

    with pytest.raises(SystemExit):
        pc2_local_solver.local_solver_loop(poll_seconds=30)

    assert cleanup_targets == [recovered_target]


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
