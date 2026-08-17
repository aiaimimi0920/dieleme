from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import browserless_seed_probe, live_batch_smoke, seed_collector, taobao_login_health


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


class _BlankPageProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(html: str, *, final_url: str) -> dict[str, Any]:
        return {
            "has_script": False,
            "item_count": None,
            "first_ids": [],
            "first_urls": [],
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
            "body_snippet": html[:80],
        }

    @staticmethod
    def extract_list_payload(_html: str) -> dict[str, Any] | None:
        return None

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {"source_page_url": source_page_url, "items": []}

class _FailureOnlyProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(_html: str, *, final_url: str) -> dict[str, Any]:
        return {
            "item_count": 2,
            "first_ids": ["3001", "3002"],
            "first_urls": [f"{final_url}#3001", f"{final_url}#3002"],
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
        }

    @staticmethod
    def extract_list_payload(_html: str) -> dict[str, Any] | None:
        return {
            "data": [
                {"id": "3001", "status": "failure", "bidCount": 0, "itemUrl": "//sf-item.taobao.com/sf_item/3001.htm"},
                {"id": "3002", "status": "failure", "bidCount": 0, "itemUrl": "//sf-item.taobao.com/sf_item/3002.htm"},
            ]
        }

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {
            "source_page_url": source_page_url,
            "items": [],
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


def test_parse_seed_job_specs_rejects_non_array_and_missing_location_code() -> None:
    fallback_sort_specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低")

    try:
        seed_collector.parse_seed_job_specs(
            {"location_code": "440115"},
            fallback_sort_specs=fallback_sort_specs,
            fallback_max_page=83,
        )
    except ValueError as exc:
        assert str(exc) == "seed jobs must be a JSON array"
    else:
        raise AssertionError("expected non-array seed jobs to raise ValueError")

    try:
        seed_collector.parse_seed_job_specs(
            [None, {"category": "50025969"}],
            fallback_sort_specs=fallback_sort_specs,
            fallback_max_page=83,
        )
    except ValueError as exc:
        assert str(exc) == "seed job at index 1 requires location_code"
    else:
        raise AssertionError("expected missing location_code to raise ValueError")


def test_should_archive_stale_seed_jobs_rejects_blank_or_duplicate_job_keys() -> None:
    sort_specs = seed_collector.parse_seed_sort_specs("bid_desc:2:出价次数由高到低")
    duplicate_job = seed_collector.SeedScanJobSpec(
        job_key="job-1",
        province="广东省",
        city="广州市",
        district="南沙区",
        location_code="440115",
        category="50025969",
        sort_specs=sort_specs,
        max_page=83,
    )
    blank_job = seed_collector.SeedScanJobSpec(
        job_key="",
        province="广东省",
        city="广州市",
        district="南沙区",
        location_code="440115",
        category="50025969",
        sort_specs=sort_specs,
        max_page=83,
    )

    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(),
            )
        )
        is False
    )
    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(duplicate_job, duplicate_job),
            )
        )
        is False
    )
    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(duplicate_job, blank_job),
            )
        )
        is False
    )
    assert (
        seed_collector._should_archive_stale_seed_jobs(
            seed_collector.SeedCollectorConfig(
                job_key="job-1",
                province="广东省",
                city="广州市",
                district="南沙区",
                location_code="440115",
                category="50025969",
                sort_specs=sort_specs,
                max_page=83,
                cdp_endpoint="http://127.0.0.1:9223",
                output_dir=Path("."),
                worker_id="seed-test",
                seed_jobs=(
                    duplicate_job,
                    seed_collector.SeedScanJobSpec(
                        job_key="job-2",
                        province="广东省",
                        city="广州市",
                        district="南沙区",
                        location_code="440115",
                        category="50025969",
                        sort_specs=sort_specs,
                        max_page=83,
                    ),
                ),
            )
        )
        is True
    )


