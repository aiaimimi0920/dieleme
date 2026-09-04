"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_evaluation_context import *


def parse_args() -> BacktestConfig:
    parser = argparse.ArgumentParser(description="AVM 多维主链时间切分回测评估")
    parser.add_argument("--data-root", type=Path, default=Path("datas"), help="数据根目录，默认 datas")
    parser.add_argument("--report-path", type=Path, default=Path("datas/avm/eval_report.json"), help="输出评估报告路径")
    parser.add_argument("--min-train-months", type=int, default=6, help="最少训练月份数")
    parser.add_argument("--max-candidates-per-subject", type=int, default=320, help="每个样本最多使用的训练候选数")
    parser.add_argument("--diagnostic-case-limit", type=int, default=30, help="评估报告中保留的最差样本数量")
    args = parser.parse_args()
    return BacktestConfig(
        data_root=args.data_root,
        report_path=args.report_path,
        min_train_months=args.min_train_months,
        max_candidates_per_subject=args.max_candidates_per_subject,
        diagnostic_case_limit=args.diagnostic_case_limit,
    )


def main() -> None:
    config = parse_args()
    report = generate_report(config)
    print(f"[INFO] Backtest samples: {report['data_summary']['backtest_sample_count']}")
    metrics = report.get("metrics", {})
    if metrics:
        print(f"[INFO] MAPE: {metrics['mape_pct']:.2f}%")
        print(f"[INFO] MdAPE: {metrics['mdape_pct']:.2f}%")
        print(f"[INFO] P50 APE: {metrics['p50_ape_pct']:.2f}%")
        print(f"[INFO] P90 APE: {metrics['p90_ape_pct']:.2f}%")
    print(f"[INFO] Report generated: {config.report_path}")


__all__ = (
    "parse_args",
    "main",
)
