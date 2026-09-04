from __future__ import annotations

import datetime
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict

from src.detail_artifacts import extract_detail_artifacts, get_detail_archive_path

from .contracts import CollectionAdapter, DetailExtractor


class DetailProcessor:
    """Processes one captured page while delegating product rules to an adapter."""

    def __init__(
        self,
        *,
        data_root: Path,
        failed_dir: Path,
        retry_dir: Path,
        adapter: CollectionAdapter,
    ) -> None:
        self.data_root = data_root
        self.failed_dir = failed_dir
        self.retry_dir = retry_dir
        self.adapter = adapter

    @staticmethod
    def _parse_ai_record(raw: str, item_id: str) -> Dict[str, Any]:
        if "```json" in raw:
            raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw:
            raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError("AI did not return a dictionary")
        record["id"] = int(item_id) if item_id.isdigit() else item_id
        record["source_item_id"] = item_id
        return record

    def _archive_source(
        self,
        *,
        record: Dict[str, Any],
        content: str,
        item_id: str,
        file_path: str,
    ) -> None:
        try:
            archive_path = get_detail_archive_path(
                self.data_root,
                self.adapter.archive_date(record),
                item_id,
                extension=os.path.splitext(file_path)[1] or ".html",
            )
            archive_path.write_text(content, encoding="utf-8")
            record["detail_archive_path"] = os.path.relpath(archive_path, self.data_root).replace("\\", "/")
        except Exception as error:
            print(f"[DETAIL-ARCHIVE] Failed for {item_id}: {error}")

        try:
            artifacts = extract_detail_artifacts(
                self.data_root,
                content,
                item_id=item_id,
                auction_date=self.adapter.archive_date(record),
                source_url=self.adapter.source_url(record),
            )
            for key, value in artifacts.items():
                if value not in (None, "", []):
                    record.setdefault(key, value)
        except Exception as error:
            print(f"[DETAIL-ARTIFACT] Failed for {item_id}: {error}")

    def _schedule_retry(
        self,
        *,
        item_id: str,
        reason: str,
        file_path: str,
        prefer_db_task_reads: Callable[[], bool],
        pending_tasks: list[str],
    ) -> bool:
        retry_path = self.retry_dir / f"item-{item_id}.html.retry"
        if retry_path.exists():
            print(f"\033[93m[DETAIL RETRY] {item_id}: second attempt still failed ({reason}); continuing.\033[0m")
            retry_path.unlink(missing_ok=True)
            return False

        print(f"\033[93m[DETAIL RETRY] {item_id}: {reason}; scheduling one retry.\033[0m")
        retry_path.write_text(
            f"Retry scheduled at {datetime.datetime.now().isoformat()}: {reason}",
            encoding="utf-8",
        )
        if not prefer_db_task_reads() and item_id not in pending_tasks:
            pending_tasks.append(item_id)
        try:
            os.remove(file_path)
            (self.data_root / "html" / f"item-{item_id}.html").unlink(missing_ok=True)
        except Exception:
            pass
        return True

    def _save_completed(
        self,
        *,
        record: Dict[str, Any],
        target_json_path: str,
        item_id: str,
        file_path: str,
        update_item_in_json: Callable[[str, str, Dict[str, Any]], None],
        persist_item_to_db: Callable[[Dict[str, Any], str, Dict[str, Any] | None], None],
        evict_runtime_item: Callable[[str], None],
        prefer_db_task_reads: Callable[[], bool],
        seen_ids: Dict[str, Any],
        pending_tasks: list[str],
    ) -> None:
        self.adapter.finalize_detail_record(record)
        update_item_in_json(target_json_path, item_id, record)
        persist_item_to_db(
            record,
            "detail_enriched",
            {"item_id": item_id, "file_path": file_path, "source_file": file_path},
        )
        if prefer_db_task_reads():
            evict_runtime_item(item_id)
        else:
            seen_ids[item_id] = {"file_path": target_json_path, "data": record}
            if item_id in pending_tasks:
                pending_tasks.remove(item_id)
        print(f"\033[92mSuccess {item_id}: Saved to {target_json_path} ({self.adapter.quality_summary(record)})\033[0m")

    def _cleanup_success(self, *, file_path: str, item_id: str, failed_marker_path: Path) -> None:
        try:
            os.remove(file_path)
        except Exception:
            pass
        failed_marker_path.unlink(missing_ok=True)
        html_name = f"item-{item_id}.html"
        for path in (
            self.data_root / "html" / f"{html_name}.processing",
            self.data_root / f"{html_name}.processing",
        ):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    def process(
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
        detail_extractor: DetailExtractor,
        extract_avm_risk_features: Callable[[str, str | None], Dict[str, Any]],
        log_prediction_event: Callable[..., None],
        current_processing: set[str],
        seen_ids: Dict[str, Any],
        pending_tasks: list[str],
    ) -> None:
        filename = os.path.basename(file_path)
        match = re.search(r"item-(.+?)(?:\.html|\.txt|$)", filename)
        if not match:
            print(f"Skipping {filename}: No ID found")
            try:
                os.remove(file_path)
            except Exception:
                pass
            return

        item_id = match.group(1)
        failed_marker_path = self.failed_dir / f"item-{item_id}.html.failed"
        started_at: float | None = None
        try:
            failed_once = failed_marker_path.exists()
            if not os.path.exists(file_path):
                print(f"File {filename} disappeared (race condition), skipping.")
                return
            content = Path(file_path).read_text(encoding="utf-8")
            if not content.strip():
                print(f"Empty content for {item_id}, deleting.")
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
                if failed_once:
                    failed_marker_path.unlink(missing_ok=True)
                return

            print(f"Processing {item_id}...")
            started_at = time.time()
            raw = detail_extractor.extract(content, item_id=item_id)
            if raw:
                print(f"\033[92m[AI SUCCESS] {item_id}: {raw[:200]}...\033[0m")
            if not raw:
                raise ValueError("Empty response from AI")
            record = self._parse_ai_record(raw, item_id)

            if getattr(self.adapter, "collects_avm_risk", False):
                risk_features = extract_avm_risk_features(content, item_id=item_id)
                if risk_features:
                    record["avm_risk_features"] = risk_features
                    sync_avm_risk_aliases(record)
                    print(f"[AVM-RISK] Attached risk features for item={item_id}")
                else:
                    print(f"[AVM-RISK] Extraction failed for item={item_id}; skipped attachment")

            original_record = get_working_item(item_id, include_processed=True)
            existing = original_record.get("data", {}) if original_record else {}
            self.adapter.prepare_detail_record(record, existing=existing, item_id=item_id)
            target_json_path = (
                original_record["file_path"]
                if original_record
                else get_data_path(self.adapter.partition_key(record))
            )
            self._archive_source(record=record, content=content, item_id=item_id, file_path=file_path)

            if not self.adapter.accepts_detail(record):
                print(f"\033[93mAI rejected item {item_id}; removing it from collection storage.\033[0m")
                remove_item_from_json(target_json_path, item_id)
                mark_item_deleted_in_db(
                    item_id,
                    "detail_not_done",
                    {"item_id": item_id, "target_json_path": target_json_path},
                )
                evict_runtime_item(item_id)
            else:
                retry_reason = self.adapter.retry_reason(record)
                if retry_reason and self._schedule_retry(
                    item_id=item_id,
                    reason=retry_reason,
                    file_path=file_path,
                    prefer_db_task_reads=prefer_db_task_reads,
                    pending_tasks=pending_tasks,
                ):
                    return
                self._save_completed(
                    record=record,
                    target_json_path=target_json_path,
                    item_id=item_id,
                    file_path=file_path,
                    update_item_in_json=update_item_in_json,
                    persist_item_to_db=persist_item_to_db,
                    evict_runtime_item=evict_runtime_item,
                    prefer_db_task_reads=prefer_db_task_reads,
                    seen_ids=seen_ids,
                    pending_tasks=pending_tasks,
                )
                recall_count = record.get("recall_count", record.get("召回数"))
                confidence = record.get("final_confidence")
                if confidence is None:
                    confidence = record.get("置信度") or record.get("最终置信度") or record.get("extraction_confidence")
                log_prediction_event(
                    task_type="analyze_html",
                    item_id=item_id,
                    duration_ms=(time.time() - started_at) * 1000,
                    recall_count=recall_count,
                    final_confidence=confidence,
                    success=True,
                    failure_reason=None,
                )
            self._cleanup_success(
                file_path=file_path,
                item_id=item_id,
                failed_marker_path=failed_marker_path,
            )
        except Exception as error:
            print(f"\033[91mError processing {item_id}: {error}\033[0m")
            duration_ms = (time.time() - started_at) * 1000 if started_at is not None else None
            log_prediction_event(
                task_type="analyze_html",
                item_id=item_id,
                duration_ms=duration_ms,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=str(error),
            )
            if failed_marker_path.exists():
                print(f"Second failure for {item_id}. Deleting file to avoid deadlock.")
                try:
                    Path(file_path).unlink(missing_ok=True)
                except Exception:
                    pass
                failed_marker_path.unlink(missing_ok=True)
            else:
                print(f"First failure for {item_id}. Marking as failed.")
                failed_marker_path.write_text(str(error), encoding="utf-8")
        finally:
            current_processing.discard(file_path)
