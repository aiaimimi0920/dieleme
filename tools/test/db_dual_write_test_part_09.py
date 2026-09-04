from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_hybrid_collection_lifecycle_state_summary_treats_unknown_policy_status_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {
            "available": True,
            "recovery_policy_status": "unknown",
        },
        {
            "policy_status": "unknown",
        },
        {
            "window_open": False,
        },
        {},
    )

    assert summary == {
        "available": True,
        "lifecycle_state": "steady",
        "lifecycle_reason": "browserless_fast_path_stable",
        "recommended_follow_up": "keep_hybrid",
        "suggested_mode": "hybrid",
        "operator_action_hint": "keep hybrid; suggested mode=hybrid",
        "priority_hint": "no_active_priority_backlog",
        "active_unresolved_priority": None,
        "active_high_priority_unresolved_count": 0,
        "policy_status": "steady_hybrid",
        "window_open": False,
    }

def test_hybrid_collection_lifecycle_state_summary_treats_negative_high_priority_count_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_lifecycle_state_summary(
        {
            "available": True,
            "recovery_policy_status": "steady_hybrid",
        },
        {
            "policy_status": "steady_hybrid",
        },
        {
            "window_open": True,
        },
        {
            "top_recent_unresolved_priority": "medium",
            "recent_high_priority_unresolved_count": -2,
        },
    )

    assert summary["available"] is True
    assert summary["lifecycle_state"] == "escalated"
    assert summary["priority_hint"] == "non_high_priority_backlog_present"
    assert summary["active_unresolved_priority"] == "medium"
    assert summary["active_high_priority_unresolved_count"] == 0

def test_hybrid_collection_action_hint_consistency_summary_treats_unknown_summaries_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_action_hint_consistency_summary("unknown", "unknown")

    assert summary == {
        "available": False,
        "runtime_operator_action_hint": None,
        "lifecycle_operator_action_hint": None,
        "hints_match": False,
        "consistency_status": "no_hint_available",
        "drift_reason": None,
        "consistency_severity": "info",
        "severity_reason": None,
        "hint_source_preference": None,
        "preferred_hint_source_detail": None,
        "preferred_hint_explanation": None,
        "preferred_operator_action_hint": None,
    }

def test_hybrid_collection_action_hint_consistency_summary_treats_unknown_available_flags_as_missing():
    server_module = importlib.import_module("src.server")

    summary = server_module._hybrid_collection_action_hint_consistency_summary(
        {"available": "unknown"},
        {"available": "unknown"},
    )

    assert summary == {
        "available": False,
        "runtime_operator_action_hint": None,
        "lifecycle_operator_action_hint": None,
        "hints_match": False,
        "consistency_status": "no_hint_available",
        "drift_reason": None,
        "consistency_severity": "info",
        "severity_reason": None,
        "hint_source_preference": None,
        "preferred_hint_source_detail": None,
        "preferred_hint_explanation": None,
        "preferred_operator_action_hint": None,
    }

def test_hybrid_collection_recovery_policy_treats_unknown_summaries_as_missing(tmp_path: Path, monkeypatch):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        "unknown",
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    )

    assert summary == {
        "policy_status": "no_history_available",
        "priority": "info",
        "effective_recommended_mode": "hybrid",
        "mode_pin_active": False,
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_policy_reason": "history_unavailable",
        "guidance_status": None,
        "guidance_recommended_mode": None,
        "recent_mode_switch_count": 0,
        "recent_browserless_success_rate": 0.0,
        "top_switch_target_mode": None,
        "top_switch_guidance_reason": None,
        "last_switch_at": None,
    }

def test_hybrid_collection_recovery_policy_treats_unknown_history_available_as_missing(tmp_path: Path, monkeypatch):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {"available": "unknown"},
        {"recommended_mode": "hybrid"},
        {},
        {},
    )

    assert summary == {
        "policy_status": "no_history_available",
        "priority": "info",
        "effective_recommended_mode": "hybrid",
        "mode_pin_active": False,
        "recommended_actions": ["collect_more_hybrid_runtime_history"],
        "top_policy_reason": "history_unavailable",
        "guidance_status": None,
        "guidance_recommended_mode": "hybrid",
        "recent_mode_switch_count": 0,
        "recent_browserless_success_rate": 0.0,
        "top_switch_target_mode": None,
        "top_switch_guidance_reason": None,
        "last_switch_at": None,
    }

