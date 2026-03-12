#!/usr/bin/env python3
"""AVM 评估脚本。

功能：
1. 从预测样本文件读取真实值与预测值，计算基础误差指标。
2. 导出 Top N 高误差样本到 datas/avm/error_cases.jsonl。
3. 每条高误差样本附带：风控字段、可比样本摘要、模型分解分量。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_INPUT = Path("datas/avm/eval_predictions.jsonl")
DEFAULT_OUTPUT = Path("datas/avm/error_cases.jsonl")


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _pick(record: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def _extract_risk_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    direct = _pick(record, ["risk_fields", "risk_flags", "risk_tags", "风控字段", "风控标签", "risk"])
    if isinstance(direct, dict):
        return direct

    property_info = record.get("property_features")
    if isinstance(property_info, dict):
        risk_like = {
            key: value
            for key, value in property_info.items()
            if key.startswith("risk_") or "风险" in key or "风控" in key
        }
        if risk_like:
            return risk_like

    return {}


def _extract_model_components(record: Dict[str, Any]) -> Dict[str, Any]:
    components = _pick(
        record,
        [
            "model_components",
            "decomposition",
            "price_components",
            "component_breakdown",
            "分解分量",
            "模型分解",
        ],
    )
    return components if isinstance(components, dict) else {}


def _summarize_comparables(record: Dict[str, Any], max_items: int = 5) -> List[Dict[str, Any]]:
    comparables = _pick(record, ["comparables", "comps", "comparable_samples", "可比样本"])
    if not isinstance(comparables, list):
        return []

    summary: List[Dict[str, Any]] = []
    for comp in comparables[:max_items]:
        if not isinstance(comp, dict):
            continue
        summary.append(
            {
                "id": _pick(comp, ["id", "item_id", "sample_id", "标的id"]),
                "community": _pick(comp, ["community", "所属小区", "小区"]),
                "distance_km": _pick(comp, ["distance_km", "distance", "距离km", "距离"]),
                "unit_price": _pick(comp, ["unit_price", "price_per_sqm", "单价"]),
                "weight": _pick(comp, ["weight", "similarity_weight", "权重"]),
                "adjusted_unit_price": _pick(comp, ["adjusted_unit_price", "adjusted_price", "修正单价"]),
            }
        )
    return summary


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if not isinstance(payload, dict):
                raise ValueError(f"第 {line_no} 行不是 JSON Object")
            payload["_line_no"] = line_no
            records.append(payload)
    return records


def evaluate_and_export(records: List[Dict[str, Any]], top_n: int, output_path: Path) -> Dict[str, float]:
    evaluated: List[Dict[str, Any]] = []
    abs_errors: List[float] = []
    ape_values: List[float] = []

    for record in records:
        actual = _to_float(_pick(record, ["actual", "y_true", "actual_price", "成交价", "真实价格"]))
        pred = _to_float(_pick(record, ["pred", "prediction", "y_pred", "predicted_price", "预测价格"]))
        if actual is None or pred is None:
            continue

        abs_error = abs(pred - actual)
        ape = abs_error / abs(actual) if actual != 0 else None

        abs_errors.append(abs_error)
        if ape is not None:
            ape_values.append(ape)

        evaluated.append(
            {
                "sample_id": _pick(record, ["id", "item_id", "sample_id", "auction_id"]),
                "line_no": record.get("_line_no"),
                "actual_price": actual,
                "predicted_price": pred,
                "abs_error": abs_error,
                "abs_pct_error": ape,
                "risk_fields": _extract_risk_fields(record),
                "comparable_summary": _summarize_comparables(record),
                "model_components": _extract_model_components(record),
            }
        )

    evaluated.sort(
        key=lambda x: (
            x["abs_pct_error"] if x["abs_pct_error"] is not None else -1,
            x["abs_error"],
        ),
        reverse=True,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for case in evaluated[:top_n]:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    return {
        "samples_used": float(len(evaluated)),
        "mae": mean(abs_errors) if abs_errors else 0.0,
        "mape": mean(ape_values) if ape_values else 0.0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AVM 评估并导出高误差样本")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="评估输入 jsonl")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="高误差样本输出 jsonl")
    parser.add_argument("--top-n", type=int, default=50, help="导出误差最大的样本数量")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records = _load_jsonl(args.input)
    metrics = evaluate_and_export(records, args.top_n, args.output)

    print(
        "[AVM-EVAL] done "
        f"samples={int(metrics['samples_used'])} "
        f"mae={metrics['mae']:.2f} "
        f"mape={metrics['mape']:.4f} "
        f"error_cases={args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
