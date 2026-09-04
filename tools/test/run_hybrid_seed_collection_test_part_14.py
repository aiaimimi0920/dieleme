from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_emit_operator_intervention_stability_console_summary_can_suppress_duplicate_status_text(capsys):
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
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "Intervention stability: escalating" not in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_keeps_status_when_suppression_would_otherwise_blank_line(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "current_intervention_status": "intervention_required",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "unknown",
        },
        suppress_action_hint=True,
        suppress_current=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention stability: escalating"

def test_emit_operator_intervention_stability_console_summary_omits_unknown_action_hint(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=unknown" not in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_unknown_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "explanation=unknown" not in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_unknown_severity(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
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
    assert "severity=unknown" not in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Intervention escalated from ready to intervention_required recently." in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_unknown_current(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
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
    assert "severity=high" in captured.err
    assert "current=unknown" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Intervention escalated from ready to intervention_required recently." in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=warning" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=0" in captured.err
    assert "Intervention is transitioning and currently in monitor." in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_unknown_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "unknown",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "Intervention escalated from ready to intervention_required recently." in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": " unknown ",
            "current_intervention_status": " unknown ",
            "previous_intervention_status": " unknown ",
            "recent_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
            "stability_action_hint": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention stability: escalating"
    assert "severity=" not in captured.err
    assert "current=" not in captured.err
    assert "previous=" not in captured.err
    assert "changes=" not in captured.err
    assert "explanation=" not in captured.err
    assert "action_hint=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_intervention_stability_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": " unknown ",
            "stability_severity": "warning",
            "current_intervention_status": "intervention_required",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_final_guidance_console_summary_reports_noninfo_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Escalating intervention" in captured.err
    assert "priority=high" in captured.err
    assert "suggested_mode=browser" in captured.err

def test_emit_operator_final_guidance_console_summary_suppresses_casefolded_info_priority(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Routine guidance",
            "guidance_priority": " Info ",
            "guidance_message": "Routine guidance: continue monitoring.",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_final_guidance_console_summary_omits_unknown_suggested_mode(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=warning" in captured.err
    assert "suggested_mode=unknown" not in captured.err

def test_emit_operator_final_guidance_console_summary_omits_unknown_priority(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "unknown",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=unknown" not in captured.err
    assert "suggested_mode=browser" in captured.err
    assert "suggested_mode=unknown" not in captured.err

def test_emit_operator_final_guidance_console_summary_omits_malformed_priority(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": {"bad": "priority"},
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=" not in captured.err
    assert "suggested_mode=browser" in captured.err

def test_emit_operator_final_guidance_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": " unknown ",
            "guidance_priority": " unknown ",
            "guidance_message": "Transitioning intervention: monitor until stable.",
            "suggested_mode": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention: monitor until stable." in captured.err
    assert "priority=" not in captured.err
    assert "suggested_mode=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_digest_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_digest_console_summary_reports_nonready_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "digest_priority": "warning",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    assert "priority=warning" in captured.err
    assert "Transitioning intervention" in captured.err

def test_emit_operator_digest_console_summary_omits_unknown_priority(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=unknown" not in captured.err

def test_emit_operator_digest_console_summary_omits_unknown_message(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "digest_priority": "warning",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    assert "priority=warning" in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_digest_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "digest_priority": " unknown ",
            "operator_digest_message": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator digest: attention_required"
    assert "priority=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_digest_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": " unknown ",
            "digest_priority": "warning",
            "operator_digest_message": "Transitioning intervention: monitor until stable.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_digest_console_summary_can_suppress_duplicate_message_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        suppress_message=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "Escalating intervention:" not in captured.err

def test_emit_operator_digest_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        suppress_message=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "priority=high" in captured.err
    assert "intervention_required" not in captured.err
    assert "Escalating intervention:" not in captured.err
