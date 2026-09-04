from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_can_fail_with_dedicated_exit_code_on_intervention_required_summary(tmp_path: Path, monkeypatch, capsys):
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
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=31", "page": 31},
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
            "runner-intervention-exit",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "Operator escalation" in captured.err
    assert "source=intervention_policy" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "reason=unresolved_escalation_window_open" not in intervention_line
    assert "priority=warning" in escalation_line
    assert "priority=warning" not in intervention_line
    assert "mode=browser" in escalation_line
    assert "suggested_mode=browser" not in intervention_line
    assert "Returning dedicated operator escalation exit code 42" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "intervention_policy"
    assert stdout_payload["operator_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_escalation_source"] == "intervention_policy"
    assert runtime_summary["operator_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert runtime_summary["intervention_status"] == "intervention_required"
    assert runtime_summary["intervention_required"] is True
    assert runtime_summary["intervention_priority"] == "warning"
    assert runtime_summary["intervention_reason"] == "unresolved_escalation_window_open"
    assert runtime_summary["intervention_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert runtime_summary["intervention_suggested_mode"] == "browser"

def test_main_can_fail_with_dedicated_exit_code_on_intervention_stability_summary(tmp_path: Path, monkeypatch, capsys):
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
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33", "page": 33},
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
            "runner-intervention-stability-exit",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "[OPERATOR] Final guidance:" not in captured.err
    assert "Operator escalation" in captured.err
    assert "source=intervention_stability" in captured.err
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "Escalating intervention:" not in digest_line
    assert "intervention_required" not in digest_line
    assert "priority=high" in digest_line
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    assert "current=intervention_required" not in digest_stability_line
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "source=intervention_stability" not in escalation_line
    assert "guidance=Escalating intervention" not in escalation_line
    assert "digest_status=intervention_required" not in escalation_line
    assert "digest_stability=digest_recently_shifted" not in escalation_line
    assert "action_hint=prefer browser and investigate escalation; suggested mode=browser" in intervention_line
    assert "escalating" not in intervention_stability_line
    assert "action_hint=prefer browser and investigate escalation; suggested mode=browser" not in intervention_stability_line
    assert "current=intervention_required" not in intervention_stability_line
    assert "action_hint=unknown" not in intervention_stability_line
    assert "Escalating intervention: prefer browser and investigate escalating intervention." in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "intervention_stability"
    assert stdout_payload["operator_final_guidance_label"] == "Escalating intervention"
    assert stdout_payload["operator_final_guidance_priority"] == "high"
    assert stdout_payload["operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert stdout_payload["operator_digest_stability_status"] == "digest_recently_shifted"
    assert stdout_payload["operator_digest_stability_severity"] == "high"
    assert stdout_payload["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to intervention_required."
    assert stdout_payload["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert (
        "[OPERATOR] Operator escalation audit: "
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    ) in captured.err
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_escalation_source"] == "intervention_stability"
    assert runtime_summary["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )

def test_main_does_not_fail_with_dedicated_exit_code_on_flapping_intervention_stability_summary(tmp_path: Path, monkeypatch, capsys):
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
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable; suggested mode=hybrid",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "flapping",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": "intervention_required",
            "recent_change_count": 3,
            "last_change_at": "2026-05-18 18:18:00",
            "operator_readable_explanation": "Intervention status changed multiple times recently.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=34", "page": 34},
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
            "runner-intervention-stability-flapping",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip().startswith("{")
    assert "Intervention stability" in captured.err
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "Intervention stability: flapping" not in intervention_stability_line
    assert "severity=warning" in intervention_stability_line
    assert "previous=intervention_required" in intervention_stability_line
    assert "changes=3" in intervention_stability_line
    assert "Intervention status changed multiple times recently." in intervention_stability_line
    assert "Operator escalation" not in captured.err
    stdout_payload = json.loads(captured.out)
    assert "operator_escalation_source" not in stdout_payload
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source") is None
