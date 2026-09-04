from tools.test.seed_collector_test_context import *  # noqa: F401,F403


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
