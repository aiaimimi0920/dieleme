from pathlib import Path

import pytest

from src.collection.adapters import GenericProductAdapter
from src.collection.search_task_policy import GenericSearchTaskPolicy
from src.collection.seed_service import SeedCollectionService
from src.storage.models import PropertySearchTask
from src.storage.repository import DatabaseSettings, PropertyRepository


def _make_repo(tmp_path: Path) -> PropertyRepository:
    db_path = tmp_path / "search-policy.sqlite3"
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )


def test_generic_policy_preserves_source_urls_and_uses_explicit_task_identity(tmp_path: Path):
    repo = _make_repo(tmp_path)
    adapter = GenericProductAdapter(source_platform="catalog_x")
    service = SeedCollectionService(repository=repo, adapter=adapter)
    first_url = "https://catalog.example/products?cursor=first"
    second_url = "https://catalog.example/products?cursor=second"
    assert service.register_search_task({"task_key": "catalog-root", "url": first_url}) is True

    assert repo.claim_search_task("legacy-session") is None
    first = service.next_task("generic-session")["task"]

    assert first["task_key"].startswith("source:catalog-x-")
    assert first["source_platform"] == "catalog_x"
    assert first["url"] == first_url
    assert first["page"] == 1
    assert first["session_id"] == "generic-session"

    with pytest.raises(ValueError, match="requires task_key"):
        service.report_progress({"url": first_url, "page_num": 1, "has_next": True})
    with pytest.raises(ValueError, match="requires session_id"):
        service.report_progress(
            {"task_key": first["task_key"], "page_num": 1, "has_next": True}
        )
    with pytest.raises(ValueError, match="lease is not owned"):
        service.report_progress(
            {
                "task_key": first["task_key"],
                "session_id": "stale-session",
                "page_num": 1,
                "has_next": True,
            }
        )

    service.report_progress(
        {
            "task_key": first["task_key"],
            "session_id": first["session_id"],
            "page_num": 1,
            "has_next": True,
            "next_url": second_url,
            "zero_bid_detected": True,
        }
    )
    second = service.next_task("generic-session")["task"]
    assert second["task_key"] == first["task_key"]
    assert second["url"] == second_url
    assert second["page"] == 2

    service.report_progress(
        {
            "task_key": second["task_key"],
            "session_id": second["session_id"],
            "page_num": 2,
            "has_next": False,
        }
    )
    assert service.next_task("generic-session")["task"] is None
    with repo.session_factory() as session:
        row = session.get(PropertySearchTask, first["task_key"])
        assert row is not None
        assert row.status == "done"
        assert row.source_url == second_url
        assert row.zero_bid_terminated is False


def test_generic_policy_rejects_an_unknown_internal_task_key(tmp_path: Path):
    service = SeedCollectionService(
        repository=_make_repo(tmp_path),
        adapter=GenericProductAdapter(source_platform="catalog_x"),
    )
    unknown_key = f"{GenericSearchTaskPolicy('catalog_x').task_key_prefix}{'0' * 40}"

    with pytest.raises(ValueError, match="unknown search task"):
        service.report_progress(
            {
                "task_key": unknown_key,
                "session_id": "generic-session",
                "page_num": 1,
                "has_next": False,
            }
        )


def test_generic_policy_rehashes_oversized_client_task_keys():
    policy = GenericSearchTaskPolicy(source_platform="catalog_x")
    oversized_key = f"{policy.task_key_prefix}{'a' * 200}"

    seed = policy.normalize_bootstrap(
        {"task_key": oversized_key, "url": "https://catalog.example/products"}
    )

    assert seed is not None
    assert seed.task_key != oversized_key
    assert len(seed.task_key) <= 128


def test_taobao_default_policy_keeps_legacy_url_and_zero_bid_sibling_pruning(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.bootstrap_search_task(
        {
            "location_code": "310115",
            "category": "50025969",
            "st_param": "2",
            "page": 1,
        }
    )
    task = repo.claim_search_task("legacy-session")

    assert task is not None
    assert task["task_key"] == "310115:50025969:2"
    assert task["source_platform"] == "taobao_sf"
    assert task["url"].startswith("https://sf.taobao.com/list/50025969__2.htm?")

    repo.report_search_task_progress(url=task["url"], page_num=1, has_next=False)
    counts = repo.search_task_counts()
    assert counts["search_done"] == 1
    assert counts["search_pruned"] == 5


def test_taobao_progress_can_restore_a_missing_legacy_task_from_its_url(tmp_path: Path):
    repo = _make_repo(tmp_path)
    url = (
        "https://sf.taobao.com/list/50025969__2.htm"
        "?location_code=310115&st_param=1&auction_start_seg=-1&page=4"
    )

    repo.report_search_task_progress(url=url, page_num=4, has_next=True)

    task = repo.claim_search_task("restored-session")
    assert task is not None
    assert task["task_key"] == "310115:50025969:1"
    assert task["page"] == 5


def test_taobao_main_sort_expands_pending_siblings_after_page_83(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.bootstrap_search_task(
        {"location_code": "310115", "category": "50025969", "st_param": "2", "page": 83}
    )
    task = repo.claim_search_task("legacy-session")
    assert task is not None

    repo.report_search_task_progress(url=task["url"], page_num=83, has_next=False)

    counts = repo.search_task_counts()
    assert counts["search_done"] == 1
    assert counts["search_pending"] == 5


def test_taobao_non_main_zero_bid_does_not_expand_sibling_tasks(tmp_path: Path):
    repo = _make_repo(tmp_path)
    repo.bootstrap_search_task(
        {"location_code": "310115", "category": "50025969", "st_param": "1", "page": 1}
    )
    task = repo.claim_search_task("legacy-session")
    assert task is not None

    repo.report_search_task_progress(
        url=task["url"], page_num=1, has_next=False, zero_bid_detected=True
    )

    assert repo.count_search_tasks() == 1
    assert repo.search_task_counts()["search_done"] == 1
