"""Manual NC CAPTCHA probe for the local test page.

The probe is intentionally opt-in: importing this module must not connect to
CDP, sleep, solve a challenge, or terminate the importing process.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local NC CAPTCHA probe")
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--wait-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.captcha_solver import CaptchaSolver

    test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
    target_url = f"file:///{test_page.as_posix()}"
    print("=" * 60)
    print("Testing Captcha Solver with Real NC Captcha")
    print("=" * 60)
    print(f"URL: {target_url}")
    print(f"Waiting {args.wait_seconds:g}s for captcha to load...")

    solver = CaptchaSolver(port=args.port, target_url=target_url)
    try:
        time.sleep(max(args.wait_seconds, 0.0))
        print("Starting solve attempt...")
        result = solver.solve(max_attempts=max(args.max_attempts, 1))
        print("\n" + "=" * 60)
        if result:
            print("SUCCESS - CAPTCHA solved")
        else:
            print(f"FAILED - Reason: {solver.last_failure_reason}")
        print("=" * 60)
        return 0 if result else 1
    finally:
        if solver.ws is not None:
            solver.ws.close()


if __name__ == "__main__":
    raise SystemExit(main())
