from tools.test.seed_collector_test_context import *  # noqa: F401,F403


def test_run_seed_collector_loop_ensures_jobs_but_exhausts_current_scope_before_next_job(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="legacy-unused",
            province="",
            city="",
            district="",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            max_runs=1,
            pages_per_run=2,
            seed_jobs=(
                seed_collector.SeedScanJobSpec(
                    job_key="440115-50025969",
                    province="广东省",
                    city="广州市",
                    district="南沙区",
                    location_code="440115",
                    category="50025969",
                    sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
                    max_page=3,
                ),
                seed_collector.SeedScanJobSpec(
                    job_key="440106-200782003",
                    province="广东省",
                    city="广州市",
                    district="天河区",
                    location_code="440106",
                    category="200782003",
                    sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
                    max_page=3,
                ),
            ),
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["pages_attempted"] == 2
    assert repo.seed_queue_counts()["seed_scan_job_pending"] >= 1
    assert len(fetched_urls) == 2
    assert all("location_code=440115" in url for url in fetched_urls)
    assert not any("location_code=440106" in url for url in fetched_urls)

def test_run_seed_collector_loop_does_not_refresh_runtime_context_when_scan_queue_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    repo.ensure_seed_scan_job(
        {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低"}],
        max_page=1,
    )
    task = repo.claim_seed_scan_page("seed-test", lease_seconds=30)
    assert task is not None
    repo.complete_seed_scan_page(
        progress_key=task["progress_key"],
        page=1,
        item_count=0,
        has_next=False,
        source_url=task["url"],
    )
    sleep_calls: list[int] = []
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="440115-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=1,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            loop_interval_seconds=7,
            max_runs=1,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=lambda: (_ for _ in ()).throw(AssertionError("empty seed queues must not refresh CDP cookies")),
        progress_emit_func=lambda _event: None,
    )

    assert summary["last_decision"] == "seed_scan_queue_empty"
    assert summary["pages_attempted"] == 0
    assert sleep_calls == []

def test_run_seed_collector_loop_stops_current_cycle_after_solver_enabled_challenge(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    run_once_calls = 0

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        nonlocal run_once_calls
        run_once_calls += 1
        return {
            "decision": "seed_page_retryable_failure",
            "reason": "list_challenge_page",
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            max_runs=1,
            pages_per_run=10,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=lambda _event: None,
    )

    assert run_once_calls == 1
    assert summary["pages_attempted"] == 1
    assert summary["last_decision"] == "seed_page_retryable_failure"

def test_run_seed_collector_loop_stops_current_cycle_after_list_challenge_without_solver(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    run_once_calls = 0

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        nonlocal run_once_calls
        run_once_calls += 1
        return {
            "decision": "seed_page_retryable_failure",
            "reason": "list_challenge_page",
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            max_runs=1,
            pages_per_run=10,
            solver_enabled=False,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=lambda _event: None,
    )

    assert run_once_calls == 1
    assert summary["pages_attempted"] == 1
    assert summary["last_decision"] == "seed_page_retryable_failure"

def test_run_seed_collector_loop_does_not_count_paused_state_as_page_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    run_once_calls = 0

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        nonlocal run_once_calls
        run_once_calls += 1
        return {
            "decision": "seed_collection_paused",
            "reason": "captcha_solver_manual_required",
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            max_runs=1,
            pages_per_run=10,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=events.append,
    )

    assert run_once_calls == 1
    assert summary["pages_attempted"] == 0
    assert events[0]["pages_attempted"] == 0

def test_run_seed_collector_loop_collects_multiple_pages_per_cycle(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    sleep_calls: list[int] = []

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            max_runs=1,
            pages_per_run=3,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collector_loop_finished"
    assert summary["runs"] == 1
    assert summary["pages_attempted"] == 3
    assert [result["task"]["page"] for result in summary["results"]] == [1, 2, 3]
    assert summary["last_cycle_summary"]["pages_attempted"] == 3
    assert summary["last_cycle_summary"]["pages_collected"] == 3
    assert summary["last_cycle_summary"]["items_collected"] == 6
    written_summary = json.loads((tmp_path / "seed_collector_summary.json").read_text(encoding="utf-8"))
    assert written_summary["last_cycle_summary"]["pages_collected"] == 3
    assert len(fetched_urls) == 3
    assert sleep_calls == []
    assert repo.seed_queue_counts()["seed_scan_progress_pending"] == 1

def test_run_seed_collector_loop_waits_instead_of_exiting_when_queue_is_empty(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[int] = []

    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 0}},
    )
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            loop_interval_seconds=7,
            max_runs=2,
            pages_per_run=3,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collector_loop_finished"
    assert summary["runs"] == 2
    assert summary["pages_attempted"] == 0
    assert summary["last_decision"] == "seed_scan_queue_empty"
    assert sleep_calls == [7]

def test_run_seed_collector_loop_refreshes_runtime_context_each_cycle(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    contexts: list[str] = []
    used_sessions: list[str] = []

    def _runtime_context_factory() -> str:
        context = f"http-{len(contexts) + 1}"
        contexts.append(context)
        return context

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        used_sessions.append(http_session)
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda _seconds: None)

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
            loop_interval_seconds=1,
            max_runs=2,
            pages_per_run=3,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=lambda _event: None,
    )

    assert summary["decision"] == "seed_collector_loop_finished"
    assert contexts == ["http-1", "http-2"]
    assert used_sessions == contexts
