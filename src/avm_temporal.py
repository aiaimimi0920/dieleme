from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple


Region = Dict[str, str]
Record = Dict[str, object]


@dataclass
class TrendModel:
    """Simple polynomial trend model on monthly average unit prices."""

    degree: int
    coefficients: Tuple[float, ...]
    anchor_date: date
    latest_date: date
    sample_count: int

    def predict(self, target_date: date) -> float:
        t = _months_between(self.anchor_date, target_date)
        if self.degree == 0:
            return self.coefficients[0]
        if self.degree == 1:
            b0, b1 = self.coefficients
            return b0 + b1 * t
        b0, b1, b2 = self.coefficients
        return b0 + b1 * t + b2 * (t ** 2)


class TemporalAdjuster:
    """Aggregate historical deals by city/district/business_area and estimate trend."""

    def __init__(self, records: Iterable[Record], current_date: Optional[date] = None, time_decay: float = 1.0):
        self.current_date = current_date or date.today()
        self.time_decay = _normalize_time_decay(time_decay)
        self._models: Dict[Tuple[str, str, str], TrendModel] = {}
        self._build(records)

    def temporal_adjust(self, price: float, subject_date: object, region: Region) -> float:
        factor, _ = self.trend_factor(
            region=region,
            target_date=self.current_date,
            reference_date=subject_date,
            clamp=None,
        )
        if factor <= 0:
            return float(price)
        return float(price) * factor

    def trend_factor(
        self,
        region: Region,
        target_date: object,
        reference_date: object | None = None,
        clamp: Tuple[float, float] | None = None,
    ) -> Tuple[float, int]:
        model = self._select_model(region)
        if model is None:
            return 1.0, 0

        target = _parse_date(target_date)
        if not target:
            return 1.0, model.sample_count

        reference = _parse_date(reference_date) if reference_date is not None else model.latest_date
        if not reference:
            return 1.0, model.sample_count

        target_value = max(model.predict(target), 1.0)
        reference_value = max(model.predict(reference), 1.0)
        factor = target_value / reference_value
        month_gap = abs(_months_between(reference, target))
        if month_gap > 0 and self.time_decay < 1.0:
            dampening = self.time_decay ** month_gap
            factor = 1.0 + (factor - 1.0) * dampening
        if clamp is not None:
            low, high = clamp
            factor = max(low, min(high, factor))
        return float(factor), model.sample_count

    def _build(self, records: Iterable[Record]) -> None:
        grouped: Dict[Tuple[str, str, str], Dict[date, List[float]]] = defaultdict(lambda: defaultdict(list))
        raw_counts: Dict[Tuple[str, str, str], int] = defaultdict(int)

        for row in records:
            normalized = _normalize_region(
                {
                    "city": row.get("city"),
                    "district": row.get("district"),
                    "business_area": row.get("business_area"),
                }
            )
            deal_date = _parse_date(row.get("auction_date") or row.get("subject_date") or row.get("date"))
            unit_price = _extract_unit_price(row)
            if not deal_date or not unit_price or unit_price <= 0:
                continue

            month_date = date(deal_date.year, deal_date.month, 1)
            city, district, business_area = normalized
            keys = {
                normalized,
                (city, district, "*"),
                (city, "*", "*"),
                ("*", "*", "*"),
            }
            for region_key in keys:
                grouped[region_key][month_date].append(unit_price)
                raw_counts[region_key] += 1

        for region_key, month_map in grouped.items():
            points = sorted((month, sum(values) / len(values)) for month, values in month_map.items())
            if not points:
                continue
            self._models[region_key] = _fit_model(points, sample_count=raw_counts[region_key])

    def _select_model(self, region: Region) -> Optional[TrendModel]:
        city = (region.get("city") or "").strip().lower()
        district = (region.get("district") or "").strip().lower()
        business_area = (region.get("business_area") or "").strip().lower()

        candidates = [
            (city, district, business_area),
            (city, district, "*"),
            (city, "*", "*"),
            ("*", "*", "*"),
        ]

        for key in candidates:
            model = self._models.get(key)
            if model:
                return model
        return None


def _fit_model(points: List[Tuple[date, float]], sample_count: int) -> TrendModel:
    anchor_date = points[0][0]
    latest_date = points[-1][0]
    x = [_months_between(anchor_date, d) for d, _ in points]
    y = [v for _, v in points]

    if len(points) >= 6:
        coeffs = _polyfit_quadratic(x, y)
        degree = 2
    elif len(points) >= 2:
        coeffs = _polyfit_linear(x, y)
        degree = 1
    else:
        coeffs = (float(y[0]),)
        degree = 0

    return TrendModel(
        degree=degree,
        coefficients=coeffs,
        anchor_date=anchor_date,
        latest_date=latest_date,
        sample_count=sample_count,
    )


