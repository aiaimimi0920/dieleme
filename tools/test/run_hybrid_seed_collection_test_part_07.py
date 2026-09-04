from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_records_operator_escalation_event_for_repeated_repin_policy(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Persistent intervention required",
            "guidance_priority": "high",
            "guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "preferred_action_hint": "treat as sustained intervention and investigate backlog",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "persistent_intervention_required",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "persistent_intervention_required",
            "final_guidance_stability_status": "persistent_noninfo_guidance",
            "operator_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "persistent_noninfo_digest",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Operator digest remains non-info with no recent message changes.",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=16", "page": 16},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalate-repin",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.strip()
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert recorded_modes == ["browser"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["effective_mode_source"] == "recovery_policy"
    assert payload["recovery_policy_status"] == "escalate_repeated_repin"
    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "repeated_repin_cycle"
    assert event_payload["policy_status"] == "escalate_repeated_repin"
    assert event_payload["policy_priority"] == "high"
    assert event_payload["top_policy_reason"] == "repeated_repin_cycle_detected"
    assert event_payload["requested_mode"] == "hybrid"
    assert event_payload["effective_mode"] == "browser"
    assert event_payload["operator_escalation_audit_message"] == (
        "Persistent intervention required: treat as sustained intervention and investigate backlog. "
        "[source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]"
    )

def test_main_records_operator_escalation_event_for_intervention_stability(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

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
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33", "page": 33},
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
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalate-intervention-stability",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_stability"
    assert event_payload["operator_escalation_source"] == "intervention_stability"
    assert event_payload["requested_mode"] == "hybrid"
    assert event_payload["effective_mode"] == "hybrid"
    assert event_payload["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )

def test_append_operator_escalation_events_omits_literal_unknown_policy_fields(tmp_path: Path):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "recovery_policy_status": "unknown",
            "recovery_policy_priority": "unknown",
            "top_policy_reason": "unknown",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=52", "page": 52},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-policy-fields",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("policy_status") != "unknown"
    assert event_payload.get("policy_priority") != "unknown"
    assert event_payload.get("top_policy_reason") != "unknown"

def test_append_operator_escalation_events_omits_literal_unknown_audit_message(tmp_path: Path):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "operator_escalation_audit_message": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=54", "page": 54},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-audit-message",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("operator_escalation_audit_message") != "unknown"

def test_append_operator_escalation_events_treats_unknown_source_as_missing_for_repeated_repin_policy(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "unknown",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-source-repeated-repin",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "repeated_repin_cycle"
    assert event_payload.get("operator_escalation_source") == "recovery_policy"

def test_append_operator_escalation_events_treats_unknown_result_as_missing(tmp_path: Path):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        "unknown",
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-result",
    )

    assert not operator_escalation_path.exists()

def test_append_operator_escalation_events_omits_literal_unknown_effective_mode_source(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=57", "page": 57},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-effective-mode-source",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("effective_mode_source") != "unknown"

def test_append_operator_escalation_events_omits_literal_unknown_effective_mode(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "guidance",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-effective-mode",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("effective_mode") != "unknown"

def test_append_operator_escalation_events_omits_literal_unknown_task_page(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": "unknown"},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-task-page",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("task_page") != "unknown"
