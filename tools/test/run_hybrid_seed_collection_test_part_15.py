from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_emit_operator_digest_stability_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_digest_stability_console_summary_reports_nonstable_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_digest_stability_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=" not in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_digest_stability_console_summary_can_suppress_duplicate_current_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
        suppress_current=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_digest_stability_console_summary_keeps_status_without_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err

def test_emit_operator_digest_stability_console_summary_omits_unknown_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "explanation=unknown" not in captured.err

def test_emit_operator_digest_stability_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": " unknown ",
            "current_digest_status": " unknown ",
            "previous_digest_status": " unknown ",
            "recent_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator digest stability: digest_recently_shifted"
    assert "severity=" not in captured.err
    assert "current=" not in captured.err
    assert "previous=" not in captured.err
    assert "changes=" not in captured.err
    assert "explanation=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_digest_stability_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": " unknown ",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_digest_stability_console_summary_keeps_status_when_suppression_would_otherwise_blank_line(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "current_digest_status": "attention_required",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "unknown",
        },
        suppress_current=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator digest stability: digest_recently_shifted"

def test_emit_operator_digest_stability_console_summary_omits_unknown_severity(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=unknown" not in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_digest_stability_console_summary_omits_unknown_current(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=unknown" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_digest_stability_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
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
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "severity=high" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=0" in captured.err
    assert "Operator digest remains non-info with no recent message changes." in captured.err

def test_emit_operator_digest_stability_console_summary_omits_unknown_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "unknown",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_digest_stability_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err

def test_emit_operator_escalation_event_trend_console_summary_reports_source_shift_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err

def test_emit_operator_escalation_event_trend_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err

def test_emit_operator_escalation_event_trend_console_summary_omits_missing_last_changed_at_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": None,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=None" not in captured.err

def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_last_changed_at_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=unknown" not in captured.err

def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err

def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_current_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "unknown",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=" not in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err

def test_emit_operator_escalation_event_trend_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": " unknown ",
            "recent_source_change_count": "unknown",
            "last_source_change_at": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_escalation_event_trend_console_summary_treats_whitespace_unknown_current_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": " unknown ",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
