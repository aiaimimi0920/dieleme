from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_can_pin_browser_mode_from_recovery_policy(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "challenge_detected",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=10", "page": 10},
            "browser_fallback_opened": True,
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-recovery-pin",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["requested_mode"] == "hybrid"
    assert payload["effective_mode"] == "browser"
    assert payload["effective_mode_source"] == "recovery_policy"
    assert payload["recovery_policy_status"] == "pin_browser_mode_temporarily"
    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload["top_guidance_reason"] == "challenge_detected"

def test_main_records_recovery_policy_release_transition_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=11", "page": 11},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-release",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["effective_mode"] == "hybrid"
    assert payload["recovery_policy_status"] == "allow_hybrid_retrial"
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload["from_policy_status"] == "pin_browser_mode_temporarily"
    assert transition_payload["to_policy_status"] == "allow_hybrid_retrial"
    assert transition_payload["from_mode_pin_active"] is True
    assert transition_payload["to_mode_pin_active"] is False
    assert transition_payload["requested_mode"] == "hybrid"
    assert transition_payload["effective_mode"] == "hybrid"

def test_append_recovery_policy_transition_events_omits_literal_unknown_effective_mode(tmp_path: Path):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": 60},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-effective-mode",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("effective_mode") != "unknown"

def test_append_recovery_policy_transition_events_omits_literal_unknown_task_page(tmp_path: Path):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": "unknown"},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-task-page",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("task_page") != "unknown"

def test_append_recovery_policy_transition_events_omits_literal_unknown_task_url(tmp_path: Path):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "unknown", "page": 60},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-task-url",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("task_url") != "unknown"

def test_append_recovery_policy_transition_events_omits_literal_unknown_requested_mode(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "unknown",
            "effective_mode": "hybrid",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": 60},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-requested-mode",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("requested_mode") != "unknown"

def test_append_recovery_policy_transition_events_omits_whitespace_unknown_fields(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "recovery_policy_status": " unknown ",
            "recovery_policy_effective_recommended_mode": " unknown ",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": " unknown ",
            "task": {"url": " unknown ", "page": "unknown"},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-whitespace-placeholder-fields",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("to_policy_status") is None
    assert transition_payload.get("to_effective_recommended_mode") is None
    assert transition_payload.get("to_top_policy_reason") is None
    assert transition_payload.get("requested_mode") is None
    assert transition_payload.get("effective_mode") is None
    assert transition_payload.get("task_url") is None
    assert transition_payload.get("task_page") is None
    assert "unknown" not in json.dumps(transition_payload)

    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": False,
        "top_policy_reason": None,
    }

def test_append_recovery_policy_transition_events_treats_unknown_result_as_missing(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        "unknown",
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-result",
    )

    assert not recovery_events_path.exists()
    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }
