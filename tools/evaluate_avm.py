#!/usr/bin/env python3
"""AVM 时间切分回测与评估报告生成工具。"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class BacktestConfig:
    data_root: Path
    report_path: Path
    min_train_months: int = 6


def load_archive_records(data_root: Path) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    archive_root = data_root / "archive"
    for json_file in sorted(archive_root.rglob("*.json")):
        try:
            with json_file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        if not isinstance(payload, list):
            continue

        for row in payload:
            if not isinstance(row, dict):
                continue
            records.append(row)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    return df


def clean_records(df: pd.DataFrame) -> pd.DataFrame:
    required_columns = ["交易时间", "成交价格", "建筑面积", "城市", "区"]
    for col in required_columns:
        if col not in df.columns:
            df[col] = np.nan

    work = df.copy()
    work["交易时间"] = pd.to_datetime(work["交易时间"], errors="coerce")
    work["成交价格"] = pd.to_numeric(work["成交价格"], errors="coerce")
    work["建筑面积"] = pd.to_numeric(work["建筑面积"], errors="coerce")

    work = work.dropna(subset=["交易时间", "成交价格", "建筑面积"])
    work = work[(work["成交价格"] > 0) & (work["建筑面积"] > 0)]

    work["actual_unit_price"] = work["成交价格"] / work["建筑面积"]
    work = work[np.isfinite(work["actual_unit_price"]) & (work["actual_unit_price"] > 0)]

    work["城市"] = work["城市"].fillna("未知城市").astype(str)
    work["区"] = work["区"].fillna("未知分区").astype(str)
    work["month"] = work["交易时间"].dt.to_period("M").astype(str)
    work["partition"] = work["城市"] + "-" + work["区"]

    return work


def predict_unit_price(train_df: pd.DataFrame, row: pd.Series) -> float:
    partition_key = row["partition"]
    city_key = row["城市"]

    partition_prices = train_df.loc[train_df["partition"] == partition_key, "actual_unit_price"]
    if not partition_prices.empty:
        return float(partition_prices.median())

    city_prices = train_df.loc[train_df["城市"] == city_key, "actual_unit_price"]
    if not city_prices.empty:
        return float(city_prices.median())

    return float(train_df["actual_unit_price"].median())


def run_time_split_backtest(df: pd.DataFrame, min_train_months: int) -> pd.DataFrame:
    months = sorted(df["month"].unique().tolist())
    if len(months) <= min_train_months:
        return pd.DataFrame()

    preds: list[dict[str, Any]] = []

    for idx, test_month in enumerate(months):
        if idx < min_train_months:
            continue

        train_months = months[:idx]
        train_df = df[df["month"].isin(train_months)]
        test_df = df[df["month"] == test_month]

        if train_df.empty or test_df.empty:
            continue

        for _, row in test_df.iterrows():
            pred_unit_price = predict_unit_price(train_df, row)
            actual_unit_price = float(row["actual_unit_price"])
            ape = abs(pred_unit_price - actual_unit_price) / actual_unit_price

            preds.append(
                {
                    "month": test_month,
                    "id": str(row.get("id", "")),
                    "partition": row["partition"],
                    "city": row["城市"],
                    "actual_unit_price": actual_unit_price,
                    "pred_unit_price": pred_unit_price,
                    "ape": float(ape),
                }
            )

    if not preds:
        return pd.DataFrame()

    return pd.DataFrame(preds)


def compute_metrics(pred_df: pd.DataFrame) -> dict[str, Any]:
    ape_arr = pred_df["ape"].to_numpy()
    mape = float(np.mean(ape_arr) * 100)
    mdape = float(np.median(ape_arr) * 100)

    partition_stats = []
    for partition, grp in pred_df.groupby("partition"):
        q = np.quantile(grp["ape"].to_numpy(), [0.25, 0.5, 0.75, 0.9])
        partition_stats.append(
            {
                "partition": partition,
                "sample_count": int(len(grp)),
                "mape_pct": float(np.mean(grp["ape"]) * 100),
                "mdape_pct": float(np.median(grp["ape"]) * 100),
                "error_quantiles_pct": {
                    "p25": float(q[0] * 100),
                    "p50": float(q[1] * 100),
                    "p75": float(q[2] * 100),
                    "p90": float(q[3] * 100),
                },
            }
        )

    partition_stats.sort(key=lambda x: x["sample_count"], reverse=True)

    partition_mdape_values = [row["mdape_pct"] for row in partition_stats]
    if partition_mdape_values:
        partition_mdape_quantiles = {
            "p25": float(np.quantile(partition_mdape_values, 0.25)),
            "p50": float(np.quantile(partition_mdape_values, 0.5)),
            "p75": float(np.quantile(partition_mdape_values, 0.75)),
            "p90": float(np.quantile(partition_mdape_values, 0.9)),
        }
    else:
        partition_mdape_quantiles = {}

    overall_err_quantiles = {
        "p25": float(np.quantile(ape_arr, 0.25) * 100),
        "p50": float(np.quantile(ape_arr, 0.5) * 100),
        "p75": float(np.quantile(ape_arr, 0.75) * 100),
        "p90": float(np.quantile(ape_arr, 0.9) * 100),
    }

    return {
        "mape_pct": mape,
        "mdape_pct": mdape,
        "overall_error_quantiles_pct": overall_err_quantiles,
        "partition_mdape_quantiles_pct": partition_mdape_quantiles,
        "partition_error_quantiles": partition_stats,
    }


def generate_report(config: BacktestConfig) -> dict[str, Any]:
    raw_df = load_archive_records(config.data_root)
    clean_df = clean_records(raw_df)
    pred_df = run_time_split_backtest(clean_df, min_train_months=config.min_train_months)

    report: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_summary": {
            "raw_record_count": int(len(raw_df)),
            "clean_record_count": int(len(clean_df)),
            "backtest_sample_count": int(len(pred_df)),
            "min_train_months": config.min_train_months,
            "month_range": {
                "start": clean_df["month"].min() if not clean_df.empty else None,
                "end": clean_df["month"].max() if not clean_df.empty else None,
            },
        },
        "metrics": {},
    }

    if not pred_df.empty:
        report["metrics"] = compute_metrics(pred_df)

    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    with config.report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report


def parse_args() -> BacktestConfig:
    parser = argparse.ArgumentParser(description="AVM 时间切分回测评估")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("datas"),
        help="数据根目录，默认 datas",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("datas/avm/eval_report.json"),
        help="输出评估报告路径",
    )
    parser.add_argument(
        "--min-train-months",
        type=int,
        default=6,
        help="最少训练月份数（用于时间切分）",
    )
    args = parser.parse_args()

    return BacktestConfig(
        data_root=args.data_root,
        report_path=args.report_path,
        min_train_months=args.min_train_months,
    )


def main() -> None:
    config = parse_args()
    report = generate_report(config)
    print(f"[INFO] Backtest samples: {report['data_summary']['backtest_sample_count']}")
    metrics = report.get("metrics", {})
    if metrics:
        print(f"[INFO] MAPE: {metrics['mape_pct']:.2f}%")
        print(f"[INFO] MdAPE: {metrics['mdape_pct']:.2f}%")
    print(f"[INFO] Report generated: {config.report_path}")


if __name__ == "__main__":
    main()
