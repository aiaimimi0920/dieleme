from pathlib import Path

import pytest

from src.collection.seed_scan_policy import GenericSeedScanPolicy
from src.storage.models import FapaiSeedItem, FapaiSeedScanJob
from tools import seed_collector
from tools.test.seed_queue_repository_test_context import _make_repo, _ensure_nansha_job


def _generic_job(template: str, job_key: str = "catalog-root") -> dict[str, str]:
    return {
        "job_key": job_key,
        "source_url_template": template,
    }


def _generic_sort() -> list[dict[str, object]]:
    return [
        {
            "sort_key": "price",
            "sort_name": "price",
            "st_param": "desc",
            "sort_order": 0,
        }
    ]


def test_generic_seed_scan_uses_template_cursor_and_lease_owner(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    template = "https://catalog.example/products?category={category}&sort={st_param}&page={page}"
    created = repo.ensure_seed_scan_job(
        _generic_job(template),
        sort_specs=_generic_sort(),
        max_page=2,
        policy=policy,
    )

    assert created["job_key"].startswith("source:catalog-x-")
    assert repo.claim_seed_scan_page("legacy-worker") is None
    first = repo.claim_seed_scan_page("generic-worker", policy=policy)
    assert first is not None
    assert first["job_key"] == created["job_key"]
    assert first["source_platform"] == "catalog_x"
    assert first["location_code"] == "source"
    assert first["category"] == "catalog_x"
    assert first["url"] == "https://catalog.example/products?category=catalog_x&sort=desc&page=1"
    upsert = repo.upsert_seed_items(
        job_key=first["job_key"],
        progress_key=first["progress_key"],
        sort_key=first["sort_key"],
        sort_name=first["sort_name"],
        st_param=first["st_param"],
        page=first["page"],
        source_page_url=first["url"],
        items=[{"id": "sku-1", "url": "//catalog.example/products/sku-1"}],
        policy=policy,
        worker_id="generic-worker",
    )
    assert upsert == {
        "seen": 1,
        "new_items": 1,
        "existing_items": 0,
        "new_occurrences": 1,
    }
    with repo.session_factory() as session:
        assert session.get(FapaiSeedItem, policy.storage_item_id("sku-1")).source_url == (
            "https://catalog.example/products/sku-1"
        )

    with pytest.raises(ValueError, match="lease is not owned"):
        repo.complete_seed_scan_page(
            progress_key=first["progress_key"],
            page=1,
            item_count=2,
            has_next=True,
            worker_id="stale-worker",
            policy=policy,
        )
    repo.complete_seed_scan_page(
        progress_key=first["progress_key"],
        page=1,
        item_count=2,
        has_next=True,
        worker_id="generic-worker",
        policy=policy,
    )

    second = repo.claim_seed_scan_page("generic-worker", policy=policy)
    assert second is not None
    assert second["page"] == 2
    assert second["url"].endswith("sort=desc&page=2")
    repo.complete_seed_scan_page(
        progress_key=second["progress_key"],
        page=2,
        item_count=0,
        has_next=True,
        worker_id="generic-worker",
        policy=policy,
    )

    assert repo.claim_seed_scan_page("generic-worker", policy=policy) is None
    assert repo.seed_queue_counts()["seed_scan_job_completed"] == 1


def test_generic_seed_item_requires_an_explicit_source_url(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/products?page={page}"),
        sort_specs=_generic_sort(),
        policy=policy,
    )
    task = repo.claim_seed_scan_page("worker-a", policy=policy)
    assert task is not None

    with pytest.raises(ValueError, match="requires source URL"):
        repo.upsert_seed_items(
            job_key=task["job_key"],
            progress_key=task["progress_key"],
            sort_key=task["sort_key"],
            sort_name=task["sort_name"],
            st_param=task["st_param"],
            page=1,
            source_page_url="https://catalog.example/products?page=1",
            items=[{"id": "sku-without-url"}],
            policy=policy,
            worker_id="worker-a",
        )


def test_generic_seed_scan_failure_requires_the_claiming_worker(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/products?page={page}"),
        sort_specs=_generic_sort(),
        max_page=2,
        policy=policy,
    )
    task = repo.claim_seed_scan_page("worker-a", policy=policy)
    assert task is not None

    with pytest.raises(ValueError, match="lease is not owned"):
        repo.fail_seed_scan_page(
            task["progress_key"],
            "stale result",
            worker_id="worker-b",
            policy=policy,
        )
    repo.fail_seed_scan_page(
        task["progress_key"],
        "retry",
        worker_id="worker-a",
        policy=policy,
    )

    retry = repo.claim_seed_scan_page("worker-b", policy=policy)
    assert retry is not None
    assert retry["progress_key"] == task["progress_key"]
    assert retry["page"] == 1


def test_generic_seed_failure_reporting_is_idempotent_after_lease_loss() -> None:
    policy = GenericSeedScanPolicy(source_platform="catalog_x")

    class StaleRepository:
        def fail_seed_scan_page(self, *_args: object, **_kwargs: object) -> None:
            raise ValueError("seed scan lease is not owned by worker: progress")

    config = type(
        "Config",
        (),
        {"worker_id": "stale-worker", "seed_scan_policy": policy},
    )()

    assert seed_collector._fail_claimed_seed_page(
        config,
        StaleRepository(),
        {"progress_key": "progress"},
        "stale result",
    ) is False


@pytest.mark.parametrize("parallel_sorts", [False, True])
def test_seed_scan_claims_are_isolated_by_policy(
    tmp_path: Path,
    parallel_sorts: bool,
) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    _ensure_nansha_job(repo)
    repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/products?page={page}"),
        sort_specs=_generic_sort(),
        policy=policy,
    )

    generic_task = repo.claim_seed_scan_page(
        "generic-worker",
        parallel_sorts=parallel_sorts,
        policy=policy,
    )
    taobao_task = repo.claim_seed_scan_page(
        "taobao-worker",
        parallel_sorts=parallel_sorts,
    )

    assert generic_task is not None
    assert generic_task["source_platform"] == "catalog_x"
    assert generic_task["job_key"].startswith("source:catalog-x-")
    assert taobao_task is not None
    assert taobao_task["source_platform"] == "taobao_sf"
    assert taobao_task["job_key"] == "guangdong-guangzhou-nansha-50025969"
    with pytest.raises(ValueError, match="does not belong to policy"):
        repo.upsert_seed_items(
            job_key=taobao_task["job_key"],
            progress_key=taobao_task["progress_key"],
            sort_key=taobao_task["sort_key"],
            sort_name=taobao_task["sort_name"],
            st_param=taobao_task["st_param"],
            page=taobao_task["page"],
            source_page_url=taobao_task["url"],
            items=[{"id": "foreign", "url": "https://catalog.example/foreign"}],
            policy=policy,
            worker_id="generic-worker",
        )


