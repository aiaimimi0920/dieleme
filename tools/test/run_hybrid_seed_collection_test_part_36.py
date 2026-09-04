from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_build_runtime_summary_treats_negative_status_scalars_as_missing():
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
        session_id="summary-negative-status-scalars",
        lifecycle_summary={
            "lifecycle_state": "escalated",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": -2,
        },
        operator_escalation_event_trend_summary={
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:12:00",
        },
    )

    assert summary["lifecycle_active_high_priority_unresolved_count"] == 0
    assert summary["operator_escalation_source_change_count"] == 0

def test_build_runtime_summary_treats_unknown_last_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": ["unknown"],
            "counts": {},
            "iterations": 1,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-last-result",
    )

    assert summary.get("last_task") == {}
    assert summary.get("last_decision") is None

def test_build_runtime_summary_treats_unknown_operator_escalation_last_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": ["unknown"],
            "counts": {},
            "iterations": 1,
            "termination_reason": "operator_escalation",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-operator-escalation-last-result",
    )

    assert summary.get("operator_escalation_source") is None
    assert summary.get("operator_escalation_audit_message") is None
    assert summary.get("operator_escalation_source_change_count") is None

def test_build_runtime_summary_treats_unknown_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result="unknown",
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-result",
    )

    assert summary.get("last_task") == {}
    assert summary.get("last_decision") is None

def test_persist_operator_intervention_state_treats_unknown_summary_as_missing(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-intervention-state.json"

    run_hybrid_seed_collection.persist_operator_intervention_state(
        "unknown",
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "intervention_status": None,
        "intervention_required": None,
        "intervention_priority": None,
        "intervention_reason": None,
        "preferred_operator_action_hint": None,
        "suggested_mode": None,
    }

def test_build_runtime_summary_treats_unknown_iterations_as_missing():
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
            "iterations": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-iterations",
    )

    assert summary.get("iterations") == 1

def test_build_runtime_summary_treats_negative_iterations_as_missing():
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
            "iterations": -1,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-negative-iterations",
    )

    assert summary.get("iterations") == 1

def test_build_runtime_summary_treats_unknown_guidance_applied_count_as_zero():
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
            "guidance_applied_count": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-applied-count",
    )

    assert summary.get("guidance_applied_count") == 0

def test_build_runtime_summary_treats_negative_guidance_applied_count_as_zero():
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
            "guidance_applied_count": -2,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-negative-guidance-applied-count",
    )

    assert summary.get("guidance_applied_count") == 0

def test_build_runtime_summary_treats_unknown_guidance_status_counts_as_missing():
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
            "guidance_status_counts": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-status-counts",
    )

    assert summary.get("guidance_status_counts") == {}

def test_build_runtime_summary_treats_unknown_guidance_status_count_values_as_missing():
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
            "guidance_status_counts": {"monitor_hybrid_runtime": "unknown"},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-status-count-values",
    )

    assert summary.get("guidance_status_counts") == {}

def test_build_runtime_summary_treats_unknown_reason_counts_as_missing():
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
            "reason_counts": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-reason-counts",
    )

    assert summary.get("reason_counts") == {}
    assert summary.get("top_fallback_reason") is None

def test_build_runtime_summary_treats_unknown_reason_count_values_as_missing():
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
            "reason_counts": {"challenge_detected": "unknown"},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-reason-count-values",
    )

    assert summary.get("reason_counts") == {}
    assert summary.get("top_fallback_reason") is None

def test_main_treats_unknown_submit_result_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
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
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=66", "page": 66},
            "collection_result": {
                "probe_summary": {"item_count": 60, "has_script": True},
                "submit_result": "unknown",
            },
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
            "--session-id",
            "runner-literal-unknown-submit-result-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["collection_result"]["submit_result"] == {}
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("last_submit_result") == {}

def test_main_omits_unknown_idle_message_from_payload(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "idle",
            "message": " unknown ",
            "task": None,
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
            "--session-id",
            "runner-main-idle-message",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["message"] is None
    assert "unknown" not in json.dumps(stdout_payload)
