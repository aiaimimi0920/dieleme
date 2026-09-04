from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_literal_unknown_digest_stability_severity_from_payloads(
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
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "unknown",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51", "page": 51},
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
            "runner-literal-unknown-digest-stability-severity-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:")
    )
    assert "severity=unknown" not in digest_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_stability_severity") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_severity") != "unknown"

def test_main_treats_unknown_audit_message_as_missing_for_console_and_final_guidance(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "guidance": {},
            "recovery_policy": {
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            "lifecycle_summary": {},
            "intervention_summary": {},
            "intervention_stability_summary": {},
            "final_guidance_summary": {
                "guidance_label": "Escalating intervention",
                "guidance_priority": "high",
                "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            },
            "digest_summary": {},
            "digest_stability_summary": {},
            "escalation_event_trend_summary": {},
            "escalation_event_stability_summary": {},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "guidance_applied": False,
            "recovery_policy_applied": True,
            "guidance_status": "",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_mode_pin_active": True,
            "recovery_policy": {
                "effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=27", "page": 27},
            "browser_fallback_opened": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_source",
        lambda *args, **kwargs: "recovery_policy",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_action_hint",
        lambda *args, **kwargs: "follow recovery policy escalation guidance; suggested mode=browser",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: "unknown",
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
            "runner-unknown-audit-treated-missing",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_audit_message") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_audit_message") != "unknown"
    assert "[OPERATOR] Operator escalation audit: unknown" not in captured.err
    assert (
        "[OPERATOR] Final guidance: "
        "Escalating intervention: prefer browser and investigate escalating intervention."
    ) in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=recovery_policy" in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=27" in escalation_line

def test_main_suppresses_duplicate_intervention_details_after_normalizing_whitespace(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "recovery-policy-state.json"
    recovery_events_path = tmp_path / "recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "operator-escalation-events.jsonl"
    operator_escalation_state_path = tmp_path / "operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "operator-escalation-recovery-events.jsonl"
    operator_intervention_state_path = tmp_path / "operator-intervention-state.json"
    operator_intervention_events_path = tmp_path / "operator-intervention-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "guidance": {},
            "recovery_policy": {
                "policy_status": "escalate_repeated_repin",
                "priority": "high",
                "mode_pin_active": True,
                "effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            "lifecycle_summary": {},
            "intervention_summary": {
                "intervention_status": "intervention_required",
                "intervention_required": True,
                "intervention_priority": " high ",
                "intervention_reason": " repeated_repin_cycle_detected ",
                "suggested_mode": " browser ",
            },
            "intervention_stability_summary": {},
            "final_guidance_summary": {},
            "digest_summary": {},
            "digest_stability_summary": {},
            "escalation_event_trend_summary": {},
            "escalation_event_stability_summary": {},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
            "browser_fallback_opened": True,
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
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--runtime-operator-intervention-state-path",
            str(operator_intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(operator_intervention_events_path),
            "--session-id",
            "runner-normalized-duplicate-intervention-details",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    escalation_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Operator escalation:")
    )
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    intervention_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Intervention status:")
    )
    assert "required=True" in intervention_line
    assert "priority=high" not in intervention_line
    assert "reason=repeated_repin_cycle_detected" not in intervention_line
    assert "suggested_mode=browser" not in intervention_line

def test_main_treats_missing_effective_mode_resolution_as_requested_mode(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "recovery-policy-state.json"
    recovery_events_path = tmp_path / "recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "operator-escalation-events.jsonl"
    operator_escalation_state_path = tmp_path / "operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "operator-escalation-recovery-events.jsonl"
    operator_intervention_state_path = tmp_path / "operator-intervention-state.json"
    operator_intervention_events_path = tmp_path / "operator-intervention-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": " hybrid ",
            "effective_mode": None,
            "effective_mode_source": " unknown ",
            "guidance_applied": "unknown",
            "recovery_policy_applied": "unknown",
            "guidance_status": " unknown ",
            "guidance": {},
            "recovery_policy": {},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: (
            recorded_modes.append(kwargs["mode"])
            or {"decision": "idle", "task": None, "message": "done"}
        ),
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
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--runtime-operator-intervention-state-path",
            str(operator_intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(operator_intervention_events_path),
            "--session-id",
            "runner-missing-effective-mode-resolution",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert recorded_modes == ["hybrid"]
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["requested_mode"] == "hybrid"
    assert stdout_payload["effective_mode"] is None
    assert stdout_payload.get("effective_mode_source") is None
    assert "unknown" not in json.dumps(stdout_payload)
    assert "None" not in json.dumps(stdout_payload)
