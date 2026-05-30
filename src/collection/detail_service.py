from __future__ import annotations

import datetime
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict

from src.avm.collection_template import sync_collection_record
from src.detail_artifacts import extract_detail_artifacts, get_detail_archive_path


class DetailCollectionService:
    """Thin orchestration wrapper for detail-stage automation entrypoints."""

    def __init__(self, data_root: str | Path, repository: Any = None):
        self.data_root = Path(data_root)
        self.repository = repository

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
        print(f"Saved HTML to {html_path}. Queued for Background AI.")

        if status:
            working_data = working_item["data"]
            working_data["status"] = status
            apply_flat_override_patch(working_data, {"status": status})
            reset_structured_sections_for_resync(working_data)
            sync_collection_record(working_data)
            if working_item["cached"] and item_id in pending_tasks:
                pending_tasks.remove(item_id)
            update_file_global(working_item["file_path"], item_id, working_data)
            event_type = "analyze_html_status"
            persist_item_to_db(
                working_data,
                event_type,
                {"item_id": item_id, "status": status, "source_file": working_item["file_path"]},
            )
            if status == "failed_timeout" and prefer_db_task_reads():
                evict_runtime_item(item_id)
            if status == "failed_timeout":
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
        sync_collection_record(current_data)

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
        prompt = f"""
# Task
根据提供的房产地址和标题，推断该房产的详细位置信息。
请基于贝壳/链家等房产数据库的标准名称。

# Input
地址: {address}
标题: {title}

# Output JSON
{{
    "所属小区": "小区名称",
    "最靠近商圈": "商圈名称",
    "省份": "省",
    "城市": "市",
    "区": "区"
}}
如果某个字段无法推断，请填 null. 仅返回 JSON对象，不要包含 ```json 标记。
"""
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
        extract_auction_data: Callable[[str, str | None], str],
        extract_avm_risk_features: Callable[[str, str | None], Dict[str, Any]],
        log_prediction_event: Callable[..., None],
        current_processing: set[str],
        seen_ids: Dict[str, Any],
        pending_tasks: list[str],
    ) -> None:
        filename = os.path.basename(file_path)
        match = re.search(r"item-(\d+)", filename)
        if not match:
            print(f"Skipping {filename}: No ID found")
            try:
                os.remove(file_path)
            except Exception:
                pass
            return

        item_id = match.group(1)
        failed_marker_path = self.failed_dir / f"item-{item_id}.html.failed"

        try:
            failed_once = failed_marker_path.exists()
            if not os.path.exists(file_path):
                print(f"File {filename} disappeared (race condition), skipping.")
                current_processing.discard(file_path)
                return

            content = Path(file_path).read_text(encoding="utf-8")
            if not content.strip():
                print(f"Empty content for {item_id}, deleting.")
                try:
                    os.remove(file_path)
                except Exception:
                    pass
                if failed_once:
                    failed_marker_path.unlink(missing_ok=True)
                return

            print(f"Processing {item_id}...")
            predict_started_at = time.time()
            json_str = extract_auction_data(content, item_id=item_id)
            if json_str:
                print(f"\033[92m[AI SUCCESS] {item_id}: {json_str[:200]}...\033[0m")
            if not json_str:
                raise ValueError("Empty response from AI")

            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            new_data = json.loads(json_str)
            if not isinstance(new_data, dict):
                raise ValueError("AI did not return a dictionary")
            found_id = new_data.get("id") or new_data.get("ID") or new_data.get("唯一id")
            if not found_id:
                raise ValueError("AI response missing 'id'/'ID'/'唯一id' field")
            if "id" not in new_data:
                new_data["id"] = found_id

            avm_risk_features = extract_avm_risk_features(content, item_id=item_id)
            if avm_risk_features:
                new_data["avm_risk_features"] = avm_risk_features
                sync_avm_risk_aliases(new_data)
                print(f"[AVM-RISK] Attached risk features for item={item_id}")
            else:
                print(f"[AVM-RISK] Extraction failed for item={item_id}; skipped attachment")

            original_record = get_working_item(item_id, include_processed=True)
            if original_record:
                target_json_path = original_record["file_path"]
                existing_data = original_record.get("data", {})
                for key in (
                    "title", "source_title", "url", "source_url", "source_item_id", "auction_date", "交易时间",
                    "currentPrice", "initialPrice", "transaction_price", "starting_price", "成交价格", "起拍价格",
                    "applyCount", "竞拍人数", "apply_count", "bidCount", "bid_count", "出价次数",
                    "bidderCount", "bidder_count", "出价人数", "deposit", "保证金",
                    "地点", "full_address", "完整地址", "城市", "区",
                    "latitude", "longitude", "纬度", "经度", "coordinate_source", "auction_round", "housing_type",
                ):
                    value = existing_data.get(key)
                    if value not in (None, ""):
                        new_data.setdefault(key, value)
            else:
                date_str = new_data.get("auction_date", "")
                if date_str:
                    try:
                        target_json_path = get_data_path(date_str)
                    except Exception:
                        target_json_path = get_data_path(datetime.datetime.now())
                else:
                    target_json_path = get_data_path(datetime.datetime.now())

            if new_data.get("交易时间") and not new_data.get("auction_date"):
                new_data["auction_date"] = new_data.get("交易时间")
            if new_data.get("原始网站") and not new_data.get("source_url"):
                new_data["source_url"] = new_data.get("原始网站")
            new_data.setdefault("source_item_id", str(item_id))
            new_data.setdefault("source_platform", "taobao_sf")

            try:
                detail_archive_path = get_detail_archive_path(
                    self.data_root,
                    new_data.get("auction_date") or datetime.datetime.now(),
                    item_id,
                    extension=os.path.splitext(file_path)[1] or ".html",
                )
                detail_archive_path.write_text(content, encoding="utf-8")
                new_data["detail_archive_path"] = os.path.relpath(detail_archive_path, self.data_root).replace("\\", "/")
            except Exception as archive_error:
                print(f"[DETAIL-ARCHIVE] Failed for {item_id}: {archive_error}")

            try:
                artifact_fields = extract_detail_artifacts(
                    self.data_root,
                    content,
                    item_id=item_id,
                    auction_date=new_data.get("auction_date") or datetime.datetime.now(),
                    source_url=new_data.get("source_url") or new_data.get("原始网站"),
                )
                for key, value in artifact_fields.items():
                    if value not in (None, "", []):
                        new_data.setdefault(key, value)
            except Exception as artifact_error:
                print(f"[DETAIL-ARTIFACT] Failed for {item_id}: {artifact_error}")

            status = str(new_data.get("status", "")).lower()
            is_sold = new_data.get("是否成交")
            is_done = (status in ["done", "成交", "ended", "finished", "结束"]) or (is_sold is True) or (
                str(new_data.get("outcome", "")).lower() in ["成交", "success", "successful"]
            )

            if not is_done:
                print(f"\033[93mAI identified item {item_id} as NOT DONE. REMOVING from database.\033[0m")
                remove_item_from_json(target_json_path, str(item_id))
                mark_item_deleted_in_db(item_id, "detail_not_done", {"item_id": item_id, "target_json_path": target_json_path})
                evict_runtime_item(item_id)
            else:
                area_value = new_data.get("建筑面积") or new_data.get("建设面积")
                area_is_empty = area_value is None or area_value == 0 or area_value == "0" or area_value == ""
                retry_marker_path = self.retry_dir / f"item-{item_id}.html.retry"
                is_retry_attempt = retry_marker_path.exists()

                if area_is_empty and not is_retry_attempt:
                    print(f"\033[93m[AREA RETRY] {item_id}: 建筑面积为空, 将重新入队重试一次...\033[0m")
                    retry_marker_path.write_text(f"Retry scheduled at {datetime.datetime.now().isoformat()}", encoding="utf-8")
                    if not prefer_db_task_reads() and str(item_id) not in pending_tasks:
                        pending_tasks.append(str(item_id))
                    try:
                        os.remove(file_path)
                        html_path = self.data_root / "html" / f"item-{item_id}.html"
                        if html_path.exists():
                            html_path.unlink()
                    except Exception:
                        pass
                    return

                if area_is_empty and is_retry_attempt:
                    print(f"\033[93m[AREA RETRY] {item_id}: 第二次仍为空, 按原逻辑继续处理...\033[0m")
                    retry_marker_path.unlink(missing_ok=True)

                new_data["detail_captured"] = True
                new_data["is_processed"] = True
                new_data["id"] = int(item_id) if item_id.isdigit() else item_id

                existing_data = (original_record or {}).get("data", {}) if isinstance(original_record, dict) else {}
                if "avm_risk_features" not in new_data:
                    new_data["avm_risk_features"] = existing_data.get("avm_risk_features", {})
                if "avm_extraction_version" not in new_data:
                    new_data["avm_extraction_version"] = existing_data.get("avm_extraction_version")

                sync_collection_record(new_data)
                update_item_in_json(target_json_path, str(item_id), new_data)
                persist_item_to_db(new_data, "detail_enriched", {"item_id": item_id, "file_path": file_path, "source_file": file_path})

                if prefer_db_task_reads():
                    evict_runtime_item(item_id)
                else:
                    seen_ids[str(item_id)] = {"file_path": target_json_path, "data": new_data}
                    if str(item_id) in pending_tasks:
                        pending_tasks.remove(str(item_id))

                q_color = "\033[92m"
                if not new_data.get("id"):
                    q_color = "\033[91m"
                elif (not new_data.get("建筑面积") or not new_data.get("所属小区") or not new_data.get("单价")):
                    q_color = "\033[93m"
                print(
                    f"{q_color}Success {item_id}: Saved to {target_json_path} "
                    f"(Area: {new_data.get('建筑面积')}, Comm: {new_data.get('所属小区')}, Price: {new_data.get('单价')})\033[0m"
                )

                recall_count = new_data.get("recall_count")
                if recall_count is None:
                    recall_count = new_data.get("召回数")
                final_confidence = new_data.get("final_confidence")
                if final_confidence is None:
                    final_confidence = (
                        new_data.get("置信度") or new_data.get("最终置信度") or new_data.get("extraction_confidence")
                    )
                log_prediction_event(
                    task_type="analyze_html",
                    item_id=item_id,
                    duration_ms=(time.time() - predict_started_at) * 1000,
                    recall_count=recall_count,
                    final_confidence=final_confidence,
                    success=True,
                    failure_reason=None,
                )

            try:
                os.remove(file_path)
            except Exception:
                pass
            if failed_once:
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
        except Exception as e:
            print(f"\033[91mError processing {item_id}: {e}\033[0m")
            duration_ms = (time.time() - predict_started_at) * 1000 if "predict_started_at" in locals() else None
            log_prediction_event(
                task_type="analyze_html",
                item_id=item_id,
                duration_ms=duration_ms,
                recall_count=0,
                final_confidence=None,
                success=False,
                failure_reason=str(e),
            )
            failed_once = failed_marker_path.exists()
            if failed_once:
                print(f"Second failure for {item_id}. Deleting file to avoid deadlock.")
                try:
                    os.remove(file_path)
                except Exception:
                    pass
                failed_marker_path.unlink(missing_ok=True)
            else:
                print(f"First failure for {item_id}. Marking as failed.")
                failed_marker_path.write_text(str(e), encoding="utf-8")
        finally:
            current_processing.discard(file_path)

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
