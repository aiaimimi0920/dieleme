from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_unknown_reason_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

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
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=22", "page": 22},
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
            "--session-id",
            "runner-escalation-no-reason",
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
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "reason=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line

def test_main_omits_unknown_status_label_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
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
            "lifecycle_state": "unknown",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "unknown",
            "suggested_mode": "unknown",
            "priority_hint": "unknown",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "unknown",
            "intervention_required": True,
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "current_intervention_status": "unknown",
            "previous_intervention_status": "unknown",
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=22", "page": 22},
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
            "runner-escalation-no-status-label",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "[OPERATOR] Operator escalation: unknown" not in escalation_line
    assert "[OPERATOR] Operator escalation: operator_escalation" in escalation_line
    assert "source=intervention_policy" in escalation_line

def test_main_omits_unknown_priority_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

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
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=23", "page": 23},
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
            "--session-id",
            "runner-escalation-no-priority",
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
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line

def test_main_omits_literal_unknown_recovery_policy_priority_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

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
            "priority": "unknown",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=24", "page": 24},
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
            "--session-id",
            "runner-literal-unknown-recovery-policy-priority-payloads",
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
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_priority") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_priority") != "unknown"

def test_main_omits_literal_unknown_recovery_policy_status_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

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
            "policy_status": "unknown",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=25", "page": 25},
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
            "runner-literal-unknown-recovery-policy-status-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_status") != "unknown"
