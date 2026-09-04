"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_suggestion_context import *


def _risk_flag_action(flag: str, mean_bias_pct: float) -> str:
    if mean_bias_pct > 0:
        return "lower_price_contribution"
    return "raise_price_contribution"


def _suggest_factor_step_pct(mean_bias_pct: float) -> float:
    return round(min(max(abs(mean_bias_pct) * 0.5, 2.0), 10.0), 4)


def _suggest_next_factor(current_factor: float | None, suggested_action: str, step_pct: float) -> float | None:
    if current_factor is None:
        return None
    step = step_pct / 100.0
    if suggested_action == "lower_price_contribution":
        return round(current_factor * (1.0 - step), 6)
    return round(current_factor * (1.0 + step), 6)


def _strategy_action(name: str) -> str:
    if name in {"global_fallback", "city_fallback", "district_fallback", "business_area_fallback"}:
        return "improve_candidate_coverage"
    return "review_weighting_and_filters"


def _temporal_action(mean_bias_pct: float) -> str:
    if mean_bias_pct > 0:
        return "strengthen_time_decay"
    return "relax_time_decay"


def _global_risk_discount_action(mean_bias_pct: float) -> str:
    if mean_bias_pct > 0:
        return "strengthen_global_risk_discount"
    return "relax_global_risk_discount"


def _suggest_next_time_decay(current_value: float | None, suggested_action: str, step_pct: float) -> float | None:
    if current_value is None:
        return None
    step = step_pct / 100.0
    if suggested_action == "strengthen_time_decay":
        return round(max(0.05, current_value * (1.0 - step)), 6)
    return round(min(1.0, current_value * (1.0 + step)), 6)


def _suggest_next_risk_discount_factor(current_value: float | None, suggested_action: str, step_pct: float) -> float | None:
    if current_value is None:
        return None
    step = step_pct / 100.0
    if suggested_action == "strengthen_global_risk_discount":
        return round(min(2.0, current_value * (1.0 + step)), 6)
    return round(max(0.05, current_value * (1.0 - step)), 6)


__all__ = (
    "_risk_flag_action",
    "_suggest_factor_step_pct",
    "_suggest_next_factor",
    "_strategy_action",
    "_temporal_action",
    "_global_risk_discount_action",
    "_suggest_next_time_decay",
    "_suggest_next_risk_discount_factor",
)
