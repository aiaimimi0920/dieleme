from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_build_runtime_summary_omits_unknown_collection_nested_payloads():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=7", "page": 7},
            "collection_result": {
                "probe_summary": {
                    "final_url": " unknown ",
                    "first_urls": [" unknown ", "https://sf.taobao.com/item/1"],
                },
                "submit_result": {
                    "batch": {"status": " unknown ", "message": " unknown "},
                    "progress": {"status": "ok", "error": " unknown "},
                },
            },
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=True,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="runner-runtime-nested-placeholder-payloads",
    )

    assert summary["last_probe_summary"]["final_url"] is None
    assert summary["last_probe_summary"]["first_urls"] == [None, "https://sf.taobao.com/item/1"]
    assert summary["last_submit_result"]["batch"]["status"] is None
    assert summary["last_submit_result"]["batch"]["message"] is None
    assert summary["last_submit_result"]["progress"]["status"] == "ok"
    assert summary["last_submit_result"]["progress"]["error"] is None
    assert "unknown" not in json.dumps(summary)

def test_main_appends_runtime_history_without_overwriting_existing_entries(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    history_path.write_text(
        json.dumps({"generated_at": "2026-05-18 18:00:00", "session_id": "old-run"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fake_result = {
        "decision": "browserless_success",
        "reason": None,
        "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=8", "page": 8},
        "collection_result": {
            "probe_summary": {
                "item_count": 60,
                "has_script": True,
                "body_has_challenge": False,
                "body_has_punish": False,
            },
            "submit_result": {
                "batch": {"status": "ok", "new": 60},
                "progress": {"status": "ok"},
            },
        },
    }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", lambda **kwargs: fake_result)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--session-id",
            "runner-single",
            "--mode",
            "browserless",
            "--submit",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    history_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 2
    old_payload = json.loads(history_lines[0])
    new_payload = json.loads(history_lines[1])
    assert old_payload["session_id"] == "old-run"
    assert new_payload["session_id"] == "runner-single"
    assert new_payload["runner_mode"] == "browserless"
    assert new_payload["decision_counts"] == {"browserless_success": 1}

def test_main_omits_literal_unknown_effective_mode_from_payloads(tmp_path: Path, monkeypatch, capsys):
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
            "effective_mode": "unknown",
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
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
            "runner-literal-unknown-effective-mode-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("effective_mode") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("effective_mode") != "unknown"
    assert runtime_summary.get("last_effective_mode") != "unknown"
    assert "unknown" not in dict(runtime_summary.get("effective_mode_counts") or {})

def test_main_omits_whitespace_unknown_effective_mode_from_payloads(
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
            "effective_mode": " unknown ",
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
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
            "runner-whitespace-placeholder-effective-mode-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("effective_mode") is None
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("effective_mode") is None
    assert runtime_summary.get("last_effective_mode") is None
    assert "unknown" not in dict(runtime_summary.get("effective_mode_counts") or {})

def test_main_treats_unknown_operator_status_bundle_nested_summaries_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "guidance": "unknown",
            "recovery_policy": "unknown",
            "lifecycle_summary": "unknown",
            "intervention_summary": "unknown",
            "intervention_stability_summary": "unknown",
            "final_guidance_summary": "unknown",
            "digest_summary": "unknown",
            "digest_stability_summary": "unknown",
            "escalation_event_trend_summary": "unknown",
            "escalation_event_stability_summary": "unknown",
        },
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=64", "page": 64},
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
            "runner-unknown-operator-status-bundle-nested-summaries",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_action_hint") is None
    assert runtime_summary.get("operator_escalation_audit_message") is None
    assert runtime_summary.get("operator_digest_status") is None
    assert runtime_summary.get("operator_digest_stability_status") is None

def test_main_loop_mode_treats_unknown_direct_status_loader_summaries_as_missing(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_loop",
        lambda **kwargs: {
            "mode": "loop",
            "iterations": 1,
            "counts": {"browserless_success": 1},
            "reason_counts": {},
            "effective_mode_counts": {"hybrid": 1},
            "guidance_status_counts": {},
            "guidance_applied_count": 0,
            "termination_reason": "max_runs_reached",
            "results": [{"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=66", "page": 66}}],
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: "unknown",
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--loop",
            "--max-runs",
            "1",
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-loop-mode-direct-status-unknown",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_digest_status") is None
    assert runtime_summary.get("operator_digest_stability_status") is None
