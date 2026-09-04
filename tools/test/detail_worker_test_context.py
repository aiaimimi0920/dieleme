from __future__ import annotations

import datetime

import json

from pathlib import Path

from typing import Any

from src.storage.models import FapaiSeedItem

from src.storage.repository import DatabaseSettings, PropertyRepository

from tools import detail_worker, live_batch_smoke, seed_collector, taobao_login_health

def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'detail-worker.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )

def _seed_one_item(repo: PropertyRepository) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
        max_page=83,
    )
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": "3001",
                "title": "南沙详情 A",
                "url": "https://sf-item.taobao.com/sf_item/3001.htm",
                "source_page_url": task["url"],
            }
        ],
    )

def _seed_items(repo: PropertyRepository, item_ids: list[str]) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[{"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"}],
        max_page=83,
    )
    task = repo.claim_seed_scan_page("seed-worker", lease_seconds=30)
    assert task is not None
    repo.upsert_seed_items(
        job_key=task["job_key"],
        progress_key=task["progress_key"],
        sort_key=task["sort_key"],
        sort_name=task["sort_name"],
        st_param=task["st_param"],
        page=1,
        source_page_url=task["url"],
        items=[
            {
                "id": item_id,
                "title": f"南沙详情 {item_id}",
                "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
                "source_page_url": task["url"],
            }
            for item_id in item_ids
        ],
    )

__all__ = [name for name in globals() if not name.startswith("__")]
