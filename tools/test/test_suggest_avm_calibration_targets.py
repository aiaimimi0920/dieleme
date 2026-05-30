from tools.suggest_avm_calibration_targets import suggest_calibration_targets


def test_suggest_calibration_targets_surfaces_risk_flag_and_strategy_actions():
    report = suggest_calibration_targets(
        {
            "risk_flag_metrics": [
                {
                    "group": "is_occupied",
                    "sample_count": 6,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 9.5,
                    "p90_ape_pct": 30.0,
                }
            ],
            "strategy_metrics": [
                {
                    "group": "global_fallback",
                    "sample_count": 5,
                    "mape_pct": 17.0,
                    "mean_bias_pct": 6.0,
                    "p90_ape_pct": 29.0,
                }
            ],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["has_recommendations"] is True
    assert report["risk_factor_targets"][0]["name"] == "is_occupied"
    assert report["risk_factor_targets"][0]["suggested_action"] == "lower_price_contribution"
    assert report["risk_factor_targets"][0]["suggested_factor_step_pct"] > 0
    assert report["risk_factor_targets"][0]["suggested_next_factor"] < report["risk_factor_targets"][0]["current_factor"]
    assert report["config_patch"]["risk_factor_overrides"]["is_occupied"] == report["risk_factor_targets"][0]["suggested_next_factor"]
    assert report["strategy_targets"][0]["name"] == "global_fallback"
    assert report["strategy_targets"][0]["suggested_action"] == "improve_candidate_coverage"
    assert report["top_calibration_target"]["target_type"] == "risk_flag"
    assert report["guidance"]["status"] == "tune_risk_factors"
    assert report["top_calibration_target_hint"]["target_type"] == "risk_flag"
    assert report["top_calibration_target_hint"]["target_name"] == "is_occupied"
    assert "adjust_risk_factor_override_is_occupied" in report["top_calibration_target_hint"]["recommended_actions"]
    assert "python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied" in report["top_calibration_target_hint"]["suggested_commands"]
    assert "python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied --write" in report["top_calibration_target_hint"]["suggested_commands"]


def test_suggest_calibration_targets_returns_empty_when_metrics_are_stable():
    report = suggest_calibration_targets(
        {
            "risk_flag_metrics": [
                {
                    "group": "is_occupied",
                    "sample_count": 2,
                    "mape_pct": 8.0,
                    "mean_bias_pct": 2.0,
                    "p90_ape_pct": 12.0,
                }
            ],
            "strategy_metrics": [
                {
                    "group": "spatial",
                    "sample_count": 10,
                    "mape_pct": 6.0,
                    "mean_bias_pct": 1.5,
                    "p90_ape_pct": 10.0,
                }
            ],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["has_recommendations"] is False
    assert report["risk_factor_targets"] == []
    assert report["temporal_targets"] == []
    assert report["strategy_targets"] == []
    assert report["top_calibration_target"] is None
    assert report["guidance"]["status"] == "no_action_required"
    assert report["config_patch"]["risk_factor_overrides"] == {}


def test_suggest_calibration_targets_uses_effective_risk_factor_map(monkeypatch):
    monkeypatch.setattr(
        "tools.suggest_avm_calibration_targets.get_effective_risk_factor_map",
        lambda: {"is_occupied": 0.5},
    )

    report = suggest_calibration_targets(
        {
            "risk_flag_metrics": [
                {
                    "group": "is_occupied",
                    "sample_count": 6,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 9.5,
                    "p90_ape_pct": 30.0,
                }
            ],
            "strategy_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["risk_factor_targets"][0]["current_factor"] == 0.5


def test_suggest_calibration_targets_can_surface_global_risk_discount_factor(monkeypatch):
    monkeypatch.setattr(
        "tools.suggest_avm_calibration_targets.get_effective_risk_discount_factor",
        lambda default=0.9: 0.9,
    )

    report = suggest_calibration_targets(
        {
            "risk_flag_metrics": [
                {
                    "group": "is_occupied",
                    "sample_count": 8,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 9.0,
                    "p90_ape_pct": 30.0,
                },
                {
                    "group": "has_long_lease",
                    "sample_count": 6,
                    "mape_pct": 16.0,
                    "mean_bias_pct": 7.0,
                    "p90_ape_pct": 26.0,
                },
            ],
            "strategy_metrics": [],
            "valuation_mode_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["global_risk_targets"][0]["name"] == "risk_discount_factor"
    assert report["global_risk_targets"][0]["suggested_action"] == "strengthen_global_risk_discount"
    assert report["config_patch"]["risk_discount_factor"] > 0.9
    assert report["top_calibration_target"]["name"] == "risk_discount_factor"
    assert report["guidance"]["status"] == "tune_global_risk_discount"
    assert report["top_calibration_target_hint"]["playbook_id"] == "tune-global-risk-discount"
    assert "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-name risk_discount_factor" in report["top_calibration_target_hint"]["suggested_commands"]
    assert "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-name risk_discount_factor --write" in report["top_calibration_target_hint"]["suggested_commands"]


def test_suggest_calibration_targets_can_surface_temporal_global_risk_bundle_commands(monkeypatch):
    monkeypatch.setattr(
        "tools.suggest_avm_calibration_targets.get_effective_risk_discount_factor",
        lambda default=0.9: 0.9,
    )
    monkeypatch.setattr(
        "tools.suggest_avm_calibration_targets.get_effective_weighting",
        lambda defaults=None: {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
    )

    report = suggest_calibration_targets(
        {
            "risk_flag_metrics": [
                {
                    "group": "is_occupied",
                    "sample_count": 8,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 9.0,
                    "p90_ape_pct": 30.0,
                },
                {
                    "group": "has_long_lease",
                    "sample_count": 6,
                    "mape_pct": 16.0,
                    "mean_bias_pct": 7.0,
                    "p90_ape_pct": 26.0,
                },
            ],
            "valuation_mode_metrics": [
                {
                    "group": "historical_strict",
                    "sample_count": 12,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 8.0,
                    "p90_ape_pct": 30.0,
                },
                {
                    "group": "current_market",
                    "sample_count": 12,
                    "mape_pct": 8.0,
                    "mean_bias_pct": 2.0,
                    "p90_ape_pct": 16.0,
                },
            ],
            "strategy_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    bundle_commands = report["top_calibration_target_hint"]["suggested_bundle_commands"]
    assert "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal" in bundle_commands
    assert "python tools/apply_avm_calibration_patch.py --target-type global_risk --target-type temporal --write" in bundle_commands


def test_suggest_calibration_targets_can_surface_multi_risk_flag_bundle_commands():
    report = suggest_calibration_targets(
        {
            "risk_flag_metrics": [
                {
                    "group": "is_occupied",
                    "sample_count": 8,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 9.0,
                    "p90_ape_pct": 30.0,
                },
                {
                    "group": "has_long_lease",
                    "sample_count": 6,
                    "mape_pct": 16.0,
                    "mean_bias_pct": -7.0,
                    "p90_ape_pct": 26.0,
                },
            ],
            "strategy_metrics": [],
            "valuation_mode_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    bundle_commands = report["top_calibration_target_hint"]["suggested_bundle_commands"]
    assert "python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied --target-name has_long_lease" in bundle_commands
    assert "python tools/apply_avm_calibration_patch.py --target-type risk_flag --target-name is_occupied --target-name has_long_lease --write" in bundle_commands


def test_suggest_calibration_targets_surfaces_temporal_time_decay_target(monkeypatch):
    monkeypatch.setattr(
        "tools.suggest_avm_calibration_targets.get_effective_weighting",
        lambda defaults=None: {"distance_power": 2.0, "time_decay": 0.85, "community_boost": 1.3},
    )

    report = suggest_calibration_targets(
        {
            "valuation_mode_metrics": [
                {
                    "group": "historical_strict",
                    "sample_count": 12,
                    "mape_pct": 18.0,
                    "mean_bias_pct": 8.0,
                    "p90_ape_pct": 30.0,
                },
                {
                    "group": "current_market",
                    "sample_count": 12,
                    "mape_pct": 8.0,
                    "mean_bias_pct": 2.0,
                    "p90_ape_pct": 16.0,
                },
            ],
            "risk_flag_metrics": [],
            "strategy_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["has_recommendations"] is True
    assert report["temporal_targets"][0]["name"] == "time_decay"
    assert report["temporal_targets"][0]["suggested_action"] == "strengthen_time_decay"
    assert report["temporal_targets"][0]["suggested_next_value"] < report["temporal_targets"][0]["current_value"]
    assert report["config_patch"]["weighting"]["time_decay"] == report["temporal_targets"][0]["suggested_next_value"]
    assert report["guidance"]["status"] == "tune_temporal_decay"
    assert report["top_calibration_target_hint"]["target_type"] == "temporal"
    assert report["top_calibration_target_hint"]["target_name"] == "time_decay"
    assert report["top_calibration_target_hint"]["playbook_id"] == "tune-temporal-decay"
    assert "tools/evaluate_avm.py" in report["top_calibration_target_hint"]["runbook_refs"]
    assert "adjust_weighting_time_decay" in report["top_calibration_target_hint"]["recommended_actions"]
    assert "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay" in report["top_calibration_target_hint"]["suggested_commands"]
    assert "python tools/apply_avm_calibration_patch.py --target-type temporal --target-name time_decay --write" in report["top_calibration_target_hint"]["suggested_commands"]
    assert "python tools/evaluate_avm.py" in report["top_calibration_target_hint"]["suggested_commands"]
    assert "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report" in report["top_calibration_target_hint"]["suggested_commands"]


def test_suggest_calibration_targets_can_prioritize_risk_data_quality():
    report = suggest_calibration_targets(
        {
            "risk_validation_metrics": [
                {
                    "group": "ok",
                    "sample_count": 20,
                    "mape_pct": 7.0,
                    "mean_bias_pct": 1.0,
                    "p90_ape_pct": 12.0,
                },
                {
                    "group": "invalid",
                    "sample_count": 6,
                    "mape_pct": 24.0,
                    "mean_bias_pct": 9.0,
                    "p90_ape_pct": 38.0,
                },
            ],
            "risk_flag_metrics": [],
            "strategy_metrics": [],
            "valuation_mode_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["guidance"]["status"] == "fix_risk_data_quality"
    assert report["guidance"]["priority"] == "high"
    assert "review_risk_validation_cohorts" in report["guidance"]["recommended_actions"]


def test_suggest_calibration_targets_can_prioritize_coordinate_quality():
    report = suggest_calibration_targets(
        {
            "coordinate_strategy_metrics": [
                {
                    "group": "observed",
                    "sample_count": 20,
                    "mape_pct": 7.0,
                    "mean_bias_pct": 1.0,
                    "p90_ape_pct": 12.0,
                },
                {
                    "group": "district_centroid",
                    "sample_count": 6,
                    "mape_pct": 22.0,
                    "mean_bias_pct": 8.0,
                    "p90_ape_pct": 35.0,
                },
            ],
            "risk_validation_metrics": [],
            "risk_flag_metrics": [],
            "strategy_metrics": [],
            "valuation_mode_metrics": [],
        },
        min_sample_count=3,
        bias_threshold_pct=5.0,
        mape_threshold_pct=12.0,
    )

    assert report["guidance"]["status"] == "fix_coordinate_quality"
    assert report["guidance"]["priority"] == "high"
    assert "review_coordinate_strategy_cohorts" in report["guidance"]["recommended_actions"]
    assert report["top_calibration_target_hint"]["status"] == "coordinate_quality_priority"
    assert report["top_calibration_target_hint"]["playbook_id"] == "fix-coordinate-quality"
    assert "tools/run_recent_enrich_maintenance.py" in report["top_calibration_target_hint"]["runbook_refs"]
    assert "python tools/run_recent_enrich_maintenance.py --dry-run" in report["top_calibration_target_hint"]["suggested_commands"]
