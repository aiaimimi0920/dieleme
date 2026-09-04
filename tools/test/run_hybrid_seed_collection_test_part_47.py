from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_run_once_treats_whitespace_unknown_mode_as_default_hybrid_for_browser_fallback():
    opened: list[tuple[str, Path, int]] = []

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode=" unknown ",
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browser_fallback_required",
            "reason": "challenge_detected",
        },
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["browser_fallback_opened"] is True
    assert opened == [
        (
            result["fallback_url"],
            Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
            9223,
        )
    ]

def test_run_once_browser_mode_opens_worker_without_browserless_probe():
    opened: list[tuple[str, Path, int]] = []
    calls = {"export": 0, "hybrid": 0}

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="browser",
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: calls.__setitem__("export", calls["export"] + 1),
        hybrid_collect_fn=lambda *_args, **_kwargs: calls.__setitem__("hybrid", calls["hybrid"] + 1),
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_worker_dispatched"
    assert result["fallback_url"].startswith("https://sf.taobao.com/list/50025969__2.htm?page=1")
    assert "uni_mode=SNIFF_WORKER" in result["fallback_url"]
    assert result["browser_fallback_opened"] is True
    assert calls == {"export": 0, "hybrid": 0}
    assert opened == [
        (
            result["fallback_url"],
            Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
            9223,
        )
    ]

def test_run_once_browserless_mode_does_not_open_browser_on_fallback():
    opened: list[tuple[str, Path, int]] = []

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="browserless",
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "browser_fallback_required", "reason": "challenge_detected"},
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["reason"] == "challenge_detected"
    assert result["browser_fallback_opened"] is False
    assert opened == []

def test_run_loop_continues_through_success_idle_and_fallback_results():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "idle", "message": "no task", "task": None},
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/b"},
                "fallback_url": "https://sf.taobao.com/list/b?uni_mode=SNIFF_WORKER",
                "browser_fallback_opened": True,
            },
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=3,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 3
    assert summary["counts"] == {
        "browserless_success": 1,
        "idle": 1,
        "browser_fallback_required": 1,
    }
    assert len(summary["results"]) == 3
    assert sleeps == [7, 11]

def test_run_loop_treats_unknown_result_as_missing():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-unknown-result",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        run_once_fn=lambda **_: "unknown",
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {}
    assert summary["results"][0].get("decision") is None
    assert summary["results"][0].get("task") is None

def test_run_loop_omits_whitespace_unknown_result_and_guidance_fields(monkeypatch):
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "guidance_applied": "unknown",
            "recovery_policy_applied": "unknown",
            "guidance_status": " unknown ",
            "recovery_policy_status": " unknown ",
            "recovery_policy_priority": " unknown ",
            "recovery_policy_mode_pin_active": "unknown",
            "guidance": {
                "recommended_mode": " unknown ",
                "top_guidance_reason": " unknown ",
            },
            "recovery_policy": {
                "effective_recommended_mode": " unknown ",
                "top_policy_reason": " unknown ",
            },
        },
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-whitespace-placeholder-fields",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        run_once_fn=lambda **_: {
            "decision": " unknown ",
            "reason": " unknown ",
            "fallback_url": " unknown ",
            "browser_fallback_opened": "unknown",
            "task": {"url": " unknown ", "page": "unknown"},
            "collection_result": {"submit_result": "unknown"},
        },
        sleep_fn=lambda *_args: None,
    )

    result = summary["results"][0]
    assert summary["counts"] == {}
    assert summary["reason_counts"] == {}
    assert summary["effective_mode_counts"] == {}
    assert summary["guidance_status_counts"] == {}
    assert result.get("decision") is None
    assert result.get("reason") is None
    assert result.get("fallback_url") is None
    assert result.get("requested_mode") == "hybrid"
    assert result.get("effective_mode") is None
    assert result.get("effective_mode_source") is None
    assert result.get("guidance_status") is None
    assert result.get("guidance_recommended_mode") is None
    assert result.get("top_guidance_reason") is None
    assert result.get("top_policy_reason") is None
    assert result.get("recovery_policy_status") is None
    assert result.get("recovery_policy_priority") is None
    assert result.get("recovery_policy_mode_pin_active") is None
    assert result.get("recovery_policy_effective_recommended_mode") is None
    assert result.get("task") == {"url": None, "page": None}
    assert result.get("collection_result") == {"submit_result": {}}
    assert "unknown" not in json.dumps(result)

