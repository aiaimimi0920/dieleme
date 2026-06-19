from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import seed_collector


class _FakeProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(html: str, *, final_url: str) -> dict[str, Any]:
        if html == "challenge":
            return {
                "item_count": None,
                "body_has_challenge": True,
                "body_has_login": False,
                "body_has_punish": True,
            }
        return {
            "item_count": 2,
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
        }

    @staticmethod
    def extract_list_payload(html: str) -> dict[str, Any] | None:
        if html == "challenge":
            return None
        return {"data": [{"id": "2001"}, {"id": "2002"}]}

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {
            "source_page_url": source_page_url,
            "items": [
                {"id": "2001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/2001.htm"},
                {"id": "2002", "title": "南沙 B", "url": "https://sf-item.taobao.com/sf_item/2002.htm"},
            ],
        }


def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'seed-collector.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def _make_repo_at(db_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_parse_seed_sort_specs_accepts_named_final_sort_contract() -> None:
    specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远")

    assert [spec.as_dict() for spec in specs] == [
        {"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低", "sort_order": 0},
        {"sort_key": "end_time_soon", "st_param": "1", "sort_name": "结拍时间由近到远", "sort_order": 1},
    ]


def test_default_seed_sort_specs_start_with_default_then_price_desc() -> None:
    specs = seed_collector.parse_seed_sort_specs(None)

    assert [(spec.sort_key, spec.st_param, spec.sort_name, spec.sort_order) for spec in specs] == [
        ("sort_0", "0", "默认排序", 0),
        ("sort_3", "3", "价格由高到低", 1),
        ("bid_desc", "2", "出价次数由高到低", 2),
        ("end_time_soon", "1", "结拍时间由近到远", 3),
        ("sort_4", "4", "排序4", 4),
        ("sort_5", "5", "排序5", 5),
    ]


