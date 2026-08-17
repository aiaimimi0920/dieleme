from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from src.storage.models import FapaiSeedItem
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools import detail_worker, live_batch_smoke, seed_collector, taobao_login_health


def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'detail-worker.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def _seed_one_item(repo: PropertyRepository) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
        max_page=83,
    )
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": "3001",
                "title": "南沙详情 A",
                "url": "https://sf-item.taobao.com/sf_item/3001.htm",
                "source_page_url": task["url"],
            }
        ],
    )


def _seed_items(repo: PropertyRepository, item_ids: list[str]) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
        max_page=83,
    )
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": item_id,
                "title": f"南沙详情 {item_id}",
                "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
                "source_page_url": task["url"],
            }
            for item_id in item_ids
        ],
    )


def test_run_detail_worker_once_claims_seed_and_marks_completed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[dict[str, Any]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(seed)
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "南沙稳定片区",
            "community_stable_key": "collector::广州市::南沙区::南沙稳定片区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": seed["id"]}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_completed"
    assert summary["item_id"] == "3001"
    assert [row["id"] for row in processed] == ["3001"]
    assert repo.seed_queue_counts()["seed_item_detail_completed"] == 1
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::南沙稳定片区"


def test_run_detail_worker_once_raw_only_marks_raw_captured_without_final_json(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps({"item_id": seed["id"], "detail_capture_mode": "raw"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            raw_only=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_item_raw_captured"
    assert summary["item_id"] == "3001"
    assert counts["seed_item_raw_detail_captured"] == 1
    assert counts["seed_item_detail_completed"] == 0
    assert repo.claim_seed_detail_item("detail-test", lease_seconds=30) is None


def test_write_durable_detail_archive_copies_to_dated_partition(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive-root"
    detail_html_path = tmp_path / "detail.html"
    detail_html_path.write_text("<html>raw archive</html>", encoding="utf-8")

    archived_path = detail_worker._write_durable_detail_archive(
        archive_root=archive_root,
        detail_html_path=detail_html_path,
        item_id="3001",
        captured_at=datetime.datetime(2026, 8, 13, 14, 30, 0),
    )

    archived_file = Path(archived_path)
    assert archived_file == archive_root / "html_archive" / "2026" / "2026-08-13" / "item-3001.html"
    assert archived_file.read_text(encoding="utf-8") == "<html>raw archive</html>"


def test_archive_raw_detail_if_configured_swallows_archive_errors(tmp_path: Path, monkeypatch) -> None:
    detail_html_path = tmp_path / "detail.html"
    detail_html_path.write_text("<html>raw archive</html>", encoding="utf-8")

    monkeypatch.setattr(
        detail_worker,
        "_write_durable_detail_archive",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    archived_path = detail_worker._archive_raw_detail_if_configured(
        config=detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            detail_archive_root=tmp_path / "archive-root",
        ),
        detail_html_path=detail_html_path,
        item_id="3001",
    )

    assert archived_path == ""


def test_assert_raw_detail_artifact_is_not_challenge_raises_when_html_is_missing(tmp_path: Path) -> None:
    selected_json_path = tmp_path / "selected.json"
    selected_json_path.write_text("{}", encoding="utf-8")

    try:
        detail_worker._assert_raw_detail_artifact_is_not_challenge(
            detail_html_path=tmp_path / "missing-detail.html",
            selected_json_path=selected_json_path,
        )
    except RuntimeError as exc:
        assert "raw detail artifact missing or unreadable" in str(exc)
    else:
        raise AssertionError("expected missing raw detail artifact to raise RuntimeError")


def test_stage_raw_detail_artifacts_ignores_non_mapping_and_missing_sources(tmp_path: Path) -> None:
    staged = detail_worker._stage_raw_detail_artifacts_for_analysis(
        {
            "id": "3001",
            "_raw_detail_artifacts": {
                "detail_html_path": str(tmp_path / "missing-detail.html"),
                "description_json_path": "",
                "selected_json_path": None,
            },
        },
        output_dir=tmp_path,
        item_id="3001",
    )

    item_dir = tmp_path / "3001"
    assert staged == {}
    assert (item_dir / "seed.json").exists()
    assert not (item_dir / "detail.html").exists()
    assert not (item_dir / "description-data.json").exists()
    assert not (item_dir / "selected.json").exists()


def test_archive_raw_detail_if_configured_returns_empty_when_disabled_or_source_missing(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    detail_html_path = tmp_path / "missing-detail.html"

    monkeypatch.setattr(
        detail_worker,
        "_write_durable_detail_archive",
        lambda **kwargs: calls.append(kwargs) or "should-not-be-used",
    )

    disabled_archive_path = detail_worker._archive_raw_detail_if_configured(
        config=detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            detail_archive_root=None,
        ),
        detail_html_path=detail_html_path,
        item_id="3001",
    )
    missing_source_archive_path = detail_worker._archive_raw_detail_if_configured(
        config=detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            detail_archive_root=tmp_path / "archive-root",
        ),
        detail_html_path=detail_html_path,
        item_id="3001",
    )

    assert disabled_archive_path == ""
    assert missing_source_archive_path == ""
    assert calls == []


def test_seed_collector_metadata_reaches_detail_worker_and_live_target_uses_source_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    collected_urls: list[str] = []
    captured: list[dict[str, object]] = []

    class _SingleItemProbe:
        DEFAULT_USER_AGENT = "fake-agent"

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, Any]:
            return {
                "item_count": 1,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
                "body_snippet": final_url,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, Any] | None:
            return {"data": [{"id": "4001"}]}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {
                        "id": "4001",
                        "title": "跨模块详情元数据测试",
                        "url": "https://sf-item.taobao.com/sf_item/4001.htm",
                    }
                ],
            }

    def _fetch_list_page(
        _http,
        *,
        cdp_endpoint: str,
        target_url: str,
        user_agent: str,
        solver_enabled: bool,
        api_base_url: str | None = None,
    ):
        collected_urls.append(target_url)
        return "ok", "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&page=1&from=browser", 200, "http_cookie"

    monkeypatch.setattr(seed_collector, "fetch_list_page", _fetch_list_page)
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _endpoint: "collector-ua")

    seed_summary = seed_collector.run_seed_collector_once(
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
        browserless_seed_probe=_SingleItemProbe,
    )

    def _process_item(_http, seed, _browser_pages, *, config):
        captured.append(
            {
                "seed": dict(seed),
                "target_url": config.target_url,
            }
        )
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "跨模块小区",
            "community_stable_key": "collector::广州市::南沙区::跨模块小区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps({"item_id": seed["id"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    detail_summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert seed_summary["decision"] == "seed_page_collected"
    assert collected_urls == [
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&auction_start_seg=-1&page=1"
    ]
    assert detail_summary["decision"] == "detail_item_completed"
    assert len(captured) == 1
    seed_payload = captured[0]["seed"]
    assert seed_payload["source_page_url"] == (
        "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&st_param=2&page=1&from=browser"
    )
    assert seed_payload["list_page"] == 1
    assert seed_payload["list_sort_key"] == "bid_desc"
    assert seed_payload["list_st_param"] == "2"
    assert captured[0]["target_url"] == seed_payload["source_page_url"]


