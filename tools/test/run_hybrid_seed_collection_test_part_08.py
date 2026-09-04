from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_append_operator_escalation_events_omits_literal_unknown_task_url(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "task": {"url": "unknown", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-task-url",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("task_url") != "unknown"

def test_append_operator_escalation_events_omits_literal_unknown_requested_mode(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "unknown",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-requested-mode",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("requested_mode") != "unknown"

def test_append_operator_escalation_events_omits_whitespace_unknown_optional_fields(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "recovery_policy_status": " unknown ",
            "recovery_policy_priority": " unknown ",
            "top_policy_reason": " unknown ",
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "operator_escalation_audit_message": " unknown ",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-whitespace-fields",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("policy_status") is None
    assert event_payload.get("policy_priority") is None
    assert event_payload.get("top_policy_reason") is None
    assert event_payload.get("requested_mode") is None
    assert event_payload.get("effective_mode") is None
    assert event_payload.get("effective_mode_source") is None
    assert event_payload.get("operator_escalation_audit_message") is None
    assert "unknown" not in json.dumps(event_payload)

def test_append_operator_escalation_events_treats_whitespace_unknown_source_as_missing_for_repeated_repin_policy(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": " unknown ",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-whitespace-unknown-source-repeated-repin",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "repeated_repin_cycle"
    assert event_payload.get("operator_escalation_source") == "recovery_policy"

def test_persist_operator_escalation_state_omits_literal_unknown_policy_fields(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-escalation-state.json"

    run_hybrid_seed_collection.persist_operator_escalation_state(
        {
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "unknown",
            "top_policy_reason": "unknown",
            "escalation_kind": "repeated_repin_cycle",
        },
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["policy_status"] == "escalate_repeated_repin"
    assert state_payload.get("policy_priority") != "unknown"
    assert state_payload.get("top_policy_reason") != "unknown"

def test_persist_operator_escalation_state_omits_whitespace_unknown_policy_fields(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-escalation-state.json"

    run_hybrid_seed_collection.persist_operator_escalation_state(
        {
            "policy_status": " unknown ",
            "policy_priority": " unknown ",
            "top_policy_reason": " unknown ",
            "escalation_kind": "repeated_repin_cycle",
        },
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["escalation_kind"] == "repeated_repin_cycle"
    assert state_payload.get("policy_status") is None
    assert state_payload.get("policy_priority") is None
    assert state_payload.get("top_policy_reason") is None
    assert "unknown" not in json.dumps(state_payload)

def test_persist_operator_escalation_state_treats_unknown_payload_as_missing(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-escalation-state.json"

    run_hybrid_seed_collection.persist_operator_escalation_state(
        "unknown",
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "escalation_kind": None,
        "policy_status": None,
        "policy_priority": None,
        "top_policy_reason": None,
    }

def test_main_records_recovery_from_operator_escalation_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
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
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=19", "page": 19},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip().startswith("{")
    assert "Operator recovery" in captured.err
    assert "steady_hybrid" in captured.err
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload["from_policy_status"] == "escalate_repeated_repin"
    assert recovery_payload["to_policy_status"] == "steady_hybrid"
    assert recovery_payload["effective_mode"] == "hybrid"

def test_append_operator_escalation_recovery_events_treats_unknown_result_as_missing(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        "unknown",
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-result",
    )

    assert recovery_events == []
    assert not operator_escalation_recovery_events_path.exists()
    state_payload = json.loads(operator_escalation_state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "escalation_kind": None,
        "policy_status": None,
        "policy_priority": None,
        "top_policy_reason": None,
    }

def test_append_operator_escalation_recovery_events_omits_literal_unknown_task_page(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": "unknown"},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-task-page",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("task_page") != "unknown"

def test_append_operator_escalation_recovery_events_records_clear_for_intervention_policy_state(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "escalation_kind": "intervention_policy",
                "policy_status": "steady_hybrid",
                "policy_priority": "warning",
                "top_policy_reason": "monitor_until_stable",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-intervention-policy",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload["from_escalation_kind"] == "intervention_policy"
    assert recovery_payload["from_policy_status"] == "steady_hybrid"
    assert recovery_payload["to_policy_status"] is None

def test_append_operator_escalation_recovery_events_omits_literal_unknown_task_url(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "hybrid",
            "task": {"url": "unknown", "page": 55},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-task-url",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("task_url") != "unknown"