def test_run_seed_collector_once_claims_one_page_and_populates_detail_queue(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_once(
        seed_collector.SeedCollectorConfig(
            job_key="guangdong-guangzhou-nansha-50025969",
            province="广东省",
            city="广州市",
            district="南沙区",
            location_code="440115",
            category="50025969",
            sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低,end_time_soon:1:结拍时间由近到远"),
            max_page=83,
            cdp_endpoint="http://127.0.0.1:9223",
            output_dir=tmp_path,
            worker_id="seed-test",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert summary["task"]["sort_key"] == "bid_desc"
    assert summary["task"]["page"] == 1
    assert summary["upsert"] == {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2}
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1"
    ]
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 2


def test_run_seed_collector_once_resumes_after_restart_without_researching_completed_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "seed-resume.sqlite3"
    config = seed_collector.SeedCollectorConfig(
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
    )
    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    first_repo = _make_repo_at(db_path)
    first_summary = seed_collector.run_seed_collector_once(
        config,
        repository=first_repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    restarted_repo = _make_repo_at(db_path)
    second_summary = seed_collector.run_seed_collector_once(
        config,
        repository=restarted_repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert first_summary["task"]["sort_key"] == "bid_desc"
    assert first_summary["task"]["page"] == 1
    assert second_summary["task"]["sort_key"] == "bid_desc"
    assert second_summary["task"]["page"] == 2
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=2",
    ]
    assert restarted_repo.seed_queue_counts()["seed_occurrence_total"] == 4


def test_run_seed_collector_once_marks_scan_page_retryable_on_challenge(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled: ("challenge", target_url, 200, "browser_page"),
    )

    summary = seed_collector.run_seed_collector_once(
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
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "list_challenge_page"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1


def test_run_seed_collector_once_passes_solver_enabled_to_fetch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    solver_flags: list[bool] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
        solver_flags.append(solver_enabled)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_once(
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
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert solver_flags == [True]


def test_run_seed_collector_once_skips_page_fetch_when_collection_api_reports_manual_required(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    )
    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("manual-required workers must not fetch pages")),
    )

    summary = seed_collector.run_seed_collector_once(
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
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True


def test_run_seed_collector_once_probes_list_page_during_manual_required_and_auto_resumes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    probe_url = "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=14&__captcha_solver_bg=1"
    fetched_urls: list[str] = []
    resumed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {"target_url": probe_url},
            },
        },
    )

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(
        seed_collector,
        "_notify_auth_probe_passed",
        lambda api_base_url, target_url: resumed.append({"api_base_url": api_base_url, "target_url": target_url})
        or {"ok": True},
    )

    summary = seed_collector.run_seed_collector_once(
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
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert summary["auth_probe"]["authenticated"] is True
    assert fetched_urls == [
        probe_url,
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
    ]
    assert resumed == [{"api_base_url": "http://collection-api.test/api", "target_url": probe_url}]


def test_run_seed_collector_once_keeps_manual_required_when_list_probe_still_challenges(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    probe_url = "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1"
    fetched_urls: list[str] = []
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {"target_url": probe_url},
            },
        },
    )

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
        fetched_urls.append(target_url)
        return "challenge", target_url, 200, "http_cookie_challenge"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(
        seed_collector,
        "_notify_auth_probe_passed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("challenge probe must not auto-resume")),
    )

    summary = seed_collector.run_seed_collector_once(
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
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["auth_probe"]["attempted"] is True
    assert summary["auth_probe"]["authenticated"] is False
    assert fetched_urls == [probe_url]
    assert repo.seed_queue_counts()["seed_scan_job_pending"] == 0


def test_seed_loop_uses_short_auth_probe_sleep_when_manual_required() -> None:
    config = seed_collector.SeedCollectorConfig(
        job_key="guangdong-guangzhou-nansha-50025969",
        province="广东省",
        city="广州市",
        district="南沙区",
        location_code="440115",
        category="50025969",
        sort_specs=seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低"),
        max_page=83,
        cdp_endpoint="http://127.0.0.1:9223",
        output_dir=Path("."),
        worker_id="seed-test",
        loop_interval_seconds=1800,
        auth_probe_interval_seconds=60,
    )

    assert (
        seed_collector._seed_loop_sleep_seconds(
            config,
            [
                {
                    "decision": "seed_collection_paused",
                    "reason": "captcha_solver_manual_required",
                    "auth_probe": {"attempted": True, "authenticated": False},
                }
            ],
        )
        == 60
    )


def test_seed_pause_state_ignores_background_solver_running_without_manual_required() -> None:
    pause_state = seed_collector._normalize_collection_pause_state(
        {
            "paused": True,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "force_unlock_flag_exists": False,
            },
        }
    )

    assert pause_state["paused"] is False
    assert pause_state["reason"] == "captcha_solver_running_ignored"


def test_run_seed_collector_once_ignores_detail_page_manual_pause(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/800691762980.htm?__captcha_solver_bg=1"
                },
            },
        },
    )

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
        fetched_urls.append(target_url)
        return "ok", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    summary = seed_collector.run_seed_collector_once(
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
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_page_collected"
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1"
    ]


