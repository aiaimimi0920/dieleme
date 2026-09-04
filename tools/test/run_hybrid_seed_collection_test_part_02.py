from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_status_snapshot_cache_scope_reuses_single_status_response_for_multiple_summary_loads():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "attention_required",
                    "digest_priority": "warning",
                    "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                },
            }
        }
    )

    with run_hybrid_seed_collection.hybrid_collection_status_snapshot_scope():
        guidance = run_hybrid_seed_collection.load_hybrid_collection_strategy_guidance(
            "http://127.0.0.1:8001/api",
            http_session=session,
        )
        policy = run_hybrid_seed_collection.load_hybrid_collection_recovery_policy(
            "http://127.0.0.1:8001/api",
            http_session=session,
        )
        digest = run_hybrid_seed_collection.load_hybrid_collection_operator_digest_summary(
            "http://127.0.0.1:8001/api",
            http_session=session,
        )

    assert guidance["recommended_mode"] == "browser"
    assert policy["policy_status"] == "pin_browser_mode_temporarily"
    assert digest["digest_status"] == "attention_required"
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_load_hybrid_collection_operator_status_bundle_reuses_single_status_response():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                },
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "escalated",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                },
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                },
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "intervention_required",
                },
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                },
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                },
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                },
            }
        }
    )

    bundle = run_hybrid_seed_collection.load_hybrid_collection_operator_status_bundle(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert bundle == {
        "guidance": {
            "guidance_status": "prefer_browser_fallback",
            "recommended_mode": "browser",
        },
        "recovery_policy": {
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
        },
        "lifecycle_summary": {
            "lifecycle_state": "escalated",
            "suggested_mode": "browser",
        },
        "intervention_summary": {
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
        "intervention_stability_summary": {
            "stability_status": "escalating",
        },
        "final_guidance_summary": {
            "guidance_label": "Escalating intervention",
        },
        "digest_summary": {
            "digest_status": "intervention_required",
        },
        "digest_stability_summary": {
            "stability_status": "digest_recently_shifted",
        },
        "escalation_event_trend_summary": {
            "current_operator_escalation_source": "intervention_stability",
        },
        "escalation_event_stability_summary": {
            "stability_status": "source_recently_shifted",
        },
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]

def test_resolve_effective_mode_only_applies_guidance_to_default_hybrid_mode():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance={"guidance_status": "prefer_browser_fallback", "recommended_mode": "browser"},
        recovery_policy={},
        respect_operator_guidance=True,
    )
    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "browser"
    assert applied["guidance_applied"] is True
    assert applied["guidance_status"] == "prefer_browser_fallback"
    assert applied["effective_mode_source"] == "guidance"

    explicit_browserless = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="browserless",
        guidance={"guidance_status": "prefer_browser_fallback", "recommended_mode": "browser"},
        recovery_policy={},
        respect_operator_guidance=True,
    )
    assert explicit_browserless["requested_mode"] == "browserless"
    assert explicit_browserless["effective_mode"] == "browserless"
    assert explicit_browserless["guidance_applied"] is False

def test_resolve_effective_mode_can_enforce_browser_pin_recovery_policy():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance={"guidance_status": "keep_hybrid", "recommended_mode": "hybrid"},
        recovery_policy={
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "challenge_detected",
        },
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "browser"
    assert applied["guidance_applied"] is True
    assert applied["effective_mode_source"] == "recovery_policy"
    assert applied["recovery_policy_status"] == "pin_browser_mode_temporarily"
    assert applied["recovery_policy_applied"] is True

def test_resolve_effective_mode_treats_unknown_guidance_and_recovery_policy_as_missing():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance="unknown",
        recovery_policy="unknown",
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "hybrid"
    assert applied["effective_mode_source"] == "requested_mode"
    assert applied["guidance_applied"] is False
    assert applied["recovery_policy_applied"] is False
    assert applied["guidance"] == {}
    assert applied["recovery_policy"] == {}

def test_resolve_effective_mode_treats_whitespace_unknown_requested_mode_as_default():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode=" unknown ",
        guidance={},
        recovery_policy={},
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert applied["effective_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert applied["effective_mode_source"] == "requested_mode"
    assert "unknown" not in json.dumps(applied)

def test_resolve_effective_mode_omits_whitespace_unknown_guidance_and_recovery_fields():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance={
            "guidance_status": " unknown ",
            "recommended_mode": " unknown ",
            "top_guidance_reason": " unknown ",
        },
        recovery_policy={
            "policy_status": " unknown ",
            "priority": " unknown ",
            "effective_recommended_mode": " unknown ",
            "mode_pin_active": "unknown",
            "top_policy_reason": " unknown ",
        },
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "hybrid"
    assert applied["effective_mode_source"] == "requested_mode"
    assert applied["guidance_applied"] is False
    assert applied["recovery_policy_applied"] is False
    assert applied["guidance_status"] is None
    assert applied["recovery_policy_status"] is None
    assert applied["recovery_policy_priority"] is None
    assert applied["recovery_policy_mode_pin_active"] is None
    assert applied["guidance"] == {
        "guidance_status": None,
        "recommended_mode": None,
        "top_guidance_reason": None,
    }
    assert applied["recovery_policy"] == {
        "policy_status": None,
        "priority": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }
    assert "unknown" not in json.dumps(applied)

def test_main_respects_operator_guidance_when_enabled(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "prefer_browser_fallback",
            "recommended_mode": "browser",
            "top_guidance_reason": "challenge_detected",
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
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=8", "page": 8},
            "browser_fallback_opened": True,
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
            "runner-guided",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["requested_mode"] == "hybrid"
    assert payload["effective_mode"] == "browser"
    assert payload["guidance_applied"] is True
    assert payload["guidance_status"] == "prefer_browser_fallback"
    assert payload["effective_mode_source"] == "guidance"
    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload["guidance_status"] == "prefer_browser_fallback"
    assert switch_payload["top_guidance_reason"] == "challenge_detected"
    assert switch_payload["session_id"] == "runner-guided"

def test_main_treats_unknown_guidance_applied_as_missing_for_payload_runtime_and_mode_switch_event(
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
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": "unknown",
            "recovery_policy_applied": False,
            "guidance_status": "monitor_hybrid_runtime",
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
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=9", "page": 9},
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
            "runner-guidance-applied-unknown",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["effective_mode"] == "hybrid"
    assert stdout_payload["guidance_applied"] is False
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["guidance_applied"] is False
    assert runtime_summary["guidance_applied_count"] == 0
    assert not switch_events_path.exists()
