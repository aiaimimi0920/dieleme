"""Shared request budgets and provider-directed retry timing."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math

MAX_INPUT_CHARACTERS = 100_000
MAX_OUTPUT_TOKENS = 8192
MAX_RETRY_WAIT_SECONDS = 60


def retry_delay(headers, attempt: int, *, now: datetime | None = None) -> float:
    fallback = float(min(2 ** max(attempt - 1, 0), 8))
    raw = str(headers.get("Retry-After") or "").strip()
    if not raw:
        return fallback
    try:
        seconds = float(raw)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(raw)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            seconds = (deadline - (now or datetime.now(timezone.utc))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return fallback
    return max(seconds, fallback) if math.isfinite(seconds) else fallback
