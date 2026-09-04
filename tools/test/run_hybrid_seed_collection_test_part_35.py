from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_build_runtime_summary_omits_whitespace_unknown_payload_fields():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": " unknown ",
                    "reason": " unknown ",
                    "requested_mode": " unknown ",
                    "effective_mode": " unknown ",
                    "effective_mode_source": " unknown ",
                    "guidance_status": " unknown ",
                    "guidance_recommended_mode": " unknown ",
                    "recovery_policy_status": " unknown ",
                    "recovery_policy_priority": " unknown ",
                    "recovery_policy_effective_recommended_mode": " unknown ",
                    "top_policy_reason": " unknown ",
                    "top_guidance_reason": " unknown ",
                    "operator_escalation_audit_message": " unknown ",
                    "operator_escalation_source": " unknown ",
                    "operator_action_hint": " unknown ",
                    "fallback_url": " unknown ",
                    "collection_result": {"submit_result": "unknown"},
                    "task": {"url": "unknown", "page": "unknown"},
                }
            ],
            "counts": {" unknown ": 1, "browserless_success": 1},
            "reason_counts": {" unknown ": 2, "browserless_success_stable": 1},
            "effective_mode_counts": {" unknown ": 3},
            "guidance_status_counts": {" unknown ": 4},
            "guidance_applied_count": "unknown",
            "iterations": 1,
            "termination_reason": " unknown ",
        },
        requested_mode=" unknown ",
        effective_mode=" unknown ",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-whitespace-placeholders",
        guidance_resolution={
            "guidance_status": " unknown ",
            "effective_mode_source": " unknown ",
            "recovery_policy_status": " unknown ",
            "recovery_policy_priority": " unknown ",
            "guidance": {
                "recommended_mode": " unknown ",
                "top_guidance_reason": " unknown ",
            },
            "recovery_policy": {
                "effective_recommended_mode": " unknown ",
                "top_policy_reason": " unknown ",
            },
        },
        lifecycle_summary={
            "lifecycle_state": " unknown ",
            "lifecycle_reason": " unknown ",
            "recommended_follow_up": " unknown ",
            "suggested_mode": " unknown ",
            "priority_hint": " unknown ",
            "active_unresolved_priority": " unknown ",
            "active_high_priority_unresolved_count": "unknown",
        },
        intervention_summary={
            "intervention_status": " unknown ",
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "preferred_operator_action_hint": " unknown ",
            "suggested_mode": " unknown ",
        },
        intervention_stability_summary={
            "stability_status": " unknown ",
            "stability_severity": " unknown ",
            "operator_readable_explanation": " unknown ",
            "stability_action_hint": " unknown ",
        },
        final_guidance_summary={
            "guidance_label": " unknown ",
            "guidance_priority": " unknown ",
            "guidance_message": " unknown ",
        },
        operator_digest_summary={
            "digest_status": " unknown ",
            "digest_priority": " unknown ",
            "operator_digest_message": " unknown ",
        },
        operator_digest_stability_summary={
            "stability_status": " unknown ",
            "stability_severity": " unknown ",
            "operator_readable_explanation": " unknown ",
        },
        operator_escalation_event_trend_summary={
            "current_operator_escalation_source": " unknown ",
            "previous_distinct_operator_escalation_source": " unknown ",
            "last_source_change_at": " unknown ",
            "recent_source_change_count": "unknown",
        },
        operator_escalation_event_stability_summary={
            "stability_status": " unknown ",
            "stability_severity": " unknown ",
            "operator_readable_explanation": " unknown ",
        },
    )

    assert summary["requested_mode"] == "hybrid"
    assert summary.get("effective_mode") is None
    assert summary.get("last_effective_mode") is None
    assert summary.get("termination_reason") is None
    assert " unknown " not in summary.get("decision_counts", {})
    assert " unknown " not in summary.get("reason_counts", {})
    assert " unknown " not in summary.get("effective_mode_counts", {})
    assert " unknown " not in summary.get("guidance_status_counts", {})
    assert summary.get("guidance_applied_count") == 0
    assert summary.get("last_task") == {"url": None, "page": None}
    assert summary.get("last_submit_result") == {}

    placeholder_fields = [
        "last_decision",
        "last_reason",
        "guidance_status",
        "guidance_recommended_mode",
        "recovery_policy_status",
        "recovery_policy_priority",
        "recovery_policy_effective_recommended_mode",
        "top_policy_reason",
        "top_guidance_reason",
        "operator_escalation_source",
        "operator_escalation_audit_message",
        "operator_action_hint",
        "last_fallback_url",
        "effective_mode_source",
        "lifecycle_state",
        "lifecycle_reason",
        "lifecycle_follow_up",
        "lifecycle_suggested_mode",
        "lifecycle_priority_hint",
        "lifecycle_active_unresolved_priority",
        "intervention_status",
        "intervention_priority",
        "intervention_reason",
        "intervention_action_hint",
        "intervention_suggested_mode",
        "intervention_stability_status",
        "intervention_stability_severity",
        "intervention_stability_explanation",
        "intervention_stability_action_hint",
        "operator_final_guidance_label",
        "operator_final_guidance_priority",
        "operator_final_guidance_message",
        "operator_digest_status",
        "operator_digest_priority",
        "operator_digest_message",
        "operator_digest_stability_status",
        "operator_digest_stability_severity",
        "operator_digest_stability_explanation",
        "operator_escalation_current_source",
        "operator_escalation_previous_source",
        "operator_escalation_source_last_changed_at",
        "operator_escalation_source_stability_status",
        "operator_escalation_source_stability_severity",
        "operator_escalation_source_stability_explanation",
    ]
    for field in placeholder_fields:
        assert summary.get(field) is None

