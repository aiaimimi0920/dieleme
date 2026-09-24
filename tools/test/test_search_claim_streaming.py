"""Search claims remain bounded and do not reserve another worker's work."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event, get_ident

import pytest
from sqlalchemy import event, insert, select

from src.collection.search_task_policy import GenericSearchTaskPolicy
from src.storage.models import PropertySearchTask
from src.storage.repository import DatabaseSettings, PropertyRepository
from tools.test import test_quality_postgres_claims as postgres_fixtures

repository = postgres_fixtures.repository


@pytest.fixture
def queue(tmp_path):
    repo = PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'search.sqlite3').as_posix()}",
            enabled=True,
            auto_create=True,
            enable_postgis=False,
        )
    )
    repo.initialize()
    yield repo
    repo.engine.dispose()


def populate(repo, count, **values):
    with repo.session_factory.begin() as session:
        session.execute(
            insert(PropertySearchTask),
            [
                dict(
                    task_key=f"{index:06d}:50025969:2",
                    location_code=f"{index:06d}",
                    category="50025969",
                    sort_param="2",
                    **values,
                )
                for index in range(count)
            ],
        )


@pytest.mark.parametrize("priorities", [None, [], ["000512"]])
def test_claim_loads_only_selected_row_and_preserves_priority(queue, priorities):
    populate(queue, 513, status="pending")
    loaded = []

    def on_load(_session, instance):
        if isinstance(instance, PropertySearchTask):
            loaded.append(instance.task_key)

    event.listen(queue.session_factory, "loaded_as_persistent", on_load)
    try:
        claim = queue.claim_search_task("worker", priority_codes=priorities)
    finally:
        event.remove(queue.session_factory, "loaded_as_persistent", on_load)
    assert claim["location_code"] == ("000512" if priorities else "000000")
    assert loaded == [claim["task_key"]]


def test_other_policy_rows_do_not_hide_work_after_multiple_windows(queue):
    populate(queue, 513, status="pending")
    policy = GenericSearchTaskPolicy("catalog")
    queue.bootstrap_search_task(
        {"task_key": "target", "url": "https://catalog.example/first"}, policy=policy
    )
    claim = queue.claim_search_task("worker", policy=policy)
    assert claim["source_platform"] == "catalog"
    assert claim["url"] == "https://catalog.example/first"


def test_unexpired_leases_are_not_stolen_to_reach_later_work(queue):
    populate(
        queue,
        513,
        status="in_progress",
        leased_by="owner",
        lease_until=datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(hours=1),
    )
    with queue.session_factory.begin() as session:
        row = session.get(PropertySearchTask, "000512:50025969:2")
        row.lease_until = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            seconds=1
        )
    queries = []

    def on_query(_connection, _cursor, statement, *_args):
        queries.append(statement)

    event.listen(queue.engine, "before_cursor_execute", on_query)
    try:
        claim = queue.claim_search_task("new-worker", lease_seconds=5)
    finally:
        event.remove(queue.engine, "before_cursor_execute", on_query)
    assert claim["location_code"] == "000512"
    assert len(queries) <= 3
    with queue.session_factory() as session:
        owners = session.scalars(
            select(PropertySearchTask.leased_by).where(
                PropertySearchTask.task_key != claim["task_key"]
            )
        ).all()
    assert owners == ["owner"] * 512


@pytest.mark.integration
def test_active_claim_does_not_lock_all_candidate_rows(repository):
    populate(repository, 3, status="pending")
    claimed, release = Event(), Event()
    first_thread = []

    def hold_first_update(_connection, _cursor, statement, *_args):
        if (
            first_thread
            and get_ident() == first_thread[0]
            and statement.startswith("UPDATE property_search_task")
        ):
            claimed.set()
            assert release.wait(10), (
                "second worker did not finish while first held its row"
            )

    def first_claim():
        first_thread.append(get_ident())
        return repository.claim_search_task("first", priority_codes=["000000"])

    event.listen(repository.engine, "before_cursor_execute", hold_first_update)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(first_claim)
            try:
                assert claimed.wait(10), "first worker did not acquire its candidate"
                second = pool.submit(
                    repository.claim_search_task, "second", priority_codes=["000000"]
                ).result(timeout=5)
                assert second is not None
                assert second["location_code"] == "000001"
            finally:
                release.set()
            assert first.result(timeout=5)["location_code"] == "000000"
    finally:
        event.remove(repository.engine, "before_cursor_execute", hold_first_update)
