from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict

from .adapters.taobao_judicial import TaobaoJudicialAuctionAdapter
from .contracts import CollectionAdapter, DetailExtractor
from .detail_extractors import resolve_detail_extractor
from .detail_processor import DetailProcessor


class DetailCollectionService:
    """Thin orchestration wrapper for detail-stage automation entrypoints."""

    def __init__(
        self,
        data_root: str | Path,
        repository: Any = None,
        adapter: CollectionAdapter | None = None,
    ):
        self.data_root = Path(data_root)
        self.repository = repository
        self.adapter = adapter or TaobaoJudicialAuctionAdapter()

    @property
    def failed_dir(self) -> Path:
        path = self.data_root / "failed"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def retry_dir(self) -> Path:
        path = self.data_root / "retry"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def next_task(self, dispatched_tasks: Dict[str, datetime.datetime], cooldown_seconds: int) -> Dict[str, Any]:
        now = datetime.datetime.now()
        if self.repository and getattr(self.repository, "enabled", False):
            for candidate in self.repository.iter_pending_task_items(limit=100):
                tid = str(candidate["id"])
                last_time = dispatched_tasks.get(tid)
                if last_time and (now - last_time).total_seconds() < cooldown_seconds:
                    continue
                dispatched_tasks[tid] = now
                return {"url": candidate.get("url")}
        return {}

    def next_visit_task(
        self,
        *,
        dispatched_tasks: Dict[str, datetime.datetime],
        cooldown_seconds: int,
        legacy_entries: list[tuple[str, Dict[str, Any]]] | None = None,
    ) -> Dict[str, Any]:
        now = datetime.datetime.now()
        candidate_entries: list[tuple[str, Dict[str, Any]]] = []
        if self.repository and getattr(self.repository, "enabled", False):
            candidate_entries = [
                (str(item.get("id")), {"data": {"url": item.get("url"), "is_processed": item.get("is_processed", False)}})
                for item in self.repository.iter_pending_flat_items(limit=500)
            ]
        elif legacy_entries is not None:
            candidate_entries = legacy_entries

        for item_id, entry in candidate_entries:
            data = entry.get("data", {})
            if not data.get("url") or data.get("is_processed"):
                continue
            html_name = f"item-{item_id}.html"
            html_path = self.data_root / "html" / html_name
            retry_path = self.retry_dir / f"{html_name}.retry"
            legacy_html = self.data_root / html_name
            txt_path = self.data_root / f"item-{item_id}.txt"
            p_html = self.data_root / "html" / f"{html_name}.processing"
            p_legacy = self.data_root / f"{html_name}.processing"
            exists = any(path.exists() for path in (html_path, retry_path, legacy_html, txt_path, p_html, p_legacy))
            if exists:
                continue
            last_time = dispatched_tasks.get(item_id)
            if last_time and (now - last_time).total_seconds() < cooldown_seconds:
                continue
            dispatched_tasks[item_id] = now
            return {
                "task_type": "visit",
                "id": item_id,
                "url": data.get("url"),
            }
        return {"task_type": "none"}

    def batch_tasks(
        self,
        *,
        dispatched_tasks: Dict[str, datetime.datetime],
        cooldown_seconds: int,
        batch_size: int = 300,
    ) -> Dict[str, Any]:
        now = datetime.datetime.now()
        if self.repository and getattr(self.repository, "enabled", False):
            counts = self.repository.counts_snapshot()
            total_count = counts["db_total_ids"]
            pending_candidates = self.repository.iter_pending_task_items(limit=batch_size * 3)
            pending_count = counts["db_pending_ids"]
            done_count = max(0, total_count - pending_count)
            tasks = []
            for candidate in pending_candidates:
                tid = str(candidate["id"])
                last_time = dispatched_tasks.get(tid)
                if last_time and (now - last_time).total_seconds() < cooldown_seconds:
                    continue
                tasks.append({"id": tid, "url": candidate.get("url")})
                dispatched_tasks[tid] = now
                if len(tasks) >= batch_size:
                    break
            return {"tasks": tasks, "total": total_count, "done": done_count, "pending": pending_count}
        return {"tasks": [], "total": 0, "done": 0, "pending": 0}

    def submit_html(
        self,
        *,
        item_id: str,
        html_content: str,
        status: str | None,
        get_working_item: Callable[[str, bool], Dict[str, Any] | None],
        apply_flat_override_patch: Callable[[Dict[str, Any], Dict[str, Any]], None],
        reset_structured_sections_for_resync: Callable[[Dict[str, Any]], None],
        update_file_global: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        submit_task: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        pending_tasks: list[str],
    ) -> Dict[str, Any]:
        working_item = get_working_item(item_id, True)
        if not working_item:
            return {"status": "id_not_found"}

        html_dir = self.data_root / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
        html_path = html_dir / f"item-{item_id}.html"
        html_path.write_text(html_content, encoding="utf-8")
        print(f"Saved HTML to {html_path}.")

        if status:
            working_data = working_item["data"]
            working_data["status"] = status
            apply_flat_override_patch(working_data, {"status": status})
            reset_structured_sections_for_resync(working_data)
            self.adapter.sync_record(working_data)
            if working_item["cached"] and item_id in pending_tasks:
                pending_tasks.remove(item_id)
            update_file_global(working_item["file_path"], item_id, working_data)
            event_type = "analyze_html_status"
            persist_item_to_db(
                working_data,
                event_type,
                {"item_id": item_id, "status": status, "source_file": working_item["file_path"]},
            )
            normalized_status = str(status).strip().lower()
            if normalized_status.startswith("failed_") and prefer_db_task_reads():
                evict_runtime_item(item_id)
            if normalized_status.startswith("failed_"):
                return {"status": "queued"}

        submit_task(str(html_path))
        return {"status": "queued"}

    def apply_working_item_patch(
        self,
        *,
        item_id: str,
        patch_data: Dict[str, Any],
        event_type: str,
        get_working_item: Callable[[str, bool], Dict[str, Any] | None],
        apply_flat_override_patch: Callable[[Dict[str, Any], Dict[str, Any]], None],
        reset_structured_sections_for_resync: Callable[[Dict[str, Any]], None],
        update_file_global: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        pending_tasks: list[str],
        mark_processed: bool = False,
        force_status: str | None = None,
    ) -> Dict[str, Any]:
        working_item = get_working_item(item_id, include_processed=True)
        if not (item_id and working_item):
            return {"status": "id_not_found"}

        current_data = working_item["data"]
        current_data.update(patch_data)
        if mark_processed:
            current_data["is_processed"] = True
        if force_status is not None:
            current_data["status"] = force_status
        apply_flat_override_patch(current_data, patch_data)
        if force_status is not None:
            apply_flat_override_patch(current_data, {"status": force_status})
        reset_structured_sections_for_resync(current_data)
        self.adapter.sync_record(current_data)

        if working_item["cached"] and item_id in pending_tasks:
            pending_tasks.remove(item_id)

        file_path = working_item["file_path"]
        update_file_global(file_path, item_id, current_data)
        persist_item_to_db(current_data, event_type, {"item_id": item_id, "source_file": file_path})
        if prefer_db_task_reads():
            evict_runtime_item(item_id)
        return {"status": "ok"}

    def infer_location(
        self,
        *,
        address: str,
        title: str,
        item_id: str | None,
        chat_with_glm: Callable[[str], str],
        log_prediction_event: Callable[..., None],
    ) -> Dict[str, Any]:
        prompt = self.adapter.location_prompt(address=address, title=title)
        if prompt is None:
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=0,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason="location inference is not supported by this collection adapter",
            )
            return {}
        infer_started_at = time.time()
        try:
            resp = chat_with_glm(prompt)
            if "```json" in resp:
                resp = resp.split("```json")[1].split("```")[0]
            elif "```" in resp:
                resp = resp.split("```")[1].split("```")[0]
            result = json.loads(resp.strip())
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=(time.time() - infer_started_at) * 1000,
                recall_count=None,
                final_confidence=None,
                success=True,
                failure_reason=None,
            )
            return result
        except Exception as e:
            print(f"Error calling LLM: {e}")
            log_prediction_event(
                task_type="infer_location",
                item_id=item_id,
                duration_ms=(time.time() - infer_started_at) * 1000,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=str(e),
            )
            return {}

    def process_html_file(
        self,
        file_path: str,
        *,
        get_working_item: Callable[[str, bool], Dict[str, Any] | None],
        get_data_path: Callable[[Any], str],
        update_item_in_json: Callable[[str, str, Dict[str, Any]], None],
        remove_item_from_json: Callable[[str, str], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        mark_item_deleted_in_db: Callable[[str, str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        sync_avm_risk_aliases: Callable[[Dict[str, Any]], Dict[str, Any]],
        extract_avm_risk_features: Callable[[str, str | None], Dict[str, Any]],
        log_prediction_event: Callable[..., None],
        current_processing: set[str],
        seen_ids: Dict[str, Any],
        pending_tasks: list[str],
        detail_extractor: DetailExtractor | None = None,
        extract_auction_data: Callable[..., str] | None = None,
    ) -> None:
        resolved_detail_extractor = resolve_detail_extractor(
            detail_extractor=detail_extractor,
            legacy_extract_auction_data=extract_auction_data,
        )
        DetailProcessor(
            data_root=self.data_root,
            failed_dir=self.failed_dir,
            retry_dir=self.retry_dir,
            adapter=self.adapter,
        ).process(
            file_path,
            get_working_item=get_working_item,
            get_data_path=get_data_path,
            update_item_in_json=update_item_in_json,
            remove_item_from_json=remove_item_from_json,
            persist_item_to_db=persist_item_to_db,
            mark_item_deleted_in_db=mark_item_deleted_in_db,
            evict_runtime_item=evict_runtime_item,
            prefer_db_task_reads=prefer_db_task_reads,
            sync_avm_risk_aliases=sync_avm_risk_aliases,
            detail_extractor=resolved_detail_extractor,
            extract_avm_risk_features=extract_avm_risk_features,
            log_prediction_event=log_prediction_event,
            current_processing=current_processing,
            seen_ids=seen_ids,
            pending_tasks=pending_tasks,
        )

    def fetch_missing_archives(
        self,
        *,
        limit: int = 20,
        timeout: int = 15,
        extract_risk: bool = False,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        from tools.fetch_missing_detail_archives import fetch_missing_detail_archives

        return fetch_missing_detail_archives(
            data_root=self.data_root,
            limit=limit,
            timeout=timeout,
            extract_risk=extract_risk,
            dry_run=dry_run,
        )

    def backfill_archived(
        self,
        *,
        limit: int = 200,
        dry_run: bool = True,
        extract_risk: bool = False,
    ) -> Dict[str, Any]:
        from tools.backfill_archived_details import backfill_archived_details

        return backfill_archived_details(
            self.data_root,
            limit=limit,
            dry_run=dry_run,
            extract_risk=extract_risk,
        )

    def prepare_replay(
        self,
        *,
        window_days: int = 7,
        limit: int = 100,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        from tools.prepare_recent_detail_replay import prepare_recent_detail_replay

        return prepare_recent_detail_replay(
            self.data_root,
            window_days=window_days,
            limit=limit,
            dry_run=dry_run,
        )

    def run_maintenance(
        self,
        *,
        window_days: int = 7,
        archive_limit: int = 200,
        sample_limit: int = 20,
        replay_limit: int = 100,
        fetch_limit: int = 20,
        fetch_timeout: int = 15,
        dry_run: bool = True,
        extract_risk: bool = False,
        prepare_replay: bool = False,
        fetch_archives: bool = False,
    ) -> Dict[str, Any]:
        from tools.run_recent_enrich_maintenance import run_recent_enrich_maintenance

        return run_recent_enrich_maintenance(
            data_root=self.data_root,
            window_days=window_days,
            archive_limit=archive_limit,
            sample_limit=sample_limit,
            replay_limit=replay_limit,
            fetch_limit=fetch_limit,
            fetch_timeout=fetch_timeout,
            dry_run=dry_run,
            extract_risk=extract_risk,
            prepare_replay=prepare_replay,
            fetch_archives=fetch_archives,
        )
