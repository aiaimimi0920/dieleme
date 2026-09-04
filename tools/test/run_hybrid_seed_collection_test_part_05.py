from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_append_recovery_policy_transition_events_records_pin_release_when_only_explicit_false_is_present(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "mode_pin_active": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "recovery_policy_mode_pin_active": False,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-policy-pin-release-explicit-false",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload["from_mode_pin_active"] is True
    assert transition_payload["to_mode_pin_active"] is False
    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload["mode_pin_active"] is False

def test_append_recovery_policy_transition_events_persists_explicit_false_without_event_when_no_previous_state_exists(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "recovery_policy_mode_pin_active": False,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=63", "page": 63},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-policy-explicit-false-no-previous-state",
    )

    assert not recovery_events_path.exists()
    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload["mode_pin_active"] is False

def test_persist_recovery_policy_state_treats_unknown_policy_as_missing(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-recovery-policy-state.json"

    run_hybrid_seed_collection.persist_recovery_policy_state(
        "unknown",
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }

def test_persist_recovery_policy_state_omits_whitespace_unknown_policy_fields(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-recovery-policy-state.json"

    run_hybrid_seed_collection.persist_recovery_policy_state(
        {
            "policy_status": " unknown ",
            "effective_recommended_mode": " unknown ",
            "mode_pin_active": "unknown",
            "top_policy_reason": " unknown ",
        },
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }

def test_main_treats_unknown_recovery_policy_mode_pin_active_as_missing_for_mode_resolution_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
            "mode_pin_active": "unknown",
            "top_policy_reason": "challenge_detected",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=12", "page": 12},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-pin-active",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["effective_mode"] == "hybrid"
    assert payload["effective_mode_source"] == "requested_mode"
    assert payload.get("recovery_policy_mode_pin_active") is None
    runtime_summary = payload
    assert runtime_summary.get("recovery_policy_mode_pin_active") is None
    recovery_state = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert recovery_state.get("mode_pin_active") is None
    if recovery_events_path.exists():
        transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
        assert len(transition_lines) == 1
        transition_payload = json.loads(transition_lines[0])
        assert transition_payload["transition_kind"] == "policy_status_changed"
        assert transition_payload["to_mode_pin_active"] is None

def test_main_omits_literal_unknown_recovery_policy_status_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "allow_hybrid_retrial",
                "effective_recommended_mode": "hybrid",
                "mode_pin_active": False,
                "top_policy_reason": "browserless_success_stable",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "unknown",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "challenge_detected",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=15", "page": 15},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-policy-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    recovery_state = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert recovery_state.get("policy_status") != "unknown"
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload.get("to_policy_status") != "unknown"
    assert transition_payload["to_mode_pin_active"] is True

def test_main_omits_literal_unknown_previous_recovery_policy_status_from_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "unknown",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
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
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=16", "page": 16},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-previous-policy-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("from_policy_status") != "unknown"
    assert transition_payload["to_policy_status"] == "allow_hybrid_retrial"

def test_main_omits_literal_unknown_previous_recovery_policy_effective_mode_from_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "unknown",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
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
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=17", "page": 17},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
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
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-previous-effective-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("from_effective_recommended_mode") != "unknown"
    assert transition_payload["to_effective_recommended_mode"] == "hybrid"
