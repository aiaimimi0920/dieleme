#!/usr/bin/env python
"""Quick test for captcha solver with mock or real page."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.captcha_solver import CaptchaSolver

def main():
    # Test with local mock HTML for quick validation
    mock_html = REPO_ROOT / "tools" / "mock_slider.html"
    target_url = f"file:///{mock_html.as_posix()}"

    print(f"[TEST] Testing solver with: {target_url}")
    print("[TEST] Make sure browser is running with: --remote-debugging-port=9223")

    solver = CaptchaSolver(port=9223, target_url=target_url)

    print("\n[TEST] Starting solve attempt...")
    result = solver.solve()

    if result:
        print("\n✅ [TEST] Solver succeeded!")
        return 0
    else:
        print("\n❌ [TEST] Solver failed")
        print(f"[TEST] Failure reason: {solver.last_failure_reason}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
