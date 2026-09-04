from tools.test.detail_worker_test_context import *  # noqa: F401,F403


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
    assert detail_worker._detail_challenge_should_break_batch(
        solver_enabled_config,
        dict(
            base_result,
            captcha_solver_report={
                "status": "recent_auth_complete",
                "reason": "recent_detail_progress",
                "captured_since_auth": 1,
            },
        ),
    ) is False

def test_detail_challenge_report_recent_auth_is_labeled_and_does_not_break_batch(tmp_path: Path) -> None:
    result = {
        "decision": "detail_item_retryable_failure",
        "reason": "detail_challenge_page",
        "captcha_solver_report": {
            "status": "recent_auth_complete",
            "reason": "recent_detail_progress",
            "captured_since_auth": 2,
        },
    }

    assert detail_worker._captcha_report_suppresses_challenge(result["captcha_solver_report"]) is True
    assert detail_worker._detail_challenge_should_break_batch(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path,
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-test",
            do_risk=False,
            solver_enabled=True,
        ),
        result,
    ) is False

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
