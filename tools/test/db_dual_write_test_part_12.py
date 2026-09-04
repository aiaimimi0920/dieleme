from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_overview_helpers_treat_negative_counts_as_missing():
    server_module = importlib.import_module("src.server")

    mode_switch_overview = server_module._hybrid_collection_operator_mode_switch_overview_fields(
        {
            "recent_switch_count": -2,
            "top_target_mode": "browser",
            "top_guidance_reason": "challenge_detected",
        }
    )
    action_hint_overview = server_module._hybrid_collection_operator_action_hint_trend_overview_fields(
        {
            "current_action_hint": "keep hybrid; suggested mode=hybrid",
            "previous_distinct_action_hint": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:24:00",
        }
    )
    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_trend_overview_fields(
        {
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "Stable ready state",
            "previous_distinct_guidance_message": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:25:00",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_trend_overview_fields(
        {
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "Stable ready state",
            "previous_distinct_digest_message": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:26:00",
        }
    )
    intervention_trend_overview = server_module._hybrid_collection_operator_intervention_trend_overview_fields(
        {
            "current_intervention_status": "ready",
            "current_intervention_priority": "info",
            "current_intervention_reason": "browserless_fast_path_stable",
            "previous_distinct_intervention_status": None,
            "recent_change_count": -1,
            "last_change_at": "2026-05-18 18:27:00",
        }
    )
    intervention_event_overview = server_module._hybrid_collection_operator_intervention_event_overview_fields(
        {
            "recent_event_count": -2,
            "last_event_at": "2026-05-18 18:28:00",
            "last_transition_kind": "status_changed",
        }
    )
    recovery_policy_overview = server_module._hybrid_collection_operator_recovery_policy_overview_fields(
        {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
            "hybrid_retrial_budget_remaining": -1,
            "last_recovery_transition_kind": "pin_released",
        }
    )
    recovery_policy_event_overview = server_module._hybrid_collection_operator_recovery_policy_event_overview_fields(
        {
            "recent_transition_count": -2,
            "last_transition_kind": "pin_released",
            "last_to_policy_status": "allow_hybrid_retrial",
        }
    )
    escalation_event_overview = server_module._hybrid_collection_operator_escalation_event_overview_fields(
        {
            "recent_event_count": -2,
            "top_escalation_kind": "repeated_repin_cycle",
        }
    )
    escalation_event_trend_overview = server_module._hybrid_collection_operator_escalation_event_trend_overview_fields(
        {
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": -2,
            "last_source_change_at": "2026-05-18 18:29:00",
        }
    )
    escalation_recovery_event_overview = server_module._hybrid_collection_operator_escalation_recovery_event_overview_fields(
        {
            "recent_recovery_count": -2,
            "last_to_policy_status": "steady_hybrid",
        }
    )

    assert mode_switch_overview["hybrid_collection_recent_mode_switch_count"] == 0
    assert action_hint_overview["hybrid_collection_action_hint_change_count"] == 0
    assert final_guidance_overview["hybrid_collection_final_guidance_change_count"] == 0
    assert digest_overview["hybrid_collection_digest_change_count"] == 0
    assert intervention_trend_overview["hybrid_collection_intervention_change_count"] == 0
    assert intervention_event_overview["hybrid_collection_recent_intervention_event_count"] == 0
    assert recovery_policy_overview["hybrid_collection_recovery_budget_remaining"] == 0
    assert recovery_policy_event_overview["hybrid_collection_recent_recovery_policy_transition_count"] == 0
    assert escalation_event_overview["hybrid_collection_recent_operator_escalation_count"] == 0
    assert escalation_event_trend_overview["hybrid_collection_operator_escalation_source_change_count"] == 0
    assert escalation_recovery_event_overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 0

def test_hybrid_collection_trend_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    action_hint_overview = server_module._hybrid_collection_operator_action_hint_trend_overview_fields(
        {
            "current_action_hint": "unknown",
            "previous_distinct_action_hint": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )
    final_guidance_overview = server_module._hybrid_collection_operator_final_guidance_trend_overview_fields(
        {
            "current_guidance_label": "unknown",
            "current_guidance_priority": "unknown",
            "current_guidance_message": "unknown",
            "previous_distinct_guidance_message": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )
    digest_overview = server_module._hybrid_collection_operator_digest_trend_overview_fields(
        {
            "current_digest_status": "unknown",
            "current_digest_priority": "unknown",
            "current_digest_message": "unknown",
            "previous_distinct_digest_message": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )
    intervention_overview = server_module._hybrid_collection_operator_intervention_trend_overview_fields(
        {
            "current_intervention_status": "unknown",
            "current_intervention_priority": "unknown",
            "current_intervention_reason": "unknown",
            "previous_distinct_intervention_status": "unknown",
            "recent_change_count": "unknown",
            "last_change_at": "unknown",
        }
    )

    assert action_hint_overview["hybrid_collection_current_action_hint"] is None
    assert action_hint_overview["hybrid_collection_previous_action_hint"] is None
    assert action_hint_overview["hybrid_collection_action_hint_change_count"] == 0
    assert action_hint_overview["hybrid_collection_action_hint_last_changed_at"] is None
    assert final_guidance_overview["hybrid_collection_current_final_guidance_label"] is None
    assert final_guidance_overview["hybrid_collection_current_final_guidance_priority"] is None
    assert final_guidance_overview["hybrid_collection_current_final_guidance_message"] is None
    assert final_guidance_overview["hybrid_collection_previous_final_guidance_message"] is None
    assert final_guidance_overview["hybrid_collection_final_guidance_change_count"] == 0
    assert final_guidance_overview["hybrid_collection_final_guidance_last_changed_at"] is None
    assert digest_overview["hybrid_collection_current_digest_status"] is None
    assert digest_overview["hybrid_collection_current_digest_priority"] is None
    assert digest_overview["hybrid_collection_current_digest_message"] is None
    assert digest_overview["hybrid_collection_previous_digest_message"] is None
    assert digest_overview["hybrid_collection_digest_change_count"] == 0
    assert digest_overview["hybrid_collection_digest_last_changed_at"] is None
    assert intervention_overview["hybrid_collection_current_intervention_status"] is None
    assert intervention_overview["hybrid_collection_current_intervention_priority"] is None
    assert intervention_overview["hybrid_collection_current_intervention_reason"] is None
    assert intervention_overview["hybrid_collection_previous_intervention_status"] is None
    assert intervention_overview["hybrid_collection_intervention_change_count"] == 0
    assert intervention_overview["hybrid_collection_intervention_last_changed_at"] is None

def test_hybrid_collection_stability_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance_stability_overview = server_module._hybrid_collection_operator_final_guidance_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
        }
    )
    digest_stability_overview = server_module._hybrid_collection_operator_digest_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
        }
    )

    assert final_guidance_stability_overview["hybrid_collection_final_guidance_stability_status"] is None
    assert final_guidance_stability_overview["hybrid_collection_final_guidance_stability_severity"] is None
    assert final_guidance_stability_overview["hybrid_collection_final_guidance_stability_explanation"] is None
    assert digest_stability_overview["hybrid_collection_digest_stability_status"] is None
    assert digest_stability_overview["hybrid_collection_digest_stability_severity"] is None
    assert digest_stability_overview["hybrid_collection_digest_stability_explanation"] is None

