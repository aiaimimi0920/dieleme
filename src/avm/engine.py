from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


EARTH_RADIUS_KM = 6371.0088
DEFAULT_SEARCH_RADIUS_KM = 3.0


# 风控因子：<1 代表折价，>1 代表正向修正
RISK_FACTOR_MAP: Dict[str, float] = {
    "is_occupied": 0.88,
    "has_long_lease": 0.86,
    "clear_delivery": 0.93,  # 当为 False 时触发
    "land_right_type": 0.95,  # 当为 划拨 时触发
    "tax_is_company_owned": 0.94,
    "is_fractional_share": 0.83,
    "is_haunted": 0.80,
    "has_lease_before_mortgage": 1.04,
}


def _get(record: Dict[str, Any], key: str, default: Any = None) -> Any:
    return record.get(key, default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _distance_weight(distance_km: float, method: str = "hybrid", idw_power: float = 2.0, sigma_km: float = 1.2) -> float:
    # 增加下限，避免 d=0 造成极端爆炸
    d = max(distance_km, 0.03)
    idw_w = 1.0 / (d**idw_power)
    gauss_w = math.exp(-0.5 * (distance_km / max(sigma_km, 1e-3)) ** 2)
    if method == "idw":
        return idw_w
    if method == "gaussian":
        return gauss_w
    # hybrid: 同时保留局部强敏感和全域平滑
    return idw_w * gauss_w


def _fit_polynomial(xs: Sequence[float], ys: Sequence[float], degree: int = 1) -> Tuple[float, ...]:
    """
    轻量回归：
    degree=1: y = a + b*x
    degree=2: y = a + b*x + c*x^2
    """
    if len(xs) != len(ys) or not xs:
        return (0.0,)

    n = len(xs)
    if degree <= 1 or n < 3:
        sx = sum(xs)
        sy = sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        den = n * sxx - sx * sx
        if abs(den) < 1e-12:
            return (sy / n, 0.0)
        b = (n * sxy - sx * sy) / den
        a = (sy - b * sx) / n
        return (a, b)

    # degree=2 正规方程求解
    sx = sum(xs)
    sx2 = sum(x**2 for x in xs)
    sx3 = sum(x**3 for x in xs)
    sx4 = sum(x**4 for x in xs)
    sy = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sx2y = sum((x**2) * y for x, y in zip(xs, ys))

    # 高斯消元解 3x3
    mat = [
        [float(n), sx, sx2, sy],
        [sx, sx2, sx3, sxy],
        [sx2, sx3, sx4, sx2y],
    ]

    for i in range(3):
        pivot = i
        for r in range(i + 1, 3):
            if abs(mat[r][i]) > abs(mat[pivot][i]):
                pivot = r
        if abs(mat[pivot][i]) < 1e-12:
            return _fit_polynomial(xs, ys, degree=1)
        if pivot != i:
            mat[i], mat[pivot] = mat[pivot], mat[i]

        div = mat[i][i]
        for c in range(i, 4):
            mat[i][c] /= div
        for r in range(3):
            if r == i:
                continue
            factor = mat[r][i]
            for c in range(i, 4):
                mat[r][c] -= factor * mat[i][c]

    a, b, c = mat[0][3], mat[1][3], mat[2][3]
    return (a, b, c)


def _eval_poly(coeffs: Sequence[float], x: float) -> float:
    if len(coeffs) == 1:
        return coeffs[0]
    if len(coeffs) == 2:
        return coeffs[0] + coeffs[1] * x
    return coeffs[0] + coeffs[1] * x + coeffs[2] * x * x


def _risk_adjustment(subject: Dict[str, Any]) -> Tuple[float, List[str]]:
    factor = 1.0
    reasons: List[str] = []

    def apply(multiplier: float, label: str) -> None:
        nonlocal factor
        factor *= multiplier
        reasons.append(label)

    if _get(subject, "is_occupied") is True:
        apply(RISK_FACTOR_MAP["is_occupied"], "占用未腾退折价")
    if _get(subject, "has_long_lease") is True:
        apply(RISK_FACTOR_MAP["has_long_lease"], "长期租约折价")
    if _get(subject, "clear_delivery") is False:
        apply(RISK_FACTOR_MAP["clear_delivery"], "法院不负责清场折价")
    if _get(subject, "land_right_type") == "划拨":
        apply(RISK_FACTOR_MAP["land_right_type"], "划拨土地折价")
    if _get(subject, "tax_is_company_owned") is True:
        apply(RISK_FACTOR_MAP["tax_is_company_owned"], "企业产权税费折价")
    if _get(subject, "is_fractional_share") is True:
        apply(RISK_FACTOR_MAP["is_fractional_share"], "部分产权折价")
    if _get(subject, "is_haunted") is True:
        apply(RISK_FACTOR_MAP["is_haunted"], "重大负面事件折价")
    if _get(subject, "has_lease_before_mortgage") is True:
        apply(RISK_FACTOR_MAP["has_lease_before_mortgage"], "先抵后租可套利正向修正")

    return factor, reasons


def predict_fair_price(subject: Dict[str, Any], comparables: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """
    估值主函数（空间加权 -> 时间校准 -> 风控修正）

    Args:
        subject: 待估标的（至少需包含经纬度/面积/区域标签）
        comparables: 历史成交样本列表

    Returns:
        {
          predicted_price: 预测总价（元）,
          confidence: 0~1,
          comparable_count: 参与估值的样本数,
          top_factors: 可解释性因子列表
        }
    """
    subject_lat = _to_float(_get(subject, "latitude"), float("nan"))
    subject_lon = _to_float(_get(subject, "longitude"), float("nan"))
    subject_area = max(_to_float(_get(subject, "area_sqm"), 0.0), 1e-6)
    subject_community = _get(subject, "community_name")
    subject_business = _get(subject, "business_district") or _get(subject, "biz_circle")
    subject_district = _get(subject, "district")

    filtered: List[Tuple[Dict[str, Any], float, float]] = []
    for comp in comparables:
        lat = _to_float(_get(comp, "latitude"), float("nan"))
        lon = _to_float(_get(comp, "longitude"), float("nan"))
        if math.isnan(subject_lat) or math.isnan(subject_lon) or math.isnan(lat) or math.isnan(lon):
            continue
        dist = _haversine_km(subject_lat, subject_lon, lat, lon)
        if dist > DEFAULT_SEARCH_RADIUS_KM:
            continue

        price = _to_float(_get(comp, "actual_paid_price") or _get(comp, "transaction_price"), 0.0)
        area = max(_to_float(_get(comp, "area_sqm"), 0.0), 1e-6)
        if price <= 0:
            continue

        unit_price = price / area
        weight = _distance_weight(dist, method="hybrid")

        if subject_community and _get(comp, "community_name") == subject_community:
            weight *= 1.8
        if subject_business and (_get(comp, "business_district") == subject_business or _get(comp, "biz_circle") == subject_business):
            weight *= 1.35
        if subject_district and _get(comp, "district") and _get(comp, "district") != subject_district:
            weight *= 0.72

        filtered.append((comp, unit_price, weight))

    if not filtered:
        return {
            "predicted_price": None,
            "confidence": 0.0,
            "comparable_count": 0,
            "top_factors": ["3km范围内缺少有效可比样本"],
        }

    # 1) 空间层结果
    sum_w = sum(w for _, _, w in filtered)
    spatial_unit_price = sum(up * w for _, up, w in filtered) / max(sum_w, 1e-12)

    # 2) 时间层：按(区, 商圈)聚合后做趋势回归，并校准到当前时点
    grouped: Dict[Tuple[Any, Any], List[Tuple[datetime, float]]] = defaultdict(list)
    for comp, up, _ in filtered:
        key = (_get(comp, "district"), _get(comp, "business_district") or _get(comp, "biz_circle"))
        dt = _parse_dt(_get(comp, "auction_date"))
        if dt is not None:
            grouped[key].append((dt, up))

    target_key = (subject_district, subject_business)
    trend_points = grouped.get(target_key) or grouped.get((subject_district, None))

    temporal_factor = 1.0
    temporal_note = "时间趋势样本不足，使用空间层基线"

    if trend_points and len(trend_points) >= 2:
        trend_points.sort(key=lambda x: x[0])
        start = trend_points[0][0]
        xs = [max((dt - start).days, 0) / 30.0 for dt, _ in trend_points]
        ys = [p for _, p in trend_points]
        coeffs = _fit_polynomial(xs, ys, degree=2 if len(xs) >= 5 else 1)
        latest_x = xs[-1]
        now_x = max((datetime.now() - start).days, 0) / 30.0

        base_now = _eval_poly(coeffs, now_x)
        base_latest = _eval_poly(coeffs, latest_x)
        if base_latest > 0:
            temporal_factor = max(0.75, min(1.25, base_now / base_latest))
            temporal_note = f"时间趋势校准系数={temporal_factor:.3f}"

    temporal_unit_price = spatial_unit_price * temporal_factor

    # 3) 风控层修正
    risk_factor, risk_reasons = _risk_adjustment(subject)
    adjusted_unit_price = temporal_unit_price * risk_factor
    predicted_price = adjusted_unit_price * subject_area

    # 置信度：样本量 + 权重集中度 + 时间有效性
    n = len(filtered)
    sample_conf = min(1.0, n / 20.0)
    weight_entropy = 0.0
    for _, _, w in filtered:
        p = w / max(sum_w, 1e-12)
        if p > 0:
            weight_entropy -= p * math.log(p)
    max_entropy = math.log(max(n, 2))
    concentration = 1.0 - min(1.0, weight_entropy / max(max_entropy, 1e-12))
    trend_conf = 1.0 if temporal_note.startswith("时间趋势校准") else 0.6
    confidence = 0.45 * sample_conf + 0.30 * (1.0 - concentration) + 0.25 * trend_conf
    confidence = max(0.0, min(1.0, confidence))

    top_factors = [
        f"空间加权单价={spatial_unit_price:.0f}元/㎡",
        temporal_note,
        f"风控修正系数={risk_factor:.3f}",
    ]
    top_factors.extend(risk_reasons[:3])

    return {
        "predicted_price": round(predicted_price, 2),
        "confidence": round(confidence, 4),
        "comparable_count": n,
        "top_factors": top_factors,
    }
