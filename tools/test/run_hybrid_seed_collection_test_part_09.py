from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_literal_unknown_previous_operator_escalation_policy_status_from_recovery_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "unknown",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=21", "page": 21},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-unknown-prev-policy-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("from_policy_status") != "unknown"
    assert recovery_payload["to_policy_status"] == "steady_hybrid"

def test_append_operator_escalation_recovery_events_omits_literal_unknown_current_policy_status(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": "unknown",
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=53", "page": 53},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-current-policy-status",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("to_policy_status") != "unknown"

def test_append_operator_escalation_recovery_events_omits_literal_unknown_effective_mode(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": 55},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-effective-mode",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("effective_mode") != "unknown"

def test_append_operator_escalation_recovery_events_omits_whitespace_unknown_state_and_effective_mode(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": " unknown ",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": " unknown ",
            "effective_mode": " unknown ",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": 55},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-whitespace-placeholders",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("from_policy_status") is None
    assert recovery_payload.get("to_policy_status") is None
    assert recovery_payload.get("effective_mode") is None
    assert "unknown" not in json.dumps(recovery_payload)

def test_main_omits_missing_page_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47"},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-no-page",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "page=None" not in recovery_line
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=steady_hybrid" in recovery_line
    assert "mode=hybrid" in recovery_line

def test_main_omits_missing_mode_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=49", "page": 49},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-no-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "mode=unknown" not in recovery_line
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=steady_hybrid" in recovery_line
    assert "page=49" in recovery_line
