from tools.test.seed_collector_test_context import *  # noqa: F401,F403


def test_config_from_env_reads_seed_jobs_file(tmp_path: Path, monkeypatch) -> None:
    jobs_file = tmp_path / "seed_jobs_all.json"
    jobs_file.write_text(
        """
        [
          {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
            "max_page": 3,
            "sorts": [{"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低"}]
          }
        ]
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_SEED_JOBS_FILE", str(jobs_file))

    config, _loop = seed_collector.config_from_env_and_args([])

    assert len(config.seed_jobs) == 1
    assert config.seed_jobs[0].job_key == "440115-50025969"
    assert config.seed_jobs[0].max_page == 3

def test_run_seed_collector_once_passes_failure_cooldown_to_repository(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _api_base_url: {"paused": False})

    class RecordingRepository:
        def __init__(self) -> None:
            self.claim_kwargs: dict[str, object] = {}

        def ensure_seed_scan_job(self, *_args, **_kwargs) -> dict[str, object]:
            return {"job_key": "job-1"}

        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 1}

        def claim_seed_scan_page(self, _worker_id: str, **kwargs) -> None:
            self.claim_kwargs = kwargs
            return None

    repository = RecordingRepository()
    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
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
            failure_cooldown_threshold=10,
            failure_cooldown_seconds=120,
        ),
        repository=repository,  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    assert summary["decision"] == "seed_scan_queue_empty"
    assert repository.claim_kwargs["failure_cooldown_threshold"] == 10
    assert repository.claim_kwargs["failure_cooldown_seconds"] == 120

def test_run_seed_collector_loop_does_not_reensure_jobs_for_each_page(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _api_base_url: {"paused": False})
    ensure_calls: list[int] = []
    monkeypatch.setattr(seed_collector, "_ensure_seed_scan_jobs", lambda *_args, **_kwargs: ensure_calls.append(1) or [])
    monkeypatch.setattr(seed_collector, "fetch_list_page", lambda *_args, **_kwargs: ("ok", "https://example.test/list", 200, "http_cookie"))
    monkeypatch.setattr(
        seed_collector,
        "_extract_seed_items",
        lambda *_args, **_kwargs: ([{"id": "1001", "title": "房产", "url": "https://example.test/item/1001"}], {}, False),
    )
    monkeypatch.setattr(seed_collector.time, "sleep", lambda _seconds: None)

    class RecordingRepository:
        def __init__(self) -> None:
            self.claim_count = 0

        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 3, "seed_scan_progress_in_progress": 0}

        def claim_seed_scan_page(self, _worker_id: str, **_kwargs) -> dict[str, object] | None:
            self.claim_count += 1
            return {
                "job_key": "job-1",
                "progress_key": f"job-1:sort-{self.claim_count}",
                "sort_key": f"sort-{self.claim_count}",
                "sort_name": "排序",
                "st_param": "2",
                "page": self.claim_count,
                "url": f"https://example.test/list?page={self.claim_count}",
                "location_code": "440115",
                "category": "50025969",
            }

        def upsert_seed_items(self, **_kwargs) -> dict[str, int]:
            return {"seen": 1, "new_items": 1, "existing_items": 0, "new_occurrences": 1}

        def complete_seed_scan_page(self, **_kwargs) -> None:
            return None

        def fail_seed_scan_page(self, *_args, **_kwargs) -> None:
            raise AssertionError("unexpected failure path")

    summary = seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
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
            active_loop_interval_seconds=0,
        ),
        repository=RecordingRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    assert summary["pages_attempted"] == 3
    assert len(ensure_calls) == 1

def test_run_seed_collector_loop_ensures_jobs_once_per_process(tmp_path: Path, monkeypatch) -> None:
    ensure_calls: list[int] = []
    monkeypatch.setattr(seed_collector, "_ensure_seed_scan_jobs", lambda *_args, **_kwargs: ensure_calls.append(1) or [])
    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_page_collected", "item_count": 1, "counts": {}},
    )
    monkeypatch.setattr(seed_collector.time, "sleep", lambda _seconds: None)

    class WorkRepository:
        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 1, "seed_scan_progress_in_progress": 0}

    seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
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
            max_runs=2,
            pages_per_run=1,
            active_loop_interval_seconds=0,
        ),
        repository=WorkRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    assert len(ensure_calls) == 1

def test_run_seed_collector_loop_releases_existing_worker_leases_once_per_process(tmp_path: Path, monkeypatch) -> None:
    ensure_calls: list[int] = []
    monkeypatch.setattr(seed_collector, "_ensure_seed_scan_jobs", lambda *_args, **_kwargs: ensure_calls.append(1) or [])
    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_scan_queue_empty", "counts": {"seed_scan_progress_pending": 0}},
    )
    monkeypatch.setattr(seed_collector.time, "sleep", lambda _seconds: None)

    class WorkRepository:
        def __init__(self) -> None:
            self.release_calls: list[str] = []

        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 1, "seed_scan_progress_in_progress": 0}

        def release_seed_scan_worker_leases(self, worker_id: str) -> dict[str, int]:
            self.release_calls.append(worker_id)
            return {"released": 2}

    repository = WorkRepository()

    seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
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
            pages_per_run=1,
        ),
        repository=repository,  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    assert repository.release_calls == ["seed-test"]

def test_run_seed_collector_loop_writes_seed_job_ensure_status_before_fetching(
    tmp_path: Path,
    monkeypatch,
) -> None:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr(
        seed_collector,
        "_write_runtime_summary",
        lambda _output_dir, summary: written.append(dict(summary)),
    )
    monkeypatch.setattr(
        seed_collector,
        "_ensure_seed_scan_jobs",
        lambda *_args, **_kwargs: [{"job_key": "job-1", "created": False, "progress_created": 0}],
    )
    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_scan_queue_empty", "counts": {"seed_scan_progress_pending": 0}},
    )

    class WorkRepository:
        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 1, "seed_scan_progress_in_progress": 0}

    seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
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
            pages_per_run=1,
        ),
        repository=WorkRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    decisions = [summary.get("decision") for summary in written]
    assert decisions[:2] == ["seed_scan_jobs_ensure_started", "seed_scan_jobs_ensure_completed"]
    assert written[1]["ensured_jobs"] == 1
    assert written[1]["counts"]["seed_scan_progress_pending"] == 1

def test_run_seed_collector_loop_archives_stale_jobs_before_ensure_when_jobs_file_is_loaded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr(
        seed_collector,
        "_write_runtime_summary",
        lambda _output_dir, summary: written.append(dict(summary)),
    )
    archive_calls: list[list[str]] = []
    monkeypatch.setattr(
        seed_collector,
        "_ensure_seed_scan_jobs",
        lambda *_args, **_kwargs: [{"job_key": "job-1", "created": False, "progress_created": 0}],
    )
    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_scan_queue_empty", "counts": {"seed_scan_progress_pending": 0}},
    )

    class WorkRepository:
        def seed_queue_counts(self) -> dict[str, int]:
            return {"seed_scan_progress_pending": 1, "seed_scan_progress_in_progress": 0}

        def archive_seed_scan_jobs_except(self, active_job_keys: list[str]) -> dict[str, int]:
            archive_calls.append(list(active_job_keys))
            return {"active_job_count": len(active_job_keys), "archived_jobs": 3, "archived_progress": 18}

    seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="legacy-unused",
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
            pages_per_run=1,
            seed_jobs=(
                seed_collector.SeedScanJobSpec(
                    job_key="440115-50025969",
                    province="广东省",
                    city="广州市",
                    district="南沙区",
                    location_code="440115",
                    category="50025969",
                    sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
                    max_page=83,
                ),
                seed_collector.SeedScanJobSpec(
                    job_key="440115-200782003",
                    province="广东省",
                    city="广州市",
                    district="南沙区",
                    location_code="440115",
                    category="200782003",
                    sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
                    max_page=83,
                ),
            ),
        ),
        repository=WorkRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    assert archive_calls == [["440115-50025969", "440115-200782003"]]
    decisions = [summary.get("decision") for summary in written]
    assert decisions[:3] == [
        "seed_scan_jobs_ensure_started",
        "seed_scan_jobs_archive_stale_completed",
        "seed_scan_jobs_ensure_completed",
    ]
    assert written[1]["archive_summary"]["archived_jobs"] == 3
    assert written[2]["archive_summary"]["archived_progress"] == 18

def test_run_seed_collector_loop_skips_seed_job_ensure_for_secondary_worker_when_queue_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    written: list[dict[str, Any]] = []
    monkeypatch.setattr(
        seed_collector,
        "_write_runtime_summary",
        lambda _output_dir, summary: written.append(dict(summary)),
    )
    monkeypatch.setattr(
        seed_collector,
        "_ensure_seed_scan_jobs",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("secondary worker should not ensure")),
    )
    monkeypatch.setattr(
        seed_collector,
        "run_seed_collector_once",
        lambda *_args, **_kwargs: {"decision": "seed_scan_queue_empty", "counts": {"seed_scan_progress_pending": 0}},
    )

    class WorkRepository:
        def seed_queue_counts(self) -> dict[str, int]:
            return {
                "seed_scan_job_pending": 10,
                "seed_scan_progress_pending": 10,
                "seed_scan_progress_in_progress": 0,
            }

    seed_collector.run_seed_collector_loop(
        seed_collector.SeedCollectorConfig(
            job_key="job-1",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-2",
            max_runs=1,
            pages_per_run=1,
        ),
        repository=WorkRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    assert written[0]["decision"] == "seed_scan_jobs_ensure_skipped"
    assert written[0]["reason"] == "existing_seed_scan_queue"