def test_hybrid_collection_recovery_policy_treats_unknown_no_history_aux_text_fields_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {"available": "unknown"},
        {"guidance_status": "unknown", "recommended_mode": "unknown"},
        {
            "recent_switch_count": "unknown",
            "top_target_mode": "unknown",
            "top_guidance_reason": "unknown",
            "last_switch_at": "unknown",
        },
        {},
    )

    assert summary["policy_status"] == "no_history_available"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "history_unavailable"
    assert summary["guidance_status"] is None
    assert summary["guidance_recommended_mode"] is None
    assert summary["recent_mode_switch_count"] == 0
    assert summary["top_switch_target_mode"] is None
    assert summary["top_switch_guidance_reason"] is None
    assert summary["last_switch_at"] is None

def test_hybrid_collection_recovery_policy_treats_unknown_summary_scalars_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": "unknown",
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": "unknown",
        },
        {
            "recent_transition_kind_counts": {
                "pin_released": "unknown",
                "pin_activated": "unknown",
            }
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["top_switch_target_mode"] is None
    assert summary["top_switch_guidance_reason"] is None
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1

def test_hybrid_collection_recovery_policy_treats_negative_summary_scalars_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": -0.5,
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": -1,
        },
        {
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.0
    assert summary["top_switch_target_mode"] is None
    assert summary["top_switch_guidance_reason"] is None

def test_hybrid_collection_recovery_policy_treats_overfull_success_rate_as_clamped(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": 1.5,
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": 0,
        },
        {
            "recent_transition_kind_counts": {},
        },
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["recent_browserless_success_rate"] == 1.0

def test_hybrid_collection_recovery_policy_treats_unknown_guidance_reason_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": 0.75,
        },
        {
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "unknown",
        },
        {
            "recent_switch_count": 0,
        },
        {},
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "hybrid_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["recent_browserless_success_rate"] == 0.75

def test_hybrid_collection_recovery_policy_treats_unknown_guidance_status_and_switch_timestamp_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {
            "available": True,
            "recent_browserless_success_rate": 0.85,
        },
        {
            "guidance_status": "unknown",
            "recommended_mode": "hybrid",
            "priority": "info",
            "top_guidance_reason": "browserless_success_stable",
        },
        {
            "recent_switch_count": 0,
            "last_switch_at": "unknown",
        },
        {},
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["guidance_status"] is None
    assert summary["guidance_recommended_mode"] == "hybrid"
    assert summary["last_switch_at"] is None

def test_hybrid_collection_recovery_policy_treats_unknown_transition_kind_counts_as_missing(
    tmp_path: Path, monkeypatch
):
    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    data_root = Path(server_module.DATA_DIR)
    (data_root / "avm").mkdir(parents=True, exist_ok=True)

    summary = server_module._hybrid_collection_recovery_policy(
        data_root,
        {},
        {"available": True, "recent_browserless_success_rate": 0.0},
        {"recommended_mode": "hybrid", "priority": "info", "top_guidance_reason": "browserless_success_stable"},
        {},
        {"recent_transition_kind_counts": "unknown"},
    )

    assert summary["policy_status"] == "steady_hybrid"
    assert summary["priority"] == "info"
    assert summary["effective_recommended_mode"] == "hybrid"
    assert summary["mode_pin_active"] is False
    assert summary["top_policy_reason"] == "browserless_success_stable"
    assert summary["recent_mode_switch_count"] == 0
    assert summary["hybrid_retrial_budget_total"] == 1
    assert summary["hybrid_retrial_attempts_used"] == 0
    assert summary["hybrid_retrial_budget_remaining"] == 1
    assert summary["last_recovery_transition_kind"] is None
    assert summary["last_recovery_transition_at"] is None
