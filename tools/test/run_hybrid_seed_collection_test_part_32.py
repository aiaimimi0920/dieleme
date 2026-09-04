from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_can_fail_with_dedicated_exit_code_on_lifecycle_high_priority_backlog(tmp_path: Path, monkeypatch, capsys):
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
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 3,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "suggested_mode": "browser",
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
            "--session-id",
            "runner-lifecycle-priority-exit",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "Lifecycle state" in captured.err
    assert "Operator escalation" in captured.err
    assert "source=lifecycle_high_priority_backlog" in captured.err
    assert "priority_hint=high_priority_backlog_present" in captured.err
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "reason=high_priority_unresolved_escalation_backlog" in escalation_line
    assert "reason=high_priority_unresolved_escalation_backlog" not in intervention_line
    assert "Returning dedicated operator escalation exit code 42" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert stdout_payload["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert runtime_summary["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert runtime_summary["lifecycle_state"] == "escalated"
    assert runtime_summary["lifecycle_reason"] == "unresolved_escalation_window_open"
    assert runtime_summary["lifecycle_follow_up"] == "prefer_browser_and_investigate_escalation"
    assert runtime_summary["lifecycle_suggested_mode"] == "browser"
    assert runtime_summary["lifecycle_priority_hint"] == "high_priority_backlog_present"
    assert runtime_summary["intervention_status"] == "intervention_required"
    assert runtime_summary["intervention_required"] is True
    assert runtime_summary["intervention_priority"] == "high"
    assert runtime_summary["intervention_reason"] == "high_priority_unresolved_escalation_backlog"
    assert runtime_summary["intervention_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert runtime_summary["intervention_suggested_mode"] == "browser"

def test_main_omits_missing_page_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
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
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=18"},
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
            "runner-escalation-no-page",
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
    assert "page=None" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line

def test_main_omits_unknown_guidance_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
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
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=19", "page": 19},
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
            "runner-escalation-no-guidance",
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
    assert "guidance=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line

def test_main_omits_unknown_digest_status_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
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
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=20", "page": 20},
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
            "runner-escalation-no-digest-status",
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
    assert "digest_status=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line

def test_main_omits_unknown_digest_stability_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
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
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=21", "page": 21},
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
            "runner-escalation-no-digest-stability",
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
    assert "digest_stability=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