def test_hybrid_collection_event_overview_fields_treat_unknown_recent_counts_as_missing():
    server_module = importlib.import_module("src.server")

    intervention_event_overview = server_module._hybrid_collection_operator_intervention_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "last_event_at": "2026-05-18 18:28:00",
            "last_transition_kind": "status_changed",
        }
    )
    recovery_policy_event_overview = server_module._hybrid_collection_operator_recovery_policy_event_overview_fields(
        {
            "recent_transition_count": "unknown",
            "last_transition_kind": "pin_released",
            "last_to_policy_status": "allow_hybrid_retrial",
        }
    )
    escalation_event_overview = server_module._hybrid_collection_operator_escalation_event_overview_fields(
        {
            "recent_event_count": "unknown",
            "top_escalation_kind": "repeated_repin_cycle",
        }
    )
    escalation_event_trend_overview = server_module._hybrid_collection_operator_escalation_event_trend_overview_fields(
        {
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:29:00",
        }
    )
    escalation_recovery_event_overview = server_module._hybrid_collection_operator_escalation_recovery_event_overview_fields(
        {
            "recent_recovery_count": "unknown",
            "last_to_policy_status": "steady_hybrid",
        }
    )

    assert intervention_event_overview["hybrid_collection_recent_intervention_event_count"] == 0
    assert recovery_policy_event_overview["hybrid_collection_recent_recovery_policy_transition_count"] == 0
    assert escalation_event_overview["hybrid_collection_recent_operator_escalation_count"] == 0
    assert escalation_event_trend_overview["hybrid_collection_operator_escalation_source_change_count"] == 0
    assert escalation_recovery_event_overview["hybrid_collection_recent_operator_escalation_recovery_count"] == 0

