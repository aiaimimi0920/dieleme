from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_emit_operator_lifecycle_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_lifecycle_console_summary_omits_empty_parentheses_when_only_status_is_visible(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "unknown",
            "suggested_mode": "unknown",
            "priority_hint": "unknown",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Lifecycle state: monitor"

def test_emit_operator_lifecycle_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": " unknown ",
            "recommended_follow_up": " unknown ",
            "suggested_mode": " unknown ",
            "priority_hint": " unknown ",
            "active_unresolved_priority": " unknown ",
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Lifecycle state: monitor"
    assert "reason=" not in captured.err
    assert "follow_up=" not in captured.err
    assert "suggested_mode=" not in captured.err
    assert "priority_hint=" not in captured.err
    assert "active_unresolved_priority=" not in captured.err
    assert "active_high_priority_unresolved_count=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_lifecycle_console_summary_treats_whitespace_unknown_state_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": " unknown ",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_intervention_console_summary_reports_nonready_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "required=True" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "suggested_mode=browser" not in captured.err

def test_emit_operator_intervention_console_summary_omits_unknown_action_hint(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "action_hint=unknown" not in captured.err
    assert "suggested_mode=browser" in captured.err

def test_emit_operator_intervention_console_summary_omits_unknown_suggested_mode(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "action_hint=inspect unresolved high-priority backlog" in captured.err
    assert "suggested_mode=unknown" not in captured.err

def test_emit_operator_final_guidance_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_intervention_console_summary_omits_unknown_priority(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=unknown" not in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "action_hint=inspect unresolved high-priority backlog" in captured.err
    assert "suggested_mode=browser" in captured.err

def test_emit_operator_intervention_console_summary_omits_unknown_reason(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=unknown" not in captured.err
    assert "action_hint=inspect unresolved high-priority backlog" in captured.err
    assert "suggested_mode=browser" in captured.err

def test_emit_operator_intervention_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_intervention_stability_console_summary_treats_unknown_summary_as_missing(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_intervention_console_summary_keeps_suggested_mode_when_action_hint_lacks_mode(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "suggested_mode=browser" in captured.err

def test_emit_operator_intervention_console_summary_can_suppress_duplicate_reason_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "preferred_operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "suggested_mode": "browser",
        },
        suppress_reason=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=repeated_repin_cycle_detected" not in captured.err
    assert "suggested_mode=browser" not in captured.err

def test_emit_operator_intervention_console_summary_can_suppress_duplicate_priority_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "preferred_operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "suggested_mode": "browser",
        },
        suppress_priority=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" not in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err
    assert "suggested_mode=browser" not in captured.err

def test_emit_operator_intervention_console_summary_can_suppress_duplicate_suggested_mode_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "preferred_operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "suggested_mode": "browser",
        },
        suppress_suggested_mode=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err
    assert "suggested_mode=browser" not in captured.err

def test_emit_operator_intervention_console_summary_omits_empty_parentheses_when_only_status_is_visible(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": "unknown",
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention status: intervention_required"

def test_emit_operator_intervention_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": " unknown ",
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "preferred_operator_action_hint": " unknown ",
            "suggested_mode": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention status: intervention_required"
    assert "required=" not in captured.err
    assert "priority=" not in captured.err
    assert "reason=" not in captured.err
    assert "action_hint=" not in captured.err
    assert "suggested_mode=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_intervention_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": " unknown ",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_intervention_stability_console_summary_reports_nonstable_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=" not in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_can_suppress_duplicate_action_hint(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
        suppress_action_hint=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" not in captured.err

def test_emit_operator_intervention_stability_console_summary_can_suppress_duplicate_current_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
        suppress_current=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err