def test_run_seed_collector_once_claims_one_page_and_populates_detail_queue(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    api_base_urls: list[str | None] = []

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
        api_base_urls.append(api_base_url)
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
            api_base_url="http://collection-api.test/api",
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
    assert api_base_urls == ["http://collection-api.test/api"]
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


def test_run_seed_collector_once_continues_to_next_page_when_raw_list_has_items_but_filtered_batch_is_empty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "seed-failure-only.sqlite3"
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
        return "failure-only", target_url, 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)

    first_repo = _make_repo_at(db_path)
    first_summary = seed_collector.run_seed_collector_once(
        config,
        repository=first_repo,
        http_session=object(),
        browserless_seed_probe=_FailureOnlyProbe,
    )

    restarted_repo = _make_repo_at(db_path)
    second_summary = seed_collector.run_seed_collector_once(
        config,
        repository=restarted_repo,
        http_session=object(),
        browserless_seed_probe=_FailureOnlyProbe,
    )

    assert first_summary["decision"] == "seed_page_collected"
    assert first_summary["item_count"] == 0
    assert first_summary["has_next"] is True
    assert first_summary["task"]["page"] == 1
    assert second_summary["task"]["page"] == 2
    assert fetched_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=2",
    ]


def test_run_seed_collector_once_marks_scan_page_retryable_on_challenge(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled, api_base_url=None: (
            "challenge",
            target_url,
            200,
            "browser_page",
        ),
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


def test_report_manual_seed_challenge_uses_manual_endpoint_without_sensitive_redirect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reports: list[dict[str, object]] = []

    def _report_captcha_via_api(
        api_base_url: str,
        cdp_endpoint: str,
        target_url: str,
        *,
        manual_only: bool = False,
    ) -> dict[str, object]:
        reports.append(
            {
                "api_base_url": api_base_url,
                "cdp_endpoint": cdp_endpoint,
                "target_url": target_url,
                "manual_only": manual_only,
            }
        )
        return {"status": "manual_required"}

    monkeypatch.setattr(taobao_login_health, "report_captcha_via_api", _report_captcha_via_api)
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
        manual_challenge_reporting=True,
        api_base_url="http://collection-api.test/api",
    )

    result = seed_collector._report_manual_seed_challenge(
        config,
        (
            "https://sf.taobao.com/list/50025969__2.htm?"
            "location_code=440115&page=1&x5secdata=sensitive&redirectURL=https%3A%2F%2Fevil.test"
        ),
    )

    assert result == {"status": "manual_required"}
    assert reports == [
        {
            "api_base_url": "http://collection-api.test/api",
            "cdp_endpoint": "http://127.0.0.1:9223",
            "target_url": (
                "https://sf.taobao.com/list/50025969__2.htm?"
                "location_code=440115&page=1&__captcha_solver_bg=1"
            ),
            "manual_only": True,
        }
    ]


def test_run_seed_collector_once_reports_challenge_and_observes_manual_pause(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    reported_targets: list[str] = []
    solver_flags: list[bool] = []
    pause_states = iter(
        [
            {"paused": False, "captcha_solver": {}},
            {
                "paused": True,
                "reason": "captcha_solver_manual_required",
                "captcha_solver": {"manual_required": True},
            },
        ]
    )
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _api: next(pause_states))
    monkeypatch.setattr(
        seed_collector,
        "_report_manual_seed_challenge",
        lambda _config, target_url: reported_targets.append(target_url) or {"status": "manual_required"},
    )

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ) -> tuple[str, str, int, str]:
        solver_flags.append(solver_enabled)
        return (
            "challenge",
            target_url + "/_____tmd_____/punish?x5secdata=secret",
            200,
            "http_cookie_challenge",
        )

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
            manual_challenge_reporting=True,
            api_base_url="http://collection-api.test/api",
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert "captcha_solver_report" not in summary
    assert reported_targets == []
    assert solver_flags == [True]


def test_run_seed_collector_once_marks_browser_payload_missing_page_retryable(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    class _BrowserShellProbe:
        DEFAULT_USER_AGENT = "fake-agent"

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, Any]:
            return {
                "has_script": False,
                "item_count": None,
                "first_ids": [],
                "first_urls": [],
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
                "body_snippet": final_url,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, Any] | None:
            return None

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
            return {"source_page_url": source_page_url, "items": []}

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled, api_base_url=None: (
            "<!doctype html><html><body>browser shell</body></html>",
            target_url,
            None,
            "browser_page_after_http_challenge",
        ),
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
        browserless_seed_probe=_BrowserShellProbe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "browser_list_payload_missing"
    assert summary["fetch"]["method"] == "browser_page_after_http_challenge"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1


