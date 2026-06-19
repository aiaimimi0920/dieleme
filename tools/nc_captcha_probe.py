import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
target_url = f"file:///{test_page.as_posix()}"

print("=" * 60)
print("Testing Captcha Solver with Real NC Captcha")
print("=" * 60)
print(f"URL: {target_url}")
print("Waiting 5s for captcha to load...")
print()

solver = CaptchaSolver(port=9223, target_url=target_url)

# Give the page time to load the captcha
time.sleep(5)

print("Starting solve attempt...")
result = solver.solve(max_attempts=5)

print("\n" + "=" * 60)
if result:
    print("✅ SUCCESS - Captcha solved!")
else:
    print(f"❌ FAILED - Reason: {solver.last_failure_reason}")
print("=" * 60)

sys.exit(0 if result else 1)
