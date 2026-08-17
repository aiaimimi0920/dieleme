import os
import sys
import json

os.environ.setdefault("FAPAI_CDP_ENDPOINT", "http://127.0.0.1:9223")

REPO = r"\\192.168.15.200\home\project\project\fapaifang"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.captcha_solver import CaptchaSolver

target = sys.argv[1] if len(sys.argv) > 1 else "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1"
print(f"[RUNNER] target={target}")
print(f"[RUNNER] cdp={os.environ['FAPAI_CDP_ENDPOINT']}")

solver = CaptchaSolver(cdp_endpoint=os.environ["FAPAI_CDP_ENDPOINT"], target_url=target)

# Just inspect the current challenge state first (does the real page show a slider?).
pre = solver._preflight_current_challenge()
print("[RUNNER] preflight=" + json.dumps(pre, ensure_ascii=False))

# Now run the real solve path end-to-end.
result = solver.solve(max_attempts=3)
print(f"[RUNNER] solve_result={result}")
print(f"[RUNNER] last_failure_reason={solver.last_failure_reason}")
