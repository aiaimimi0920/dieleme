from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_unknown_suggested_mode_on_intervention_status_line(tmp_path: Path, monkeypatch, capsys):
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
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable",
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
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=38", "page": 38},
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
            "runner-intervention-unknown-suggested-mode",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "suggested_mode=unknown" not in intervention_line
    assert "action_hint=monitor until stable" in intervention_line

def test_main_omits_missing_previous_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
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
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Persistent intervention required",
            "guidance_priority": "high",
            "guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "preferred_action_hint": "treat as sustained intervention and investigate backlog",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "persistent_intervention_required",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "persistent_intervention_required",
            "final_guidance_stability_status": "persistent_noninfo_guidance",
            "operator_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "persistent_noninfo_digest",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Operator digest remains non-info with no recent message changes.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=36", "page": 36},
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
            "runner-digest-stability-no-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "previous=None" not in digest_stability_line
    assert "changes=0" in digest_stability_line
    assert "Operator digest remains non-info with no recent message changes." in digest_stability_line

def test_main_omits_unknown_previous_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
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
            "current_digest_status": "attention_required",
            "previous_digest_status": "unknown",
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": 50},
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
            "runner-digest-stability-unknown-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "severity=warning" in digest_stability_line
    assert "current=attention_required" in digest_stability_line
    assert "previous=unknown" not in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "Operator digest recently shifted from ready to attention_required." in digest_stability_line

def test_main_omits_unknown_explanation_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
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
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51", "page": 51},
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
            "runner-digest-stability-unknown-explanation",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" in digest_stability_line
    assert "severity=warning" in digest_stability_line
    assert "current=attention_required" in digest_stability_line
    assert "previous=ready" in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "explanation=unknown" not in digest_stability_line

def test_main_omits_literal_unknown_digest_stability_explanation_from_payloads(tmp_path: Path, monkeypatch, capsys):
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
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51", "page": 51},
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
            "runner-digest-stability-literal-unknown-explanation-payload",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "explanation=unknown" not in digest_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_stability_explanation") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_explanation") != "unknown"

def test_main_omits_unknown_severity_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
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
            "current_digest_status": "attention_required",
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=52", "page": 52},
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
            "runner-digest-stability-unknown-severity",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    assert "severity=unknown" not in digest_stability_line
    assert "current=attention_required" in digest_stability_line
    assert "previous=ready" in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "Operator digest recently shifted from ready to attention_required." in digest_stability_line
