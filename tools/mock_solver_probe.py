import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

mock_html = Path(__file__).resolve().parents[1] / "tools" / "mock_slider.html"
target_url = f"file:///{mock_html.as_posix()}"

print(f"Mock page: {target_url}")
solver = CaptchaSolver(port=9223, target_url=target_url)
result = solver.solve()
print(f"\n{'SUCCESS' if result else 'FAILED'}: {solver.last_failure_reason or 'OK'}")
sys.exit(0 if result else 1)