def test_hybrid_collection_stability_helpers_treat_unknown_recent_counts_as_missing():
    server_module = importlib.import_module("src.server")

    final_guidance_stability = server_module._hybrid_collection_operator_final_guidance_stability_summary(
        {
            "available": True,
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "info",
            "current_guidance_message": "Stable ready state",
            "previous_distinct_guidance_label": None,
            "previous_distinct_guidance_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:30:00",
        }
    )
    digest_stability = server_module._hybrid_collection_operator_digest_stability_summary(
        {
            "available": True,
            "current_digest_status": "ready",
            "current_digest_priority": "info",
            "current_digest_message": "Stable ready state",
            "previous_distinct_digest_status": None,
            "previous_distinct_digest_message": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:31:00",
        }
    )
    intervention_stability = server_module._hybrid_collection_operator_intervention_stability_summary(
        {
            "available": True,
            "current_intervention_status": "ready",
            "previous_distinct_intervention_status": None,
            "recent_change_count": "unknown",
            "last_change_at": "2026-05-18 18:32:00",
        }
    )
    escalation_event_stability = server_module._hybrid_collection_operator_escalation_event_stability_summary(
        {
            "available": True,
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "repeated_repin_cycle",
            "current_operator_escalation_audit_message": "audit",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:33:00",
        }
    )

    assert final_guidance_stability["recent_change_count"] == 0
    assert final_guidance_stability["stability_status"] == "stable_guidance"
    assert digest_stability["recent_change_count"] == 0
    assert digest_stability["stability_status"] == "stable_digest"
    assert intervention_stability["recent_change_count"] == 0
    assert intervention_stability["stability_status"] == "stable_ready"
    assert escalation_event_stability["recent_source_change_count"] == 0
    assert escalation_event_stability["stability_status"] == "persistent_recovery_policy_source"

def test_hybrid_collection_operator_mode_switch_overview_fields_treat_unknown_switch_count_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_mode_switch_overview_fields(
        {
            "recent_switch_count": "unknown",
            "top_target_mode": "browser",
            "top_guidance_reason": "challenge_detected",
        }
    )

    assert overview["hybrid_collection_recent_mode_switch_count"] == 0
    assert overview["hybrid_collection_top_switch_target_mode"] == "browser"
    assert overview["hybrid_collection_top_switch_guidance_reason"] == "challenge_detected"