def test_main_omits_whitespace_unknown_status_bundle_fields_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "digest_summary": {
                "digest_status": " unknown ",
                "digest_priority": " unknown ",
                "operator_digest_message": " unknown ",
            },
            "digest_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "operator_readable_explanation": " unknown ",
            },
            "escalation_event_trend_summary": {
                "current_operator_escalation_source": " unknown ",
                "previous_distinct_operator_escalation_source": " unknown ",
                "last_source_change_at": " unknown ",
                "recent_source_change_count": "unknown",
            },
            "escalation_event_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "operator_readable_explanation": " unknown ",
            },
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": " unknown ",
            "reason": " unknown ",
            "fallback_url": " unknown ",
            "browser_fallback_opened": "unknown",
            "task": {"url": "unknown", "page": "unknown"},
            "collection_result": {"submit_result": "unknown"},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-whitespace-placeholders",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))

    for payload in (stdout_payload, runtime_summary):
        assert payload.get("operator_digest_status") is None
        assert payload.get("operator_digest_priority") is None
        assert payload.get("operator_digest_message") is None
        assert payload.get("operator_digest_stability_status") is None
        assert payload.get("operator_digest_stability_severity") is None
        assert payload.get("operator_digest_stability_explanation") is None
        assert payload.get("operator_escalation_current_source") is None
        assert payload.get("operator_escalation_previous_source") is None
        assert payload.get("operator_escalation_source_last_changed_at") is None
        assert payload.get("operator_escalation_source_stability_status") is None
        assert payload.get("operator_escalation_source_stability_severity") is None
        assert payload.get("operator_escalation_source_stability_explanation") is None
    assert stdout_payload.get("decision") is None
    assert stdout_payload.get("reason") is None
    assert stdout_payload.get("fallback_url") is None
    assert stdout_payload.get("task") == {"url": None, "page": None}

def test_build_runtime_summary_treats_unknown_decision_counts_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": "unknown",
            "iterations": 1,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-decision-counts",
    )

    assert summary.get("decision_counts") == {}

def test_build_runtime_summary_treats_unknown_effective_mode_counts_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "effective_mode_counts": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-effective-mode-counts",
    )

    assert summary.get("effective_mode_counts") == {}

def test_build_runtime_summary_treats_unknown_effective_mode_count_values_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "effective_mode_counts": {"hybrid": "unknown"},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-effective-mode-count-values",
    )

    assert summary.get("effective_mode_counts") == {}

def test_build_runtime_summary_treats_unknown_submit_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "collection_result": {
                "probe_summary": {"item_count": 60, "has_script": True},
                "submit_result": "unknown",
            },
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-submit-result",
    )

    assert summary.get("last_submit_result") == {}

def test_build_runtime_summary_treats_unknown_guidance_resolution_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-resolution",
        guidance_resolution="unknown",
    )

    assert summary.get("guidance_status_counts") == {}
    assert summary.get("guidance_applied_count") == 0

def test_build_runtime_summary_treats_unknown_nested_guidance_resolution_summaries_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-resolution-nested",
        guidance_resolution={
            "guidance": "unknown",
            "recovery_policy": "unknown",
        },
    )

    assert summary.get("last_guidance_recommended_mode") is None
    assert summary.get("last_recovery_policy_effective_recommended_mode") is None
    assert summary.get("top_guidance_reason") is None
    assert summary.get("top_policy_reason") is None
