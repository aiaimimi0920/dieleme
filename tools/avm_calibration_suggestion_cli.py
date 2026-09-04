"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_suggestion_context import *


def main() -> None:
    parser = argparse.ArgumentParser(description="Suggest AVM calibration targets from eval report metrics")
    parser.add_argument("--eval-report", type=Path, default=Path("datas/avm/eval_report.json"))
    parser.add_argument("--output", type=Path, default=Path("datas/avm/calibration_targets.json"))
    parser.add_argument("--min-sample-count", type=int, default=3)
    parser.add_argument("--bias-threshold-pct", type=float, default=5.0)
    parser.add_argument("--mape-threshold-pct", type=float, default=12.0)
    args = parser.parse_args()

    payload = json.loads(args.eval_report.read_text(encoding="utf-8"))
    result = suggest_calibration_targets(
        payload.get("metrics", {}) or {},
        min_sample_count=args.min_sample_count,
        bias_threshold_pct=args.bias_threshold_pct,
        mape_threshold_pct=args.mape_threshold_pct,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = (
    "main",
)
