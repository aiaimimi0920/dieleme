from tools.test.seed_collector_test_context import *  # noqa: F401,F403


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
