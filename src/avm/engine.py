"""AVM engine helpers.

This module currently exposes risk adjustment utilities used by valuation logic.
"""

from __future__ import annotations

from typing import Any, Mapping

DEFAULT_RISK_WEIGHTS = {
    "occupation": -0.08,
    "allocated": -0.12,
    "enterprise_property_tax": -0.03,
    "long_term_lease": -0.05,
}

DEFAULT_LEASE_BEFORE_MORTGAGE_BONUS = 0.02
DEFAULT_LEASE_BEFORE_MORTGAGE_CAP = 0.03


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def risk_adjustment(risk_features: Mapping[str, Any] | None) -> float:
    """Compute valuation risk adjustment ratio.

    Negative factors are applied when the corresponding flags are truthy:
      - ``occupation``
      - ``allocated``
      - ``enterprise_property_tax``
      - ``long_term_lease``

    Special positive factor:
      - If ``has_lease_before_mortgage`` is truthy, a moderate positive adjustment
        is applied. The bonus is capped by a configurable upper bound.

    Configurable keys in ``risk_features``:
      - ``risk_weights``: dict overriding weights for negative factors.
      - ``lease_before_mortgage_bonus``: proposed positive bonus (default 0.02).
      - ``lease_before_mortgage_cap``: maximum allowed positive bonus (default 0.03).

    Returns:
        float: Adjustment ratio to apply to baseline valuation.
    """
    if not risk_features:
        return 0.0

    weights = dict(DEFAULT_RISK_WEIGHTS)
    custom_weights = risk_features.get("risk_weights")
    if isinstance(custom_weights, Mapping):
        for key, value in custom_weights.items():
            if key in weights:
                weights[key] = _to_float(value, weights[key])

    adjustment = 0.0
    for factor, weight in weights.items():
        if _to_bool(risk_features.get(factor)):
            adjustment += weight

    if _to_bool(risk_features.get("has_lease_before_mortgage")):
        proposed_bonus = _to_float(
            risk_features.get(
                "lease_before_mortgage_bonus", DEFAULT_LEASE_BEFORE_MORTGAGE_BONUS
            ),
            DEFAULT_LEASE_BEFORE_MORTGAGE_BONUS,
        )
        cap = max(
            0.0,
            _to_float(
                risk_features.get(
                    "lease_before_mortgage_cap", DEFAULT_LEASE_BEFORE_MORTGAGE_CAP
                ),
                DEFAULT_LEASE_BEFORE_MORTGAGE_CAP,
            ),
        )
        adjustment += min(max(proposed_bonus, 0.0), cap)

    return adjustment
