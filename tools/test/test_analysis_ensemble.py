from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from src.analysis_ensemble import (
    build_adjudication_prompt,
    build_field_consensus,
    compose_final_payload,
    normalize_field_value,
    parse_distinct_models,
    validate_adjudication,
)
from src.storage.models import FapaiSeedItem
from src.storage.repository import DatabaseSettings, PropertyRepository


def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'analysis-ensemble.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_model_list_requires_three_distinct_models() -> None:
    assert parse_distinct_models("flash;pro,grok") == ("flash", "pro", "grok")
    with pytest.raises(ValueError, match="exactly 3 distinct"):
        parse_distinct_models("flash,flash,pro")


def test_field_consensus_normalizes_units_and_requires_source_evidence() -> None:
    candidates = [
        {"起拍价格": 1_250_000, "建筑面积": 89.35, "完整地址": "北京市东城区测试路1号", "单价": 1},
        {"起拍价格": "125万元", "建筑面积": "89.350㎡", "完整地址": "北京市 东城区 测试路1号", "单价": 2},
        {"起拍价格": 1_250_000.0, "建筑面积": 89.35, "完整地址": "北京市东城区测试路1号", "单价": 3},
    ]
    source = "起拍价为125万元，建筑面积89.35平方米，标的地址为北京市东城区测试路1号。"

    consensus = build_field_consensus(candidates, source_text=source)

    assert consensus["locked_fields"]["起拍价格"]["agreement"] == "3/3"
    assert consensus["locked_fields"]["建筑面积"]["normalized_value"] == "number:89.35"
    assert "完整地址" in consensus["locked_fields"]
    assert "单价" in consensus["derived_fields"]
    assert consensus["stats"]["conflict_count"] == 0
    assert normalize_field_value("起拍价格", "125万元") == normalize_field_value("起拍价格", 1_250_000)


def test_two_of_three_and_unsupported_same_value_are_conflicts() -> None:
    candidates = [
        {"建筑面积": 89.35, "最靠近商圈": "测试板块"},
        {"建筑面积": 89.35, "最靠近商圈": "测试板块"},
        {"建筑面积": 98.35, "最靠近商圈": "测试板块"},
    ]

    consensus = build_field_consensus(candidates, source_text="建筑面积89.35平方米。")

    assert consensus["conflicts"]["建筑面积"]["reason"] == "candidate_disagreement"
    assert consensus["conflicts"]["建筑面积"]["high_risk"] is True
    assert consensus["conflicts"]["最靠近商圈"]["reason"] == "evidence_missing"


def test_unanimous_null_is_omitted_instead_of_being_locked_without_evidence() -> None:
    consensus = build_field_consensus(
        [{"tax_burden": None}, {"tax_burden": None}, {"tax_burden": None}],
        source_text="公告没有说明税费承担。",
    )

    assert "tax_burden" not in consensus["locked_fields"]
    assert "tax_burden" not in consensus["conflicts"]
    assert consensus["omitted_fields"] == ["tax_burden"]
    assert consensus["stats"]["omitted_count"] == 1


def test_adjudicator_cannot_rewrite_locked_fields_or_use_unsupported_evidence() -> None:
    consensus = {
        "locked_fields": {"起拍价格": {"value": 1_000_000}},
        "conflicts": {
            "建筑面积": {"candidate_values": [89.35, 89.35, 98.35]},
            "tax_burden": {"candidate_values": ["各自承担", "未知", "各自承担"]},
        },
    }
    raw = {
        "decisions": {
            "起拍价格": {"value": 1, "decision": "new", "evidence": "伪造", "confidence": 1},
            "建筑面积": {
                "value": 89.35,
                "decision": "candidate_1",
                "evidence": "建筑面积89.35平方米",
                "confidence": 0.98,
            },
            "tax_burden": {
                "value": "各自承担",
                "decision": "candidate_1",
                "evidence": "原文不存在的税费结论",
                "confidence": 0.9,
            },
        }
    }

    adjudication = validate_adjudication(
        raw,
        consensus=consensus,
        source_text="公告载明建筑面积89.35平方米，但未说明税费承担。",
    )

    assert adjudication["decisions"]["建筑面积"]["value"] == 89.35
    assert adjudication["decisions"]["tax_burden"]["value"] is None
    assert adjudication["needs_review"] == ["tax_burden"]
    assert adjudication["ignored_fields"] == ["起拍价格"]