def test_run_seed_collector_once_retries_initial_status_unavailable_before_claiming_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    pause_states = [
        {"paused": False, "reason": "status_unavailable", "error": "api starting"},
        {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    ]
    sleep_calls: list[float] = []

    def _pause_state(_api_base_url):
        return pause_states.pop(0)

    monkeypatch.setattr(seed_collector, "_collection_pause_state", _pause_state)
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("status retry should pause before fetching")),
    )

    summary = seed_collector.run_seed_collector_once(
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
            solver_enabled=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True
    assert sleep_calls == [1.0]
    assert repo.seed_queue_counts()["seed_scan_job_pending"] == 0


def test_config_from_env_reads_captcha_solver_enabled(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_CAPTCHA_SOLVER_ENABLED", "1")

    config, _loop = seed_collector.config_from_env_and_args([])

    assert config.solver_enabled is True


def test_config_from_env_reads_seed_api_base_url(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_API_BASE_URL", "http://collection-api:8001/api")

    config, _loop = seed_collector.config_from_env_and_args([])

    assert config.api_base_url == "http://collection-api:8001/api"


def test_config_from_env_reads_seed_failure_cooldown(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_SEED_FAILURE_COOLDOWN_THRESHOLD", "10")
    monkeypatch.setenv("FAPAI_SEED_FAILURE_COOLDOWN_SECONDS", "120")

    config, _loop = seed_collector.config_from_env_and_args([])

    assert config.failure_cooldown_threshold == 10
    assert config.failure_cooldown_seconds == 120


def test_config_from_env_reads_seed_jobs_json_as_multi_job_task_pool(monkeypatch) -> None:
    monkeypatch.setenv(
        "FAPAI_SEED_JOBS_JSON",
        """
        [
          {
            "job_key": "440115-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
            "max_page": 12,
            "sorts": [
              {"sort_key": "bid_desc", "st_param": "2", "sort_name": "出价次数由高到低", "sort_order": 0}
            ]
          },
          {
            "job_key": "440106-200782003",
            "province": "广东省",
            "city": "广州市",
            "district": "天河区",
            "location_code": "440106",
            "category": "200782003",
            "max_page": 8,
            "sorts": [
              {"sort_key": "end_time_soon", "st_param": "1", "sort_name": "结拍时间由近到远", "sort_order": 0}
            ]
          }
        ]
        """,
    )

    config, _loop = seed_collector.config_from_env_and_args([])

    assert [job.job_key for job in config.seed_jobs] == ["440115-50025969", "440106-200782003"]
    assert [job.location_code for job in config.seed_jobs] == ["440115", "440106"]
    assert [job.category for job in config.seed_jobs] == ["50025969", "200782003"]
    assert [job.max_page for job in config.seed_jobs] == [12, 8]
    assert [job.sort_specs[0].st_param for job in config.seed_jobs] == ["2", "1"]


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


def test_run_seed_collector_loop_ensures_jobs_but_exhausts_current_scope_before_next_job(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
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

    def _fetch_list_page(_http, *, cdp_endpoint: str, target_url: str, user_agent: str, solver_enabled: bool):
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


def test_run_seed_collector_loop_emits_compact_run_and_sleep_events(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_collected", "item_count": 2, "has_next": True, "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_scan_queue_empty", "counts": {"seed_item_pending_detail": 2}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            pages_per_run=2,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=events.append,
    )

    assert sleep_calls == [7]
    assert [event["event"] for event in events] == [
        "seed_collector_run",
        "seed_collector_sleep",
        "seed_collector_run",
    ]
    assert events[0]["run"] == 1
    assert events[0]["pages_attempted"] == 1
    assert events[0]["last_decision"] == "seed_scan_queue_empty"
    assert events[0]["last_item_count"] is None
    assert events[1] == {
        "event": "seed_collector_sleep",
        "run": 1,
        "sleep_seconds": 7,
        "counts": events[0]["counts"],
    }


def test_seed_run_progress_event_includes_operator_cycle_summary() -> None:
    event = seed_collector._seed_run_progress_event(
        7,
        [
            {
                "decision": "seed_page_collected",
                "item_count": 60,
                "upsert": {"seen": 60, "new_items": 30, "existing_items": 30, "new_occurrences": 60},
                "counts": {"seed_occurrence_total": 100},
            },
            {
                "decision": "seed_page_retryable_failure",
                "reason": "list_challenge_page",
                "counts": {"seed_occurrence_total": 100},
            },
            {
                "decision": "seed_scan_queue_empty",
                "counts": {"seed_occurrence_total": 100},
            },
        ],
    )

    assert event["cycle_summary"] == {
        "pages_attempted": 2,
        "pages_collected": 1,
        "retryable_failures": 1,
        "paused_count": 0,
        "queue_empty_count": 1,
        "items_seen": 60,
        "items_collected": 60,
        "new_items": 30,
        "existing_items": 30,
        "new_occurrences": 60,
        "decision_counts": {
            "seed_page_collected": 1,
            "seed_page_retryable_failure": 1,
            "seed_scan_queue_empty": 1,
        },
    }
    assert event["pages_attempted"] == 2
    assert event["new_occurrences"] == 60


def test_run_seed_collector_loop_writes_partial_cycle_summary_after_each_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    written: list[dict[str, Any]] = []
    run_results = iter(
        [
            {
                "decision": "seed_page_collected",
                "item_count": 2,
                "upsert": {"seen": 2, "new_items": 2, "existing_items": 0, "new_occurrences": 2},
                "counts": {"seed_occurrence_total": 2},
            },
            {
                "decision": "seed_page_retryable_failure",
                "reason": "list_challenge_page",
                "counts": {"seed_occurrence_total": 2},
            },
        ]
    )
    monkeypatch.setattr(seed_collector, "_write_runtime_summary", lambda _output_dir, summary: written.append(dict(summary)))
    monkeypatch.setattr(seed_collector, "_ensure_seed_scan_jobs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))

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
            pages_per_run=2,
        ),
        repository=WorkRepository(),  # type: ignore[arg-type]
        http_session=object(),
        browserless_seed_probe=object(),
    )

    partial_events = [summary for summary in written if summary.get("event") == "seed_collector_run_in_progress"]
    assert [event["cycle_summary"]["pages_attempted"] for event in partial_events] == [1, 2]
    assert partial_events[0]["cycle_summary"]["pages_collected"] == 1
    assert partial_events[1]["cycle_summary"]["retryable_failures"] == 1


def test_run_seed_collector_loop_uses_active_sleep_after_productive_run(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_collected", "item_count": 2, "has_next": True, "counts": {"seed_item_pending_detail": 2}},
            {"decision": "seed_page_collected", "item_count": 1, "has_next": True, "counts": {"seed_item_pending_detail": 3}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            active_loop_interval_seconds=0,
            max_runs=2,
            pages_per_run=1,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=events.append,
    )

    assert sleep_calls == [0]
    assert events[1] == {
        "event": "seed_collector_sleep",
        "run": 1,
        "sleep_seconds": 0,
        "counts": events[0]["counts"],
    }


def test_run_seed_collector_loop_keeps_idle_sleep_after_challenge_page(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[int] = []
    run_results = iter(
        [
            {"decision": "seed_page_retryable_failure", "reason": "list_challenge_page", "counts": {}},
            {"decision": "seed_page_collected", "item_count": 1, "has_next": True, "counts": {}},
        ]
    )

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", lambda *_args, **_kwargs: next(run_results))
    monkeypatch.setattr(seed_collector.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    seed_collector.run_seed_collector_loop(
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
            active_loop_interval_seconds=0,
            max_runs=2,
            pages_per_run=1,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=lambda _event: None,
    )

    assert sleep_calls == [7]


def test_run_seed_collector_loop_retries_after_runtime_context_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    contexts: list[str] = []

    def _runtime_context_factory() -> str:
        if not contexts:
            contexts.append("failed")
            raise RuntimeError("cdp unavailable")
        contexts.append("ok")
        return "http-ok"

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
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
            loop_interval_seconds=5,
            max_runs=2,
            pages_per_run=2,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert contexts == ["failed", "ok"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "seed_collector_runtime_refresh_failed",
        "seed_collector_sleep",
        "seed_collector_run",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "seed_runtime_refresh_failed"
    assert "cdp unavailable" in events[0]["error"]
    assert summary["runs"] == 2
    assert summary["last_decision"] == "seed_scan_queue_empty"


def test_run_seed_collector_loop_reuses_last_runtime_context_after_later_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    used_sessions: list[str] = []
    calls = {"count": 0}

    def _runtime_context_factory() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            return "http-1"
        raise RuntimeError("cdp refresh timed out")

    def _run_once(_config, *, repository, http_session, browserless_seed_probe, ensure_jobs=True):
        used_sessions.append(http_session)
        return {"decision": "seed_scan_queue_empty", "counts": repository.seed_queue_counts()}

    monkeypatch.setattr(seed_collector, "run_seed_collector_once", _run_once)
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
            loop_interval_seconds=5,
            max_runs=2,
            pages_per_run=2,
        ),
        repository=repo,
        browserless_seed_probe=_FakeProbe,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert used_sessions == ["http-1", "http-1"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "seed_collector_run",
        "seed_collector_sleep",
        "seed_collector_runtime_refresh_reused_last_context",
        "seed_collector_run",
    ]
    assert events[2]["run"] == 2
    assert "cdp refresh timed out" in events[2]["error"]
    assert summary["runs"] == 2
    assert summary["last_decision"] == "seed_scan_queue_empty"