def test_run_seed_collector_once_treats_punish_final_url_shell_as_challenge(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent, solver_enabled, api_base_url=None: (
            "<!doctype html><html><body>browser shell</body></html>",
            target_url + "/_____tmd_____/punish?x5secdata=abc",
            None,
            "browser_page_after_http_challenge",
        ),
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
        browserless_seed_probe=browserless_seed_probe,
    )

    assert summary["decision"] == "seed_page_retryable_failure"
    assert summary["reason"] == "list_challenge_page"


def test_run_seed_collector_once_pauses_and_requeues_when_cdp_endpoint_is_unreachable(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)

    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            live_batch_smoke.CdpEndpointUnavailableError(
                "http://127.0.0.1:9223",
                "open_list_page_target",
                TimeoutError("timed out"),
            )
        ),
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
            auth_probe_interval_seconds=10,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "cdp_unreachable"
    assert summary["auth_probe"]["attempted"] is True
    assert summary["auth_probe"]["authenticated"] is False
    assert summary["auth_probe"]["status"] == "cdp_unreachable"
    retry = repo.claim_seed_scan_page("seed-retry", lease_seconds=30)
    assert retry is not None
    assert retry["page"] == 1


def test_run_seed_collector_once_passes_solver_enabled_to_fetch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    solver_flags: list[bool] = []

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
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


def test_run_seed_collector_once_probes_default_list_when_manual_required_lacks_last_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    fetched_urls: list[str] = []
    solver_flags: list[bool] = []
    resumed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    )

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
        solver_flags.append(solver_enabled)
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
        "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1",
    ]
    assert solver_flags == [False, True]
    assert resumed == [
        {
            "api_base_url": "http://collection-api.test/api",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        }
    ]


def test_run_seed_collector_once_does_not_auto_resume_on_blank_auth_probe_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    probe_url = "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
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
        return "<html><head></head><body></body></html>", "about:blank", None, "browser_page_after_http_challenge"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(
        seed_collector,
        "_notify_auth_probe_passed",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("blank probe must not auto-resume")),
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
        browserless_seed_probe=_BlankPageProbe,
    )

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["auth_probe"]["attempted"] is True
    assert summary["auth_probe"]["authenticated"] is False
    assert summary["auth_probe"]["reason"] == "probe_not_authenticated"
    assert fetched_urls == [probe_url]

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


