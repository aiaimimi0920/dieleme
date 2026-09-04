from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_main_omits_literal_unknown_top_guidance_reason_from_mode_switch_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "unknown",
            "recommended_mode": "browser",
            "top_guidance_reason": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=2", "page": 2},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guided-unknown-top-reason",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("guidance_status") != "unknown"
    assert switch_payload.get("top_guidance_reason") != "unknown"

def test_append_mode_switch_events_omits_literal_unknown_status_fields(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "unknown",
            "recovery_policy_status": "unknown",
            "top_guidance_reason": "unknown",
            "reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=3", "page": 3},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-status-fields",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("guidance_status") != "unknown"
    assert switch_payload.get("recovery_policy_status") != "unknown"
    assert switch_payload.get("top_guidance_reason") != "unknown"

def test_append_mode_switch_events_omits_literal_unknown_effective_mode_source(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "unknown",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=4", "page": 4},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-effective-mode-source",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("effective_mode_source") != "unknown"

def test_append_mode_switch_events_omits_literal_unknown_effective_mode(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=5", "page": 5},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-effective-mode",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload.get("effective_mode") != "unknown"
    assert switch_payload["effective_mode_source"] == "guidance"

def test_append_mode_switch_events_omits_literal_unknown_task_page(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=6", "page": "unknown"},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-task-page",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("task_page") != "unknown"

def test_append_mode_switch_events_omits_negative_task_page(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=6", "page": -6},
        },
        switch_events_path,
        session_id="runner-direct-negative-mode-switch-task-page",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("task_page") is None

def test_append_mode_switch_events_omits_literal_unknown_task_url(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "unknown", "page": 6},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-task-url",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("task_url") != "unknown"

def test_append_mode_switch_events_omits_literal_unknown_requested_mode(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "unknown",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=6", "page": 6},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-requested-mode",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload.get("requested_mode") != "unknown"
    assert switch_payload["effective_mode"] == "browser"

def test_append_mode_switch_events_omits_whitespace_unknown_fields(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "guidance_status": " unknown ",
            "recovery_policy_status": " unknown ",
            "top_guidance_reason": " unknown ",
            "reason": " unknown ",
            "task": {"url": " unknown ", "page": "unknown"},
        },
        switch_events_path,
        session_id="runner-direct-whitespace-placeholder-mode-switch-fields",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload.get("requested_mode") is None
    assert switch_payload.get("effective_mode") is None
    assert switch_payload.get("effective_mode_source") is None
    assert switch_payload.get("guidance_status") is None
    assert switch_payload.get("recovery_policy_status") is None
    assert switch_payload.get("top_guidance_reason") is None
    assert switch_payload.get("task_url") is None
    assert switch_payload.get("task_page") is None
    assert "unknown" not in json.dumps(switch_payload)

def test_append_mode_switch_events_treats_unknown_result_as_missing(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        "unknown",
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-result",
    )

    assert not switch_events_path.exists()

def test_main_reuses_single_status_snapshot_for_operator_summary_loads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "top_policy_reason": "challenge_detected",
                },
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "escalated",
                    "lifecycle_reason": "unresolved_escalation_window_open",
                    "recommended_follow_up": "prefer_browser_and_investigate_escalation",
                    "suggested_mode": "browser",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                },
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "preferred_action_hint": "prefer browser and investigate escalating intervention",
                    "suggested_mode": "browser",
                    "intervention_status": "intervention_required",
                    "stability_status": "escalating",
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        }
    )
    monkeypatch.setattr(run_hybrid_seed_collection.requests, "Session", lambda: session)
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=8", "page": 8},
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
            "runner-guided-snapshot",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]
