from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {
                "decision": "browser_worker_dispatched",
                "task": {"url": "https://sf.taobao.com/list/b"},
                "recovery_policy_status": "escalate_repeated_repin",
                "recovery_policy_priority": "high",
                "recovery_policy_effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/c"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        load_guidance_fn=lambda *_args, **_kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
        load_recovery_policy_fn=lambda *_args, **_kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "recovery_policy"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "recovery_policy"
    assert sleeps == []

def test_run_loop_omits_mixed_case_unknown_operator_escalation_audit_message(monkeypatch):
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: " Unknown ",
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-placeholder-audit",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        load_guidance_fn=lambda *_args, **_kwargs: {},
        load_recovery_policy_fn=lambda *_args, **_kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
        run_once_fn=lambda **_: {
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/a"},
        },
        sleep_fn=lambda *_args: None,
    )

    assert summary["termination_reason"] == "operator_escalation"
    result = summary["results"][0]
    assert result.get("operator_escalation_source") == "recovery_policy"
    assert result.get("operator_escalation_audit_message") is None
    assert summary.get("operator_escalation_audit_message") is None

def test_run_loop_reuses_single_status_snapshot_when_guidance_and_escalation_checks_are_enabled():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "priority": "high",
                    "top_policy_reason": "challenge_detected",
                },
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "escalated",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        }
    )
    sleeps: list[float] = []

    original_session_factory = run_hybrid_seed_collection.requests.Session
    run_hybrid_seed_collection.requests.Session = lambda: session
    try:
        summary = run_hybrid_seed_collection.run_loop(
            api_base="http://127.0.0.1:8001/api",
            session_id="runner-loop-snapshot",
            cdp_endpoint="http://127.0.0.1:9223",
            submit=True,
            max_runs=10,
            idle_sleep_seconds=11,
            success_sleep_seconds=7,
            fallback_sleep_seconds=13,
            stop_on_operator_escalation=True,
            respect_operator_guidance=True,
            run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            sleep_fn=sleeps.append,
        )
    finally:
        run_hybrid_seed_collection.requests.Session = original_session_factory

    assert summary["termination_reason"] == "operator_escalation"
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]
    assert sleeps == []

def test_run_loop_can_use_operator_status_bundle_when_default_status_loads_are_active():
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-bundle",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: (
            bundle_calls.append("called")
            or {
                "guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "priority": "high",
                    "top_policy_reason": "challenge_detected",
                },
                "lifecycle_summary": {
                    "lifecycle_state": "escalated",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                    "suggested_mode": "browser",
                },
                "intervention_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "suggested_mode": "browser",
                },
                "digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        ),
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "operator_escalation"
    assert bundle_calls == ["called"]
    assert sleeps == []

def test_run_loop_treats_unknown_operator_status_bundle_nested_summaries_as_missing():
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-bundle-unknown",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        respect_operator_guidance=True,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: (
            bundle_calls.append("called")
            or {
                "guidance": "unknown",
                "recovery_policy": "unknown",
                "lifecycle_summary": "unknown",
                "intervention_summary": "unknown",
                "intervention_stability_summary": "unknown",
                "final_guidance_summary": "unknown",
                "digest_summary": "unknown",
                "digest_stability_summary": "unknown",
                "escalation_event_trend_summary": "unknown",
                "escalation_event_stability_summary": "unknown",
            }
        ),
        load_guidance_fn=lambda *args, **kwargs: {},
        load_recovery_policy_fn=lambda *args, **kwargs: {},
        load_lifecycle_summary_fn=lambda *args, **kwargs: {},
        load_intervention_summary_fn=lambda *args, **kwargs: {},
        load_stability_summary_fn=lambda *args, **kwargs: {},
        load_final_guidance_summary_fn=lambda *args, **kwargs: {},
        load_digest_summary_fn=lambda *args, **kwargs: {},
        load_digest_stability_summary_fn=lambda *args, **kwargs: {},
        load_escalation_event_trend_summary_fn=lambda *args, **kwargs: {},
        load_escalation_event_stability_summary_fn=lambda *args, **kwargs: {},
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert bundle_calls == ["called"]
    assert sleeps == []

def test_run_loop_omits_whitespace_unknown_operator_status_bundle_fields():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-bundle-whitespace-placeholder",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {
            "escalation_event_trend_summary": {
                "current_operator_escalation_source": " unknown ",
                "previous_distinct_operator_escalation_source": " unknown ",
                "recent_source_change_count": "unknown",
                "last_source_change_at": " unknown ",
            },
            "escalation_event_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "current_operator_escalation_source": " unknown ",
                "previous_operator_escalation_source": " unknown ",
                "recent_source_change_count": "unknown",
                "operator_readable_explanation": " unknown ",
            },
            "digest_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "operator_readable_explanation": " unknown ",
            },
        },
        run_once_fn=lambda **_: {
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/a"},
        },
        sleep_fn=lambda *_args: None,
    )

    result = summary["results"][0]
    assert result.get("operator_digest_stability_status") is None
    assert result.get("operator_digest_stability_severity") is None
    assert result.get("operator_digest_stability_explanation") is None
    assert result.get("operator_escalation_current_source") is None
    assert result.get("operator_escalation_previous_source") is None
    assert result.get("operator_escalation_source_last_changed_at") is None
    assert result.get("operator_escalation_source_stability_status") is None
    assert result.get("operator_escalation_source_stability_severity") is None
    assert result.get("operator_escalation_source_stability_explanation") is None
    assert result.get("operator_escalation_source") is None
    assert "unknown" not in json.dumps(result)

def test_run_loop_omits_whitespace_unknown_result_operator_escalation_source():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-result-whitespace-placeholder-source",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {},
        run_once_fn=lambda **_: {
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/a"},
            "operator_escalation_source": " unknown ",
        },
        sleep_fn=lambda *_args: None,
    )

    assert summary["termination_reason"] == "max_runs_reached"
    result = summary["results"][0]
    assert result.get("operator_escalation_source") is None
    assert "unknown" not in json.dumps(result)
