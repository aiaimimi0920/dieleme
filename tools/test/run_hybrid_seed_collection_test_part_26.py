from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_unknown_current_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

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
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=53", "page": 53},
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
            "runner-digest-stability-unknown-current",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    assert "severity=warning" in digest_stability_line
    assert "current=unknown" not in digest_stability_line
    assert "previous=ready" in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "Operator digest recently shifted from ready to attention_required." in digest_stability_line

def test_main_can_fail_with_dedicated_exit_code_on_operator_escalation(tmp_path: Path, monkeypatch, capsys):
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
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=18", "page": 18},
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
            "runner-escalation-exit",
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
    assert captured.out.strip().startswith("{")
    assert "Operator escalation" in captured.err
    assert "source=recovery_policy" in captured.err
    assert "Returning dedicated operator escalation exit code 42" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "recovery_policy"
    assert stdout_payload["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["recovery_policy_status"] == "escalate_repeated_repin"
    assert payload["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"

def test_operator_action_hint_omits_unknown_suggested_mode_for_recovery_policy():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        }
    )

    assert hint == "follow recovery policy escalation guidance"
    assert "suggested mode=unknown" not in hint

def test_operator_action_hint_ignores_unknown_preferred_intervention_action_hint():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        },
        intervention_summary={
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
    )

    assert hint == "follow recovery policy escalation guidance; suggested mode=browser"
    assert hint != "unknown"

def test_main_omits_unknown_suggested_mode_in_generated_operator_action_hint(tmp_path: Path, monkeypatch, capsys):
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
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": "monitor_hybrid_runtime",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_mode_pin_active": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=25", "page": 25},
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
            "runner-action-hint-no-suggested-mode",
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
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_action_hint"] == "follow recovery policy escalation guidance"
    assert "suggested mode=unknown" not in stdout_payload["operator_action_hint"]
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_action_hint"] == "follow recovery policy escalation guidance"
    assert "suggested mode=unknown" not in runtime_summary["operator_action_hint"]

def test_main_ignores_unknown_preferred_intervention_action_hint_in_operator_action_hint(
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
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "guidance_applied": False,
            "recovery_policy_applied": True,
            "guidance_status": "monitor_hybrid_runtime",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_mode_pin_active": True,
            "recovery_policy": {
                "effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
        },
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
            "runner-action-hint-unknown-preferred-intervention-hint",
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
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"
    assert stdout_payload["operator_action_hint"] != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"
    assert runtime_summary["operator_action_hint"] != "unknown"

def test_main_omits_literal_unknown_intervention_action_hint_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

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
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
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
            "runner-literal-unknown-intervention-action-hint-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "action_hint=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_action_hint") != "unknown"
