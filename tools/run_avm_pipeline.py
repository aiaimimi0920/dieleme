import argparse
import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.pipeline import AVMPipelineManager, AVMPipelineConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unified AVM pipeline")
    parser.add_argument("--data-dir", default="datas", help="Data directory")
    parser.add_argument("--async", dest="run_async", action="store_true", help="Run in async background mode")
    parser.add_argument("--poll-seconds", type=float, default=0.2, help="Polling interval for async status")
    parser.add_argument("--alerts-threshold", type=float, default=0.15, help="Alert margin threshold")
    parser.add_argument("--alerts-limit", type=int, default=500, help="Max rows for alert generation")
    args = parser.parse_args()

    mgr = AVMPipelineManager(data_dir=args.data_dir)
    config = AVMPipelineConfig(
        data_dir=args.data_dir,
        alerts_threshold=args.alerts_threshold,
        alerts_limit=args.alerts_limit,
    )
    result = mgr.run(async_mode=args.run_async, config=config)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.run_async:
        return

    while True:
        state = mgr.status()
        if not state.get("running"):
            print(json.dumps(state, ensure_ascii=False, indent=2))
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
