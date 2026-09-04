from __future__ import annotations

from tools.test.analysis_module_b_integration_test_context import *


def test_module_b_runs_three_distinct_candidates_in_parallel_and_writes_versioned_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path)
    calls: list[str] = []

    def _extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-1"
        assert model is not None
        calls.append(model)
        return json.dumps(
            {
                "标题": seed["title"],
                "完整地址": "北京市东城区测试小区1号房",
                "成交价格": 1_000_000,
                "起拍价格": 800_000,
                "建筑面积": 80,
                "单价": 1,
            },
            ensure_ascii=False,
        )

    def _unexpected_arbiter(*_args, **_kwargs):
        raise AssertionError("full 3/3 evidence-backed consensus must skip the arbiter")

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract)
    monkeypatch.setattr(llm_helper, "chat_with_glm", _unexpected_arbiter)

    result = live_batch_smoke._run_analysis_module_b(
        item_id="module-b-1",
        item_dir=item_dir,
        analysis_text=(
            "currentPrice: 1000000\ninitialPrice: 800000\n"
            "完整地址: 北京市东城区测试小区1号房\n建筑面积80平方米"
        ),
        evidence_text=(
            "成交价格1000000元，起拍价格800000元，"
            "建筑面积80平方米，完整地址北京市东城区测试小区1号房，"
            "交易时间2026-09-01 10:00:00，status: done。"
        ),
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )

    assert result["status"] == "finalized"
    assert sorted(calls) == ["flash", "grok", "pro"]
    assert result["arbiter_independent_model"] is True
    for path in result["artifacts"]["candidate_paths"]:
        assert Path(path).is_file()
    assert Path(result["artifacts"]["consensus_path"]).is_file()
    assert Path(result["artifacts"]["final_path"]).is_file()
    assert result["final_payload"]["单价"] == 12_500.0
    provenance = result["analysis_provenance"]
    assert provenance == result["final_payload"]["analysis_provenance"]
    assert provenance["module"] == "B"
    assert provenance["pipeline_version"] == "analysis_module_b_v1"
    assert provenance["run_id"] == result["run_id"]
    assert provenance["input_sha256"] == result["input_sha256"]
    assert provenance["model_routing_sha256"] == result["model_routing_sha256"]
    assert live_batch_smoke.load_json(Path(result["artifacts"]["final_path"]))[
        "analysis_provenance"
    ] == provenance
    assert live_batch_smoke.load_json(Path(result["artifacts"]["receipt_path"]))[
        "analysis_provenance"
    ] == provenance
    assert live_batch_smoke.load_json(item_dir / "analysis-b" / "latest.json")[
        "analysis_provenance"
    ] == provenance


def test_module_b_reuses_successful_candidates_after_partial_failure(tmp_path: Path, monkeypatch) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path, "module-b-resume")
    first_calls: list[str] = []

    def _first_extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-resume"
        assert model is not None
        first_calls.append(model)
        if model == "grok":
            raise RuntimeError("temporary model outage")
        return json.dumps({"成交价格": 1_000_000, "起拍价格": 800_000, "建筑面积": 80})

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    monkeypatch.setattr(llm_helper, "extract_auction_data", _first_extract)
    first = live_batch_smoke._run_analysis_module_b(
        item_id="module-b-resume",
        item_dir=item_dir,
        analysis_text="currentPrice: 1000000\ninitialPrice: 800000\n建筑面积80平方米\nstatus: done",
        evidence_text=(
            "成交价格1000000元，起拍价格800000元，建筑面积80平方米，"
            "交易时间2026-09-01 10:00:00，status: done。"
        ),
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )
    assert first["status"] == "candidate_partial"
    assert sorted(first_calls) == ["flash", "grok", "pro"]

    second_calls: list[str] = []

    def _second_extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-resume"
        assert model is not None
        second_calls.append(model)
        return json.dumps({"成交价格": 1_000_000, "起拍价格": 800_000, "建筑面积": 80})

    monkeypatch.setattr(llm_helper, "extract_auction_data", _second_extract)
    second = live_batch_smoke._run_analysis_module_b(
        item_id="module-b-resume",
        item_dir=item_dir,
        analysis_text="currentPrice: 1000000\ninitialPrice: 800000\n建筑面积80平方米\nstatus: done",
        evidence_text=(
            "成交价格1000000元，起拍价格800000元，建筑面积80平方米，"
            "交易时间2026-09-01 10:00:00，status: done。"
        ),
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )
    assert second["status"] == "finalized"
    assert second_calls == ["grok"]


