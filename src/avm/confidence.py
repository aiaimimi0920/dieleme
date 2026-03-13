"""AVM 估值置信度融合计算。"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any

from .config import CONFIDENCE_RULES


@dataclass(frozen=True)
class ConfidenceInput:
    """置信度输入因子。"""

    comparable_sample_count: int
    comparable_distances_m: list[float]
    time_span_days: int
    key_field_completeness_rate: float


@dataclass(frozen=True)
class ConfidenceResult:
    """置信度输出。"""

    score: float
    explanation: str
    factors: dict[str, float]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]

    index = (len(sorted_values) - 1) * p
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _score_sample_count(count: int, rules: dict[str, Any]) -> float:
    return _clamp(_safe_ratio(max(0, count), rules["target"]))


def _score_distance_distribution(distances_m: list[float], rules: dict[str, Any]) -> float:
    if not distances_m:
        return 0.0

    cleaned = [d for d in distances_m if d >= 0]
    if not cleaned:
        return 0.0

    sorted_d = sorted(cleaned)
    mean_distance = mean(sorted_d)
    p90_distance = _percentile(sorted_d, 0.9)

    mean_score = 1 - _clamp(
        _safe_ratio(mean_distance - rules["ideal_mean_m"], rules["max_mean_m"] - rules["ideal_mean_m"])
    )
    p90_score = 1 - _clamp(_safe_ratio(p90_distance, rules["max_p90_m"]))

    return _clamp(0.7 * mean_score + 0.3 * p90_score)


def _score_time_span(days: int, rules: dict[str, Any]) -> float:
    days = max(0, days)

    if days <= rules["target_days"]:
        return _clamp(_safe_ratio(days, rules["target_days"]))

    if days <= rules["stale_days"]:
        # 覆盖范围足够后保持高分
        return 1.0

    # 过旧样本占比可能变高，轻微折损（不低于 0.7）
    overshoot = days - rules["stale_days"]
    penalty = _clamp(_safe_ratio(overshoot, rules["stale_days"])) * 0.3
    return _clamp(1.0 - penalty, 0.7, 1.0)


def _score_field_completeness(rate: float) -> float:
    return _clamp(rate)


def calculate_confidence(
    comparable_sample_count: int,
    comparable_distances_m: list[float],
    time_span_days: int,
    key_field_completeness_rate: float,
    rules: dict[str, Any] | None = None,
) -> ConfidenceResult:
    """融合可比样本数量、距离分布、时间跨度、关键字段完整率，输出 0-1 置信度及解释文本。"""

    active_rules = rules or CONFIDENCE_RULES
    weights = active_rules["weights"]

    factor_scores = {
        "sample_count": _score_sample_count(comparable_sample_count, active_rules["sample_count"]),
        "distance_distribution": _score_distance_distribution(
            comparable_distances_m, active_rules["distance_distribution"]
        ),
        "time_span": _score_time_span(time_span_days, active_rules["time_span"]),
        "field_completeness": _score_field_completeness(key_field_completeness_rate),
    }

    total_weight = sum(weights.values()) or 1.0
    final_score = sum(factor_scores[k] * weights.get(k, 0.0) for k in factor_scores) / total_weight
    final_score = round(_clamp(final_score), 4)

    explanation = _build_explanation(
        final_score=final_score,
        comparable_sample_count=comparable_sample_count,
        comparable_distances_m=comparable_distances_m,
        time_span_days=time_span_days,
        key_field_completeness_rate=key_field_completeness_rate,
        factor_scores=factor_scores,
        rules=active_rules,
    )

    return ConfidenceResult(score=final_score, explanation=explanation, factors=factor_scores)


def _build_explanation(
    final_score: float,
    comparable_sample_count: int,
    comparable_distances_m: list[float],
    time_span_days: int,
    key_field_completeness_rate: float,
    factor_scores: dict[str, float],
    rules: dict[str, Any],
) -> str:
    banding = rules["banding"]

    if final_score >= banding["high"]:
        level = "高"
    elif final_score >= banding["medium"]:
        level = "中"
    elif final_score >= banding["low"]:
        level = "偏低"
    else:
        level = "低"

    avg_distance = mean(comparable_distances_m) if comparable_distances_m else 0.0

    notes: list[str] = []
    if comparable_sample_count < rules["sample_count"]["weak_threshold"]:
        notes.append("可比样本数量偏少")
    if time_span_days < rules["time_span"]["weak_days"]:
        notes.append("时间覆盖跨度不足")
    if key_field_completeness_rate < rules["field_completeness"]["weak_threshold"]:
        notes.append("关键字段完整率偏低")
    if avg_distance > rules["distance_distribution"]["max_mean_m"]:
        notes.append("可比样本整体距离偏远")

    note_text = "；".join(notes) if notes else "各核心维度表现均衡"

    return (
        f"综合置信度={final_score:.4f}（{level}）。"
        f"样本量得分{factor_scores['sample_count']:.2f}（n={comparable_sample_count}），"
        f"距离分布得分{factor_scores['distance_distribution']:.2f}（平均距离{avg_distance:.0f}m），"
        f"时间跨度得分{factor_scores['time_span']:.2f}（{time_span_days}天），"
        f"关键字段完整率得分{factor_scores['field_completeness']:.2f}（{key_field_completeness_rate:.1%}）。"
        f"解释：{note_text}。"
    )
