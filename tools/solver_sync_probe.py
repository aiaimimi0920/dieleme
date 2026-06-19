#!/usr/bin/env python
"""Synchronous captcha solver test."""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.captcha_solver import CaptchaSolver

# Test with mock HTML
mock_html = REPO_ROOT / "tools" / "mock_slider.html"
target_url = f"file:///{mock_html.as_posix()}"

print(f"Testing solver with: {target_url}")
print("Ensure browser runs with: --remote-debugging-port=9223\n")

solver = CaptchaSolver(port=9223, target_url=target_url)

try:
    print("Starting solve...")
    result = solver.solve()

    if result:
        print("\n✅ SUCCESS!")
        sys.exit(0)
    else:
        print(f"\n❌ FAILED: {solver.last_failure_reason}")
        sys.exit(1)
except KeyboardInterrupt:
    print("\nInterrupted")
    sys.exit(2)
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