def _polyfit_linear(x: List[int], y: List[float]) -> Tuple[float, float]:
    n = len(x)
    sx = float(sum(x))
    sy = float(sum(y))
    sxx = float(sum(v * v for v in x))
    sxy = float(sum(v * t for v, t in zip(x, y)))

    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return (sy / n, 0.0)

    b1 = (n * sxy - sx * sy) / denom
    b0 = (sy - b1 * sx) / n
    return (b0, b1)


def _polyfit_quadratic(x: List[int], y: List[float]) -> Tuple[float, float, float]:
    n = float(len(x))
    sx = float(sum(x))
    sx2 = float(sum(v ** 2 for v in x))
    sx3 = float(sum(v ** 3 for v in x))
    sx4 = float(sum(v ** 4 for v in x))
    sy = float(sum(y))
    sxy = float(sum(v * t for v, t in zip(x, y)))
    sx2y = float(sum((v ** 2) * t for v, t in zip(x, y)))

    matrix = [
        [n, sx, sx2, sy],
        [sx, sx2, sx3, sxy],
        [sx2, sx3, sx4, sx2y],
    ]
    solved = _gaussian_elimination(matrix)
    return (solved[0], solved[1], solved[2])


def _gaussian_elimination(matrix: List[List[float]]) -> List[float]:
    m = [row[:] for row in matrix]
    size = len(m)

    for pivot in range(size):
        best = max(range(pivot, size), key=lambda r: abs(m[r][pivot]))
        if abs(m[best][pivot]) < 1e-9:
            return [0.0, 0.0, 0.0]
        if best != pivot:
            m[pivot], m[best] = m[best], m[pivot]

        factor = m[pivot][pivot]
        m[pivot] = [value / factor for value in m[pivot]]

        for row in range(size):
            if row == pivot:
                continue
            scale = m[row][pivot]
            m[row] = [v - scale * p for v, p in zip(m[row], m[pivot])]

    return [m[i][-1] for i in range(size)]


def _extract_unit_price(row: Record) -> Optional[float]:
    for key in ("_neutral_unit_price", "neutral_unit_price", "unit_price", "单价"):
        value = row.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)

    area = row.get("area_sqm") or row.get("建筑面积")
    price = row.get("transaction_price") or row.get("成交价格")
    if isinstance(area, (int, float)) and isinstance(price, (int, float)) and area > 0 and price > 0:
        return float(price) / float(area)

    return None


def _normalize_region(region: Region) -> Tuple[str, str, str]:
    city = (region.get("city") or "").strip().lower()
    district = (region.get("district") or "").strip().lower()
    business_area = (region.get("business_area") or "").strip().lower()

    if not city:
        return ("*", "*", "*")
    if not district:
        return (city, "*", "*")
    if not business_area:
        return (city, district, "*")
    return (city, district, business_area)


def _parse_date(value: object) -> Optional[date]:
    if isinstance(value, date):
        return value
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_time_decay(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 1.0
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


_DEFAULT_ADJUSTER: Optional[TemporalAdjuster] = None


def configure_temporal_adjuster(records: Iterable[Record], current_date: Optional[date] = None) -> TemporalAdjuster:
    global _DEFAULT_ADJUSTER
    _DEFAULT_ADJUSTER = TemporalAdjuster(records, current_date=current_date)
    return _DEFAULT_ADJUSTER


def temporal_adjust(price: float, subject_date: object, region: Region) -> float:
    """Public API: adjust historical price to current date using regional trend."""
    if _DEFAULT_ADJUSTER is None:
        raise RuntimeError("Temporal adjuster is not configured. Call configure_temporal_adjuster(records) first.")
    return _DEFAULT_ADJUSTER.temporal_adjust(price, subject_date, region)


def temporal_factor(
    target_date: object,
    region: Region,
    reference_date: object | None = None,
    clamp: Tuple[float, float] | None = None,
) -> Tuple[float, int]:
    """Public API: compute a regional temporal coefficient and sample count."""
    if _DEFAULT_ADJUSTER is None:
        raise RuntimeError("Temporal adjuster is not configured. Call configure_temporal_adjuster(records) first.")
    return _DEFAULT_ADJUSTER.trend_factor(
        region=region,
        target_date=target_date,
        reference_date=reference_date,
        clamp=clamp,
    )
