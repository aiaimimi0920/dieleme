from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_intervention_stability_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "browser",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        load_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        },
        load_final_guidance_summary_fn=lambda *_args, **_kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
        load_digest_summary_fn=lambda *_args, **_kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        load_digest_stability_summary_fn=lambda *_args, **_kwargs: {
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
        load_escalation_event_trend_summary_fn=lambda *_args, **_kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
        load_escalation_event_stability_summary_fn=lambda *_args, **_kwargs: {
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
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "intervention_stability"
    assert summary["operator_final_guidance_label"] == "Escalating intervention"
    assert summary["operator_final_guidance_priority"] == "high"
    assert summary["operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["operator_digest_status"] == "intervention_required"
    assert summary["operator_digest_priority"] == "high"
    assert summary["operator_digest_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["operator_digest_stability_status"] == "digest_recently_shifted"
    assert summary["operator_digest_stability_severity"] == "high"
    assert summary["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to intervention_required."
    assert summary["operator_escalation_current_source"] == "intervention_stability"
    assert summary["operator_escalation_previous_source"] == "recovery_policy"
    assert summary["operator_escalation_source_change_count"] == 1
    assert summary["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert summary["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert summary["operator_escalation_source_stability_severity"] == "high"
    assert summary["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    assert summary["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "intervention_stability"
    assert summary["results"][0]["operator_final_guidance_label"] == "Escalating intervention"
    assert summary["results"][0]["operator_final_guidance_priority"] == "high"
    assert summary["results"][0]["operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["results"][0]["operator_digest_status"] == "intervention_required"
    assert summary["results"][0]["operator_digest_priority"] == "high"
    assert summary["results"][0]["operator_digest_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["results"][0]["operator_digest_stability_status"] == "digest_recently_shifted"
    assert summary["results"][0]["operator_digest_stability_severity"] == "high"
    assert summary["results"][0]["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to intervention_required."
    assert summary["results"][0]["operator_escalation_current_source"] == "intervention_stability"
    assert summary["results"][0]["operator_escalation_previous_source"] == "recovery_policy"
    assert summary["results"][0]["operator_escalation_source_change_count"] == 1
    assert summary["results"][0]["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert summary["results"][0]["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert summary["results"][0]["operator_escalation_source_stability_severity"] == "high"
    assert summary["results"][0]["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    assert summary["results"][0]["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert sleeps == []

def test_run_loop_treats_negative_operator_escalation_source_change_count_as_missing():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-negative-source-change",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "browser",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        load_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        },
        load_final_guidance_summary_fn=lambda *_args, **_kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
        load_digest_summary_fn=lambda *_args, **_kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        load_digest_stability_summary_fn=lambda *_args, **_kwargs: {
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
        load_escalation_event_trend_summary_fn=lambda *_args, **_kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
        load_escalation_event_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["operator_escalation_source_change_count"] == 0
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source_change_count"] == 0
    assert sleeps == []

def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_flapping_intervention_stability_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "monitor",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "hybrid",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "monitor",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable; suggested mode=hybrid",
            "suggested_mode": "hybrid",
        },
        load_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "flapping",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": "intervention_required",
            "recent_change_count": 3,
            "last_change_at": "2026-05-18 18:18:00",
            "operator_readable_explanation": "Intervention status changed multiple times recently.",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "intervention_stability_flapping"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "intervention_stability_flapping"
    assert summary["results"][0]["operator_action_hint"] == "monitor until stable; suggested mode=hybrid"
    assert sleeps == []

def test_run_hybrid_seed_collection_script_can_run_help_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "run_hybrid_seed_collection.py"), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert "browserless-first" in result.stdout
    assert "--loop" in result.stdout
    assert "--mode" in result.stdout

def test_main_persists_hybrid_runtime_summary_for_loop_runs(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    fake_result = {
        "mode": "loop",
        "iterations": 2,
        "counts": {
            "browserless_success": 1,
            "browser_fallback_required": 1,
        },
        "reason_counts": {"challenge_detected": 1},
        "termination_reason": "stop_on_fallback",
        "results": [
            {
                "decision": "browserless_success",
                "reason": None,
                "task": {
                    "url": "https://sf.taobao.com/list/50025969__2.htm?page=6",
                    "page": 6,
                    "location_code": "440112",
                    "category": "50025969",
                },
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
            },
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {
                    "url": "https://sf.taobao.com/list/50025969__2.htm?page=7",
                    "page": 7,
                    "location_code": "440112",
                    "category": "50025969",
                },
                "fallback_url": "https://sf.taobao.com/list/50025969__2.htm?page=7&uni_mode=SNIFF_WORKER",
                "browser_fallback_opened": True,
                "collection_result": {
                    "probe_summary": {
                        "item_count": 0,
                        "has_script": False,
                        "body_has_challenge": True,
                        "body_has_punish": True,
                    }
                },
            },
        ],
    }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_loop", lambda **kwargs: fake_result)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--loop",
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--session-id",
            "runner-loop",
            "--mode",
            "hybrid",
            "--submit",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["runner_mode"] == "hybrid"
    assert payload["loop_mode"] is True
    assert payload["submit_enabled"] is True
    assert payload["session_id"] == "runner-loop"
    assert payload["decision_counts"] == {
        "browserless_success": 1,
        "browser_fallback_required": 1,
    }
    assert payload["reason_counts"] == {"challenge_detected": 1}
    assert payload["termination_reason"] == "stop_on_fallback"
    assert payload["last_decision"] == "browser_fallback_required"
    assert payload["last_reason"] == "challenge_detected"
    assert payload["last_task"]["page"] == 7
    assert payload["last_probe_summary"]["body_has_challenge"] is True
    assert payload["last_browser_fallback_opened"] is True
    history_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 1
    history_payload = json.loads(history_lines[0])
    assert history_payload["runner_mode"] == "hybrid"
    assert history_payload["decision_counts"]["browserless_success"] == 1
    assert history_payload["decision_counts"]["browser_fallback_required"] == 1
    assert history_payload["top_fallback_reason"] == "challenge_detected"
