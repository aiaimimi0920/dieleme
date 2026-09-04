"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_pipeline_runner_context import *


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AVM pipeline: canonical -> risk -> feature -> predict -> alert -> evaluate -> calibration -> gate")
    parser.add_argument("--data-dir", default="datas", help="Data directory")
    parser.add_argument("--alerts-threshold", type=float, default=0.15, help="Alert margin threshold")
    parser.add_argument("--predict-limit", type=int, default=500, help="Max candidate rows for prediction stage")
    args = parser.parse_args()

    result = run_pipeline(data_dir=args.data_dir, alerts_threshold=args.alerts_threshold, predict_limit=args.predict_limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


__all__ = (
    "main",
)
