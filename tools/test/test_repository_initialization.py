"""Concurrent first use must share repository resources and schema setup."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest
from sqlalchemy import inspect

from src.storage import repository_core
from src.storage.repository import DatabaseSettings, PropertyRepository


@pytest.mark.parametrize("resource", ["engine", "session_factory", "initialize"])
def test_concurrent_first_use_initializes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    repo = PropertyRepository(
        DatabaseSettings(url=f"sqlite:///{tmp_path / 'concurrent.sqlite'}", auto_create=True)
    )
    owner, name = {
        "engine": (repository_core, "create_engine"),
        "session_factory": (repository_core, "sessionmaker"),
        "initialize": (repository_core.Base.metadata, "create_all"),
    }[resource]
    original = getattr(owner, name)
    calls = []
    start = Barrier(8)

    def delayed_create(*args, **kwargs):
        calls.append(resource)
        # Keep first use open while the other barrier participants arrive.
        Event().wait(0.05)
        return original(*args, **kwargs)

    def first_use():
        start.wait(timeout=5)
        if resource == "initialize":
            repo.initialize()
            return repo.session_factory
        return getattr(repo, resource)

    monkeypatch.setattr(owner, name, delayed_create)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: first_use(), range(8)))
        assert calls == [resource]
        assert all(result is results[0] for result in results)
        if resource == "initialize":
            assert inspect(repo.engine).has_table("property_listing")
    finally:
        repo.engine.dispose()


def test_failed_schema_setup_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = PropertyRepository(
        DatabaseSettings(url=f"sqlite:///{tmp_path / 'retry.sqlite'}", auto_create=True)
    )
    original = repository_core.Base.metadata.create_all
    calls = 0

    def interrupted_create(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic schema interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(repository_core.Base.metadata, "create_all", interrupted_create)
    try:
        with pytest.raises(RuntimeError, match="synthetic schema interruption"):
            repo.initialize()
        repo.initialize()
        repo.initialize()
        assert calls == 2
        assert inspect(repo.engine).has_table("property_listing")
    finally:
        repo.engine.dispose()
