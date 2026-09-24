from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.collection import detail_service
from src.collection.detail_service import DetailCollectionService


def test_detail_dispatch_uses_aware_utc_timestamps(tmp_path) -> None:
    service = DetailCollectionService(tmp_path)
    dispatched = {"old": datetime.now(timezone.utc)}
    service._expire_dispatches(dispatched, datetime.now(timezone.utc), cooldown_seconds=60)
    assert dispatched["old"].tzinfo is not None


def test_detail_service_source_uses_utc_clock() -> None:
    source = Path(__file__).parents[2].joinpath("src", "collection", "detail_service.py").read_text(encoding="utf-8")
    assert "datetime.datetime.now(_timezone.utc)" in source
    assert "datetime.datetime.now()\n" not in source


def test_zero_argument_clock_fallback_prefers_utcnow(monkeypatch):
    local_wall_clock = datetime.fromisoformat("2026-09-22T12:00:00")
    utc_clock = datetime.fromisoformat("2026-09-22T04:00:00")

    class Clock:
        @staticmethod
        def now(*args):
            if args:
                raise TypeError("zero-argument fake")
            return local_wall_clock

        @staticmethod
        def utcnow():
            return utc_clock

    monkeypatch.setattr(
        detail_service,
        "datetime",
        SimpleNamespace(datetime=Clock),
    )

    assert detail_service._utc_now() == utc_clock.replace(tzinfo=timezone.utc)
