#!/usr/bin/env python
"""Monitor captcha solver progress."""
import time
import json
from urllib.request import urlopen

def check_solver_status():
    try:
        with urlopen("http://127.0.0.1:8001/api/status", timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('captcha_solver', {})
    except Exception as e:
        return {"error": str(e)}

print("Monitoring captcha solver...")
for i in range(20):
    cs = check_solver_status()

    running = cs.get('running')
    status = cs.get('last_status')
    elapsed = cs.get('elapsed_seconds', 0)
    manual = cs.get('manual_required')
    failure = cs.get('last_failure_reason')

    print(f"[{i+1}/20] running={running}, status={status}, elapsed={elapsed}s, manual={manual}, failure={failure}")

    if not running and status in ['idle', 'solved', 'manual_required']:
        print(f"\n✅ Solver finished with status: {status}")
        if failure:
            print(f"   Failure reason: {failure}")
        break

    time.sleep(5)

print("\nFinal status check:")
final = check_solver_status()
print(json.dumps(final, indent=2))
