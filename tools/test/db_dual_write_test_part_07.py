from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_operator_digest_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_digest_status": None,
        "current_digest_priority": None,
        "current_digest_message": None,
        "previous_digest_status": None,
        "previous_digest_message": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
    }

def test_hybrid_collection_operator_final_guidance_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "unknown",
            "current_guidance_message": "unknown",
            "previous_distinct_guidance_label": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "2026-05-18 18:20:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "stable_guidance"
    assert summary["stability_severity"] == "info"
    assert summary["current_guidance_label"] == "Stable ready state"
    assert summary["current_guidance_priority"] == "info"
    assert summary["current_guidance_message"] is None
    assert summary["previous_guidance_message"] is None
    assert summary["recent_change_count"] == 0
    assert summary["last_change_at"] == "2026-05-18 18:20:00"
    assert summary["operator_readable_explanation"] == "Final guidance remains stable with no recent message changes."

def test_hybrid_collection_operator_final_guidance_stability_summary_treats_missing_current_label_with_recent_change_as_transitioning():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "unknown",
            "current_guidance_priority": "warning",
            "current_guidance_message": "unknown",
            "previous_distinct_guidance_label": "Stable ready state",
            "previous_distinct_guidance_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:20:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "guidance_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_guidance_label"] is None
    assert summary["current_guidance_priority"] == "warning"
    assert summary["current_guidance_message"] is None
    assert summary["previous_guidance_message"] == "Stable ready state: keep hybrid and continue monitoring."
    assert summary["recent_change_count"] == 1
    assert summary["last_change_at"] == "2026-05-18 18:20:00"
    assert summary["operator_readable_explanation"] == "Final guidance is transitioning."

def test_hybrid_collection_operator_digest_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "unknown",
            "current_digest_message": "unknown",
            "previous_distinct_digest_status": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "2026-05-18 18:21:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "stable_digest"
    assert summary["stability_severity"] == "info"
    assert summary["current_digest_status"] == "ready"
    assert summary["current_digest_priority"] == "info"
    assert summary["current_digest_message"] is None
    assert summary["previous_digest_status"] is None
    assert summary["previous_digest_message"] is None
    assert summary["recent_change_count"] == 0
    assert summary["last_change_at"] == "2026-05-18 18:21:00"
    assert summary["operator_readable_explanation"] == "Operator digest remains stable with no recent message changes."

def test_hybrid_collection_operator_digest_stability_summary_treats_missing_current_status_with_recent_change_as_transitioning():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "unknown",
            "current_digest_priority": "warning",
            "current_digest_message": "unknown",
            "previous_distinct_digest_status": "ready",
            "previous_distinct_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:22:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "digest_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_digest_status"] is None
    assert summary["current_digest_priority"] == "warning"
    assert summary["current_digest_message"] is None
    assert summary["previous_digest_status"] == "ready"
    assert summary["previous_digest_message"] == "Stable ready state: keep hybrid and continue monitoring."
    assert summary["recent_change_count"] == 1
    assert summary["last_change_at"] == "2026-05-18 18:22:00"
    assert summary["operator_readable_explanation"] == "Operator digest is transitioning."

def test_hybrid_collection_stability_summaries_treat_unknown_change_timestamps_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "All clear",
            "previous_distinct_guidance_label": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "unknown",
        }
    )
    assert final_guidance["last_change_at"] is None

    digest = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "All clear",
            "previous_distinct_digest_status": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": 0,
            "last_change_at": "unknown",
        }
    )
    assert digest["last_change_at"] is None

    intervention = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "ready",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": 0,
            "last_change_at": "unknown",
        }
    )
    assert intervention["last_change_at"] is None

    escalation = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "policy",
            "current_operator_escalation_audit_message": "watch",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 0,
            "last_source_change_at": "unknown",
        }
    )
    assert escalation["last_source_change_at"] is None

