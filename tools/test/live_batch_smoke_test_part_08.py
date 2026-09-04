from tools.test.live_batch_smoke_test_context import *  # noqa: F401,F403


def test_run_live_smoke_uses_resume_state_to_continue_after_restart(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 4, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
            }

    class _FakeResponse:
        text = "<html>list</html>"
        url = "https://sf.taobao.com/list/page"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeHttp:
        @staticmethod
        def get(*_args, **_kwargs) -> _FakeResponse:
            return _FakeResponse()

    processed_ids: list[str] = []
    resume_state_path = tmp_path / "resume_state.json"
    state = live_batch_smoke.load_resume_state(resume_state_path)
    live_batch_smoke.mark_resume_item(state, "a", status="completed")
    live_batch_smoke.mark_resume_item(state, "b", status="completed")
    live_batch_smoke.save_resume_state(resume_state_path, state)

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: _FakeHttp())
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=3,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["c", "d"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["attempted_items"] == 2
    assert summary["skipped_completed_items"] == 2
    assert summary["resume_state_path"] == str(resume_state_path)

    reloaded = live_batch_smoke.load_resume_state(resume_state_path)
    assert live_batch_smoke.is_resume_completed(reloaded, "a") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "b") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "c") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "d") is True

def test_run_live_smoke_recovers_completed_items_from_existing_artifacts(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {"item_count": 3, "final_url": final_url}

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            }

    class _FakeResponse:
        text = "<html>list</html>"
        url = "https://sf.taobao.com/list/page"
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

    class _FakeHttp:
        @staticmethod
        def get(*_args, **_kwargs) -> _FakeResponse:
            return _FakeResponse()

    item_dir = tmp_path / "a"
    item_dir.mkdir()
    (item_dir / "final.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text("{}", encoding="utf-8")
    processed_ids: list[str] = []
    resume_state_path = tmp_path / "resume_state.json"

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: _FakeHttp())
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        return _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)

    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=2,
            do_risk=False,
            resume_state_path=resume_state_path,
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["b"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["artifact_completed_items"] == 1
    assert summary["skipped_completed_items"] == 1

    reloaded = live_batch_smoke.load_resume_state(resume_state_path)
    assert live_batch_smoke.is_resume_completed(reloaded, "a") is True
    assert live_batch_smoke.is_resume_completed(reloaded, "b") is True

def test_run_live_smoke_preserves_browser_recovered_list_fetch_method_when_all_candidates_are_completed(
    tmp_path: Path, monkeypatch
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 1,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [{"id": "a", "url": "https://sf-item.taobao.com/sf_item/a.htm"}],
            }

    item_dir = tmp_path / "a"
    item_dir.mkdir()
    (item_dir / "final.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text("{}", encoding="utf-8")

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list",
            target_url,
            None,
            "browser_page_after_http_challenge",
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(
        live_batch_smoke,
        "process_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("all candidates should already be completed")),
    )

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["list_fetch_method"] == "browser_page_after_http_challenge"
    assert summary["artifact_completed_items"] == 1
    assert summary["skipped_completed_items"] == 1
    assert summary["no_candidate_reason"] == "all_candidates_already_completed"

def test_run_live_smoke_records_browser_recovered_list_fetch_and_result_detail_methods(
    tmp_path: Path, monkeypatch
) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 2,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {
                "source_page_url": source_page_url,
                "items": [
                    {"id": "open-detail", "url": "https://sf-item.taobao.com/sf_item/open-detail.htm"},
                    {"id": "nav-detail", "url": "https://sf-item.taobao.com/sf_item/nav-detail.htm"},
                ],
            }

    processed_ids: list[str] = []

    def _process_item(_http, seed, _browser_pages, *, config):
        processed_ids.append(str(seed["id"]))
        result = _result(str(seed["id"]), area_sqm=88.8, unit_price=12345, desc_area=88.8)
        result["fetch"]["method"] = "open_browser_page" if seed["id"] == "open-detail" else "browser_navigation"
        return result

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list",
            target_url,
            None,
            "browser_page_after_http_challenge",
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(live_batch_smoke, "process_item", _process_item)

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page",
            target_success=2,
            max_attempts=2,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        )
    )

    assert exit_code == 0
    assert processed_ids == ["open-detail", "nav-detail"]
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["list_fetch_method"] == "browser_page_after_http_challenge"
    assert summary["processed_items"] == 2
    assert [row["fetch"]["method"] for row in summary["results"]] == [
        "open_browser_page",
        "browser_navigation",
    ]

def test_run_live_smoke_no_eligible_items_records_summary_and_followup_queue(tmp_path: Path, monkeypatch) -> None:
    class _FakeProbe:
        DEFAULT_USER_AGENT = live_batch_smoke.DEFAULT_USER_AGENT

        @staticmethod
        def summarize_list_page(_html: str, *, final_url: str) -> dict[str, object]:
            return {
                "item_count": 0,
                "final_url": final_url,
                "body_has_challenge": False,
                "body_has_login": False,
                "body_has_punish": False,
            }

        @staticmethod
        def extract_list_payload(_html: str) -> dict[str, object]:
            return {"ok": True}

        @staticmethod
        def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, object]:
            return {"source_page_url": source_page_url, "items": []}

    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(live_batch_smoke, "_browserless_seed_probe", lambda: _FakeProbe)
    monkeypatch.setattr(live_batch_smoke, "export_cookies", lambda _endpoint: [{"name": "cookie"}])
    monkeypatch.setattr(live_batch_smoke, "build_http", lambda _cookies: object())
    monkeypatch.setattr(
        live_batch_smoke,
        "fetch_list_page",
        lambda _http, *, cdp_endpoint, target_url, user_agent: (
            "list",
            "https://sf.taobao.com/list/page=1&redirected=1",
            206,
            "browser_page_after_http_challenge",
        ),
    )
    monkeypatch.setattr(live_batch_smoke, "fetch_open_browser_pages", lambda _endpoint: {})
    monkeypatch.setattr(
        live_batch_smoke,
        "process_item",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no items should be processed")),
    )

    exit_code = live_batch_smoke.run_live_smoke(
        live_batch_smoke.LiveSmokeConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_url="https://sf.taobao.com/list/page=1",
            target_success=1,
            max_attempts=1,
            do_risk=False,
            resume_state_path=tmp_path / "resume_state.json",
            resume_enabled=True,
        )
    )

    assert exit_code == 1
    summary = live_batch_smoke.load_json(tmp_path / "summary.json")
    assert summary["no_candidate_reason"] == "no_eligible_done_items"
    assert summary["eligible_done_item_count"] == 0
    assert summary["attempted_items"] == 0
    assert summary["processed_items"] == 0
    assert summary["list_status"] == 206
    assert summary["list_fetch_method"] == "browser_page_after_http_challenge"
    assert summary["list_final_url"] == "https://sf.taobao.com/list/page=1&redirected=1"
    queue = live_batch_smoke.load_json(tmp_path / "area_followup_queue.json")
    assert queue["job_count"] == 0
    assert queue["source_summary"] == str(tmp_path / "summary.json")
