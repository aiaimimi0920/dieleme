from __future__ import annotations

import json

from pathlib import Path

from typing import Any

from src.storage.repository import DatabaseSettings, PropertyRepository

from tools import browserless_seed_probe, live_batch_smoke, seed_collector, taobao_login_health

class _FakeProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(html: str, *, final_url: str) -> dict[str, Any]:
        if html == "challenge":
            return {
                "item_count": None,
                "body_has_challenge": True,
                "body_has_login": False,
                "body_has_punish": True,
            }
        return {
            "item_count": 2,
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
        }

    @staticmethod
    def extract_list_payload(html: str) -> dict[str, Any] | None:
        if html == "challenge":
            return None
        return {"data": [{"id": "2001"}, {"id": "2002"}]}

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {
            "source_page_url": source_page_url,
            "items": [
                {"id": "2001", "title": "南沙 A", "url": "https://sf-item.taobao.com/sf_item/2001.htm"},
                {"id": "2002", "title": "南沙 B", "url": "https://sf-item.taobao.com/sf_item/2002.htm"},
            ],
        }

class _BlankPageProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(html: str, *, final_url: str) -> dict[str, Any]:
        return {
            "has_script": False,
            "item_count": None,
            "first_ids": [],
            "first_urls": [],
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
            "body_snippet": html[:80],
        }

    @staticmethod
    def extract_list_payload(_html: str) -> dict[str, Any] | None:
        return None

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {"source_page_url": source_page_url, "items": []}

class _FailureOnlyProbe:
    DEFAULT_USER_AGENT = "fake-agent"

    @staticmethod
    def summarize_list_page(_html: str, *, final_url: str) -> dict[str, Any]:
        return {
            "item_count": 2,
            "first_ids": ["3001", "3002"],
            "first_urls": [f"{final_url}#3001", f"{final_url}#3002"],
            "body_has_challenge": False,
            "body_has_login": False,
            "body_has_punish": False,
        }

    @staticmethod
    def extract_list_payload(_html: str) -> dict[str, Any] | None:
        return {
            "data": [
                {"id": "3001", "status": "failure", "bidCount": 0, "itemUrl": "//sf-item.taobao.com/sf_item/3001.htm"},
                {"id": "3002", "status": "failure", "bidCount": 0, "itemUrl": "//sf-item.taobao.com/sf_item/3002.htm"},
            ]
        }

    @staticmethod
    def build_userscript_like_batch_payload(_payload, *, source_page_url: str) -> dict[str, Any]:
        return {
            "source_page_url": source_page_url,
            "items": [],
        }

def _make_repo(tmp_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{(tmp_path / 'seed-collector.sqlite3').resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )

def _make_repo_at(db_path: Path) -> PropertyRepository:
    return PropertyRepository(
        DatabaseSettings(
            url=f"sqlite:///{db_path.resolve().as_posix()}",
            echo=False,
            enable_postgis=False,
            auto_create=True,
            enabled=True,
        )
    )

__all__ = [name for name in globals() if not name.startswith("__")]
