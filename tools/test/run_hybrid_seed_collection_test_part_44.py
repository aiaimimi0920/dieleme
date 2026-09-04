from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_treats_unknown_intervention_required_as_missing_on_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": "unknown",
            "intervention_priority": "warning",
            "intervention_reason": "recovery_policy_monitoring_active",
            "preferred_operator_action_hint": "monitor until stable",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-required",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["to_intervention_status"] == "monitor"
    assert event_payload["to_intervention_required"] is False
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("intervention_required") is None

def test_main_treats_unknown_intervention_required_as_missing_for_console_runtime_and_escalation(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": "unknown",
            "intervention_priority": "warning",
            "intervention_reason": "recovery_policy_monitoring_active",
            "preferred_operator_action_hint": "monitor until stable",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
            "stability_action_hint": "monitor until stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-intervention-required-runtime",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "required=True" not in intervention_line
    assert "required=" not in intervention_line
    assert "[OPERATOR] Operator escalation:" not in captured.err
    stdout_payload = json.loads(captured.out)
    assert "operator_escalation_source" not in stdout_payload
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_required") is None
    assert runtime_summary.get("operator_escalation_source") is None

def test_build_next_task_request_url_uses_collection_seed_endpoint():
    url = run_hybrid_seed_collection.build_next_task_request_url(
        "http://127.0.0.1:8001/api",
        session_id="runner-a",
    )

    parsed = urlparse(url)
    assert parsed.path == "/api/collection/seeds/next_task"
    assert parse_qs(parsed.query) == {"session_id": ["runner-a"]}

def test_build_browser_fallback_url_adds_sniff_worker_mode():
    url = run_hybrid_seed_collection.build_browser_fallback_url(
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&page=1"
    )

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "sf.taobao.com"
    assert parse_qs(parsed.query)["uni_mode"] == ["SNIFF_WORKER"]
    assert parse_qs(parsed.query)["location_code"] == ["110101"]

def test_claim_next_seed_task_uses_http_endpoint():
    session = _FakeHttpSession({"task": {"url": "https://sf.taobao.com/x"}, "message": "ok"})

    payload = run_hybrid_seed_collection.claim_next_seed_task(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        http_session=session,
    )

    assert payload == {"task": {"url": "https://sf.taobao.com/x"}, "message": "ok"}
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/collection/seeds/next_task?session_id=runner-a",
            "timeout": 30,
        }
    ]

def test_run_once_returns_idle_when_no_task_is_available():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": None, "message": "所有嗅探任务已完成"},
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "idle",
        "message": "所有嗅探任务已完成",
        "task": None,
    }

def test_run_once_omits_unknown_idle_message():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": None, "message": " unknown "},
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "idle",
        "message": None,
        "task": None,
    }
    assert "unknown" not in json.dumps(result)

def test_run_once_treats_whitespace_unknown_task_url_as_idle():
    calls = {"export": 0, "hybrid": 0}

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": " unknown ", "page": "unknown"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: calls.__setitem__("export", calls["export"] + 1),
        hybrid_collect_fn=lambda *_args, **_kwargs: calls.__setitem__("hybrid", calls["hybrid"] + 1),
    )

    assert result == {
        "decision": "idle",
        "message": "ok",
        "task": {"url": None, "page": None},
    }
    assert calls == {"export": 0, "hybrid": 0}
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_malformed_task_payload():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": " unknown ", "message": "ok"},
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "idle",
        "message": "ok",
        "task": {},
    }
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_task_metadata():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {
            "task": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "page": 1,
                "source": " unknown ",
            },
            "message": "ok",
        },
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "browserless_success", "reason": None},
    )

    assert result["task"]["source"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_returns_api_unavailable_when_dispatch_endpoint_is_down():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: (_ for _ in ()).throw(requests.exceptions.ConnectionError("boom")),
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "api_unavailable",
        "reason": "dispatch_endpoint_unreachable",
        "error": "boom",
    }

def test_run_once_omits_unknown_api_error_message():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: (_ for _ in ()).throw(requests.exceptions.ConnectionError(" unknown ")),
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "api_unavailable",
        "reason": "dispatch_endpoint_unreachable",
        "error": None,
    }
    assert "unknown" not in json.dumps(result)

def test_run_once_executes_browserless_collection_when_task_is_available():
    calls = {}

    def _hybrid_collect(url: str, *, cookies, submit: bool, api_base: str):
        calls["url"] = url
        calls["cookies"] = cookies
        calls["submit"] = submit
        calls["api_base"] = api_base
        return {"decision": "browserless_success", "reason": None}

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=_hybrid_collect,
    )

    assert result["decision"] == "browserless_success"
    assert result["task"]["url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert calls == {
        "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        "cookies": [{"name": "cookie2", "value": "abc"}],
        "submit": True,
        "api_base": "http://127.0.0.1:8001/api",
    }

def test_run_once_treats_malformed_collection_result_as_missing():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: "unknown",
    )

    assert result["decision"] is None
    assert result["reason"] is None
    assert result["collection_result"] == {}
    assert result["task"]["url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert "unknown" not in json.dumps(result)
