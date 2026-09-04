from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_literal_unknown_intervention_priority_from_runtime_summary(
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
            "intervention_priority": "unknown",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=29", "page": 29},
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
            "runner-literal-unknown-intervention-priority-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "priority=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_priority") != "unknown"

def test_main_omits_literal_unknown_intervention_reason_from_runtime_summary(
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
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=30", "page": 30},
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
            "runner-literal-unknown-intervention-reason-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "reason=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_reason") != "unknown"

def test_main_omits_literal_unknown_intervention_suggested_mode_from_runtime_summary(
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
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "unknown",
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
            "runner-literal-unknown-intervention-suggested-mode-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "suggested_mode=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_suggested_mode") != "unknown"

def test_main_omits_literal_unknown_intervention_stability_action_hint_from_runtime_summary(
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
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
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
            "runner-literal-unknown-intervention-stability-action-hint-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:")
    )
    assert "action_hint=unknown" not in intervention_stability_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_stability_action_hint") != "unknown"

def test_main_omits_literal_unknown_intervention_stability_severity_from_runtime_summary(
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
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "unknown",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
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
            "runner-literal-unknown-intervention-stability-severity-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:")
    )
    assert "severity=unknown" not in intervention_stability_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_stability_severity") != "unknown"

def test_main_omits_literal_unknown_intervention_status_from_runtime_summary(
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
            "intervention_status": "unknown",
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "browser",
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
            "runner-literal-unknown-intervention-status-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Intervention status:") for line in captured.err.splitlines())
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_status") != "unknown"