def test_adjudicator_rejects_invalid_decisions_candidate_mismatches_and_unrelated_evidence() -> None:
    consensus = {
        "conflicts": {
            "建筑面积": {"candidate_values": [80, 81, 82]},
            "起拍价格": {"candidate_values": [1_000_000, 1_100_000, 1_200_000]},
            "成交价格": {"candidate_values": [2_000_000, 2_100_000, 2_200_000]},
        }
    }
    raw = {
        "decisions": {
            "建筑面积": {
                "value": 80,
                "decision": "majority",
                "evidence": "建筑面积80平方米",
                "confidence": 0.99,
            },
            "起拍价格": {
                "value": 1_200_000,
                "decision": "candidate_1",
                "evidence": "起拍价格1200000元",
                "confidence": 0.99,
            },
            "成交价格": {
                "value": 2_000_000,
                "decision": "candidate_1",
                "evidence": "建筑面积80平方米",
                "confidence": 0.99,
            },
        }
    }

    adjudication = validate_adjudication(
        raw,
        consensus=consensus,
        source_text=(
            "建筑面积80平方米，起拍价格1200000元，成交价格2000000元。"
        ),
    )

    assert adjudication["needs_review"] == ["建筑面积", "成交价格", "起拍价格"]
    assert adjudication["decisions"]["建筑面积"]["validation"] == "invalid_decision"
    assert adjudication["decisions"]["起拍价格"]["validation"] == "candidate_value_mismatch"
    assert adjudication["decisions"]["成交价格"]["validation"] == "unsupported_evidence"


def test_adjudication_prompt_contains_original_evidence_and_all_three_independent_results() -> None:
    candidates = [
        {"建筑面积": 80, "tax_burden": "买受人承担"},
        {"建筑面积": 81, "tax_burden": "各自承担"},
        {"建筑面积": 82, "tax_burden": None},
    ]
    prompt = build_adjudication_prompt(
        item_id="ensemble-prompt",
        consensus={"conflicts": {"建筑面积": {"candidate_values": [80, 81, 82]}}},
        candidates=candidates,
        source_text="公告原文：建筑面积80平方米，税费承担未说明。",
    )

    assert "Three independent module A results" in prompt
    assert '"建筑面积": 80' in prompt
    assert '"建筑面积": 81' in prompt
    assert '"建筑面积": 82' in prompt
    assert "公告原文：建筑面积80平方米" in prompt


def test_final_payload_combines_locked_and_adjudicated_fields_then_recomputes_unit_price() -> None:
    final_payload = compose_final_payload(
        consensus={
            "locked_fields": {
                "成交价格": {"value": 1_000_000},
                "完整地址": {"value": "北京市东城区测试路1号"},
            }
        },
        adjudication={
            "decisions": {
                "建筑面积": {"value": 80},
                "tax_burden": {"value": None},
            }
        },
    )

    assert final_payload["成交价格"] == 1_000_000
    assert final_payload["建筑面积"] == 80
    assert final_payload["单价"] == 12_500.0
    assert final_payload["tax_burden"] is None
    assert final_payload["is_processed"] is True


def test_repository_persists_versioned_module_b_receipt_without_touching_seed_payload(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    repo.initialize()
    with repo.session_factory.begin() as session:
        session.add(
            FapaiSeedItem(
                item_id="ensemble-1",
                source_item_id="ensemble-1",
                source_payload={"stable": "seed"},
            )
        )
    receipt = {
        "run_id": "a" * 64,
        "schema_version": "analysis_module_b_v1",
        "input_sha256": "b" * 64,
        "mode": "shadow",
        "status": "candidate_partial",
        "candidate_models": ["flash", "pro", "grok"],
        "arbiter_model": "pro",
        "arbiter_independent_model": False,
        "artifacts": {"receipt_path": "/tmp/receipt.json"},
    }

    repo.record_analysis_ensemble_run("ensemble-1", receipt)
    receipt["status"] = "finalized"
    repo.record_analysis_ensemble_run("ensemble-1", receipt)

    stored = repo.get_analysis_ensemble_run("a" * 64)
    assert stored is not None
    assert stored["status"] == "finalized"
    assert stored["candidate_models"] == ["flash", "pro", "grok"]
    with repo.session_factory() as session:
        seed = session.get(FapaiSeedItem, "ensemble-1")
        assert seed is not None
        assert seed.source_payload == {"stable": "seed"}


def test_analysis_ensemble_migration_upgrades_and_downgrades_in_isolation(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.sqlite3').resolve().as_posix()}")
    migration_path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260901_0009_add_analysis_ensemble_runs.py"
    spec = importlib.util.spec_from_file_location("analysis_ensemble_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        FapaiSeedItem.__table__.create(connection)
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)

        migration.upgrade()
        columns = {column["name"] for column in inspect(connection).get_columns("fapai_analysis_run")}
        assert {"run_id", "item_id", "status", "receipt"} <= columns

        migration.downgrade()
        assert not inspect(connection).has_table("fapai_analysis_run")