def test_run_loop_omits_unknown_idle_message():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-idle-message",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        run_once_fn=lambda **_: {
            "decision": "idle",
            "message": " unknown ",
            "task": None,
        },
        sleep_fn=lambda *_args: None,
    )

    result = summary["results"][0]
    assert result["message"] is None
    assert "unknown" not in json.dumps(result)

def test_run_loop_tracks_reason_counts_and_escalates_after_consecutive_fallbacks():
    results = iter(
        [
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/a"},
            },
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/b"},
            },
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/c"},
            },
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        fallback_sleep_seconds=13,
        max_consecutive_fallbacks=2,
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 2
    assert summary["counts"] == {"browser_fallback_required": 2}
    assert summary["reason_counts"] == {"challenge_detected": 2}
    assert summary["termination_reason"] == "fallback_escalation_threshold_reached"
    assert sleeps == [13]

def test_run_loop_passes_mode_through_to_default_run_once():
    recorded: list[str] = []

    def _run_once(**kwargs):
        recorded.append(kwargs["mode"])
        return {"decision": "idle", "task": None, "message": "done"}

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="browser",
        max_runs=1,
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert recorded == ["browser"]

def test_run_loop_treats_whitespace_unknown_mode_as_default_hybrid():
    recorded: list[str] = []

    def _run_once(**kwargs):
        recorded.append(kwargs["mode"])
        return {"decision": "idle", "task": None, "message": "done"}

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode=" unknown ",
        max_runs=1,
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert recorded == [run_hybrid_seed_collection.DEFAULT_MODE]
    assert summary["results"][0]["requested_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert summary["results"][0]["effective_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert "unknown" not in json.dumps(summary)

def test_run_loop_treats_unknown_mode_resolution_as_default_hybrid(monkeypatch):
    recorded: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **_kwargs: {
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "guidance_applied": "unknown",
            "guidance_status": " unknown ",
            "guidance": {},
            "recovery_policy": {},
        },
    )

    def _run_once(**kwargs):
        recorded.append(kwargs["mode"])
        return {"decision": "idle", "task": None, "message": "done"}

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode=" unknown ",
        max_runs=1,
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert recorded == [run_hybrid_seed_collection.DEFAULT_MODE]
    assert summary["results"][0]["requested_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert summary["results"][0]["effective_mode"] is None
    assert summary["results"][0]["effective_mode_source"] is None
    assert "unknown" not in json.dumps(summary)

def test_run_loop_can_reload_operator_guidance_and_switch_effective_mode():
    recorded_modes: list[str] = []
    guidances = iter(
        [
            {"guidance_status": "keep_hybrid", "recommended_mode": "hybrid"},
            {"guidance_status": "prefer_browser_fallback", "recommended_mode": "browser"},
        ]
    )
    results = iter(
        [
            {"decision": "idle", "task": None, "message": "round-1"},
            {"decision": "browser_worker_dispatched", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return next(results)

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="hybrid",
        max_runs=2,
        respect_operator_guidance=True,
        load_guidance_fn=lambda *_args, **_kwargs: next(guidances),
        load_recovery_policy_fn=lambda *_args, **_kwargs: {},
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 2
    assert recorded_modes == ["hybrid", "browser"]
    assert summary["effective_mode_counts"] == {"hybrid": 1, "browser": 1}
    assert summary["guidance_applied_count"] == 1
    assert summary["guidance_status_counts"] == {
        "keep_hybrid": 1,
        "prefer_browser_fallback": 1,
    }
    assert summary["results"][0]["effective_mode"] == "hybrid"
    assert summary["results"][1]["effective_mode"] == "browser"
    assert summary["results"][1]["guidance_applied"] is True

def test_run_loop_stops_when_stop_on_fallback_is_requested():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/b"},
                "fallback_url": "https://sf.taobao.com/list/b?uni_mode=SNIFF_WORKER",
                "browser_fallback_opened": True,
            },
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/c"}},
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
        stop_on_fallback=True,
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 2
    assert summary["counts"] == {
        "browserless_success": 1,
        "browser_fallback_required": 1,
    }
    assert len(summary["results"]) == 2
    assert sleeps == [7]
