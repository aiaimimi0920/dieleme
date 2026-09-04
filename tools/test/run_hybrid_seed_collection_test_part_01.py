from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_this_file_does_not_define_duplicate_test_names():
    path = Path(__file__)
    names = re.findall(r"^def (test_[A-Za-z0-9_]+)\(", path.read_text(encoding="utf-8"), flags=re.M)
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    assert duplicates == []

def test_load_hybrid_collection_status_snapshot_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                }
            }
        }
    )

    snapshot = run_hybrid_seed_collection.load_hybrid_collection_status_snapshot(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert snapshot == {
        "hybrid_collection_strategy_guidance": {
            "guidance_status": "prefer_browser_fallback",
            "recommended_mode": "browser",
        }
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_status_snapshot_treats_unknown_collection_stage_as_missing():
    session = _FakeHttpSession(
        {
            "collection_stage": "unknown",
        }
    )

    snapshot = run_hybrid_seed_collection.load_hybrid_collection_status_snapshot(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert snapshot == {}

def test_load_hybrid_collection_strategy_guidance_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                }
            }
        }
    )

    guidance = run_hybrid_seed_collection.load_hybrid_collection_strategy_guidance(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert guidance == {
        "guidance_status": "prefer_browser_fallback",
        "recommended_mode": "browser",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_strategy_guidance_treats_unknown_summary_as_missing():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": "unknown",
            }
        }
    )

    guidance = run_hybrid_seed_collection.load_hybrid_collection_strategy_guidance(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert guidance == {}

def test_load_hybrid_collection_recovery_policy_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                }
            }
        }
    )

    policy = run_hybrid_seed_collection.load_hybrid_collection_recovery_policy(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert policy == {
        "policy_status": "pin_browser_mode_temporarily",
        "effective_recommended_mode": "browser",
        "mode_pin_active": True,
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_lifecycle_state_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "retrial_window_open",
                    "lifecycle_reason": "hybrid_retrial_budget_active",
                    "recommended_follow_up": "continue_hybrid_with_budget_watch",
                    "suggested_mode": "hybrid",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_lifecycle_state_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "lifecycle_state": "retrial_window_open",
        "lifecycle_reason": "hybrid_retrial_budget_active",
        "recommended_follow_up": "continue_hybrid_with_budget_watch",
        "suggested_mode": "hybrid",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_intervention_policy_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "high",
                    "intervention_reason": "high_priority_unresolved_escalation_backlog",
                    "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                    "suggested_mode": "browser",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_intervention_policy_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "intervention_status": "intervention_required",
        "intervention_required": True,
        "intervention_priority": "high",
        "intervention_reason": "high_priority_unresolved_escalation_backlog",
        "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
        "suggested_mode": "browser",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_intervention_stability_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_intervention_stability_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "stability_status": "escalating",
        "stability_severity": "high",
        "current_intervention_status": "intervention_required",
        "previous_intervention_status": "ready",
        "recent_change_count": 1,
        "last_change_at": "2026-05-18 18:12:00",
        "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_final_guidance_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "preferred_action_hint": "prefer browser and investigate escalating intervention",
                    "suggested_mode": "browser",
                    "intervention_status": "intervention_required",
                    "stability_status": "escalating",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_final_guidance_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "guidance_label": "Escalating intervention",
        "guidance_priority": "high",
        "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        "preferred_action_hint": "prefer browser and investigate escalating intervention",
        "suggested_mode": "browser",
        "intervention_status": "intervention_required",
        "stability_status": "escalating",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_digest_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "attention_required",
                    "digest_priority": "warning",
                    "final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                    "intervention_status": "monitor",
                    "intervention_stability_status": "transitioning",
                    "final_guidance_stability_status": "guidance_recently_shifted",
                    "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_digest_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "digest_status": "attention_required",
        "digest_priority": "warning",
        "final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        "intervention_status": "monitor",
        "intervention_stability_status": "transitioning",
        "final_guidance_stability_status": "guidance_recently_shifted",
        "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_digest_stability_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_digest_stability_summary": {
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
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_digest_stability_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
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
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_escalation_event_trend_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_escalation_event_trend_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "current_operator_escalation_source": "intervention_stability",
        "previous_distinct_operator_escalation_source": "recovery_policy",
        "recent_source_change_count": 1,
        "last_source_change_at": "2026-05-18 18:24:00",
        "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_escalation_event_stability_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_escalation_event_stability_summary": {
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
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_escalation_event_stability_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
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
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]