def test_module_b_retries_a_rate_limited_candidate_without_route_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path, "module-b-rate-limit")
    calls: list[str] = []
    sleeps: list[float] = []

    def _extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-rate-limit"
        assert model is not None
        calls.append(model)
        if model == "minimax" and calls.count(model) == 1:
            response = requests.Response()
            response.status_code = 429
            response.url = "http://gateway.test/v1/chat/completions"
            raise requests.HTTPError("rate limited", response=response)
        return json.dumps(
            {
                "标题": seed["title"],
                "完整地址": "北京市东城区测试小区1号房",
                "成交价格": 1_000_000,
                "起拍价格": 800_000,
                "建筑面积": 80,
                "单价": 1,
            },
            ensure_ascii=False,
        )

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,minimax")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_ATTEMPTS", "3")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_RETRY_SECONDS", "10")
    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract)
    monkeypatch.setattr(live_batch_smoke.time, "sleep", sleeps.append)

    result = live_batch_smoke._run_analysis_module_b(
        item_id="module-b-rate-limit",
        item_dir=item_dir,
        analysis_text=(
            "currentPrice: 1000000\ninitialPrice: 800000\n"
            "完整地址: 北京市东城区测试小区1号房\n建筑面积80平方米"
        ),
        evidence_text=(
            "成交价格1000000元，起拍价格800000元，"
            "建筑面积80平方米，完整地址北京市东城区测试小区1号房，"
            "交易时间2026-09-01 10:00:00，status: done。"
        ),
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )

    assert result["status"] == "finalized"
    assert calls.count("flash") == 1
    assert calls.count("pro") == 1
    assert calls.count("minimax") == 2
    assert sleeps == [10.0]
    candidate = live_batch_smoke.load_json(Path(result["artifacts"]["candidate_paths"][2]))
    assert candidate["model"] == "minimax"
    assert candidate["attempt_count"] == 2


def test_module_b_candidate_cache_is_invalidated_when_raw_html_changes(tmp_path: Path) -> None:
    path = tmp_path / "candidate-1.json"
    live_batch_smoke.write_json(
        path,
        {
            "schema_version": "analysis_module_b_v1",
            "model": "flash",
            "input_sha256": "a" * 64,
            "raw_html_sha256": "b" * 64,
            "result": {"建筑面积": 80},
        },
    )

    assert live_batch_smoke._module_b_cached_candidate(
        path,
        model="flash",
        input_sha256="a" * 64,
        raw_html_sha256="b" * 64,
    ) is not None
    assert live_batch_smoke._module_b_cached_candidate(
        path,
        model="flash",
        input_sha256="a" * 64,
        raw_html_sha256="c" * 64,
    ) is None


def test_module_b_raw_html_change_creates_a_new_versioned_run(tmp_path: Path, monkeypatch) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path, "module-b-versioned-input")
    calls: list[str] = []

    def _extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-versioned-input"
        assert model is not None
        calls.append(model)
        return json.dumps({"成交价格": 1_000_000, "起拍价格": 800_000, "建筑面积": 80})

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract)
    common = {
        "item_id": "module-b-versioned-input",
        "item_dir": item_dir,
        "analysis_text": "currentPrice: 1000000\ninitialPrice: 800000\n建筑面积80平方米",
        "evidence_text": "成交价格1000000元，起拍价格800000元，建筑面积80平方米。",
        "effective_seed": seed,
        "do_risk": False,
        "mode": "shadow",
    }

    first = live_batch_smoke._run_analysis_module_b(html=html, **common)
    second = live_batch_smoke._run_analysis_module_b(html=html + "<!-- changed -->", **common)

    assert first["run_id"] != second["run_id"]
    assert first["input_sha256"] != second["input_sha256"]
    assert first["artifacts"]["run_dir"] != second["artifacts"]["run_dir"]
    assert len(calls) == 6


