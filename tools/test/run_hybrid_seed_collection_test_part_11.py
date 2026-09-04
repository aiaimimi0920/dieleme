from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_emit_operator_console_summary_omits_unknown_page_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Escalating intervention: prefer browser and investigate escalating intervention. "
                "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
            ),
            "operator_final_guidance_label": "Escalating intervention",
            "operator_digest_status": "intervention_required",
            "operator_digest_stability_status": "digest_recently_shifted",
            "task": {"page": "unknown"},
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
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "page=unknown" not in escalation_line
    assert "priority=warning" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line

def test_emit_operator_console_summary_treats_unknown_audit_message_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": "unknown",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 34},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[OPERATOR] Operator escalation audit: unknown" not in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=recovery_policy" in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=34" in escalation_line

def test_emit_operator_console_summary_omits_unknown_reason_value_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Operator escalation "
                "[source=intervention_policy, digest=unknown, digest_stability=unknown]"
            ),
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "suggested_mode": "browser",
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=warning" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unknown" not in escalation_line
    assert "page=33" in escalation_line

def test_emit_operator_console_summary_omits_unknown_priority_value_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Operator escalation "
                "[source=intervention_policy, digest=unknown, digest_stability=unknown]"
            ),
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "page=33" in escalation_line

def test_emit_operator_console_summary_omits_unknown_mode_value_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Operator escalation "
                "[source=intervention_policy, digest=unknown, digest_stability=unknown]"
            ),
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "mode=unknown" not in escalation_line
    assert "priority=warning" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "page=33" in escalation_line

def test_emit_operator_console_summary_omits_empty_parentheses_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": "Operator escalation [source=intervention_policy]",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33"},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line == "[OPERATOR] Operator escalation: intervention_required"
    assert "()" not in escalation_line

def test_operator_escalation_audit_message_omits_unknown_digest_status():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {},
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )

    assert message is not None
    assert "[source=intervention_policy" in message
    assert "digest=unknown" not in message

def test_operator_escalation_source_treats_unknown_summaries_as_missing():
    source = run_hybrid_seed_collection.operator_escalation_source(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
    )

    assert source == "recovery_policy"

def test_operator_escalation_source_strips_known_status_fields():
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {"recovery_policy_status": " escalate_repeated_repin "}
        )
        == "recovery_policy"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            lifecycle_summary={"priority_hint": " high_priority_backlog_present "},
        )
        == "lifecycle_high_priority_backlog"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            intervention_summary={
                "intervention_reason": " high_priority_unresolved_escalation_backlog "
            },
        )
        == "lifecycle_high_priority_backlog"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            stability_summary={"stability_status": " escalating "},
        )
        == "intervention_stability"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            stability_summary={"stability_status": " flapping "},
            include_flapping=True,
        )
        == "intervention_stability_flapping"
    )

def test_operator_escalation_source_treats_unhashable_intervention_required_as_missing():
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            intervention_summary={"intervention_required": []},
        )
        is None
    )

def test_operator_action_hint_treats_unknown_summaries_as_missing():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_effective_recommended_mode": "browser",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
    )

    assert hint == "follow recovery policy escalation guidance; suggested mode=browser"

def test_operator_escalation_audit_message_omits_unknown_digest_stability_status():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {},
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )

    assert message is not None
    assert "[source=intervention_policy" in message
    assert "digest_stability=unknown" not in message

def test_operator_escalation_audit_message_treats_unknown_summaries_as_missing():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
        final_guidance_summary="unknown",
        digest_summary="unknown",
        digest_stability_summary="unknown",
    )

    assert message == "Operator escalation [source=recovery_policy]"

def test_operator_escalation_audit_message_uses_fallback_when_primary_values_are_whitespace_unknown():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "operator_final_guidance_message": " unknown ",
            "operator_digest_status": " unknown ",
            "operator_digest_stability_status": " unknown ",
        },
        final_guidance_summary={
            "guidance_message": "Escalating intervention",
        },
        digest_summary={
            "digest_status": "intervention_required",
        },
        digest_stability_summary={
            "stability_status": "digest_recently_shifted",
        },
    )

    assert message == (
        "Escalating intervention "
        "[source=recovery_policy, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert "unknown" not in message

def test_operator_action_hint_uses_fallback_when_primary_suggested_mode_is_whitespace_unknown():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_effective_recommended_mode": " unknown ",
        },
        intervention_summary={
            "suggested_mode": " unknown ",
        },
        lifecycle_summary={
            "suggested_mode": "browser",
        },
    )

    assert hint == "follow recovery policy escalation guidance; suggested mode=browser"
    assert "unknown" not in hint

def test_emit_operator_console_summary_omits_missing_page_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=17"},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err

def test_emit_operator_console_summary_treats_unknown_summaries_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
        final_guidance_summary="unknown",
        digest_summary="unknown",
        digest_stability_summary="unknown",
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "unknown" not in escalation_line
    assert "page=None" not in captured.err

def test_emit_operator_console_summary_omits_unknown_guidance_value(capsys):
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
    assert "guidance=unknown" not in captured.err

def test_emit_operator_console_summary_omits_unknown_digest_status_value(capsys):
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
    assert "digest_status=unknown" not in captured.err

def test_emit_operator_console_summary_omits_unknown_digest_stability_value(capsys):
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
    assert "digest_stability=unknown" not in captured.err

def test_emit_operator_console_summary_omits_unknown_reason_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "reason=unknown" not in captured.err
