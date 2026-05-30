from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict

from src.avm.collection_template import sync_collection_record

from .search_bootstrap import (
    DEFAULT_CATEGORIES,
    DEFAULT_SORT_ORDER,
    iter_job_snapshots,
    load_all_location_codes,
    load_priority_codes,
)


class SeedCollectionService:
    """Bridge legacy sniff-task orchestration into explicit collection-stage APIs."""

    def __init__(self, repository: Any = None, jobs_dir: str | None = None, data_root: str | None = None):
        self.repository = repository
        self.jobs_dir = jobs_dir
        self.data_root = data_root

    @staticmethod
    def build_seed_stub(item: Dict[str, Any], parse_price: Callable[[Any], Any], safe_int: Callable[[Any], Any]) -> Dict[str, Any]:
        deal_price = parse_price(item.get("currentPrice")) or parse_price(item.get("成交价格"))
        starting_price = parse_price(item.get("initialPrice")) or parse_price(item.get("起拍价格"))
        apply_count = safe_int(item.get("applyCount")) or safe_int(item.get("竞拍人数"))
        bid_count = safe_int(item.get("bidCount")) or safe_int(item.get("出价次数"))
        bidder_count = safe_int(item.get("bidderCount")) or safe_int(item.get("bidder_count")) or safe_int(item.get("出价人数"))
        deposit = parse_price(item.get("deposit")) or parse_price(item.get("保证金"))
        auction_date = str(item.get("auction_date", "") or "").strip()
        auction_start_time = str(item.get("auction_start_time", "") or item.get("startTime", "") or "").strip()
        full_address = item.get("full_address") or item.get("完整地址") or item.get("location") or item.get("地点")
        coordinate_source = item.get("coordinate_source")
        watch_count = safe_int(item.get("watchCount")) or safe_int(item.get("watch_count")) or safe_int(item.get("围观人数"))
        reminder_count = safe_int(item.get("remindCount")) or safe_int(item.get("reminder_count")) or safe_int(item.get("提醒人数"))
        view_count = safe_int(item.get("viewCount")) or safe_int(item.get("view_count")) or safe_int(item.get("浏览次数"))

        stub = {
            "id": str(item.get("id")),
            "title": item.get("title"),
            "source_title": item.get("title"),
            "source_platform": item.get("source_platform") or "taobao_sf",
            "url": item.get("url"),
            "source_url": item.get("url"),
            "地点": full_address,
            "full_address": full_address,
            "完整地址": full_address,
            "城市": item.get("city"),
            "区": item.get("district"),
            "end": item.get("end"),
            "status": "done",
            "is_processed": False,
            "auction_date": auction_date,
            "交易时间": auction_date or None,
            "auction_start_time": auction_start_time or None,
            "开拍时间": auction_start_time or None,
            "currentPrice": deal_price,
            "initialPrice": starting_price,
            "transaction_price": deal_price,
            "starting_price": starting_price,
            "成交价格": deal_price,
            "起拍价格": starting_price,
            "applyCount": apply_count,
            "竞拍人数": apply_count,
            "apply_count": apply_count,
            "bidCount": bid_count,
            "bid_count": bid_count,
            "出价次数": bid_count,
            "bidderCount": bidder_count,
            "bidder_count": bidder_count,
            "出价人数": bidder_count,
            "watchCount": watch_count,
            "watch_count": watch_count,
            "围观人数": watch_count,
            "remindCount": reminder_count,
            "reminder_count": reminder_count,
            "提醒人数": reminder_count,
            "viewCount": view_count,
            "view_count": view_count,
            "浏览次数": view_count,
            "deposit": deposit,
            "保证金": deposit,
            "latitude": parse_price(item.get("latitude")) if item.get("latitude") is not None else None,
            "longitude": parse_price(item.get("longitude")) if item.get("longitude") is not None else None,
            "纬度": parse_price(item.get("latitude")) if item.get("latitude") is not None else None,
            "经度": parse_price(item.get("longitude")) if item.get("longitude") is not None else None,
            "coordinate_source": coordinate_source,
            "auction_round": safe_int(item.get("auction_round")),
            "housing_type": item.get("housing_type"),
            "source_item_id": str(item.get("id")),
            "list_payload_path": item.get("list_payload_path"),
            "source_page_url": item.get("source_page_url") or item.get("page_url"),
        }

        filtered = {key: value for key, value in stub.items() if value not in (None, "")}
        return sync_collection_record(filtered)

    def _bootstrap_db_search_tasks(self) -> None:
        if not (self.repository and getattr(self.repository, "enabled", False)):
            return
        try:
            if getattr(self.repository, "count_search_tasks", None) and self.repository.count_search_tasks() > 0:
                return
        except Exception:
            return

        snapshots = iter_job_snapshots(self.jobs_dir) if self.jobs_dir else []
        all_codes = load_all_location_codes(self.data_root) if self.data_root else []
        if snapshots:
            try:
                self.repository.import_search_task_snapshots(snapshots)
            except Exception:
                pass

        if all_codes:
            try:
                self.repository.ensure_seed_search_tasks(all_codes, DEFAULT_CATEGORIES, sort_param="2")
            except Exception:
                pass

    def next_task(self, session_id: str, *, paused: bool = False) -> Dict[str, Any]:
        if paused:
            return {"task": None, "message": "Paused (Captcha)"}
        if not (self.repository and getattr(self.repository, "enabled", False)):
            return {"task": None, "message": "搜索任务数据库未启用"}

        self._bootstrap_db_search_tasks()
        task = None
        try:
            priority_codes = load_priority_codes(self.jobs_dir) if self.jobs_dir else []
            task = self.repository.claim_search_task(
                session_id,
                priority_codes=priority_codes,
                sort_order=DEFAULT_SORT_ORDER,
            )
        except Exception:
            task = None

        if task:
            return {
                "task": task,
                "location": {"code": task.get("location_code"), "name": task.get("location_code")},
                "is_resume": task.get("is_resume", False),
                "message": task.get("desc", "Task assigned"),
            }
        return {"task": None, "message": "所有嗅探任务已完成"}

    def report_progress(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = payload.get("url")
        if not url:
            raise ValueError("Missing URL")

        if self.repository and getattr(self.repository, "enabled", False):
            self.repository.report_search_task_progress(
                url=url,
                page_num=int(payload.get("page_num", 1) or 1),
                has_next=bool(payload.get("has_next", True)),
                max_page=int(payload.get("total_pages")) if payload.get("total_pages") else None,
                zero_bid_detected=bool(payload.get("zero_bid_detected", False)),
            )

        return {"status": "ok"}

    def counts_snapshot(self) -> Dict[str, int]:
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                return self.repository.search_task_counts()
            except Exception:
                pass
        return {
            "search_pending": 0,
            "search_in_progress": 0,
            "search_done": 0,
            "search_pruned": 0,
        }

    def submit_batch(
        self,
        data: Dict[str, Any],
        *,
        parse_price: Callable[[Any], Any],
        safe_int: Callable[[Any], Any],
        prefer_db_task_reads: Callable[[], bool],
        get_seen_entry: Callable[[str], Any],
        get_flat_item: Callable[[str], Dict[str, Any] | None],
        get_data_path: Callable[[Any], str],
        update_file_global: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        seen_ids: Dict[str, Any],
        pending_tasks: list[str],
        archive_list_payload: Callable[[Any, datetime.datetime], str | None],
    ) -> Dict[str, Any]:
        items = data.get("items", [])
        source_page_url = data.get("source_page_url") or data.get("page_url") or data.get("url")
        list_payload_path = None
        try:
            list_payload_path = archive_list_payload(data.get("raw_payload"), datetime.datetime.now())
        except Exception as archive_error:
            print(f"[LIST-PAYLOAD] Archive failed: {archive_error}")

        new_count = 0
        items_by_date: Dict[str, list[Dict[str, Any]]] = {}

        for item in items:
            item_id = str(item.get("id"))
            status = str(item.get("status", "")).lower()
            is_sold = item.get("是否成交")
            if list_payload_path and not item.get("list_payload_path"):
                item["list_payload_path"] = list_payload_path
            if source_page_url and not item.get("source_page_url"):
                item["source_page_url"] = source_page_url

            prepared_item = self.build_seed_stub(item, parse_price=parse_price, safe_int=safe_int)
            if source_page_url and not prepared_item.get("source_page_url"):
                prepared_item["source_page_url"] = source_page_url

            is_done = (status in ["done", "成交"]) or (is_sold is True) or (str(item.get("outcome", "")).lower() == "成交")
            if not is_done:
                continue

            existing_entry = get_seen_entry(item_id)
            db_existing_item = None
            if existing_entry is None:
                try:
                    db_existing_item = get_flat_item(item_id)
                except Exception as db_existing_error:
                    print(f"[DB] Existing item lookup failed item={item_id}: {db_existing_error}")

            event_payload = {
                "source": "collection_seed_batch",
                "item_id": item_id,
                "source_page_url": source_page_url,
            }

            if existing_entry or db_existing_item:
                print(f"[SEED ITEM] [EXISTING] Scanned: {item.get('title', 'Unknown')} | ID: {item_id}")
                merged = dict((existing_entry or {}).get("data", {}) or db_existing_item or {})
                for key, value in prepared_item.items():
                    if value not in (None, "") and merged.get(key) in (None, ""):
                        merged[key] = value
                sync_collection_record(merged)
                if existing_entry and not prefer_db_task_reads():
                    entry = seen_ids[item_id]
                    entry["data"] = merged
                    if not merged.get("is_processed") and item_id not in pending_tasks:
                        pending_tasks.append(item_id)
                    target_file_path = existing_entry["file_path"]
                else:
                    target_file_path = get_data_path((merged.get("auction_date", "") or "").split(" ")[0] or "unknown")
                update_file_global(target_file_path, item_id, merged)
                event_payload["source_file"] = target_file_path
                persist_item_to_db(merged, "sniff_saved", event_payload)
                if prefer_db_task_reads():
                    evict_runtime_item(item_id)
                continue

            print(f"[SEED ITEM] [NEW] Found: {item.get('title', 'Unknown')} | Status: {status} | URL: {item.get('url')}")
            if item_id not in seen_ids:
                a_date = prepared_item.get("auction_date", "").split(" ")[0] or "unknown"
                items_by_date.setdefault(a_date, []).append(prepared_item)
                file_path = get_data_path(a_date)
                if not prefer_db_task_reads():
                    seen_ids[item_id] = {"file_path": file_path, "data": prepared_item, "status": item.get("status")}
                    if not prepared_item.get("is_processed") and item_id not in pending_tasks:
                        pending_tasks.append(item_id)
                event_payload["source_file"] = file_path
                persist_item_to_db(prepared_item, "sniff_saved", event_payload)
                if prefer_db_task_reads():
                    evict_runtime_item(item_id)
                new_count += 1

        for date_str, date_items in items_by_date.items():
            file_path = get_data_path(date_str)
            current_file_data = []
            if os.path.exists(file_path):
                try:
                    current_file_data = json.loads(Path(file_path).read_text(encoding="utf-8"))
                except Exception:
                    current_file_data = []
            current_file_data.extend(date_items)
            Path(file_path).write_text(json.dumps(current_file_data, ensure_ascii=False, indent=4), encoding="utf-8")

        return {"status": "ok", "new": new_count}
