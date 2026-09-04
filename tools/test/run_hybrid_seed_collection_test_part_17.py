from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_emits_operator_lifecycle_banner_when_status_summary_available(tmp_path: Path, monkeypatch, capsys):
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
            "lifecycle_state": "retrial_window_open",
            "lifecycle_reason": "hybrid_retrial_budget_active",
            "recommended_follow_up": "continue_hybrid_with_budget_watch",
            "suggested_mode": "hybrid",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 2,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "hybrid_retrial_budget_active",
            "preferred_operator_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "digest_priority": "warning",
            "final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "intervention_status": "monitor",
            "intervention_stability_status": "transitioning",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
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
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=24", "page": 24},
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
            "runner-lifecycle-banner",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip().startswith("{")
    assert "Lifecycle state" in captured.err
    assert "retrial_window_open" in captured.err
    assert "priority_hint=high_priority_backlog_present" in captured.err
    assert "active_unresolved_priority=high" in captured.err
    assert "active_high_priority_unresolved_count=2" in captured.err
    assert "Intervention status" in captured.err
    assert "intervention_status" not in captured.err
    assert "required=False" in captured.err
    assert "priority=warning" in captured.err
    assert "reason=hybrid_retrial_budget_active" in captured.err
    assert "Intervention stability" in captured.err
    assert "transitioning" in captured.err
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "previous=None" not in intervention_stability_line
    assert "action_hint=monitor until stable before resuming aggressive intervention" in intervention_stability_line
    assert "Final guidance" not in captured.err
    assert "Transitioning intervention" in captured.err
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "Transitioning intervention:" not in digest_line
    assert "attention_required" not in digest_line
    assert "priority=warning" in digest_line
    assert "Operator digest stability" in captured.err
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "current=attention_required" not in digest_stability_line
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "Operator escalation source stability" in captured.err
    assert "Operator escalation audit" in captured.err
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "source_recently_shifted" not in source_stability_line
    assert "current=intervention_stability" not in source_stability_line
    assert "previous=recovery_policy" not in source_stability_line
    assert "changes=1" not in source_stability_line
    operator_lines = [line for line in captured.err.splitlines() if line.startswith("[OPERATOR]")]
    assert operator_lines[0].startswith("[OPERATOR] Operator digest:")
    assert operator_lines[1].startswith("[OPERATOR] Operator digest stability:")
    assert operator_lines[2].startswith("[OPERATOR] Operator escalation source trend:")
    assert operator_lines[3].startswith("[OPERATOR] Operator escalation source stability:")
    assert operator_lines[4].startswith("[OPERATOR] Operator escalation audit:")
    intervention_status_index = next(i for i, line in enumerate(operator_lines) if line.startswith("[OPERATOR] Intervention status:"))
    intervention_stability_index = next(i for i, line in enumerate(operator_lines) if line.startswith("[OPERATOR] Intervention stability:"))
    lifecycle_index = next(i for i, line in enumerate(operator_lines) if line.startswith("[OPERATOR] Lifecycle state:"))
    assert intervention_status_index > 4
    assert intervention_stability_index > intervention_status_index
    assert lifecycle_index > intervention_stability_index
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_digest_status"] == "attention_required"
    assert stdout_payload["operator_digest_priority"] == "warning"
    assert stdout_payload["operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    assert stdout_payload["operator_digest_stability_status"] == "digest_recently_shifted"
    assert stdout_payload["operator_digest_stability_severity"] == "warning"
    assert stdout_payload["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to attention_required."
    assert stdout_payload["operator_escalation_current_source"] == "intervention_stability"
    assert stdout_payload["operator_escalation_previous_source"] == "recovery_policy"
    assert stdout_payload["operator_escalation_source_change_count"] == 1
    assert stdout_payload["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert stdout_payload["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert stdout_payload["operator_escalation_source_stability_severity"] == "high"
    assert stdout_payload["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["intervention_stability_status"] == "transitioning"
    assert runtime_summary["intervention_stability_severity"] == "warning"
    assert runtime_summary["intervention_stability_explanation"] == "Intervention is transitioning and currently in monitor."
    assert runtime_summary["intervention_stability_action_hint"] == "monitor until stable before resuming aggressive intervention"
    assert runtime_summary["operator_final_guidance_label"] == "Transitioning intervention"
    assert runtime_summary["operator_final_guidance_priority"] == "warning"
    assert runtime_summary["operator_final_guidance_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    assert runtime_summary["operator_digest_status"] == "attention_required"
    assert runtime_summary["operator_digest_priority"] == "warning"
    assert runtime_summary["operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    assert runtime_summary["operator_digest_stability_status"] == "digest_recently_shifted"
    assert runtime_summary["operator_digest_stability_severity"] == "warning"
    assert runtime_summary["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to attention_required."
    assert runtime_summary["operator_escalation_current_source"] == "intervention_stability"
    assert runtime_summary["operator_escalation_previous_source"] == "recovery_policy"
    assert runtime_summary["operator_escalation_source_change_count"] == 1
    assert runtime_summary["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert runtime_summary["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert runtime_summary["operator_escalation_source_stability_severity"] == "high"
    assert runtime_summary["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."

def test_main_omits_missing_previous_on_source_stability_line(tmp_path: Path, monkeypatch, capsys):
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
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "persistent_recovery_policy_source",
            "stability_severity": "high",
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "recovery_policy",
            "previous_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
            "operator_readable_explanation": "Operator escalation source remains recovery_policy with no recent source changes.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=39", "page": 39},
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
            "runner-source-stability-no-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "previous=None" not in source_stability_line
    assert "current=recovery_policy" in source_stability_line
    assert "changes=0" in source_stability_line

def test_main_omits_missing_previous_on_source_trend_line(tmp_path: Path, monkeypatch, capsys):
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
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=40", "page": 40},
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
            "runner-source-trend-no-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:"))
    assert "previous=None" not in source_trend_line
    assert "current=intervention_stability" in source_trend_line
    assert "changes=1" in source_trend_line
    assert "last_changed_at=2026-05-18 18:24:00" in source_trend_line