def test_run_detail_worker_once_raw_only_rejects_challenge_artifact(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    solver_reports: list[tuple[str, str, str]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text(
            "<html><title>安全验证</title><body>验证码 x5secdata</body></html>",
            encoding="utf-8",
        )
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps(
                {
                    "item_id": seed["id"],
                    "detail_capture_mode": "raw",
                    "fetch": {
                        "detail_final_url": "https://sf-item.taobao.com/sf_item/3001.htm/_____tmd_____/punish?x5secdata=abc",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda api_base_url, cdp_endpoint, target_url: solver_reports.append(
            (api_base_url, cdp_endpoint, target_url)
        )
        or {"status": "queued"},
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            raw_only=True,
            solver_enabled=True,
            api_base_url="http://collector.local/api",
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    assert summary["captcha_solver_report"] == {"status": "queued"}
    assert solver_reports == [
        ("http://collector.local/api", "http://127.0.0.1:9223", "https://sf-item.taobao.com/sf_item/3001.htm")
    ]
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_pending_detail"] == 1
def test_run_detail_worker_once_raw_only_rejects_login_artifact(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    solver_reports: list[tuple[str, str, str]] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text(
            "<html><title>登录</title><body>扫码登录 login.taobao.com</body></html>",
            encoding="utf-8",
        )
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps(
                {
                    "item_id": seed["id"],
                    "detail_capture_mode": "raw",
                    "fetch": {
                        "detail_final_url": "https://login.taobao.com/havanaone/login/login.htm?redirectURL=https%3A%2F%2Fsf-item.taobao.com%2Fsf_item%2F3001.htm",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda api_base_url, cdp_endpoint, target_url: solver_reports.append(
            (api_base_url, cdp_endpoint, target_url)
        )
        or {"status": "queued"},
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            raw_only=True,
            solver_enabled=True,
            api_base_url="http://collector.local/api",
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    assert summary["captcha_solver_report"] == {"status": "queued"}
    assert solver_reports == [
        ("http://collector.local/api", "http://127.0.0.1:9223", "https://sf-item.taobao.com/sf_item/3001.htm")
    ]
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_pending_detail"] == 1
def test_run_detail_worker_once_passes_failure_cooldown_to_repository(tmp_path: Path) -> None:
    class SpyRepository:
        def __init__(self) -> None:
            self.claim_kwargs: dict[str, Any] | None = None

        def claim_seed_detail_item(self, _worker_id: str, **kwargs: Any):
            self.claim_kwargs = dict(kwargs)
            return None

        def seed_queue_counts(self) -> dict[str, int]:
            return {}

    repository = SpyRepository()

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            failure_cooldown_seconds=1800,
        ),
        repository=repository,  # type: ignore[arg-type]
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert summary == {"decision": "detail_queue_empty"}
    assert repository.claim_kwargs is not None
    assert repository.claim_kwargs["failure_cooldown_seconds"] == 1800


def test_detail_worker_config_reads_failure_cooldown_env(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_DETAIL_FAILURE_COOLDOWN_SECONDS", "1800")

    config, _loop = detail_worker.config_from_env_and_args([])

    assert config.failure_cooldown_seconds == 1800


def test_detail_worker_config_reads_per_attempt_delay_env(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_DETAIL_SUCCESS_DELAY_SECONDS", "0.25")
    monkeypatch.setenv("FAPAI_DETAIL_FAILURE_DELAY_SECONDS", "1.75")

    config, _loop = detail_worker.config_from_env_and_args([])

    assert config.success_delay_seconds == 0.25
    assert config.failure_delay_seconds == 1.75


def test_detail_worker_report_keeps_real_taobao_on_automatic_solver_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        taobao_login_health,
        "report_captcha_via_api",
        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs) or {"status": "manual_required"},
    )

    result = detail_worker._report_captcha_solver(
        "http://collection-api.test/api",
        "http://127.0.0.1:9225",
        "https://sf-item.taobao.com/sf_item/3001.htm",
    )

    assert result == {"status": "manual_required"}
    assert captured["kwargs"] == {}


def test_detail_worker_config_reads_llm_preflight_retry_env(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_LLM_PREFLIGHT_ATTEMPTS", "4")
    monkeypatch.setenv("FAPAI_LLM_PREFLIGHT_RETRY_DELAY_SECONDS", "1.5")

    config, _loop = detail_worker.config_from_env_and_args([])

    assert config.llm_preflight_attempts == 4
    assert config.llm_preflight_retry_delay_seconds == 1.5


def test_run_detail_analysis_once_claims_raw_item_and_marks_completed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    claimed = repo.claim_seed_detail_item("raw-worker", lease_seconds=30)
    assert claimed is not None
    item_dir = tmp_path / "3001"
    item_dir.mkdir()
    (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
    (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text(
        json.dumps({"item_id": "3001", "detail_capture_mode": "raw"}, ensure_ascii=False),
        encoding="utf-8",
    )
    repo.mark_seed_raw_detail_captured(
        "3001",
        detail_html_path=str(item_dir / "detail.html"),
        description_json_path=str(item_dir / "description-data.json"),
        selected_json_path=str(item_dir / "selected.json"),
    )

    def _analyze_raw_item(item_id: str, *, output_dir: Path, do_risk: bool):
        assert item_id == "3001"
        assert output_dir == tmp_path
        assert do_risk is False
        final = {
            "id": item_id,
            "title": "南沙详情 A",
            "source_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "community_name": "南沙分析小区",
            "community_stable_key": "collector::广州市::南沙区::南沙分析小区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": item_id}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": item_id, "final_core": {"title": "南沙详情 A"}}

    summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-test",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_raw_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_analysis_completed"
    assert summary["item_id"] == "3001"
    assert counts["seed_item_detail_completed"] == 1
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_analysis_in_progress"] == 0
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::南沙分析小区"


def test_run_detail_analysis_once_releases_claim_without_consuming_retry_budget_when_llm_backend_unavailable(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    claimed = repo.claim_seed_detail_item("raw-worker", lease_seconds=30)
    assert claimed is not None
    item_dir = tmp_path / "3001"
    item_dir.mkdir()
    (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
    (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text(
        json.dumps({"item_id": "3001", "detail_capture_mode": "raw"}, ensure_ascii=False),
        encoding="utf-8",
    )
    repo.mark_seed_raw_detail_captured(
        "3001",
        detail_html_path=str(item_dir / "detail.html"),
        description_json_path=str(item_dir / "description-data.json"),
        selected_json_path=str(item_dir / "selected.json"),
    )

    def _analyze_raw_item(_item_id: str, *, output_dir: Path, do_risk: bool):
        assert output_dir == tmp_path
        assert do_risk is False
        raise RuntimeError("LLM backend unavailable: AppIdNoAuthError")

    summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-test",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_raw_item,
    )

    counts = repo.seed_queue_counts()
    assert summary["decision"] == "detail_analysis_backend_unavailable"
    assert summary["item_id"] == "3001"
    assert counts["seed_item_raw_detail_captured"] == 1
    assert counts["seed_item_analysis_in_progress"] == 0
    assert counts["seed_item_analysis_failed"] == 0
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "raw_detail_captured"
        assert row.detail_leased_by is None
        payload = dict(row.source_payload or {})
        assert payload.get("_analysis_attempt_count") in (0, None)
        assert "LLM backend unavailable" in str(row.detail_last_error or "")


def test_build_runtime_context_tolerates_open_browser_page_cache_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(detail_worker, "export_cookies", lambda _endpoint: [{"name": "cookie2", "value": "abc"}])
    monkeypatch.setattr(detail_worker, "build_http", lambda _cookies: "http-session")
    monkeypatch.setattr(detail_worker, "load_open_browser_pages", lambda _endpoint: {})

    http_session, browser_pages = detail_worker._build_runtime_context(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        )
    )

    assert http_session == "http-session"
    assert browser_pages == {}


def test_build_runtime_context_skips_open_browser_page_cache_when_disabled(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES", "0")
    monkeypatch.setattr(detail_worker, "export_cookies", lambda _endpoint: [{"name": "cookie2", "value": "abc"}])
    monkeypatch.setattr(detail_worker, "build_http", lambda _cookies: "http-session")

    def _fail_load_open_browser_pages(_endpoint):
        raise AssertionError("open browser page cache should not be loaded")

    monkeypatch.setattr(detail_worker, "load_open_browser_pages", _fail_load_open_browser_pages)

    http_session, browser_pages = detail_worker._build_runtime_context(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:1",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        )
    )

    assert http_session == "http-session"
    assert browser_pages == {}


def test_run_detail_worker_once_marks_retryable_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, seed, _browser_pages, *, config):
        raise RuntimeError("detail timeout")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["item_id"] == "3001"
    assert "detail timeout" in summary["error"]
    retry = repo.claim_seed_detail_item("detail-retry", lease_seconds=30)
    assert retry is not None
    assert retry["id"] == "3001"


def test_run_detail_worker_once_does_not_consume_retry_budget_for_transient_dns_failure(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError(
            "ConnectionError(MaxRetryError('HTTPSConnectionPool(host=\\'sf-item.taobao.com\\', port=443): "
            "Max retries exceeded (Caused by NameResolutionError(\"Failed to resolve "
            "\\'sf-item.taobao.com\\' ([Errno -3] Temporary failure in name resolution)\"))'))"
        )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0


def test_collection_pause_state_reads_status_via_direct_internal_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_fetch_json(url: str, *, timeout: float):
        captured["url"] = url
        captured["timeout"] = timeout
        return {"paused": True, "captcha_solver": {"manual_required": True}}

    monkeypatch.setattr(detail_worker, "fetch_json", _fake_fetch_json)

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state == {
        "paused": True,
        "reason": "captcha_solver_manual_required",
        "captcha_solver": {"manual_required": True},
    }
    assert captured == {
        "url": "http://192.168.15.200:8001/api/status",
        "timeout": 5,
    }


def test_collection_pause_state_returns_status_unavailable_for_non_object_payload(monkeypatch) -> None:
    monkeypatch.setattr(detail_worker, "fetch_json", lambda _url, *, timeout: ["paused"])

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state == {
        "paused": False,
        "reason": "status_unavailable",
        "error": "non_object_status",
    }


def test_detail_pause_state_pauses_during_same_node_solver(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc2")
    monkeypatch.setattr(
        detail_worker,
        "fetch_json",
        lambda _url, *, timeout: {
            "paused": False,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "last_request": {"node_id": "pc2"},
            },
        },
    )

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state["paused"] is True
    assert pause_state["reason"] == "captcha_solver_running"


def test_detail_pause_state_ignores_solver_running_for_other_node(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_NODE_ID", "pc3")
    monkeypatch.setattr(
        detail_worker,
        "fetch_json",
        lambda _url, *, timeout: {
            "paused": True,
            "captcha_solver": {
                "running": True,
                "paused": True,
                "manual_required": False,
                "last_request": {"node_id": "pc2"},
            },
        },
    )

    pause_state = detail_worker._collection_pause_state("http://192.168.15.200:8001/api")

    assert pause_state["paused"] is False
    assert pause_state["reason"] == "captcha_solver_running_other_node"


def test_run_detail_worker_once_skips_claiming_items_when_collection_api_reports_manual_required(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[str] = []

    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {},
    )

    assert summary["decision"] == "detail_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1


def test_run_detail_worker_once_ignores_manual_required_when_target_detail_page_is_already_open(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[str] = []

    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test&__captcha_solver_bg=1",
                },
            },
        },
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={
            "3001": (
                "<html><body><h1>竞买公告</h1><div>标的物介绍</div></body></html>",
                "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test",
            )
        },
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {"item_id": "3001", "final_core": {}},
    )

    assert summary["decision"] == "detail_item_completed"
    assert summary["item_id"] == "3001"
    assert processed == ["called"]


def test_run_detail_worker_once_keeps_manual_required_when_open_detail_page_is_still_challenge(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    processed: list[str] = []

    monkeypatch.setattr(
        detail_worker,
        "_collection_pause_state",
        lambda _api_base_url: {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {
                "manual_required": True,
                "last_request": {
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test&__captcha_solver_bg=1",
                },
            },
        },
    )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={
            "3001": (
                "<script>var url='https://sf-item.taobao.com//sf_item/3001.htm/_____tmd_____/punish?x5secdata=abc';</script>",
                "https://sf-item.taobao.com/sf_item/3001.htm?track_id=test",
            )
        },
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {"item_id": "3001", "final_core": {}},
    )

    assert summary["decision"] == "detail_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert processed == []


def test_run_detail_worker_once_retries_initial_status_unavailable_before_claiming_item(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    pause_states = [
        {"paused": False, "reason": "status_unavailable", "error": "api starting"},
        {
            "paused": True,
            "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True},
        },
    ]
    sleep_calls: list[float] = []
    processed: list[str] = []

    monkeypatch.setattr(detail_worker, "_collection_pause_state", lambda _api_base_url: pause_states.pop(0))
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: processed.append("called") or {},
    )

    assert summary["decision"] == "detail_collection_paused"
    assert summary["reason"] == "captcha_solver_manual_required"
    assert summary["captcha_solver"]["manual_required"] is True
    assert sleep_calls == [1.0]
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1


def test_run_detail_worker_once_reports_solver_when_detail_challenge_appears(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    reports: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda api_base_url, cdp_endpoint, target_url: (
            reports.append((api_base_url, cdp_endpoint, target_url)) or {"status": "solving"}
        ),
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["captcha_solver_report"] == {"status": "solving"}
    assert reports == [
        (
            "http://collection-api.test/api",
            "http://127.0.0.1:9223",
            "https://sf-item.taobao.com/sf_item/3001.htm",
        )
    ]


def test_run_detail_worker_once_prefers_enabled_solver_over_manual_reporting(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)
    reports: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *args, **kwargs: reports.append((args, kwargs)) or {"status": "manual_required"},
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9225",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
            manual_challenge_reporting=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["reason"] == "detail_challenge_page"
    assert summary["captcha_solver_report"] == {"status": "manual_required"}
    assert reports == [
        (
            (
                "http://collection-api.test/api",
                "http://127.0.0.1:9225",
                "https://sf-item.taobao.com/sf_item/3001.htm",
            ),
            {},
        )
    ]


def test_run_detail_worker_once_records_report_failure_when_captcha_report_raises(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("captcha report offline")),
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["reason"] == "detail_challenge_page"
    assert summary["captcha_solver_report"]["status"] == "report_failed"
    assert "captcha report offline" in str(summary["captcha_solver_report"]["error"])


def test_run_detail_worker_once_does_not_report_when_solver_and_manual_reporting_are_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("solver reporting should be disabled")),
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=False,
            manual_challenge_reporting=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert "captcha_solver_report" not in summary


def test_llm_preflight_network_unavailable_is_treated_as_unavailable() -> None:
    assert detail_worker._llm_preflight_is_unavailable(
        {"enabled": True, "status_code": 0, "error_type": "ConnectTimeout"}
    ) is True


def test_llm_preflight_retries_transient_chat_failure_and_recovers(tmp_path: Path, monkeypatch) -> None:
    responses = [
        {"enabled": True, "status_code": 200, "chat_status_code": 503},
        {"enabled": True, "status_code": 200, "chat_status_code": 200},
    ]
    calls: list[dict[str, object]] = []
    sleep_calls: list[float] = []

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        calls.append({"timeout": timeout, "check_chat": check_chat})
        return responses.pop(0)

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", sleep_calls.append)

    result = detail_worker._run_llm_preflight(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
            llm_preflight_attempts=3,
            llm_preflight_retry_delay_seconds=1.5,
            analysis_only=True,
        )
    )

    assert result is not None
    assert result["chat_status_code"] == 200
    assert result["attempt"] == 2
    assert result["max_attempts"] == 3
    assert calls == [
        {"timeout": 2.5, "check_chat": True},
        {"timeout": 2.5, "check_chat": True},
    ]
    assert sleep_calls == [1.5]


def test_run_detail_worker_once_preserves_retry_budget_when_detail_challenge_appears(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    monkeypatch.setattr(
        detail_worker,
        "_report_captcha_solver",
        lambda *_args, **_kwargs: {"status": "already_running"},
    )

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise RuntimeError("browser detail request returned anti-bot challenge")

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            api_base_url="http://collection-api.test/api",
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_challenge_page"
    assert summary["retry_budget_preserved"] is True
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0


def test_run_detail_worker_once_preserves_retry_budget_when_detail_cdp_endpoint_is_unreachable(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    def _process_item(_http, _seed, _browser_pages, *, config):
        raise live_batch_smoke.CdpEndpointUnavailableError(
            "http://127.0.0.1:9223",
            "connect_over_cdp",
            TimeoutError("timed out"),
        )

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_item_retryable_failure"
    assert summary["reason"] == "detail_cdp_unreachable"
    assert summary["retry_budget_preserved"] is True
    assert summary["cdp_health"]["status"] == "cdp_unreachable"
    with repo.session_factory() as session:
        row = session.get(FapaiSeedItem, "3001")
        assert row is not None
        assert row.status == "pending_detail"
        assert row.detail_attempt_count == 0


def test_run_detail_worker_batch_does_not_retry_same_failed_item_in_same_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001", "3002"])
    processed: list[str] = []
    sleep_calls: list[float] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        if seed["id"] == "3001":
            raise RuntimeError("llm backend 503")
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        final = {
            "id": seed["id"],
            "title": seed["title"],
            "url": seed["url"],
            "source_url": seed["url"],
            "community_name": "南沙稳定片区",
            "community_stable_key": f"collector::广州市::南沙区::{seed['id']}",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": seed["id"]}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": seed["id"], "final_core": {"source_url": seed["url"], "title": seed["title"]}}

    monkeypatch.setattr(detail_worker.time, "sleep", sleep_calls.append)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=2,
            worker_id="detail-test",
            do_risk=False,
            success_delay_seconds=9.0,
            failure_delay_seconds=1.25,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert processed == ["3001", "3002"]
    assert summary["attempts"] == 2
    assert summary["completed"] == 1
    assert [result["item_id"] for result in summary["results"]] == ["3001", "3002"]
    assert sleep_calls == [1.25]


def test_run_detail_worker_batch_has_no_default_delay_between_successful_items(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[float] = []
    results = iter(
        [
            {"decision": "detail_item_raw_captured", "item_id": "3001"},
            {"decision": "detail_item_raw_captured", "item_id": "3002"},
        ]
    )

    monkeypatch.setattr(detail_worker, "run_detail_worker_once", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(detail_worker.time, "sleep", sleep_calls.append)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=2,
            max_attempts=2,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
    )

    assert summary["completed"] == 2
    assert sleep_calls == []


def test_run_detail_worker_batch_stops_current_cycle_after_solver_enabled_challenge(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001", "3002"])
    calls: list[int] = []

    def _run_once(_config, **_kwargs):
        calls.append(len(calls) + 1)
        return {
            "decision": "detail_item_retryable_failure",
            "reason": "detail_challenge_page",
            "item_id": "3001",
            "counts": repo.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_once", _run_once)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert calls == [1]
    assert summary["attempts"] == 1
    assert summary["completed"] == 0
    assert summary["results"][0]["reason"] == "detail_challenge_page"


def test_run_detail_worker_batch_continues_when_global_solver_is_already_busy(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001", "3002"])
    calls: list[int] = []

    results = iter(
        [
            {
                "decision": "detail_item_retryable_failure",
                "reason": "detail_challenge_page",
                "item_id": "3001",
                "captcha_solver_report": {"status": "already_running"},
                "counts": repo.seed_queue_counts(),
            },
            {
                "decision": "detail_item_completed",
                "item_id": "3002",
                "counts": repo.seed_queue_counts(),
            },
        ]
    )

    def _run_once(_config, **_kwargs):
        calls.append(len(calls) + 1)
        return next(results)

    monkeypatch.setattr(detail_worker, "run_detail_worker_once", _run_once)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            solver_enabled=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert calls == [1, 2]
    assert summary["attempts"] == 2
    assert summary["completed"] == 1
    assert [result["item_id"] for result in summary["results"]] == ["3001", "3002"]


def test_detail_challenge_should_break_batch_respects_solver_status_matrix(tmp_path: Path) -> None:
    base_result = {
        "decision": "detail_item_retryable_failure",
        "reason": "detail_challenge_page",
    }
    solver_enabled_config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_success=1,
        max_attempts=1,
        worker_id="detail-test",
        do_risk=False,
        solver_enabled=True,
    )
    manual_reporting_config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_success=1,
        max_attempts=1,
        worker_id="detail-test",
        do_risk=False,
        solver_enabled=False,
        manual_challenge_reporting=True,
    )
    disabled_config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_success=1,
        max_attempts=1,
        worker_id="detail-test",
        do_risk=False,
        solver_enabled=False,
    )

    assert detail_worker._detail_challenge_should_break_batch(
        disabled_config,
        dict(base_result),
    ) is False
    assert detail_worker._detail_challenge_should_break_batch(
        solver_enabled_config,
        dict(base_result, captcha_solver_report={"status": " queued "}),
    ) is True
    assert detail_worker._detail_challenge_should_break_batch(
        solver_enabled_config,
        dict(base_result, captcha_solver_report={"status": " Already_Running "}),
    ) is False
    assert detail_worker._detail_challenge_should_break_batch(
        manual_reporting_config,
        dict(base_result, captcha_solver_report={"status": "manual_required"}),
    ) is True


def test_detail_challenge_should_break_batch_always_breaks_on_cdp_unreachable(tmp_path: Path) -> None:
    config = detail_worker.DetailWorkerConfig(
        output_dir=tmp_path,
        cdp_endpoint="http://127.0.0.1:9223",
        target_success=1,
        max_attempts=1,
        worker_id="detail-test",
        do_risk=False,
        solver_enabled=False,
        manual_challenge_reporting=False,
    )

    assert detail_worker._detail_challenge_should_break_batch(
        config,
        {
            "decision": "detail_item_retryable_failure",
            "reason": "detail_cdp_unreachable",
        },
    ) is True


def test_run_detail_worker_batch_aborts_before_claiming_items_when_llm_chat_is_unavailable(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        return {}

    preflight_calls: list[dict[str, object]] = []

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        preflight_calls.append({"timeout": timeout, "check_chat": check_chat})
        return {
            "enabled": True,
            "url": "http://llm.local/v1/models",
            "status_code": 200,
            "chat_url": "http://llm.local/v1/chat/completions",
            "chat_status_code": 503,
        }

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_worker_llm_unavailable"
    assert summary["attempts"] == 0
    assert summary["completed"] == 0
    assert summary["results"] == []
    assert summary["llm_preflight"]["chat_status_code"] == 503
    assert summary["llm_preflight"]["attempt"] == 3
    assert preflight_calls == [{"timeout": 2.5, "check_chat": True}] * 3
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1


def test_run_detail_worker_batch_raw_only_skips_llm_preflight_even_when_enabled(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text("<html>raw</html>", encoding="utf-8")
        (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
        (item_dir / "selected.json").write_text(
            json.dumps({"item_id": seed["id"], "detail_capture_mode": "raw"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return {"item_id": seed["id"], "detail_capture_mode": "raw"}

    def _preflight_llm_backend(*_args, **_kwargs):
        raise AssertionError("raw-only detail worker must not preflight the LLM backend")

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            raw_only=True,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_worker_batch_finished"
    assert summary["completed"] == 1
    assert summary["llm_preflight"] is None
    assert processed == ["3001"]
    assert repo.seed_queue_counts()["seed_item_raw_detail_captured"] == 1


def test_run_detail_analysis_batch_aborts_before_claiming_raw_when_llm_unavailable(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    claimed = repo.claim_seed_detail_item("raw-worker", lease_seconds=30)
    assert claimed is not None
    repo.mark_seed_raw_detail_captured(
        "3001",
        detail_html_path=str(tmp_path / "3001" / "detail.html"),
        description_json_path=str(tmp_path / "3001" / "description-data.json"),
        selected_json_path=str(tmp_path / "3001" / "selected.json"),
    )
    preflight_calls: list[dict[str, object]] = []

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        preflight_calls.append({"timeout": timeout, "check_chat": check_chat})
        return {
            "enabled": True,
            "url": "http://llm.local/v1/models",
            "status_code": 200,
            "chat_url": "http://llm.local/v1/chat/completions",
            "chat_status_code": 503,
        }

    def _analyze_raw_item(*_args, **_kwargs):
        raise AssertionError("analysis must not claim or process items when LLM preflight fails")

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="analysis-test",
            do_risk=False,
            analysis_only=True,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=None,
        browser_pages={},
        analyze_item_func=_analyze_raw_item,
    )

    assert summary["decision"] == "detail_worker_llm_unavailable"
    assert summary["llm_preflight"]["attempt"] == 3
    assert preflight_calls == [{"timeout": 2.5, "check_chat": True}] * 3
    assert repo.seed_queue_counts()["seed_item_raw_detail_captured"] == 1


def test_run_detail_analysis_once_stages_raw_artifacts_from_capture_worker_output_dir(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    claimed = repo.claim_seed_detail_item("raw-worker-2", lease_seconds=30)
    assert claimed is not None
    expected_title = str(claimed["title"])
    raw_dir = tmp_path / "detail_worker_2" / "3001"
    raw_dir.mkdir(parents=True)
    (raw_dir / "detail.html").write_text("<html>raw detail from worker 2</html>", encoding="utf-8")
    (raw_dir / "description-data.json").write_text('{"text":"raw text"}', encoding="utf-8")
    (raw_dir / "selected.json").write_text('{"fetch":{"method":"raw-only"}}', encoding="utf-8")
    repo.mark_seed_raw_detail_captured(
        "3001",
        detail_html_path=str(raw_dir / "detail.html"),
        description_json_path=str(raw_dir / "description-data.json"),
        selected_json_path=str(raw_dir / "selected.json"),
    )
    analysis_dir = tmp_path / "detail_analysis_worker"

    def _analyze_raw_item(item_id: str, *, output_dir: Path, do_risk: bool) -> dict[str, object]:
        item_dir = output_dir / item_id
        assert (item_dir / "detail.html").read_text(encoding="utf-8") == "<html>raw detail from worker 2</html>"
        assert "raw text" in (item_dir / "description-data.json").read_text(encoding="utf-8")
        seed = json.loads((item_dir / "seed.json").read_text(encoding="utf-8"))
        assert seed["id"] == "3001"
        assert seed["title"] == expected_title
        (item_dir / "final.json").write_text(json.dumps({"id": 3001, "title": expected_title}), encoding="utf-8")
        (item_dir / "selected.json").write_text('{"item_id":"3001"}', encoding="utf-8")
        return {"item_id": item_id, "do_risk": do_risk}

    summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=analysis_dir,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="analysis-1",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_raw_item,
    )

    assert summary["decision"] == "detail_analysis_completed"
    assert summary["final_json_path"] == str(analysis_dir / "3001" / "final.json")
    assert repo.seed_queue_counts()["seed_item_detail_completed"] == 1


def test_three_stage_task_pool_can_buffer_raw_detail_between_independent_workers(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    raw_output_dir = tmp_path / "detail_worker_2"
    analysis_output_dir = tmp_path / "detail_analysis_worker_3"

    def _capture_raw_detail(_http, seed, _browser_pages, *, config):
        item_dir = config.output_dir / str(seed["id"])
        item_dir.mkdir(parents=True)
        (item_dir / "detail.html").write_text("<html>buffered raw detail</html>", encoding="utf-8")
        (item_dir / "description-data.json").write_text('{"text":"buffered page text"}', encoding="utf-8")
        (item_dir / "selected.json").write_text('{"fetch":{"method":"raw-only"}}', encoding="utf-8")
        return {"item_id": str(seed["id"]), "detail_capture_mode": "raw"}

    raw_summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=raw_output_dir,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-2",
            do_risk=False,
            raw_only=True,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_capture_raw_detail,
    )

    assert raw_summary["decision"] == "detail_item_raw_captured"
    assert repo.seed_queue_counts()["seed_item_raw_detail_captured"] == 1

    def _analyze_buffered_raw(item_id: str, *, output_dir: Path, do_risk: bool) -> dict[str, object]:
        item_dir = output_dir / item_id
        assert item_dir == analysis_output_dir / "3001"
        assert (item_dir / "detail.html").read_text(encoding="utf-8") == "<html>buffered raw detail</html>"
        assert "buffered page text" in (item_dir / "description-data.json").read_text(encoding="utf-8")
        final = {
            "id": item_id,
            "title": "三段式任务池结果",
            "source_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "community_name": "任务池小区",
            "community_stable_key": "collector::广州市::南沙区::任务池小区",
            "city": "广州市",
            "district": "南沙区",
            "is_processed": True,
            "detail_captured": True,
        }
        (item_dir / "final.json").write_text(json.dumps(final, ensure_ascii=False), encoding="utf-8")
        (item_dir / "selected.json").write_text(json.dumps({"item_id": item_id}, ensure_ascii=False), encoding="utf-8")
        return {"item_id": item_id, "do_risk": do_risk}

    analysis_summary = detail_worker.run_detail_analysis_once(
        detail_worker.DetailWorkerConfig(
            output_dir=analysis_output_dir,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="analysis-3",
            do_risk=False,
            analysis_only=True,
        ),
        repository=repo,
        analyze_item_func=_analyze_buffered_raw,
    )

    counts = repo.seed_queue_counts()
    assert analysis_summary["decision"] == "detail_analysis_completed"
    assert analysis_summary["staged_raw_artifacts"]["detail_html_path"] == str(
        analysis_output_dir / "3001" / "detail.html"
    )
    assert counts["seed_item_raw_detail_captured"] == 0
    assert counts["seed_item_detail_completed"] == 1
    assert repo.get_flat_item("3001")["community_stable_key"] == "collector::广州市::南沙区::任务池小区"


def test_llm_preflight_allows_missing_models_endpoint_when_chat_succeeds() -> None:
    assert detail_worker._llm_preflight_is_unavailable(
        {
            "enabled": True,
            "status_code": 404,
            "chat_status_code": 200,
        }
    ) is False


def test_run_detail_worker_batch_aborts_before_claiming_items_when_llm_chat_is_forbidden(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        return {}

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        return {
            "enabled": True,
            "url": "http://llm.local/v1/models",
            "status_code": 200,
            "chat_url": "http://llm.local/v1/chat/completions",
            "chat_status_code": 403,
        }

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_worker_llm_unavailable"
    assert summary["attempts"] == 0
    assert summary["completed"] == 0
    assert summary["results"] == []
    assert summary["llm_preflight"]["chat_status_code"] == 403
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1


def test_run_detail_worker_batch_aborts_before_claiming_items_when_llm_preflight_raises(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    _seed_items(repo, ["3001"])
    processed: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed.append(str(seed["id"]))
        return {}

    preflight_calls: list[dict[str, object]] = []

    def _preflight_llm_backend(*, timeout: float, check_chat: bool = False) -> dict[str, object]:
        preflight_calls.append({"timeout": timeout, "check_chat": check_chat})
        raise RuntimeError("llm preflight connect timeout")

    monkeypatch.setattr(detail_worker, "preflight_llm_backend", _preflight_llm_backend)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=3,
            worker_id="detail-test",
            do_risk=False,
            llm_preflight_enabled=True,
            llm_preflight_timeout_seconds=2.5,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item,
    )

    assert summary["decision"] == "detail_worker_llm_unavailable"
    assert summary["attempts"] == 0
    assert summary["completed"] == 0
    assert summary["results"] == []
    assert "llm preflight connect timeout" in summary["llm_preflight"]["error"]
    assert summary["llm_preflight"]["attempt"] == 3
    assert preflight_calls == [{"timeout": 2.5, "check_chat": True}] * 3
    assert processed == []
    assert repo.seed_queue_counts()["seed_item_pending_detail"] == 1


def test_run_detail_worker_once_exits_cleanly_when_queue_is_empty(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=lambda *_args, **_kwargs: {},
    )

    assert summary == {"decision": "detail_queue_empty"}


def test_run_detail_worker_loop_refreshes_runtime_context_each_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    contexts: list[tuple[str, dict[str, tuple[str, str]]]] = []
    batches: list[tuple[str, dict[str, tuple[str, str]]]] = []

    def _runtime_context_factory():
        run = len(contexts) + 1
        context = (f"http-{run}", {"page": (f"title-{run}", f"url-{run}")})
        contexts.append(context)
        return context

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        batches.append((http_session, browser_pages))
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=1,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=lambda _event: None,
    )

    assert summary["decision"] == "detail_worker_loop_finished"
    assert len(contexts) == 2
    assert batches == contexts


def test_run_detail_worker_loop_releases_existing_worker_leases_once_per_process(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    release_calls: list[str] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_queue_empty",
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        repo,
        "release_seed_detail_worker_leases",
        lambda worker_id: release_calls.append(worker_id) or {"released": 1},
    )

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=1,
            max_runs=1,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=lambda _event: None,
    )

    assert release_calls == ["detail-test"]


def test_run_detail_worker_loop_emits_compact_batch_and_sleep_events(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 2,
            "completed": 1,
            "target_success": 3,
            "max_attempts": 4,
            "results": [
                {"decision": "detail_item_completed", "item_id": "3001"},
            ],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=events.append,
    )

    assert sleep_calls == [7]
    assert [event["event"] for event in events] == [
        "detail_worker_batch",
        "detail_worker_sleep",
        "detail_worker_batch",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "detail_worker_batch_finished"
    assert events[0]["completed"] == 1
    assert events[0]["last_result_decision"] == "detail_item_completed"
    assert events[0]["last_item_id"] == "3001"
    assert events[1] == {
        "event": "detail_worker_sleep",
        "run": 1,
        "sleep_seconds": 7,
        "counts": events[0]["counts"],
    }


def test_run_detail_worker_loop_uses_active_sleep_after_productive_batch(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 2,
            "completed": 2,
            "target_success": 3,
            "max_attempts": 4,
            "results": [
                {"decision": "detail_item_raw_captured", "item_id": "3001"},
                {"decision": "detail_item_raw_captured", "item_id": "3002"},
            ],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            active_loop_interval_seconds=0,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=events.append,
    )

    assert sleep_calls == [0]
    assert events[1] == {
        "event": "detail_worker_sleep",
        "run": 1,
        "sleep_seconds": 0,
        "counts": events[0]["counts"],
    }


def test_run_detail_worker_loop_keeps_idle_sleep_when_llm_unavailable(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    sleep_calls: list[int] = []

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_llm_unavailable",
            "attempts": 0,
            "completed": 0,
            "target_success": 3,
            "max_attempts": 4,
            "results": [],
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=3,
            max_attempts=4,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=7,
            active_loop_interval_seconds=0,
            max_runs=2,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        progress_emit_func=lambda _event: None,
    )

    assert sleep_calls == [7]


def test_run_detail_worker_loop_retries_after_runtime_context_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    contexts: list[str] = []

    def _runtime_context_factory():
        if not contexts:
            contexts.append("failed")
            raise RuntimeError("cdp unavailable")
        contexts.append("ok")
        return "http-ok", {}

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=5,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert contexts == ["failed", "ok"]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "detail_worker_runtime_refresh_failed",
        "detail_worker_sleep",
        "detail_worker_batch",
    ]
    assert events[0]["run"] == 1
    assert events[0]["decision"] == "detail_runtime_refresh_failed"
    assert "cdp unavailable" in events[0]["error"]
    assert summary["runs"] == 2
    assert summary["last_decision"] == "detail_worker_batch_finished"


def test_run_detail_worker_loop_reuses_last_runtime_context_after_later_refresh_failure(tmp_path: Path, monkeypatch) -> None:
    repo = _make_repo(tmp_path)
    events: list[dict[str, Any]] = []
    sleep_calls: list[int] = []
    used_batches: list[tuple[str, dict[str, tuple[str, str]]]] = []
    calls = {"count": 0}

    def _runtime_context_factory():
        calls["count"] += 1
        if calls["count"] == 1:
            return "http-1", {"page": ("title-1", "url-1")}
        raise RuntimeError("cdp refresh timed out")

    def _run_batch(_config, *, repository, http_session, browser_pages, process_item_func=detail_worker.process_item):
        used_batches.append((http_session, browser_pages))
        return {
            "decision": "detail_worker_batch_finished",
            "attempts": 0,
            "completed": 0,
            "counts": repository.seed_queue_counts(),
        }

    monkeypatch.setattr(detail_worker, "run_detail_worker_batch", _run_batch)
    monkeypatch.setattr(detail_worker.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    summary = detail_worker.run_detail_worker_loop(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            loop_interval_seconds=5,
            max_runs=2,
        ),
        repository=repo,
        runtime_context_factory=_runtime_context_factory,
        progress_emit_func=events.append,
    )

    assert used_batches == [
        ("http-1", {"page": ("title-1", "url-1")}),
        ("http-1", {"page": ("title-1", "url-1")}),
    ]
    assert sleep_calls == [5]
    assert [event["event"] for event in events] == [
        "detail_worker_batch",
        "detail_worker_sleep",
        "detail_worker_runtime_refresh_reused_last_context",
        "detail_worker_batch",
    ]
    assert events[2]["run"] == 2
    assert "cdp refresh timed out" in events[2]["error"]
    assert summary["runs"] == 2
    assert summary["last_decision"] == "detail_worker_batch_finished"
