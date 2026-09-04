from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_emit_operator_escalation_event_trend_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_escalation_event_stability_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_escalation_event_stability_console_summary_reports_shifted_source_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=" not in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_console_summaries_omit_negative_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": -1,
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": -1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "Operator digest stability" in captured.err
    assert "Operator escalation source trend" in captured.err
    assert "Operator escalation source stability" in captured.err
    assert "changes=" not in captured.err

def test_emit_operator_escalation_event_stability_console_summary_can_suppress_duplicate_source_context(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        suppress_source_context=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" not in captured.err
    assert "previous=recovery_policy" not in captured.err
    assert "changes=1" not in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" not in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "persistent_recovery_policy_source",
            "stability_severity": "high",
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "recovery_policy",
            "previous_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
            "operator_readable_explanation": "Operator escalation source remains recovery_policy with no recent source changes.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=recovery_policy" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=0" in captured.err
    assert "Operator escalation source remains recovery_policy with no recent source changes." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "explanation=unknown" not in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_severity(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "severity=unknown" not in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_current(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=unknown" not in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_previous(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err

def test_emit_operator_escalation_event_stability_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": " unknown ",
            "current_operator_escalation_source": " unknown ",
            "previous_operator_escalation_source": " unknown ",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator escalation source stability: source_recently_shifted"
    assert "severity=" not in captured.err
    assert "current=" not in captured.err
    assert "previous=" not in captured.err
    assert "changes=" not in captured.err
    assert "explanation=" not in captured.err
    assert "unknown" not in captured.err

def test_emit_operator_escalation_event_stability_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": " unknown ",
            "stability_severity": "warning",
            "current_operator_escalation_source": "intervention_stability",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""

def test_emit_operator_escalation_event_stability_console_summary_omits_empty_payload_when_everything_is_suppressed(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
        },
        suppress_source_context=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
