from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_resolution_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_high_priority_unresolved_count": "unknown",
            "suggested_mode": "hybrid",
            "window_open": "unknown",
        },
        {
            "available": True,
        },
        {
            "available": "unknown",
            "recent_unresolved_count": "unknown",
            "recent_resolution_rate": "unknown",
        },
        {
            "available": "unknown",
            "last_recovery_latency_minutes": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["preferred_operator_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["lifecycle_state"] == "steady"
    assert summary["window_open"] is False
    assert summary["active_high_priority_unresolved_count"] == 0
    assert summary["hint_consistency_status"] is None
    assert summary["hint_consistency_severity"] is None
    assert summary["resolution_trend_available"] is False
    assert summary["recent_unresolved_count"] == 0
    assert summary["recent_resolution_rate"] == 0.0
    assert summary["recovery_latency_available"] is False
    assert summary["last_recovery_latency_minutes"] is None

def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_lifecycle_hint_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "unknown",
            "priority_hint": "unknown",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "unknown",
            "window_open": False,
        },
        {
            "available": True,
            "preferred_operator_action_hint": "unknown",
            "consistency_status": "unknown",
            "consistency_severity": "unknown",
        },
        {},
        {
            "available": True,
            "last_recovery_latency_minutes": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["preferred_operator_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["lifecycle_state"] == "steady"
    assert summary["window_open"] is False
    assert summary["active_high_priority_unresolved_count"] == 0
    assert summary["hint_consistency_status"] is None
    assert summary["hint_consistency_severity"] is None
    assert summary["resolution_trend_available"] is False
    assert summary["recent_unresolved_count"] == 0
    assert summary["recent_resolution_rate"] == 0.0
    assert summary["recovery_latency_available"] is True
    assert summary["last_recovery_latency_minutes"] is None

def test_hybrid_collection_operator_intervention_policy_summary_treats_negative_resolution_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_high_priority_unresolved_count": -2,
            "suggested_mode": "hybrid",
            "window_open": False,
        },
        {
            "available": True,
        },
        {
            "available": True,
            "recent_unresolved_count": -3,
            "recent_resolution_rate": -0.5,
        },
        {
            "available": True,
            "last_recovery_latency_minutes": -1.5,
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_required"] is False
    assert summary["intervention_priority"] == "info"
    assert summary["intervention_reason"] == "browserless_fast_path_stable"
    assert summary["active_high_priority_unresolved_count"] == 0
    assert summary["recent_unresolved_count"] == 0
    assert summary["recent_resolution_rate"] == 0.0
    assert summary["last_recovery_latency_minutes"] is None

def test_hybrid_collection_operator_intervention_policy_summary_treats_overfull_resolution_rate_as_clamped():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "hybrid",
            "window_open": False,
        },
        {
            "available": True,
        },
        {
            "available": True,
            "recent_unresolved_count": 0,
            "recent_resolution_rate": 1.5,
        },
        {
            "available": True,
        },
    )

    assert summary["available"] is True
    assert summary["intervention_status"] == "ready"
    assert summary["recent_resolution_rate"] == 1.0

def test_hybrid_collection_operator_intervention_stability_summary_treats_unknown_summary_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_stability_summary("unknown")

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_intervention_status": None,
        "previous_intervention_status": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
        "stability_action_hint": None,
    }

def test_hybrid_collection_operator_intervention_stability_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_stability_summary(
        {"available": "unknown"}
    )

    assert summary == {
        "available": False,
        "stability_status": "unknown",
        "stability_severity": "info",
        "current_intervention_status": None,
        "previous_intervention_status": None,
        "recent_change_count": 0,
        "last_change_at": None,
        "operator_readable_explanation": None,
        "stability_action_hint": None,
    }

def test_hybrid_collection_operator_intervention_stability_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "unknown",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": 0,
            "last_change_at": "2026-05-18 18:23:00",
        }
    )

    assert summary["available"] is True
    assert summary["stability_status"] == "transitioning"
    assert summary["stability_severity"] == "warning"
    assert summary["current_intervention_status"] is None
    assert summary["previous_intervention_status"] is None
    assert summary["recent_change_count"] == 0
    assert summary["last_change_at"] == "2026-05-18 18:23:00"
    assert summary["operator_readable_explanation"] == "Intervention is transitioning."
    assert summary["stability_action_hint"] == "monitor until stable before resuming aggressive intervention"

