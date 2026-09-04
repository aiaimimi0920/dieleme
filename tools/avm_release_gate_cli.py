"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_release_gate_context import *


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AVM 发布门禁预检")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--min-sample-size", type=int, default=1000)
    parser.add_argument("--smoke-sample-size", type=int, default=8)
    parser.add_argument("--eval-report-path", type=Path, default=Path("datas/avm/eval_report.json"))
    parser.add_argument("--gate-report-path", type=Path, default=Path("datas/avm/release_gate.json"))
    parser.add_argument("--reuse-eval-report", action="store_true", help="复用已存在的评估报告")
    parser.add_argument("--reuse-drift-report", action="store_true", help="复用已存在的漂移报告")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    output = generate_release_gate_report(
        data_root=args.data_root,
        eval_report_path=args.eval_report_path,
        gate_report_path=args.gate_report_path,
        window_days=args.window_days,
        min_sample_size=args.min_sample_size,
        smoke_sample_size=args.smoke_sample_size,
        reuse_eval_report=args.reuse_eval_report,
        reuse_drift_report=args.reuse_drift_report,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


__all__ = (
    "parse_args",
    "main",
)