def test_generic_archive_is_scoped_and_normalizes_active_job_keys(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    _ensure_nansha_job(repo)
    active = repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/a?page={page}", "active"),
        sort_specs=_generic_sort(),
        policy=policy,
    )
    stale = repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/b?page={page}", "stale"),
        sort_specs=_generic_sort(),
        policy=policy,
    )
    other_policy = GenericSeedScanPolicy(source_platform="catalog_y")
    other = repo.ensure_seed_scan_job(
        _generic_job("https://other.example/products?page={page}", "other"),
        sort_specs=_generic_sort(),
        policy=other_policy,
    )

    result = repo.archive_seed_scan_jobs_except(["active"], policy=policy)

    assert result["archived_jobs"] == 1
    with repo.session_factory() as session:
        assert session.get(FapaiSeedScanJob, active["job_key"]).status == "pending"
        assert session.get(FapaiSeedScanJob, stale["job_key"]).status == "archived"
        assert session.get(FapaiSeedScanJob, other["job_key"]).status == "pending"
        assert session.get(
            FapaiSeedScanJob,
            "guangdong-guangzhou-nansha-50025969",
        ).status == "pending"


def test_invalid_generic_template_does_not_leave_a_claimed_lease(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    policy = GenericSeedScanPolicy(source_platform="catalog_x")
    repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/products?value={unknown}"),
        sort_specs=_generic_sort(),
        policy=policy,
    )

    with pytest.raises(ValueError, match="invalid seed scan URL template"):
        repo.claim_seed_scan_page("worker-a", policy=policy)

    repo.ensure_seed_scan_job(
        _generic_job("https://catalog.example/products?page={page}"),
        sort_specs=_generic_sort(),
        policy=policy,
    )
    task = repo.claim_seed_scan_page("worker-b", policy=policy)
    assert task is not None
    assert task["url"].endswith("page=1")


def test_seed_collector_generic_defaults_come_from_adapter_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CROW_COLLECTION_ADAPTER", "generic")
    monkeypatch.setenv("CROW_COLLECTION_SOURCE_PLATFORM", "catalog_x")
    monkeypatch.setenv(
        "CROW_SEED_SOURCE_URL_TEMPLATE",
        "https://catalog.example/products?page={page}",
    )
    monkeypatch.setenv("FAPAI_OUTPUT_DIR", str(tmp_path / "output"))
    for name in (
        "FAPAI_SEED_JOB_KEY",
        "FAPAI_SEED_LOCATION_CODE",
        "FAPAI_SEED_CATEGORY",
        "FAPAI_SEED_SORTS",
        "FAPAI_SEED_MAX_PAGE",
    ):
        monkeypatch.delenv(name, raising=False)

    config, loop_enabled = seed_collector.config_from_env_and_args([])

    assert loop_enabled is False
    assert config.job_key == "catalog_x-seed"
    assert config.location_code == "source"
    assert config.category == "catalog_x"
    assert config.max_page == 1
    assert config.source_url_template.endswith("?page={page}")
    assert config.sort_specs[0].sort_key == "source"
    assert isinstance(config.seed_scan_policy, GenericSeedScanPolicy)
    assert config.collection_adapter is not None
    assert config.collection_adapter.source_platform == "catalog_x"