def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary("unknown", "unknown")

    assert summary == {
        "available": False,
        "guidance_label": None,
        "guidance_priority": None,
        "guidance_message": None,
        "preferred_action_hint": None,
        "suggested_mode": None,
        "intervention_status": None,
        "stability_status": None,
    }

def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "guidance_label": None,
        "guidance_priority": None,
        "guidance_message": None,
        "preferred_action_hint": None,
        "suggested_mode": None,
        "intervention_status": None,
        "stability_status": None,
    }

def test_hybrid_collection_operator_digest_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_summary(
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "digest_status": "unknown",
        "digest_priority": "info",
        "final_guidance_message": None,
        "intervention_status": None,
        "intervention_stability_status": None,
        "final_guidance_stability_status": None,
        "operator_digest_message": None,
    }

def test_hybrid_collection_operator_digest_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_summary(
        {"available": "unknown"},
        {"available": "unknown"},
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "digest_status": "unknown",
        "digest_priority": "info",
        "final_guidance_message": None,
        "intervention_status": None,
        "intervention_stability_status": None,
        "final_guidance_stability_status": None,
        "operator_digest_message": None,
    }

def test_hybrid_collection_unresolved_escalation_window_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary("unknown", "unknown")

    assert summary == {
        "available": False,
        "window_status": "no_escalation_history",
        "window_open": False,
        "last_escalation_at": None,
        "last_escalation_policy_status": None,
        "last_recovery_at": None,
        "last_recovery_to_policy_status": None,
        "current_window_duration_seconds": None,
        "current_window_duration_minutes": None,
    }

def test_hybrid_collection_unresolved_escalation_window_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_unresolved_escalation_window_summary(
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "window_status": "no_escalation_history",
        "window_open": False,
        "last_escalation_at": None,
        "last_escalation_policy_status": None,
        "last_recovery_at": None,
        "last_recovery_to_policy_status": None,
        "current_window_duration_seconds": None,
        "current_window_duration_minutes": None,
    }

def test_hybrid_collection_escalation_resolution_trend_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_escalation_resolution_trend_summary(
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "recent_escalation_count": 0,
        "recent_recovery_count": 0,
        "recent_resolved_count": 0,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "window_open": False,
    }

def test_hybrid_collection_escalation_resolution_trend_summary_treats_unknown_scalar_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_escalation_resolution_trend_summary(
        {"available": True, "recent_event_count": "unknown"},
        {"available": True, "recent_recovery_count": "unknown"},
        {"window_open": "unknown"},
    )

    assert summary == {
        "available": True,
        "recent_escalation_count": 0,
        "recent_recovery_count": 0,
        "recent_resolved_count": 0,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "window_open": False,
    }

def test_hybrid_collection_escalation_resolution_trend_summary_treats_negative_counts_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_escalation_resolution_trend_summary(
        {"available": True, "recent_event_count": -3},
        {"available": True, "recent_recovery_count": -2},
        {"window_open": True},
    )

    assert summary == {
        "available": True,
        "recent_escalation_count": 0,
        "recent_recovery_count": 0,
        "recent_resolved_count": 0,
        "recent_unresolved_count": 0,
        "recent_resolution_rate": 0.0,
        "window_open": True,
    }

def test_hybrid_collection_lifecycle_state_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "available": False,
        "lifecycle_state": "unknown",
        "lifecycle_reason": "no_runtime_signals",
        "recommended_follow_up": "collect_runtime_history",
        "suggested_mode": "hybrid",
        "operator_action_hint": "collect runtime history; suggested mode=hybrid",
        "priority_hint": "no_priority_data",
        "active_unresolved_priority": None,
        "active_high_priority_unresolved_count": 0,
        "policy_status": None,
        "window_open": False,
    }

def test_hybrid_collection_lifecycle_state_summary_treats_unknown_available_and_window_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {"available": "unknown", "recovery_policy_status": "steady_hybrid"},
        {},
        {"window_open": "unknown"},
        {
            "recent_high_priority_unresolved_count": "unknown",
            "top_recent_unresolved_priority": "unknown",
        },
    )

    assert summary == {
        "available": False,
        "lifecycle_state": "unknown",
        "lifecycle_reason": "no_runtime_signals",
        "recommended_follow_up": "collect_runtime_history",
        "suggested_mode": "hybrid",
        "operator_action_hint": "collect runtime history; suggested mode=hybrid",
        "priority_hint": "no_priority_data",
        "active_unresolved_priority": None,
        "active_high_priority_unresolved_count": 0,
        "policy_status": None,
        "window_open": False,
    }
