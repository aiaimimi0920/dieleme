import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

# 使用真实的淘宝页面
target_url = "https://sec.taobao.com/query.htm?action=QueryAction&event_submit_do_login=ok"

print(f"Testing with real Taobao captcha page")
print(f"Target: {target_url}")
print("Note: This will only work if a captcha is actually displayed\n")

solver = CaptchaSolver(port=9223, target_url=target_url)

try:
    result = solver.solve(max_attempts=10)
    print(f"\n{'=' * 50}")
    print(f"Result: {'SUCCESS' if result else 'FAILED'}")
    print(f"Reason: {solver.last_failure_reason or 'None'}")
    print(f"{'=' * 50}")
    sys.exit(0 if result else 1)
except KeyboardInterrupt:
    print("\nInterrupted by user")
    sys.exit(2)
except Exception as e:
    print(f"\nException: {e}")
    sys.exit(1)
