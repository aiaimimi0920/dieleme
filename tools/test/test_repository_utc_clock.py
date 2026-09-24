import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from src.storage.repository_context import _parse_dt, _utc_now, use_repository_clock


def test_repository_clock_defaults_to_current_utc() -> None:
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    observed = _utc_now()
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert before <= observed <= after


def test_repository_clock_injection_normalizes_aware_values_without_facade_monkeypatch() -> (
    None
):
    fixed = datetime(2026, 9, 22, 12, 34, 56, tzinfo=timezone.utc)
    with use_repository_clock(lambda: fixed):
        assert _utc_now() == fixed.replace(tzinfo=None)


@pytest.mark.parametrize("offset_hours", [-7, 8])
def test_repository_clock_normalizes_offset_instants(offset_hours) -> None:
    fixed = datetime(2026, 9, 22, 12, tzinfo=timezone(timedelta(hours=offset_hours)))
    with use_repository_clock(lambda: fixed):
        assert _utc_now() == datetime(2026, 9, 22, 12) - timedelta(hours=offset_hours)


def test_repository_clock_nested_failure_restores_outer_clock() -> None:
    outer = datetime(2020, 1, 2)
    inner = datetime(2021, 3, 4)
    with use_repository_clock(lambda: outer):
        with pytest.raises(RuntimeError, match="operation failed"):
            with use_repository_clock(lambda: inner):
                assert _utc_now() == inner
                raise RuntimeError("operation failed")
        assert _utc_now() == outer
    assert _utc_now() != outer


def test_repository_clock_does_not_change_parsing() -> None:
    with use_repository_clock(lambda: datetime(2020, 1, 2)):
        assert _parse_dt("2026/09/22 12:34:56") == datetime(2026, 9, 22, 12, 34, 56)
        assert _parse_dt("2026-09-22") == datetime(2026, 9, 22)
        assert _parse_dt("invalid") is None


def test_repository_clock_isolated_between_threads() -> None:
    ready = Barrier(2)
    instants = (datetime(2020, 1, 2), datetime(2021, 3, 4))

    def read_clock(instant):
        with use_repository_clock(lambda: instant):
            ready.wait(timeout=5)
            return _utc_now()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert tuple(pool.map(read_clock, instants)) == instants


def test_repository_clock_isolated_between_async_tasks() -> None:
    instants = (datetime(2020, 1, 2), datetime(2021, 3, 4))

    async def read_clock(instant):
        with use_repository_clock(lambda: instant):
            await asyncio.sleep(0)
            return _utc_now()

    async def read_all():
        return await asyncio.gather(*(read_clock(instant) for instant in instants))

    assert tuple(asyncio.run(read_all())) == instants
