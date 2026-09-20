from __future__ import annotations

import random


def jittered_delay_seconds(base_seconds: float, jitter_ratio: float) -> float:
    """Return a bounded non-negative delay with symmetric jitter."""
    base = max(float(base_seconds), 0.0)
    ratio = min(max(float(jitter_ratio), 0.0), 1.0)
    if base == 0 or ratio == 0:
        return base
    return random.uniform(base * (1.0 - ratio), base * (1.0 + ratio))


__all__ = ["jittered_delay_seconds"]