def test_run_seed_collector_once_does_not_probe_while_solver_is_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(
        seed_collector,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_running",
            "captcha_solver": {
                "running": True,
                "manual_required": False,
                "last_request": {"node_id": "pc2", "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"},
            },
        },
    )
    monkeypatch.setattr(
        seed_collector,
        "fetch_list_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("seed probe must wait for active solver")),
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
    assert summary["reason"] == "captcha_solver_running"
    assert "auth_probe" not in summary

def test_run_seed_collector_once_converts_list_challenge_into_manual_pause_when_status_flips(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    pause_states = iter(
        [
            {"paused": False, "reason": None, "captcha_solver": {}},
            {
                "paused": True,
                "reason": "captcha_solver_manual_required",
                "captcha_solver": {
                    "manual_required": True,
                    "last_request": {
                        "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&page=14&__captcha_solver_bg=1"
                    },
                },
            },
        ]
    )
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _api_base_url: next(pause_states))

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        return "challenge", target_url, 200, "http_cookie_challenge"

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

    assert summary["decision"] == "seed_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True


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


def test_seed_pause_state_pauses_during_same_node_solver(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    pause_state = seed_collector._normalize_collection_pause_state(
        {
            "paused": False,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "force_unlock_flag_exists": False,
                "last_request": {"node_id": "pc2"},
            },
        }
    )

    assert pause_state["paused"] is True
    assert pause_state["reason"] == "captcha_solver_running"


def test_seed_pause_state_ignores_solver_running_for_other_node(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc3")
    pause_state = seed_collector._normalize_collection_pause_state(
        {
            "paused": True,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "force_unlock_flag_exists": False,
                "last_request": {"node_id": "pc2"},
            },
        }
    )

    assert pause_state["paused"] is False
    assert pause_state["reason"] == "captcha_solver_running_other_node"


def test_seed_pause_state_force_unlock_keeps_collection_paused_even_for_other_node(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc3")
    pause_state = seed_collector._normalize_collection_pause_state(
        {
            "paused": True,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "force_unlock_flag_exists": True,
                "last_request": {"node_id": "pc2"},
            },
        }
    )

    assert pause_state["paused"] is True
    assert pause_state["reason"] == "collection_paused"


def test_seed_captcha_solver_targets_current_node_treats_blank_or_casefolded_node_ids_as_current(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "PC2")

    assert seed_collector._captcha_solver_targets_current_node(
        {
            "running": True,
            "last_request": {"node_id": "pc2"},
        }
    ) is True
    assert seed_collector._captcha_solver_targets_current_node(
        {
            "running": True,
            "last_request": {"node_id": ""},
        }
    ) is True


def test_pause_state_blocks_seed_stage_ignores_detail_page_manual_pause() -> None:
    assert seed_collector._pause_state_blocks_seed_stage({"paused": False}) is False
    assert (
        seed_collector._pause_state_blocks_seed_stage(
            {
                "paused": True,
                "captcha_solver": {
                    "manual_required": True,
                    "last_request": {
                        "target_url": "https://sf-item.taobao.com/sf_item/3001.htm?__captcha_solver_bg=1"
                    },
                },
            }
        )
        is False
    )
    assert (
        seed_collector._pause_state_blocks_seed_stage(
            {
                "paused": True,
                "captcha_solver": {
                    "manual_required": True,
                    "last_request": {
                        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
                    },
                },
            }
        )
        is True
    )
    assert seed_collector._pause_state_blocks_seed_stage({"paused": True}) is True


def test_collection_pause_state_reads_status_via_direct_internal_api(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")

    def _fake_fetch_json(url: str, *, timeout: float):
        captured["url"] = url
        captured["timeout"] = timeout
        return {
            "paused": True,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "force_unlock_flag_exists": False,
                "last_request": {"node_id": "pc2"},
            },
        }

    monkeypatch.setattr(seed_collector, "fetch_json", _fake_fetch_json)

    pause_state = seed_collector._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state["paused"] is True
    assert pause_state["reason"] == "captcha_solver_running"
    assert captured == {
        "url": "http://192.168.15.200:8001/api/status",
        "timeout": 5,
    }


def test_browser_page_payload_missing_without_challenge_requires_browser_method_and_missing_metadata() -> None:
    assert (
        seed_collector._browser_page_payload_missing_without_challenge(
            "http_cookie",
            {"has_script": False, "item_count": None},
        )
        is False
    )
    assert (
        seed_collector._browser_page_payload_missing_without_challenge(
            "browser_page_after_http_challenge",
            [],
        )
        is True
    )
    assert (
        seed_collector._browser_page_payload_missing_without_challenge(
            "browser_page_after_http_challenge",
            {"has_script": False, "item_count": None},
        )
        is True
    )
    assert (
        seed_collector._browser_page_payload_missing_without_challenge(
            "browser_page_after_http_challenge",
            {"has_script": True, "item_count": None},
        )
        is False
    )
    assert (
        seed_collector._browser_page_payload_missing_without_challenge(
            "browser_page_after_http_challenge",
            {"has_script": False, "item_count": 0},
        )
        is False
    )


def test_extract_seed_items_normalizes_summary_and_filters_non_dict_items() -> None:
    class _MixedProbe:
        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> object:
            return "not-a-dict"

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object] | None:
            return {"data": [{"id": "3001"}]}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "3001"}, None, "skip-me", {"id": "3002"}],
            }

    items, summary, has_challenge = seed_collector._extract_seed_items(
        _MixedProbe,
        "<html>ok</html>",
        final_url="https://sf.taobao.com/list/page=1",
    )

    assert items == [{"id": "3001"}, {"id": "3002"}]
    assert summary == {}
    assert has_challenge is False


def test_seed_page_has_next_respects_max_page_and_raw_item_count() -> None:
    assert (
        seed_collector._seed_page_has_next(
            task_page=3,
            task_max_page=3,
            list_summary={"item_count": 2},
            filtered_items=[{"id": "3001"}],
        )
        is False
    )
    assert (
        seed_collector._seed_page_has_next(
            task_page=1,
            task_max_page=3,
            list_summary={"item_count": "0"},
            filtered_items=[{"id": "3001"}],
        )
        is False
    )
    assert (
        seed_collector._seed_page_has_next(
            task_page=1,
            task_max_page=3,
            list_summary={"item_count": "2"},
            filtered_items=[],
        )
        is True
    )
    assert (
        seed_collector._seed_page_has_next(
            task_page=1,
            task_max_page=3,
            list_summary={"item_count": None},
            filtered_items=[],
        )
        is False
    )
    assert (
        seed_collector._seed_page_has_next(
            task_page=1,
            task_max_page=3,
            list_summary={"item_count": "unknown"},
            filtered_items=[{"id": "3001"}],
        )
        is True
    )