def test_module_b_model_route_change_creates_a_new_versioned_run(tmp_path: Path, monkeypatch) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path, "module-b-versioned-models")
    calls: list[str] = []

    def _extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-versioned-models"
        assert model is not None
        calls.append(model)
        return json.dumps({"成交价格": 1_000_000, "起拍价格": 800_000, "建筑面积": 80})

    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract)
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "arbiter")
    common = {
        "item_id": "module-b-versioned-models",
        "item_dir": item_dir,
        "analysis_text": "currentPrice: 1000000\ninitialPrice: 800000\n建筑面积80平方米",
        "evidence_text": "成交价格1000000元，起拍价格800000元，建筑面积80平方米。",
        "html": html,
        "effective_seed": seed,
        "do_risk": False,
        "mode": "shadow",
    }

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    first = live_batch_smoke._run_analysis_module_b(**common)
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,minimax")
    second = live_batch_smoke._run_analysis_module_b(**common)

    assert first["run_id"] != second["run_id"]
    assert first["input_sha256"] != second["input_sha256"]
    assert first["model_routing_sha256"] != second["model_routing_sha256"]
    assert first["artifacts"]["run_dir"] != second["artifacts"]["run_dir"]
    assert len(calls) == 6


def test_module_b_does_not_finalize_conflicts_with_a_non_independent_arbiter(tmp_path: Path, monkeypatch) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path, "module-b-arbiter-gate")
    areas = {"flash": 80, "pro": 81, "grok": 82}

    def _extract(_content: str, item_id: str | None = None, *, model: str | None = None) -> str:
        assert item_id == "module-b-arbiter-gate"
        assert model is not None
        return json.dumps(
            {
                "成交价格": 1_000_000,
                "起拍价格": 800_000,
                "建筑面积": areas[model],
            },
            ensure_ascii=False,
        )

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "pro")
    monkeypatch.setattr(llm_helper, "extract_auction_data", _extract)
    monkeypatch.setattr(
        llm_helper,
        "chat_with_glm",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a non-independent arbiter must be skipped instead of billed again")
        ),
    )

    result = live_batch_smoke._run_analysis_module_b(
        item_id="module-b-arbiter-gate",
        item_dir=item_dir,
        analysis_text="currentPrice: 1000000\ninitialPrice: 800000\n建筑面积80平方米",
        evidence_text="成交价格1000000元，起拍价格800000元，建筑面积80平方米。",
        html=html,
        effective_seed=seed,
        do_risk=False,
        mode="shadow",
    )

    assert result["status"] == "needs_review"
    assert result["arbiter_independent_model"] is False
    assert "analysis_module_b.arbiter_model_not_independent" in result["needs_review"]


def test_module_b_rejects_gpt_routes_and_primary_rejects_non_independent_arbiter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    item_dir, seed, html = _write_raw_item(tmp_path, "module-b-model-policy")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,gpt-5.4,grok")
    try:
        live_batch_smoke._analysis_module_b_models()
    except ValueError as exc:
        assert "non-GPT" in str(exc)
    else:
        raise AssertionError("GPT candidate routes must be rejected")

    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS", "flash,pro,grok")
    monkeypatch.setenv("FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL", "pro")
    monkeypatch.setattr(
        llm_helper,
        "extract_auction_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("primary configuration must fail before making model calls")
        ),
    )
    try:
        live_batch_smoke._run_analysis_module_b(
            item_id="module-b-model-policy",
            item_dir=item_dir,
            analysis_text="建筑面积80平方米",
            evidence_text="建筑面积80平方米",
            html=html,
            effective_seed=seed,
            do_risk=False,
            mode="primary",
        )
    except ValueError as exc:
        assert "independent" in str(exc)
    else:
        raise AssertionError("primary mode must require a fourth independent model")
