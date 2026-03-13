#!/usr/bin/env python3
"""比较近 30 天与历史分布，计算核心特征 PSI 与简化漂移分，并输出告警。"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ARCHIVE_DIR = Path("datas/archive")
OUTPUT_PATH = Path("datas/avm/drift_alerts.json")

CORE_FEATURES = [
    "起拍价格",
    "成交价格",
    "建筑面积",
    "单价",
    "出价人数",
    "竞拍人数",
    "是否成交",
    "省份",
    "城市",
    "区",
]

NUMERIC_FEATURES = {
    "起拍价格",
    "成交价格",
    "建筑面积",
    "单价",
    "出价人数",
    "竞拍人数",
}

PSI_ALERT_THRESHOLD = 0.2
DRIFT_SCORE_ALERT_THRESHOLD = 0.3
EPS = 1e-6


@dataclass
class FeatureMetric:
    feature: str
    metric_type: str
    psi: float
    drift_score: float
    recent_count: int
    historical_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "metric_type": self.metric_type,
            "psi": round(self.psi, 6),
            "drift_score": round(self.drift_score, 6),
            "recent_count": self.recent_count,
            "historical_count": self.historical_count,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查核心特征分布漂移")
    parser.add_argument("--window-days", type=int, default=30, help="近期窗口天数，默认 30")
    parser.add_argument("--psi-threshold", type=float, default=PSI_ALERT_THRESHOLD)
    parser.add_argument("--drift-threshold", type=float, default=DRIFT_SCORE_ALERT_THRESHOLD)
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    return parser.parse_args()


def parse_trade_date(record: dict[str, Any], fallback: datetime | None) -> datetime | None:
    raw = record.get("交易时间")
    if isinstance(raw, str) and raw.strip():
        for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw.strip(), fmt)
            except ValueError:
                continue
    return fallback


def parse_date_from_filename(file_path: Path) -> datetime | None:
    try:
        return datetime.strptime(file_path.stem, "%Y-%m-%d")
    except ValueError:
        return None


def load_records(archive_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(archive_dir.glob("*/*.json")):
        file_date = parse_date_from_filename(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, list):
            continue

        for item in payload:
            if not isinstance(item, dict):
                continue
            item = item.copy()
            item["__trade_date"] = parse_trade_date(item, file_date)
            records.append(item)
    return records


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("empty values")
    if q <= 0:
        return sorted_values[0]
    if q >= 1:
        return sorted_values[-1]
    idx = (len(sorted_values) - 1) * q
    low = math.floor(idx)
    high = math.ceil(idx)
    if low == high:
        return sorted_values[low]
    w = idx - low
    return sorted_values[low] * (1 - w) + sorted_values[high] * w


def psi_from_probs(base_probs: list[float], target_probs: list[float]) -> float:
    total = 0.0
    for b, t in zip(base_probs, target_probs):
        b = max(b, EPS)
        t = max(t, EPS)
        total += (t - b) * math.log(t / b)
    return total


def compute_numeric_metric(feature: str, recent_vals: list[float], hist_vals: list[float]) -> FeatureMetric | None:
    if len(recent_vals) < 5 or len(hist_vals) < 20:
        return None

    sorted_hist = sorted(hist_vals)
    bin_edges = [percentile(sorted_hist, i / 10) for i in range(11)]

    def count_bins(values: list[float]) -> list[int]:
        counts = [0] * 10
        for v in values:
            idx = 9
            for i in range(10):
                left = bin_edges[i]
                right = bin_edges[i + 1]
                if i == 9:
                    if left <= v <= right:
                        idx = i
                        break
                elif left <= v < right:
                    idx = i
                    break
            counts[idx] += 1
        return counts

    hist_bins = count_bins(hist_vals)
    recent_bins = count_bins(recent_vals)
    hist_probs = [c / len(hist_vals) for c in hist_bins]
    recent_probs = [c / len(recent_vals) for c in recent_bins]
    psi = psi_from_probs(hist_probs, recent_probs)

    hist_mean = sum(hist_vals) / len(hist_vals)
    recent_mean = sum(recent_vals) / len(recent_vals)
    hist_var = sum((v - hist_mean) ** 2 for v in hist_vals) / len(hist_vals)
    recent_var = sum((v - recent_mean) ** 2 for v in recent_vals) / len(recent_vals)
    hist_std = math.sqrt(hist_var)
    recent_std = math.sqrt(recent_var)

    mean_shift = abs(recent_mean - hist_mean) / (abs(hist_mean) + EPS)
    std_shift = abs(recent_std - hist_std) / (hist_std + EPS)
    drift_score = min(1.0, (mean_shift + std_shift) / 2)

    return FeatureMetric(feature, "numeric", psi, drift_score, len(recent_vals), len(hist_vals))


def compute_categorical_metric(feature: str, recent_vals: list[Any], hist_vals: list[Any]) -> FeatureMetric | None:
    if len(recent_vals) < 5 or len(hist_vals) < 20:
        return None

    recent_counter = Counter(str(v) for v in recent_vals)
    hist_counter = Counter(str(v) for v in hist_vals)
    categories = sorted(set(recent_counter) | set(hist_counter))

    hist_probs = [hist_counter[c] / len(hist_vals) for c in categories]
    recent_probs = [recent_counter[c] / len(recent_vals) for c in categories]
    psi = psi_from_probs(hist_probs, recent_probs)

    # 简化漂移分：总变差距离（0~1）
    drift_score = 0.5 * sum(abs(r - h) for r, h in zip(recent_probs, hist_probs))

    return FeatureMetric(feature, "categorical", psi, drift_score, len(recent_vals), len(hist_vals))


def split_recent_historical(records: list[dict[str, Any]], window_days: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime]:
    dated_records = [r for r in records if isinstance(r.get("__trade_date"), datetime)]
    if not dated_records:
        raise ValueError("找不到可用交易时间，无法计算漂移")

    max_date = max(r["__trade_date"] for r in dated_records)
    recent_start = max_date - timedelta(days=window_days - 1)

    recent = [r for r in dated_records if r["__trade_date"] >= recent_start]
    historical = [r for r in dated_records if r["__trade_date"] < recent_start]
    return recent, historical, max_date


def build_metrics(recent: list[dict[str, Any]], historical: list[dict[str, Any]]) -> list[FeatureMetric]:
    metrics: list[FeatureMetric] = []
    for feature in CORE_FEATURES:
        if feature in NUMERIC_FEATURES:
            recent_vals = [to_float(r.get(feature)) for r in recent]
            hist_vals = [to_float(r.get(feature)) for r in historical]
            recent_clean = [v for v in recent_vals if v is not None]
            hist_clean = [v for v in hist_vals if v is not None]
            metric = compute_numeric_metric(feature, recent_clean, hist_clean)
        else:
            recent_clean = [r.get(feature) for r in recent if r.get(feature) not in (None, "")]
            hist_clean = [r.get(feature) for r in historical if r.get(feature) not in (None, "")]
            metric = compute_categorical_metric(feature, recent_clean, hist_clean)
        if metric:
            metrics.append(metric)
    return metrics


def main() -> None:
    args = parse_args()
    records = load_records(args.archive_dir)
    recent, historical, max_date = split_recent_historical(records, args.window_days)
    metrics = build_metrics(recent, historical)

    alerts = [
        {
            "feature": m.feature,
            "metric_type": m.metric_type,
            "psi": round(m.psi, 6),
            "drift_score": round(m.drift_score, 6),
            "reasons": [
                reason
                for reason, triggered in (
                    ("psi_exceeded", m.psi >= args.psi_threshold),
                    ("drift_score_exceeded", m.drift_score >= args.drift_threshold),
                )
                if triggered
            ],
        }
        for m in metrics
        if m.psi >= args.psi_threshold or m.drift_score >= args.drift_threshold
    ]

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": args.window_days,
        "recent_period": {
            "start": (max_date - timedelta(days=args.window_days - 1)).strftime("%Y-%m-%d"),
            "end": max_date.strftime("%Y-%m-%d"),
            "count": len(recent),
        },
        "historical_count": len(historical),
        "thresholds": {
            "psi": args.psi_threshold,
            "drift_score": args.drift_threshold,
        },
        "feature_metrics": [m.to_dict() for m in metrics],
        "alerts": alerts,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Drift report saved to: {args.output}")
    print(f"Metrics: {len(metrics)}, Alerts: {len(alerts)}")


if __name__ == "__main__":
    main()