def test_hybrid_collection_stability_summaries_treat_negative_change_counts_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "All clear",
            "previous_distinct_guidance_label": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:20:00",
        }
    )
    assert final_guidance["recent_change_count"] == 0
    assert final_guidance["stability_status"] == "stable_guidance"

    digest = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "All clear",
            "previous_distinct_digest_status": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:21:00",
        }
    )
    assert digest["recent_change_count"] == 0
    assert digest["stability_status"] == "stable_digest"

    intervention = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "ready",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:22:00",
        }
    )
    assert intervention["recent_change_count"] == 0
    assert intervention["stability_status"] == "stable_ready"

    escalation = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "policy",
            "current_operator_escalation_audit_message": "watch",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": -1,
            "last_source_change_at": "2026-05-18 18:23:00",
        }
    )
    assert escalation["recent_source_change_count"] == 0
    assert escalation["stability_status"] == "persistent_recovery_policy_source"

def test_hybrid_collection_operator_escalation_event_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_operator_escalation_source": None,
        "current_escalation_kind": None,
        "current_operator_escalation_audit_message": None,
        "previous_operator_escalation_source": None,
        "recent_source_change_count": 0,
        "last_source_change_at": None,
        "operator_readable_explanation": None,
    }

def test_hybrid_collection_operator_escalation_event_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_operator_escalation_source": None,
        "current_escalation_kind": None,
        "current_operator_escalation_audit_message": None,
        "previous_operator_escalation_source": None,
        "recent_source_change_count": 0,
        "last_source_change_at": None,
        "operator_readable_explanation": None,
    }

def test_hybrid_collection_operator_escalation_event_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "unknown",
            "current_escalation_kind": "unknown",
            "current_operator_escalation_audit_message": "unknown",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 0,
            "last_source_change_at": "2026-05-18 18:22:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "source_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_operator_escalation_source"] is None
    assert summary["current_escalation_kind"] is None
    assert summary["current_operator_escalation_audit_message"] is None
    assert summary["previous_operator_escalation_source"] is None
    assert summary["recent_source_change_count"] == 0
    assert summary["last_source_change_at"] == "2026-05-18 18:22:00"
    assert summary["operator_readable_explanation"] == "Operator escalation source is transitioning."

def test_hybrid_collection_operator_escalation_event_stability_summary_treats_missing_current_source_with_recent_change_as_transitioning():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "unknown",
            "current_escalation_kind": "unknown",
            "current_operator_escalation_audit_message": "unknown",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "source_transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_operator_escalation_source"] is None
    assert summary["current_escalation_kind"] is None
    assert summary["current_operator_escalation_audit_message"] is None
    assert summary["previous_operator_escalation_source"] == "recovery_policy"
    assert summary["recent_source_change_count"] == 1
    assert summary["last_source_change_at"] == "2026-05-18 18:24:00"
    assert summary["operator_readable_explanation"] == "Operator escalation source is transitioning."

def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "intervention_status": "unknown",
        "intervention_required": False,
        "intervention_priority": "info",
        "intervention_reason": "no_runtime_signals",
        "preferred_operator_action_hint": None,
        "suggested_mode": None,
        "lifecycle_state": None,
        "window_open": False,
        "active_high_priority_unresolved_count": 0,
        "hint_consistency_status": None,
        "hint_consistency_severity": None,
        "resolution_trend_available": False,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "recovery_latency_available": False,
        "last_recovery_latency_minutes": None,
    }

def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {"available": "unknown"},
        {"available": "unknown"},
        {},
        {},
    )

    assert summary == {
        "available": False,
        "intervention_status": "unknown",
        "intervention_required": False,
        "intervention_priority": "info",
        "intervention_reason": "no_runtime_signals",
        "preferred_operator_action_hint": None,
        "suggested_mode": None,
        "lifecycle_state": None,
        "window_open": False,
        "active_high_priority_unresolved_count": 0,
        "hint_consistency_status": None,
        "hint_consistency_severity": None,
        "resolution_trend_available": False,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "recovery_latency_available": False,
        "last_recovery_latency_minutes": None,
    }
