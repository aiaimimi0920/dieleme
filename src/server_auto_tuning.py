from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def auto_tuner_thread():
    """
    Background thread for automatic concurrency tuning.
    Runs every 5 minutes, analyzes error rates, and adjusts ModelSelector limits.
    """
    from llm_helper import model_selector, MODEL_POOL

    TUNING_INTERVAL = 5 * 60  # 5 minutes
    MIN_REQUESTS = 20
    ERROR_RATE_LOW = 1.0   # Below this: increase
    ERROR_RATE_HIGH = 5.0  # Above this: decrease
    MAX_LIMIT = 20
    MIN_LIMIT = 3
    STEP_SIZE = 2
    STABLE_ROUNDS = 2

    stable_count = {m["name"]: 0 for m in MODEL_POOL}
    is_stable = False

    print("[AUTO-TUNER] Started (5-minute intervals)")

    while True:
        time.sleep(TUNING_INTERVAL)

        if is_stable:
            # Already stable, just monitor
            continue

        try:
            stats = model_selector.get_stats()
            all_stable = True

            print(f"\n[AUTO-TUNER] Analysis @ {time.strftime('%H:%M:%S')}")

            for name, s in stats.items():
                current_limit = model_selector.limits.get(name, 5)
                total = s["success"] + s["error"]

                if total < MIN_REQUESTS:
                    print(f"  [{name}] Requests {total} < {MIN_REQUESTS}, skipping")
                    continue

                error_rate = (s["concurrency_error"] / total * 100) if total > 0 else 0

                if error_rate < ERROR_RATE_LOW and current_limit < MAX_LIMIT:
                    new_limit = min(current_limit + STEP_SIZE, MAX_LIMIT)
                    print(f"  [{name}] Error {error_rate:.1f}% < {ERROR_RATE_LOW}% → {current_limit} → {new_limit}")
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                    all_stable = False
                elif error_rate > ERROR_RATE_HIGH and current_limit > MIN_LIMIT:
                    new_limit = max(current_limit - STEP_SIZE, MIN_LIMIT)
                    print(f"  [{name}] Error {error_rate:.1f}% > {ERROR_RATE_HIGH}% → {current_limit} → {new_limit}")
                    model_selector.update_limit(name, new_limit)
                    stable_count[name] = 0
                    all_stable = False
                else:
                    print(f"  [{name}] Error {error_rate:.1f}% OK, keeping {current_limit}")
                    stable_count[name] += 1

            # Reset stats for next round
            with model_selector.stats_lock:
                for name in model_selector.stats:
                    model_selector.stats[name] = {"success": 0, "error": 0, "concurrency_error": 0, "active": model_selector.stats[name]["active"]}

            # Check stability
            if min(stable_count.values()) >= STABLE_ROUNDS:
                is_stable = True
                print(f"[AUTO-TUNER] ✅ Stable! Final config: {model_selector.limits}")

        except Exception as e:
            print(f"[AUTO-TUNER] Error: {e}")

__all__ = ["auto_tuner_thread"]
