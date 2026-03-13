"""AVM 空间权重模块。

提供距离衰减（高斯或 IDW）、位置关系加权（同小区/同商圈/跨行政区）
以及归一化输出，避免极端值主导估价结果。
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def distance_weight_km(
    d: float,
    method: str = "gaussian",
    sigma_km: float = 0.9,
    idw_power: float = 1.6,
    min_weight: float = 0.05,
    max_weight: float = 1.0,
    idw_softening_km: float = 0.08,
) -> float:
    """根据公里距离计算基础权重。

    Args:
        d: 距离（公里）。
        method: "gaussian" 或 "idw"。
        sigma_km: 高斯衰减参数（越小衰减越快）。
        idw_power: IDW 幂指数。
        min_weight: 下限，防止过小导致完全失真。
        max_weight: 上限，防止极近样本权重爆炸。
        idw_softening_km: IDW 平滑项，避免 d=0 时无穷大。

    Returns:
        截断后的基础距离权重。
    """
    d = max(float(d), 0.0)
    method = (method or "gaussian").lower().strip()

    if method == "gaussian":
        # w = exp(-d^2 / (2*sigma^2))
        sigma = max(sigma_km, 1e-6)
        raw_weight = math.exp(-(d * d) / (2.0 * sigma * sigma))
    elif method == "idw":
        # w = 1 / (d + s)^p
        power = max(idw_power, 1e-6)
        softening = max(idw_softening_km, 1e-6)
        raw_weight = 1.0 / math.pow(d + softening, power)
        # 映射到 (0,1]：w' = w/(1+w)
        raw_weight = raw_weight / (1.0 + raw_weight)
    else:
        raise ValueError(f"Unsupported distance method: {method}")

    return _clamp(raw_weight, min_weight, max_weight)


def location_multiplier(
    same_community: bool,
    same_business_area: bool,
    same_district: bool,
    same_community_boost: float = 1.8,
    same_business_boost: float = 1.2,
    cross_district_penalty: float = 0.7,
    min_multiplier: float = 0.3,
    max_multiplier: float = 2.0,
) -> float:
    """位置关系倍率：同小区 > 同商圈 > 跨行政区惩罚。"""
    multiplier = 1.0

    if same_community:
        multiplier *= same_community_boost
    if same_business_area:
        multiplier *= same_business_boost
    if not same_district:
        multiplier *= cross_district_penalty

    return _clamp(multiplier, min_multiplier, max_multiplier)


def normalize_weights(
    raw_weights: Iterable[float],
    floor_share: float = 0.02,
) -> List[float]:
    """将权重归一化为和为 1，同时做地板保护以避免极端值。

    floor_share: 每个样本最小占比（最终会再次归一化）。
    """
    weights = [max(float(w), 0.0) for w in raw_weights]
    if not weights:
        return []

    total = sum(weights)
    if total <= 0:
        return [1.0 / len(weights)] * len(weights)

    normalized = [w / total for w in weights]

    if floor_share > 0:
        normalized = [max(w, floor_share) for w in normalized]
        total_after_floor = sum(normalized)
        normalized = [w / total_after_floor for w in normalized]

    return normalized


def compute_location_weights(
    comparables: List[Dict[str, object]],
    *,
    distance_method: str = "gaussian",
) -> List[float]:
    """按距离和位置关系计算可比样本权重并归一化。

    comparables 每项支持字段：
    - distance_km: float
    - same_community: bool
    - same_business_area: bool
    - same_district: bool
    """
    raw: List[float] = []
    for item in comparables:
        dw = distance_weight_km(float(item.get("distance_km", 0.0)), method=distance_method)
        lm = location_multiplier(
            bool(item.get("same_community", False)),
            bool(item.get("same_business_area", False)),
            bool(item.get("same_district", True)),
        )
        raw.append(dw * lm)

    return normalize_weights(raw)