def test_pause_state_seed_probe_target_url_normalizes_punish_list_url() -> None:
    pause_state = {
        "paused": True,
        "reason": "captcha_solver_manual_required",
        "captcha_solver": {
            "manual_required": True,
            "last_request": {
                "target_url": (
                    "https://sf.taobao.com//list/200782003__2.htm/_____tmd_____/punish"
                    "?x5secdata=demo&x5step=1&__captcha_solver_bg=1"
                )
            },
        },
    }

    target_url = seed_collector._pause_state_seed_probe_target_url(pause_state)

    assert target_url == "https://sf.taobao.com/list/200782003__2.htm?__captcha_solver_bg=1"


def test_pause_state_seed_probe_target_url_uses_default_for_login_redirect_url() -> None:
    pause_state = {
        "paused": True,
        "reason": "captcha_solver_manual_required",
        "captcha_solver": {
            "manual_required": True,
            "last_request": {
                "target_url": (
                    "https://login.taobao.com/havanaone/login/login.htm?"
                    "redirectURL=https%3A%2F%2Fsf.taobao.com%2Flist%2F50025969__2.htm"
                    "%3Flocation_code%3D532301%26st_param%3D2%26page%3D19"
                    "&__captcha_solver_bg=1"
                )
            },
        },
    }

    target_url = seed_collector._pause_state_seed_probe_target_url(pause_state, allow_default=True)

    assert target_url == "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"


def test_pause_state_seed_probe_target_url_filters_punish_query_to_whitelist() -> None:
    pause_state = {
        "paused": True,
        "reason": "captcha_solver_manual_required",
        "captcha_solver": {
            "manual_required": True,
            "last_request": {
                "target_url": (
                    "https://sf.taobao.com/list/50025969__2.htm/_____tmd_____/punish?"
                    "location_code=440115&st_param=2&auction_start_seg=-1&page=14&keep=visible&x5secdata=demo"
                )
            },
        },
    }

    target_url = seed_collector._pause_state_seed_probe_target_url(pause_state)

    assert target_url == (
        "https://sf.taobao.com/list/50025969__2.htm?"
        "location_code=440115&st_param=2&auction_start_seg=-1&page=14&__captcha_solver_bg=1"
    )

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


def test_config_from_env_reads_manual_challenge_reporting(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_MANUAL_CHALLENGE_REPORTING", "1")

    config, _loop = seed_collector.config_from_env_and_args([])

    assert config.manual_challenge_reporting is True


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
    assert event["last_reason"] is None

    retry_event = seed_collector._seed_run_progress_event(
        8,
        [{"decision": "seed_page_retryable_failure", "reason": "list_challenge_page", "counts": {"seed_occurrence_total": 100}}],
    )

    assert retry_event["last_reason"] == "list_challenge_page"


def test_seed_run_progress_event_surfaces_last_auth_probe_for_operator_visibility() -> None:
    event = seed_collector._seed_run_progress_event(
        9,
        [
            {
                "decision": "seed_collection_paused",
                "reason": "captcha_solver_manual_required",
                "auth_probe": {
                    "attempted": True,
                    "authenticated": False,
                    "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
                },
                "counts": {"seed_occurrence_total": 100},
            }
        ],
    )

    assert event["last_auth_probe"] == {
        "attempted": True,
        "authenticated": False,
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    assert event["auth_probe_attempted"] is True

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


def test_run_seed_collector_loop_uses_auth_probe_sleep_after_challenge_page(tmp_path: Path, monkeypatch) -> None:
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
            auth_probe_interval_seconds=3,
            max_runs=2,
            pages_per_run=1,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browserless_seed_probe=_FakeProbe,
        progress_emit_func=lambda _event: None,
    )

    assert sleep_calls == [3]


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