def test_hybrid_collection_lifecycle_resolution_overview_fields_treat_unknown_numeric_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    lifecycle_overview = server_module._hybrid_collection_operator_lifecycle_state_overview_fields(
        {
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "recommended_follow_up": "keep_hybrid",
            "suggested_mode": "hybrid",
            "operator_action_hint": "keep hybrid; suggested mode=hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": "unknown",
        }
    )
    resolution_overview = server_module._hybrid_collection_operator_escalation_resolution_trend_overview_fields(
        {
            "recent_resolved_count": "unknown",
            "recent_unresolved_count": "unknown",
            "recent_resolution_rate": "unknown",
        }
    )
    priority_mix_overview = server_module._hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
        {
            "recent_high_priority_escalation_count": "unknown",
            "recent_high_priority_resolved_count": "unknown",
            "recent_high_priority_unresolved_count": "unknown",
            "top_recent_escalation_priority": "high",
            "top_recent_unresolved_priority": "high",
        }
    )

    assert lifecycle_overview["hybrid_collection_lifecycle_active_high_priority_unresolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_resolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_unresolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_resolution_rate"] == 0.0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_escalation_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_resolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_unresolved_count"] == 0

def test_hybrid_collection_escalation_overview_helpers_treat_unknown_text_fields_as_missing():
    server_module = importlib.import_module("src.server")

    escalation_trend_overview = server_module._hybrid_collection_operator_escalation_event_trend_overview_fields(
        {
            "current_operator_escalation_source": "unknown",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": "unknown",
            "last_source_change_at": "unknown",
        }
    )
    escalation_stability_overview = server_module._hybrid_collection_operator_escalation_event_stability_overview_fields(
        {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "operator_readable_explanation": "unknown",
        }
    )
    priority_mix_overview = server_module._hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
        {
            "recent_high_priority_escalation_count": "unknown",
            "recent_high_priority_resolved_count": "unknown",
            "recent_high_priority_unresolved_count": "unknown",
            "top_recent_escalation_priority": "unknown",
            "top_recent_unresolved_priority": "unknown",
        }
    )

    assert escalation_trend_overview["hybrid_collection_current_operator_escalation_source"] is None
    assert escalation_trend_overview["hybrid_collection_previous_operator_escalation_source"] is None
    assert escalation_trend_overview["hybrid_collection_operator_escalation_source_change_count"] == 0
    assert escalation_trend_overview["hybrid_collection_operator_escalation_source_last_changed_at"] is None
    assert escalation_stability_overview["hybrid_collection_operator_escalation_source_stability_status"] is None
    assert escalation_stability_overview["hybrid_collection_operator_escalation_source_stability_severity"] is None
    assert escalation_stability_overview["hybrid_collection_operator_escalation_source_stability_explanation"] is None
    assert priority_mix_overview["hybrid_collection_recent_high_priority_escalation_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_resolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_unresolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_top_recent_escalation_priority"] is None
    assert priority_mix_overview["hybrid_collection_top_recent_unresolved_priority"] is None

def test_hybrid_collection_resolution_and_priority_overview_helpers_treat_negative_counts_as_missing():
    server_module = importlib.import_module("src.server")

    resolution_overview = server_module._hybrid_collection_operator_escalation_resolution_trend_overview_fields(
        {
            "recent_resolved_count": -2,
            "recent_unresolved_count": -3,
            "recent_resolution_rate": -0.5,
        }
    )
    priority_mix_overview = server_module._hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(
        {
            "recent_high_priority_escalation_count": -1,
            "recent_high_priority_resolved_count": -2,
            "recent_high_priority_unresolved_count": -3,
            "top_recent_escalation_priority": "high",
            "top_recent_unresolved_priority": "high",
        }
    )

    assert resolution_overview["hybrid_collection_recent_escalation_resolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_unresolved_count"] == 0
    assert resolution_overview["hybrid_collection_recent_escalation_resolution_rate"] == 0.0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_escalation_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_resolved_count"] == 0
    assert priority_mix_overview["hybrid_collection_recent_high_priority_unresolved_count"] == 0
