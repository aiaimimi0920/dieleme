from __future__ import annotations

from datetime import datetime, timedelta

from pathlib import Path

from sqlalchemy import event, func, insert, select

from sqlalchemy.orm import Session as SqlAlchemySession

import src.storage.repository as repository_module

from src.storage.models import FapaiSeedItem, FapaiSeedOccurrence, FapaiSeedScanJob, FapaiSeedScanProgress

from src.storage.repository import DatabaseSettings, PropertyRepository

def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'seed-queue.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )

def _ensure_nansha_job(repo: PropertyRepository) -> None:
    repo.ensure_seed_scan_job(
        {
            "job_key": "guangdong-guangzhou-nansha-50025969",
            "province": "广东省",
            "city": "广州市",
            "district": "南沙区",
            "location_code": "440115",
            "category": "50025969",
        },
        sort_specs=[
            {"sort_key": "bid_desc", "sort_name": "出价次数由高到低", "st_param": "2"},
            {"sort_key": "end_time_soon", "sort_name": "结拍时间由近到远", "st_param": "1"},
        ],
        max_page=83,
    )

def _upsert_sample_seed(repo: PropertyRepository, item_id: str = "1001") -> None:
    repo.upsert_seed_items(
        job_key="guangdong-guangzhou-nansha-50025969",
        progress_key="guangdong-guangzhou-nansha-50025969::bid_desc",
        sort_key="bid_desc",
        sort_name="出价次数由高到低",
        st_param="2",
        page=1,
        source_page_url="https://sf-item.taobao.com/list/guangzhou?page=1",
        source_final_url="https://sf-item.taobao.com/list/guangzhou?page=1&st=2",
        items=[
            {
                "id": item_id,
                "title": "广州市南沙区测试房产",
                "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
                "extra": "kept-for-observer",
            }
        ],
    )

__all__ = [name for name in globals() if not name.startswith("__")]
