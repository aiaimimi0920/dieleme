from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_run_loop_treats_unknown_nested_guidance_resolution_summaries_as_missing(monkeypatch):
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
            "guidance": "unknown",
            "recovery_policy": "unknown",
        },
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-guidance-resolution-unknown",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        respect_operator_guidance=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {},
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert summary["results"][0].get("guidance_recommended_mode") is None
    assert summary["results"][0].get("top_guidance_reason") is None
    assert summary["results"][0].get("top_policy_reason") is None
    assert summary["results"][0].get("recovery_policy_effective_recommended_mode") is None

def test_run_loop_treats_unknown_direct_status_loader_summaries_as_missing():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-direct-status-unknown",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {},
        load_lifecycle_summary_fn=lambda *args, **kwargs: "unknown",
        load_intervention_summary_fn=lambda *args, **kwargs: "unknown",
        load_stability_summary_fn=lambda *args, **kwargs: "unknown",
        load_final_guidance_summary_fn=lambda *args, **kwargs: "unknown",
        load_digest_summary_fn=lambda *args, **kwargs: "unknown",
        load_digest_stability_summary_fn=lambda *args, **kwargs: "unknown",
        load_escalation_event_trend_summary_fn=lambda *args, **kwargs: "unknown",
        load_escalation_event_stability_summary_fn=lambda *args, **kwargs: "unknown",
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert summary["termination_reason"] == "max_runs_reached"
    assert summary.get("operator_escalation_source") is None
    assert summary.get("operator_digest_status") is None

def test_run_loop_uses_default_operator_status_bundle_when_default_loaders_are_active(monkeypatch):
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: (
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
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-default-bundle",
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

    assert summary["termination_reason"] == "operator_escalation"
    assert bundle_calls == ["called"]
    assert sleeps == []

def test_run_loop_skips_operator_status_bundle_when_status_dependent_features_are_disabled():
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-no-status",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=False,
        respect_operator_guidance=False,
        load_operator_status_bundle_fn=lambda *args, **kwargs: (
            bundle_calls.append("called") or {"guidance": {"recommended_mode": "browser"}}
        ),
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "max_runs_reached"
    assert bundle_calls == []
    assert sleeps == []

def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_lifecycle_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
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
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 2,
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert sleeps == []

def test_run_loop_treats_non_dict_operator_escalation_last_result_as_missing():
    class _ResultLike:
        def __init__(self, payload):
            self.payload = dict(payload)

        def __contains__(self, key):
            return key in self.payload

        def __setitem__(self, key, value):
            self.payload[key] = value

        def get(self, key, default=None):
            return self.payload.get(key, default)

        def pop(self, key, default=None):
            return self.payload.pop(key, default)

    result = _ResultLike({"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}})
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-weird-operator-escalation-result",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 2,
        },
        run_once_fn=lambda **_: result,
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert summary["operator_escalation_audit_message"] == "Operator escalation [source=lifecycle_high_priority_backlog]"
    assert summary["operator_escalation_source_change_count"] is None
    assert sleeps == []

def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_intervention_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
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
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "browser",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "intervention_policy"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "intervention_policy"
    assert summary["results"][0]["operator_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert sleeps == []
