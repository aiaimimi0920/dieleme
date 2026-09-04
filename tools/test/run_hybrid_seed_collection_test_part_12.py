from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_emit_operator_console_summary_omits_unknown_priority_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=unknown" not in captured.err
    assert "mode=browser" in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err

def test_emit_operator_console_summary_omits_unknown_mode_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=unknown" not in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err

def test_emit_operator_console_summary_uses_fallback_when_primary_values_are_whitespace_unknown(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": " unknown ",
            "recovery_policy_effective_recommended_mode": " unknown ",
            "top_policy_reason": " unknown ",
            "operator_final_guidance_label": " unknown ",
            "operator_digest_status": " unknown ",
            "operator_digest_stability_status": " unknown ",
            "task": {"page": "unknown"},
        },
        intervention_summary={
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        final_guidance_summary={
            "guidance_label": "Escalating intervention",
        },
        digest_summary={
            "digest_status": "intervention_required",
        },
        digest_stability_summary={
            "stability_status": "digest_recently_shifted",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=recovery_policy" in escalation_line
    assert "priority=warning" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "guidance=Escalating intervention" in escalation_line
    assert "digest_status=intervention_required" in escalation_line
    assert "digest_stability=digest_recently_shifted" in escalation_line
    assert "page=" not in escalation_line
    assert "unknown" not in escalation_line

def test_emit_operator_console_summary_omits_whitespace_unknown_values_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": "Operator escalation [source=intervention_policy]",
            "recovery_policy_effective_recommended_mode": " unknown ",
            "recovery_policy_priority": " unknown ",
            "top_policy_reason": " unknown ",
            "task": {"page": "unknown"},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "suggested_mode": " unknown ",
        },
        stability_summary={
            "stability_status": " unknown ",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line == "[OPERATOR] Operator escalation: intervention_required"
    assert "unknown" not in escalation_line
    assert "()" not in escalation_line

def test_emit_operator_console_summary_treats_whitespace_unknown_status_label_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {},
        intervention_summary={
            "intervention_status": " unknown ",
            "intervention_required": True,
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line.startswith("[OPERATOR] Operator escalation: operator_escalation")
    assert "unknown" not in escalation_line

def test_emit_operator_recovery_console_summary_reports_escalation_cleared_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=20" in captured.err

def test_emit_operator_recovery_console_summary_strips_transition_kind(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": " escalation_cleared ",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err

def test_emit_operator_recovery_console_summary_omits_missing_page_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": None,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=None" not in captured.err

def test_emit_operator_recovery_console_summary_omits_negative_page_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": -20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=" not in captured.err

def test_emit_operator_recovery_console_summary_omits_missing_mode_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": None,
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=unknown" not in captured.err
    assert "page=20" in captured.err

def test_emit_operator_recovery_console_summary_omits_missing_to_status_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": None,
                "effective_mode": "hybrid",
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=unknown" not in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=20" in captured.err

def test_emit_operator_recovery_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": " unknown ",
                "to_policy_status": " unknown ",
                "effective_mode": " unknown ",
                "task_page": "unknown",
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator recovery: escalation_cleared"
    assert "from=" not in captured.err
    assert "to=" not in captured.err
    assert "mode=" not in captured.err
    assert "page=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_lifecycle_console_summary_reports_nonsteady_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "retrial_window_open",
            "lifecycle_reason": "hybrid_retrial_budget_active",
            "recommended_follow_up": "continue_hybrid_with_budget_watch",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "retrial_window_open" in captured.err
    assert "follow_up=continue_hybrid_with_budget_watch" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err
    assert "active_unresolved_priority=None" not in captured.err

def test_emit_operator_lifecycle_console_summary_omits_unknown_follow_up(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "follow_up=unknown" not in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err

def test_emit_operator_lifecycle_console_summary_omits_unknown_active_unresolved_priority(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "reason=recovery_policy_monitoring_active" in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err
    assert "active_unresolved_priority=unknown" not in captured.err
    assert "active_high_priority_unresolved_count=0" in captured.err

def test_emit_operator_lifecycle_console_summary_omits_unknown_suggested_mode(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=unknown" not in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err

def test_emit_operator_lifecycle_console_summary_omits_unknown_active_high_priority_unresolved_count(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "active_high_priority_unresolved_count=" not in captured.err

def test_emit_operator_lifecycle_console_summary_omits_negative_active_high_priority_unresolved_count(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": -2,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "active_high_priority_unresolved_count=" not in captured.err

def test_emit_operator_lifecycle_console_summary_omits_unknown_priority_hint(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=unknown" not in captured.err

def test_emit_operator_lifecycle_console_summary_omits_unknown_reason(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "reason=unknown" not in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err
