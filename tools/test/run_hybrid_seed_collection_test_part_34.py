from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_literal_unknown_recovery_policy_effective_recommended_mode_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "unknown",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=27", "page": 27},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
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
            "runner-literal-unknown-recovery-policy-effective-mode-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_effective_recommended_mode") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_effective_recommended_mode") != "unknown"

def test_main_omits_literal_unknown_top_policy_reason_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=26", "page": 26},
            "browser_fallback_opened": True,
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
            str(operator_escalation_path),
            "--session-id",
            "runner-literal-unknown-top-policy-reason-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "reason=unknown" not in escalation_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("top_policy_reason") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("top_policy_reason") != "unknown"

def test_main_omits_literal_unknown_top_guidance_reason_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
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
            "runner-literal-unknown-top-guidance-reason-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("top_guidance_reason") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("top_guidance_reason") != "unknown"

def test_build_runtime_summary_omits_literal_unknown_top_guidance_reason():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "top_guidance_reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-top-guidance-reason",
        guidance_resolution={
            "guidance": {
                "top_guidance_reason": "unknown",
            }
        },
    )

    assert summary.get("top_guidance_reason") != "unknown"

def test_build_runtime_summary_omits_literal_unknown_operator_escalation_audit_message():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "operator_escalation_audit_message": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-escalation-audit-message",
    )

    assert summary.get("operator_escalation_audit_message") != "unknown"

def test_build_runtime_summary_omits_literal_unknown_operator_action_hint():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "operator_action_hint": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-operator-action-hint",
    )

    assert summary.get("operator_action_hint") != "unknown"

def test_build_runtime_summary_omits_literal_unknown_last_fallback_url():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "fallback_url": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-last-fallback-url",
    )

    assert summary.get("last_fallback_url") != "unknown"

def test_build_runtime_summary_omits_literal_unknown_termination_reason():
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
            "termination_reason": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-termination-reason",
    )

    assert summary.get("termination_reason") != "unknown"
