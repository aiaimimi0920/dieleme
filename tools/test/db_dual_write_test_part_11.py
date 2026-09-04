from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_operator_unresolved_escalation_window_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
        {
            "window_open": False,
            "last_escalation_policy_status": "unknown",
            "last_recovery_to_policy_status": "unknown",
            "last_escalation_at": "unknown",
            "last_recovery_at": "unknown",
            "current_window_duration_seconds": "unknown",
            "current_window_duration_minutes": "unknown",
        }
    )

    assert overview["hybrid_collection_unresolved_escalation_window_open"] is False
    assert overview["hybrid_collection_unresolved_escalation_policy_status"] is None
    assert overview["hybrid_collection_unresolved_escalation_last_event_at"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None

def test_hybrid_collection_operator_action_hint_consistency_overview_fields_treat_unknown_hints_match_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_action_hint_consistency_overview_fields(
        {
            "consistency_status": "unknown",
            "hints_match": "unknown",
            "drift_reason": "unknown",
            "consistency_severity": "unknown",
            "severity_reason": "unknown",
            "hint_source_preference": "unknown",
            "preferred_hint_source_detail": "unknown",
            "preferred_hint_explanation": "unknown",
            "preferred_operator_action_hint": "unknown",
        }
    )

    assert overview["hybrid_collection_action_hint_consistency_status"] is None
    assert overview["hybrid_collection_action_hint_hints_match"] is False
    assert overview["hybrid_collection_action_hint_drift_reason"] is None
    assert overview["hybrid_collection_action_hint_consistency_severity"] is None
    assert overview["hybrid_collection_action_hint_severity_reason"] is None
    assert overview["hybrid_collection_action_hint_source_preference"] is None
    assert overview["hybrid_collection_action_hint_source_detail"] is None
    assert overview["hybrid_collection_action_hint_explanation"] is None
    assert overview["hybrid_collection_preferred_action_hint"] is None

def test_hybrid_collection_operator_intervention_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    intervention_event_overview = server_module._hybrid_collection_operator_intervention_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "last_event_at": "unknown",
            "last_transition_kind": "unknown",
            "last_to_intervention_status": "unknown",
            "last_to_intervention_priority": "unknown",
            "last_to_final_guidance_label": "unknown",
            "last_to_final_guidance_priority": "unknown",
            "last_to_final_guidance_message": "unknown",
        }
    )
    intervention_stability_overview = server_module._hybrid_collection_operator_intervention_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "unknown",
        }
    )
    intervention_policy_overview = server_module._hybrid_collection_operator_intervention_policy_overview_fields(
        {
            "intervention_status": "unknown",
            "intervention_required": "unknown",
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "unknown",
        }
    )

    assert intervention_event_overview["hybrid_collection_recent_intervention_event_count"] == 0
    assert intervention_event_overview["hybrid_collection_last_intervention_event_at"] is None
    assert intervention_event_overview["hybrid_collection_last_intervention_transition_kind"] is None
    assert intervention_event_overview["hybrid_collection_last_to_intervention_status"] is None
    assert intervention_event_overview["hybrid_collection_last_to_intervention_priority"] is None
    assert intervention_event_overview["hybrid_collection_last_to_final_guidance_label"] is None
    assert intervention_event_overview["hybrid_collection_last_to_final_guidance_priority"] is None
    assert intervention_event_overview["hybrid_collection_last_to_final_guidance_message"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_status"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_severity"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_explanation"] is None
    assert intervention_stability_overview["hybrid_collection_intervention_stability_action_hint"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_status"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_required"] is False
    assert intervention_policy_overview["hybrid_collection_operator_intervention_priority"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_reason"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_action_hint"] is None
    assert intervention_policy_overview["hybrid_collection_operator_intervention_suggested_mode"] is None

def test_hybrid_collection_operator_guidance_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_overview_fields(
        {
            "guidance_label": "unknown",
            "guidance_priority": "unknown",
            "guidance_message": "unknown",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_overview_fields(
        {
            "digest_status": "unknown",
            "digest_priority": "unknown",
            "operator_digest_message": "unknown",
        }
    )

    assert final_guidance_overview["hybrid_collection_operator_final_guidance_label"] is None
    assert final_guidance_overview["hybrid_collection_operator_final_guidance_priority"] is None
    assert final_guidance_overview["hybrid_collection_operator_final_guidance_message"] is None
    assert digest_overview["hybrid_collection_operator_digest_status"] is None
    assert digest_overview["hybrid_collection_operator_digest_priority"] is None
    assert digest_overview["hybrid_collection_operator_digest_message"] is None

def test_hybrid_collection_operator_lifecycle_state_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_lifecycle_state_overview_fields(
        {
            "lifecycle_state": "unknown",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "unknown",
            "suggested_mode": "unknown",
            "operator_action_hint": "unknown",
            "priority_hint": "unknown",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    assert overview["hybrid_collection_lifecycle_state"] is None
    assert overview["hybrid_collection_lifecycle_reason"] is None
    assert overview["hybrid_collection_lifecycle_follow_up"] is None
    assert overview["hybrid_collection_lifecycle_suggested_mode"] is None
    assert overview["hybrid_collection_lifecycle_action_hint"] is None
    assert overview["hybrid_collection_lifecycle_priority_hint"] is None
    assert overview["hybrid_collection_lifecycle_active_unresolved_priority"] is None
    assert overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0

def test_hybrid_collection_unresolved_window_and_lifecycle_overview_fields_treat_negative_numeric_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    unresolved_overview = server_module._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
        {
            "window_open": True,
            "last_escalation_policy_status": "escalate_repeated_repin",
            "last_escalation_at": "2026-05-18 18:40:00",
            "current_window_duration_seconds": -300,
            "current_window_duration_minutes": -5.0,
        }
    )
    lifecycle_overview = server_module._hybrid_collection_operator_lifecycle_state_overview_fields(
        {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": -2,
        }
    )

    assert unresolved_overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert unresolved_overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None
    assert lifecycle_overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0

def test_hybrid_collection_operator_recovery_latency_overview_fields_treat_unknown_policy_status_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_latency_overview_fields(
        {
            "last_recovery_latency_seconds": "unknown",
            "last_recovery_latency_minutes": "unknown",
            "last_recovery_from_policy_status": "unknown",
            "last_recovery_to_policy_status": "unknown",
        }
    )

    assert overview["hybrid_collection_last_recovery_latency_seconds"] is None
    assert overview["hybrid_collection_last_recovery_latency_minutes"] is None
    assert overview["hybrid_collection_last_recovery_latency_from_policy_status"] is None
    assert overview["hybrid_collection_last_recovery_latency_to_policy_status"] is None

def test_hybrid_collection_operator_recovery_latency_overview_fields_treat_negative_latency_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_latency_overview_fields(
        {
            "last_recovery_latency_seconds": -90,
            "last_recovery_latency_minutes": -1.5,
            "last_recovery_from_policy_status": "escalate_repeated_repin",
            "last_recovery_to_policy_status": "steady_hybrid",
        }
    )

    assert overview["hybrid_collection_last_recovery_latency_seconds"] is None
    assert overview["hybrid_collection_last_recovery_latency_minutes"] is None
    assert overview["hybrid_collection_last_recovery_latency_from_policy_status"] == "escalate_repeated_repin"
    assert overview["hybrid_collection_last_recovery_latency_to_policy_status"] == "steady_hybrid"

def test_hybrid_collection_operator_recovery_policy_event_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_policy_event_overview_fields(
        {
            "recent_transition_count": "unknown",
            "last_transition_kind": "unknown",
            "last_to_policy_status": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_recovery_policy_transition_count"] == 0
    assert overview["hybrid_collection_last_recovery_transition_kind"] is None
    assert overview["hybrid_collection_last_recovery_to_policy_status"] is None

def test_hybrid_collection_operator_escalation_event_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_escalation_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "top_escalation_kind": "unknown",
            "top_operator_escalation_source": "unknown",
            "top_policy_status": "unknown",
            "last_operator_escalation_source": "unknown",
            "last_operator_escalation_audit_message": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_operator_escalation_count"] == 0
    assert overview["hybrid_collection_top_operator_escalation_kind"] is None
    assert overview["hybrid_collection_top_operator_escalation_source"] is None
    assert overview["hybrid_collection_top_operator_escalation_policy_status"] is None
    assert overview["hybrid_collection_last_operator_escalation_source"] is None
    assert overview["hybrid_collection_last_operator_escalation_audit_message"] is None

def test_hybrid_collection_operator_escalation_recovery_event_overview_fields_treat_unknown_policy_status_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_escalation_recovery_event_overview_fields(
        {
            "recent_recovery_count": "unknown",
            "last_to_policy_status": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 0
    assert overview["hybrid_collection_last_operator_escalation_recovery_policy_status"] is None

def test_hybrid_collection_operator_overview_fields_treat_unknown_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_overview_fields(
        {
            "available": "unknown",
            "runner_mode": "unknown",
            "requested_mode": "unknown",
            "effective_mode_source": "unknown",
            "operator_action_hint": "unknown",
            "last_decision": "unknown",
            "last_reason": "unknown",
            "last_effective_mode": "unknown",
            "top_fallback_reason": "unknown",
            "termination_reason": "unknown",
            "guidance_applied_count": -2,
            "guidance_status": "unknown",
            "recovery_policy_status": "unknown",
            "recovery_policy_mode_pin_active": "unknown",
            "browserless_success_count": -1,
            "browser_fallback_required_count": -3,
            "browser_worker_dispatched_count": -4,
            "last_task_url": "unknown",
            "last_task_page": -1,
            "last_submit_batch_status": "unknown",
            "last_submit_progress_status": "unknown",
        }
    )

    assert overview["hybrid_collection_available"] is False
    assert overview["hybrid_collection_runner_mode"] is None
    assert overview["hybrid_collection_requested_mode"] is None
    assert overview["hybrid_collection_effective_mode_source"] is None
    assert overview["hybrid_collection_operator_action_hint"] is None
    assert overview["hybrid_collection_last_decision"] is None
    assert overview["hybrid_collection_last_reason"] is None
    assert overview["hybrid_collection_last_effective_mode"] is None
    assert overview["hybrid_collection_top_fallback_reason"] is None
    assert overview["hybrid_collection_termination_reason"] is None
    assert overview["hybrid_collection_guidance_applied_count"] == 0
    assert overview["hybrid_collection_guidance_status"] is None
    assert overview["hybrid_collection_recovery_policy_status"] is None
    assert overview["hybrid_collection_recovery_mode_pin_active"] is False
    assert overview["hybrid_collection_browserless_success_count"] == 0
    assert overview["hybrid_collection_browser_fallback_required_count"] == 0
    assert overview["hybrid_collection_browser_worker_dispatched_count"] == 0
    assert overview["hybrid_collection_last_task_url"] is None
    assert overview["hybrid_collection_last_task_page"] is None
    assert overview["hybrid_collection_last_submit_batch_status"] is None
    assert overview["hybrid_collection_last_submit_progress_status"] is None

def test_hybrid_collection_operator_history_overview_fields_treat_unknown_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_history_overview_fields(
        {
            "recent_runs": -2,
            "recent_browserless_success_count": -1,
            "recent_browser_fallback_required_count": -3,
            "recent_browser_worker_dispatched_count": -4,
            "recent_browserless_success_rate": 1.5,
            "recent_top_fallback_reason": "unknown",
            "recent_top_termination_reason": "unknown",
        }
    )

    assert overview["hybrid_collection_recent_runs"] == 0
    assert overview["hybrid_collection_recent_browserless_success_count"] == 0
    assert overview["hybrid_collection_recent_browser_fallback_required_count"] == 0
    assert overview["hybrid_collection_recent_browser_worker_dispatched_count"] == 0
    assert overview["hybrid_collection_recent_browserless_success_rate"] == 1.0
    assert overview["hybrid_collection_recent_top_fallback_reason"] is None
    assert overview["hybrid_collection_recent_top_termination_reason"] is None

def test_hybrid_collection_operator_guidance_and_mode_switch_overview_fields_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    guidance_overview = server_module._hybrid_collection_operator_guidance_overview_fields(
        {
            "guidance_status": "unknown",
            "priority": "unknown",
            "recommended_mode": "unknown",
            "top_guidance_reason": "unknown",
        }
    )
    mode_switch_overview = server_module._hybrid_collection_operator_mode_switch_overview_fields(
        {
            "recent_switch_count": "unknown",
            "top_target_mode": "unknown",
            "top_guidance_reason": "unknown",
        }
    )

    assert guidance_overview["hybrid_collection_guidance_status"] is None
    assert guidance_overview["hybrid_collection_guidance_priority"] is None
    assert guidance_overview["hybrid_collection_recommended_mode"] is None
    assert guidance_overview["hybrid_collection_top_guidance_reason"] is None
    assert mode_switch_overview["hybrid_collection_recent_mode_switch_count"] == 0
    assert mode_switch_overview["hybrid_collection_top_switch_target_mode"] is None
    assert mode_switch_overview["hybrid_collection_top_switch_guidance_reason"] is None

def test_hybrid_collection_trend_overview_fields_treat_unknown_change_counts_as_missing():
    server_module = importlib.import_module("src.server")

    action_hint_overview = server_module._hybrid_collection_operator_action_hint_trend_overview_fields(
        {
            "current_action_hint": "keep hybrid; suggested mode=hybrid",
            "previous_distinct_action_hint": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:24:00",
        }
    )
    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_trend_overview_fields(
        {
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "Stable ready state",
            "previous_distinct_guidance_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:25:00",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_trend_overview_fields(
        {
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "Stable ready state",
            "previous_distinct_digest_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:26:00",
        }
    )
    intervention_overview = server_module._hybrid_collection_operator_intervention_trend_overview_fields(
        {
            "current_intervention_status": "ready",
            "current_intervention_priority": "info",
            "current_intervention_reason": "browserless_fast_path_stable",
            "previous_distinct_intervention_status": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:27:00",
        }
    )

    assert action_hint_overview["hybrid_collection_action_hint_change_count"] == 0
    assert final_guidance_overview["hybrid_collection_final_guidance_change_count"] == 0
    assert digest_overview["hybrid_collection_digest_change_count"] == 0
    assert intervention_overview["hybrid_collection_intervention_change_count"] == 0
