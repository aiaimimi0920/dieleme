from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_append_operator_intervention_transition_events_treats_unknown_final_guidance_summary_as_missing(
    tmp_path: Path,
):
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

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
        },
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        "unknown",
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-unknown-final-guidance-summary",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("to_final_guidance_label") is None
    assert event_payload.get("to_final_guidance_priority") is None
    assert event_payload.get("to_final_guidance_message") is None

def test_append_operator_intervention_transition_events_records_required_flag_clear_when_only_explicit_false_is_present(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_required": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
        },
        {
            "intervention_required": False,
        },
        {},
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-required-flag-cleared",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "required_flag_changed"
    assert event_payload["from_intervention_required"] is True
    assert event_payload["to_intervention_required"] is False
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload["intervention_required"] is False

def test_append_operator_intervention_transition_events_persists_explicit_false_without_event_when_no_previous_state_exists(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
        },
        {
            "intervention_required": False,
        },
        {},
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-explicit-false-no-previous-state",
    )

    assert not intervention_events_path.exists()
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload["intervention_required"] is False

def test_main_omits_literal_unknown_final_guidance_priority_from_intervention_transition_event(
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
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "unknown",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
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
            "runner-intervention-event-unknown-guidance-priority",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["to_final_guidance_label"] == "Escalating intervention"
    assert event_payload.get("to_final_guidance_priority") != "unknown"
    assert event_payload["to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."

def test_main_omits_literal_unknown_final_guidance_message_from_intervention_transition_event(
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
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "unknown",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
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
            "runner-intervention-event-unknown-guidance-message",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["to_final_guidance_label"] == "Escalating intervention"
    assert event_payload["to_final_guidance_priority"] == "high"
    assert event_payload.get("to_final_guidance_message") != "unknown"
