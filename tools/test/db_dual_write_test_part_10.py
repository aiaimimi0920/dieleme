from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_recovery_policy_treats_unknown_history_decision_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:27:00",
                "session_id": "policy-unknown-1",
                "decision_counts": "unknown",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {"generated_at": "2026-05-18 18:28:00", "last_decision": "browserless_success"},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:26:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 1
    assert summary["hybrid_retrial_budget_remaining"] == 0
    assert summary["last_recovery_transition_kind"] == "pin_released"
    assert summary["last_recovery_transition_at"] == "2026-05-18 18:26:00"

def test_hybrid_collection_recovery_policy_treats_negative_history_decision_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-05-18 18:27:00",
                "session_id": "policy-neg-1",
                "decision_counts": {
                    "browserless_success": -1,
                    "browser_fallback_required": -2,
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {"generated_at": "2026-05-18 18:28:00"},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:26:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1

def test_hybrid_collection_recovery_policy_treats_unknown_history_timestamp_as_missing_for_budget_usage(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)

    history_path = avm_root / "hybrid_seed_collection_runtime_history.jsonl"
    history_path.write_text(
        json.dumps(
            {
                "generated_at": "unknown",
                "session_id": "policy-ts-unknown-1",
                "decision_counts": {"browserless_success": 1},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {"generated_at": "2026-05-18 18:24:00"},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:23:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1

def test_hybrid_collection_recovery_policy_treats_unknown_latest_summary_timestamp_as_missing_for_budget_usage(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {
            "generated_at": "unknown",
            "last_decision": "browserless_success",
        },
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {
            "last_transition_kind": "pin_released",
            "last_transition_at": "2026-05-18 18:23:00",
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1

def test_hybrid_collection_lifecycle_state_summary_treats_unknown_runtime_action_hint_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {
            "available": True,
            "operator_action_hint": "unknown",
        },
        {
            "policy_status": "steady_hybrid",
        },
        {},
        {},
    )

    assert summary["available"] is True
    assert summary["lifecycle_state"] == "steady"
    assert summary["lifecycle_reason"] == "browserless_fast_path_stable"
    assert summary["suggested_mode"] == "hybrid"
    assert summary["operator_action_hint"] == "keep hybrid; suggested mode=hybrid"
    assert summary["policy_status"] == "steady_hybrid"
    assert summary["window_open"] is False

def test_hybrid_collection_action_hint_consistency_summary_treats_unknown_hints_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_action_hint_consistency_summary(
        {
            "available": True,
            "operator_action_hint": "unknown",
        },
        {
            "available": True,
            "operator_action_hint": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["runtime_operator_action_hint"] is None
    assert summary["lifecycle_operator_action_hint"] is None
    assert summary["hints_match"] is False
    assert summary["consistency_status"] == "no_hint_available"
    assert summary["drift_reason"] is None
    assert summary["consistency_severity"] == "info"
    assert summary["severity_reason"] is None
    assert summary["hint_source_preference"] is None
    assert summary["preferred_hint_source_detail"] is None
    assert summary["preferred_hint_explanation"] is None
    assert summary["preferred_operator_action_hint"] is None

def test_hybrid_collection_operator_intervention_policy_summary_treats_unknown_action_hints_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_intervention_policy_summary(
        {
            "available": True,
            "lifecycle_state": "steady",
            "lifecycle_reason": "browserless_fast_path_stable",
            "operator_action_hint": "unknown",
            "suggested_mode": "hybrid",
            "window_open": False,
            "active_high_priority_unresolved_count": 0,
        },
        {
            "available": True,
            "preferred_operator_action_hint": "unknown",
        },
        {},
        {},
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

def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_action_hint_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {
            "available": True,
            "intervention_priority": "warning",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
        },
        {
            "available": True,
            "stability_status": "transitioning",
            "stability_action_hint": "unknown",
            "current_intervention_status": "monitor",
        },
    )

    assert summary["available"] is True
    assert summary["guidance_label"] == "Transitioning intervention"
    assert summary["guidance_priority"] == "warning"
    assert summary["guidance_message"] == "Transitioning intervention"
    assert summary["preferred_action_hint"] is None
    assert summary["suggested_mode"] == "hybrid"
    assert summary["intervention_status"] == "monitor"
    assert summary["stability_status"] == "transitioning"

def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_status_and_mode_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {
            "available": True,
            "intervention_priority": "warning",
            "suggested_mode": "unknown",
            "intervention_status": "monitor",
        },
        {
            "available": True,
            "stability_status": "transitioning",
            "stability_action_hint": "unknown",
            "current_intervention_status": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["guidance_label"] == "Transitioning intervention"
    assert summary["guidance_priority"] == "warning"
    assert summary["guidance_message"] == "Transitioning intervention"
    assert summary["preferred_action_hint"] is None
    assert summary["suggested_mode"] is None
    assert summary["intervention_status"] == "monitor"
    assert summary["stability_status"] == "transitioning"

def test_hybrid_collection_operator_final_guidance_summary_treats_unknown_fallback_priority_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_final_guidance_summary(
        {
            "available": True,
            "intervention_priority": "unknown",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
        },
        {
            "available": True,
            "stability_status": "unknown",
            "stability_action_hint": "inspect backlog",
            "current_intervention_status": "monitor",
        },
    )

    assert summary["available"] is True
    assert summary["guidance_label"] == "Operator guidance"
    assert summary["guidance_priority"] is None
    assert summary["guidance_message"] == "Operator guidance: inspect backlog."
    assert summary["preferred_action_hint"] == "inspect backlog"
    assert summary["suggested_mode"] == "hybrid"
    assert summary["intervention_status"] == "monitor"
    assert summary["stability_status"] is None

def test_hybrid_collection_operator_digest_summary_treats_unknown_guidance_fields_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_operator_digest_summary(
        {
            "available": True,
            "intervention_status": "ready",
        },
        {
            "available": True,
            "stability_status": "stable_ready",
        },
        {
            "available": True,
            "guidance_label": "Stable ready state",
            "guidance_priority": "unknown",
            "guidance_message": "unknown",
        },
        {
            "available": True,
            "stability_status": "stable_guidance",
            "current_guidance_label": "Stable ready state",
            "current_guidance_priority": "unknown",
            "current_guidance_message": "unknown",
        },
    )

    assert summary["available"] is True
    assert summary["digest_status"] == "ready"
    assert summary["digest_priority"] == "info"
    assert summary["final_guidance_message"] is None
    assert summary["intervention_status"] == "ready"
    assert summary["intervention_stability_status"] == "stable_ready"
    assert summary["final_guidance_stability_status"] == "stable_guidance"
    assert summary["operator_digest_message"] is None

def test_hybrid_collection_operator_intervention_policy_overview_fields_treat_unknown_required_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_intervention_policy_overview_fields(
        {
            "intervention_status": "ready",
            "intervention_required": "unknown",
            "intervention_priority": "info",
            "intervention_reason": "browserless_fast_path_stable",
            "preferred_operator_action_hint": None,
            "suggested_mode": "hybrid",
        }
    )

    assert overview["hybrid_collection_operator_intervention_status"] == "ready"
    assert overview["hybrid_collection_operator_intervention_required"] is False
    assert overview["hybrid_collection_operator_intervention_priority"] == "info"
    assert overview["hybrid_collection_operator_intervention_reason"] == "browserless_fast_path_stable"
    assert overview["hybrid_collection_operator_intervention_action_hint"] is None
    assert overview["hybrid_collection_operator_intervention_suggested_mode"] == "hybrid"

def test_hybrid_collection_operator_recovery_policy_overview_fields_treat_unknown_scalars_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_recovery_policy_overview_fields(
        {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": "unknown",
            "top_policy_reason": "unknown",
            "hybrid_retrial_budget_remaining": "unknown",
            "last_recovery_transition_kind": "unknown",
        }
    )

    assert overview["hybrid_collection_recovery_policy_status"] == "steady_hybrid"
    assert overview["hybrid_collection_recovery_policy_priority"] == "info"
    assert overview["hybrid_collection_recovery_effective_mode"] == "hybrid"
    assert overview["hybrid_collection_recovery_mode_pin_active"] is False
    assert overview["hybrid_collection_recovery_top_policy_reason"] is None
    assert overview["hybrid_collection_recovery_budget_remaining"] == 0
    assert overview["hybrid_collection_recovery_last_transition_kind"] is None

def test_hybrid_collection_operator_unresolved_escalation_window_overview_fields_treat_unknown_window_open_as_missing():
    server_module = importlib.import_module("src.server")

    overview = server_module._hybrid_collection_operator_unresolved_escalation_window_overview_fields(
        {
            "window_open": "unknown",
            "last_escalation_policy_status": "escalate_repeated_repin",
            "last_recovery_to_policy_status": "allow_hybrid_retrial",
            "last_escalation_at": "2026-05-18 18:40:00",
            "last_recovery_at": "2026-05-18 18:41:00",
            "current_window_duration_seconds": "unknown",
            "current_window_duration_minutes": "unknown",
        }
    )

    assert overview["hybrid_collection_unresolved_escalation_window_open"] is False
    assert overview["hybrid_collection_unresolved_escalation_policy_status"] == "allow_hybrid_retrial"
    assert overview["hybrid_collection_unresolved_escalation_last_event_at"] == "2026-05-18 18:41:00"
    assert overview["hybrid_collection_unresolved_escalation_duration_seconds"] is None
    assert overview["hybrid_collection_unresolved_escalation_duration_minutes"] is None
