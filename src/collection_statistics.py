"""Shared, bounded API count snapshots; runtime control state is never cached."""
from collections import deque
from threading import RLock
import time


def unique_counts(counts: dict[str, int]) -> list[int]:
    finalized = counts.get("seed_item_detail_completed", 0)
    captured = finalized + sum(counts.get("seed_item_" + status, 0) for status in (
        "raw_detail_captured", "analysis_in_progress", "analysis_failed", "analysis_blocked"))
    return [sum(value for key, value in counts.items() if key.startswith("seed_item_")), captured, finalized]


class StatisticsCache:
    def __init__(self, *, ttl=15.0, clock=time.monotonic, wall_clock=time.time):
        self.ttl, self.clock, self.wall_clock = ttl, clock, wall_clock
        self.lock = RLock()
        self.owner = None
        self.values = None
        self.attempted = float("-inf")
        self.sampled = 0.0
        self.generated_at = None
        self.error = None
        self.history = deque(maxlen=32)

    def snapshot(self, owner, load):
        with self.lock:
            now = self.clock()
            if self.owner is not owner or now < self.attempted:
                self.owner, self.values = owner, None
                self.attempted = float("-inf")
                self.generated_at = None
                self.history.clear()
            if now - self.attempted >= self.ttl:
                self.attempted = now
                try:
                    values = dict(load())
                    if any(not isinstance(v, int) or v < 0 for v in values.values()):
                        raise ValueError("Invalid collection counts")
                    self.values, self.error = values, None
                    self.sampled = self.clock()
                    self.generated_at = self.wall_clock()
                    while self.history and self.history[0][0] < self.sampled - 90:
                        self.history.popleft()
                    self.history.append((self.sampled, unique_counts(values)))
                except Exception as error:
                    # Keep the previous snapshot, but never label a failed refresh as live.
                    self.error = type(error).__name__
            baseline = next((sample for sample in reversed(self.history)
                             if 60 <= self.sampled - sample[0] <= 90), None)
            delta = [None, None, None]
            if baseline and self.values is not None and self.error is None:
                delta = [current - old for current, old in zip(unique_counts(self.values), baseline[1])]
            return {
                "counts": dict(self.values or {}),
                "metadata": {
                    "valid": self.values is not None,
                    "stale": self.error is not None,
                    "error_type": self.error,
                    "generated_at": self.generated_at,
                    "age_seconds": max(0.0, self.clock() - self.sampled) if self.values is not None else None,
                    "ttl_seconds": self.ttl,
                    "minute_delta": delta,
                    "window_seconds": round(self.sampled - baseline[0]) if baseline and self.error is None else None,
                },
            }


SNAPSHOTS = StatisticsCache()
