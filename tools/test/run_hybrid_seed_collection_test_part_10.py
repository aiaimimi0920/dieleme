from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_missing_to_status_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": 50},
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
            "runner-escalation-recovered-no-to-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=unknown" not in recovery_line
    assert "mode=hybrid" in recovery_line
    assert "page=50" in recovery_line

def test_main_omits_unknown_page_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": "unknown"},
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
            "runner-escalation-recovered-unknown-page",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "page=unknown" not in recovery_line
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=steady_hybrid" in recovery_line
    assert "mode=hybrid" in recovery_line

def test_emit_operator_recovery_console_summary_omits_empty_parentheses(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert recovery_line == "[OPERATOR] Operator recovery: escalation_cleared"
    assert "()" not in recovery_line

def test_main_omits_empty_parentheses_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

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
        "resolve_effective_mode",
        lambda *args, **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "requested_mode",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51"},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "append_operator_escalation_recovery_events",
        lambda *args, **kwargs: [
            {
                "transition_kind": "escalation_cleared",
            }
        ],
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
            "runner-escalation-recovered-empty-parts",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert recovery_line == "[OPERATOR] Operator recovery: escalation_cleared"
    assert "()" not in recovery_line

def test_emit_operator_console_summary_reports_repeated_repin_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "page=17" in captured.err

def test_emit_operator_console_summary_omits_unknown_page_on_non_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": "unknown"},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "page=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line

def test_emit_operator_console_summary_treats_unhashable_page_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": []},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Operator escalation:")
    )
    assert "page=" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line

def test_emit_operator_console_summary_treats_unknown_task_payload_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=" not in escalation_line

def test_emit_operator_console_summary_omits_negative_task_page(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": -3},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=" not in escalation_line

def test_emit_operator_console_summary_can_include_audit_message_on_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Escalating intervention: prefer browser and investigate escalating intervention. "
                "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
            ),
            "operator_final_guidance_label": "Escalating intervention",
            "operator_digest_status": "intervention_required",
            "operator_digest_stability_status": "digest_recently_shifted",
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        stability_summary={
            "stability_status": "escalating",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "[OPERATOR] Operator escalation audit: "
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    ) in captured.err
    assert "Operator escalation" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=intervention_stability" not in escalation_line
    assert "digest_status=intervention_required" not in escalation_line
    assert "digest_stability=digest_recently_shifted" not in escalation_line
