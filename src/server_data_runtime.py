from __future__ import annotations

import logging

from .server_context import *  # noqa: F401,F403
from .runtime_json import load_json_file

logger = logging.getLogger(__name__)

def get_data_path(date_str_or_obj):
    """
    Helper to get the correct archive path: datas/archive/YYYY/YYYY-MM-DD.json
    """
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except ValueError:
            dt = datetime.datetime.now()
    elif isinstance(date_str_or_obj, datetime.date) or isinstance(date_str_or_obj, datetime.datetime):
        dt = date_str_or_obj
    else:
        dt = datetime.datetime.now()

    year = dt.strftime("%Y")
    filename = f"{dt.strftime('%Y-%m-%d')}.json"

    archive_dir = os.path.join(DATA_DIR, "archive", year)
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)

    return os.path.join(archive_dir, filename)

def get_detail_archive_path(date_str_or_obj, item_id, extension=".html"):
    return str(_shared_get_detail_archive_path(DATA_DIR, date_str_or_obj, item_id, extension))

def get_list_payload_archive_path(date_str_or_obj=None, suffix=".json"):
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except ValueError:
            dt = datetime.datetime.now()
    elif isinstance(date_str_or_obj, datetime.date) or isinstance(date_str_or_obj, datetime.datetime):
        dt = date_str_or_obj
    else:
        dt = datetime.datetime.now()

    year = dt.strftime("%Y")
    day = dt.strftime("%Y-%m-%d")
    archive_dir = os.path.join(DATA_DIR, "list_payload_archive", year, day)
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
    timestamp = dt.strftime("%Y%m%d-%H%M%S-%f")
    normalized_suffix = suffix if str(suffix).startswith(".") else f".{suffix}"
    return os.path.join(archive_dir, f"list-{timestamp}{normalized_suffix}")

def archive_list_payload(raw_payload, captured_at=None):
    if raw_payload in (None, "", []):
        return None
    payload_path = get_list_payload_archive_path(captured_at, ".json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(raw_payload, f, ensure_ascii=False, indent=2)
    return os.path.relpath(payload_path, DATA_DIR).replace("\\", "/")

def _extract_detail_artifacts(html_content, item_id, auction_date=None, source_url=None):
    return _shared_extract_detail_artifacts(
        data_root=DATA_DIR,
        html_content=html_content,
        item_id=item_id,
        auction_date=auction_date,
        source_url=source_url,
    )

def load_data(data_root: str | Path | None = None):
    """Load all json files from datas/ directory (and archives) into memory index"""
    active_data_root = os.fspath(data_root or DATA_DIR)
    collection = _collection_runtime_index()
    # Preserve the historical facade alias when tests or maintenance callbacks
    # replace it explicitly; normal RuntimeState calls already share identity.
    legacy_pending = globals().get("PENDING_TASKS")
    if isinstance(legacy_pending, list) and legacy_pending is not collection.pending_tasks:
        collection.pending_tasks = legacy_pending
    with collection.lock:
        collection.clear()

    if not os.path.exists(active_data_root):
        os.makedirs(active_data_root)

    logger.info("Loading collection data")

    prefer_db_runtime_index = DB_REPOSITORY.enabled and _runtime_env_flag("FAPAI_DB_PREFER_RUNTIME_INDEX", True)
    if prefer_db_runtime_index:
        try:
            counts = _db_counts_snapshot()
            total_count = counts["db_total_ids"]
            if total_count:
                pending_count = counts["db_pending_ids"]
                logger.info("DB-first runtime index enabled; pending items will be cached on demand")
                cached_count, _pending_count = collection.counts_snapshot()
                logger.info("Loaded runtime cache=%s total_db=%s pending_db=%s", cached_count, total_count, pending_count)
                return
            logger.warning("DB-first runtime index requested but repository is empty; falling back to JSON scan")
        except Exception as db_load_error:
            logger.exception("DB-first runtime index failed; falling back to JSON scan")

    # 1. Scan root JSONs (priority config, current files)
    try:
        root_files = glob.glob(os.path.join(active_data_root, '*.json'))
    except Exception:
        logger.exception("Failed to scan collection root JSON files")
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(active_data_root, 'archive', '**', '*.json')
        archive_files = glob.glob(archive_pattern, recursive=True)
    except Exception:
        logger.exception("Failed to scan archived collection JSON files")
        archive_files = []

    files = root_files + archive_files

    # Skip non-data json files (config files, progress files, etc.)
    skip_files = [
        "all_locations.json", "sniff_queue", "sniff_status", "sniff_history", "sniff_done",
        "manual_priority_locations.json", "sniff_progress.json", "collected_locations.json",
        "model_config.json", "tuning_history.json", "seen_ids.json"
    ]
    # Filter by basename to be safe with paths
    files = [f for f in files if not any(skip in os.path.basename(f) for skip in skip_files)]

    logger.info("Loading collection data files=%s", len(files))

    for file_path in files:
        try:
            content = load_json_file(file_path)
        except (OSError, UnicodeError, ValueError):
            logger.exception("Failed to load collection data file=%s", file_path)
            continue

        if isinstance(content, list):
            items = content
        elif isinstance(content, dict):
            items = [content]
        else:
            items = []

        for item in items:
            if not isinstance(item, dict):
                logger.warning("Skipping non-object collection item file=%s", file_path)
                continue
            try:
                item_id = str(item.get("id"))
                if not item_id:
                    continue
                sync_collection_record(item)

                collection.set_seen(item_id, {"file_path": file_path, "data": item})
                is_done = item.get("status") in ["done", "成交", "failure", "failed_timeout"] or item.get("是否成交") is True
                is_processed = item.get("is_processed", False)

                # Queue valid, unprocessed items through the RuntimeState API.
                if is_done and not is_processed:
                    collection.queue_pending(item_id)
            except (AttributeError, KeyError, TypeError, ValueError):
                logger.exception("Failed to process collection item file=%s", file_path)
    if DB_REPOSITORY.enabled:
        try:
            db_items = DB_REPOSITORY.iter_flat_items()
            for item in db_items:
                item_id = str(item.get("id") or item.get("item_id"))
                if not item_id:
                    continue
                sync_collection_record(item)
                existing = collection.get_seen(item_id) or {}
                existing_data = dict(existing.get("data", {}))
                existing_data.update(item)
                sync_collection_record(existing_data)
                file_path = existing.get("file_path")
                if not file_path:
                    file_path = get_data_path(existing_data.get("auction_date") or datetime.datetime.now())
                collection.set_seen(item_id, {"file_path": file_path, "data": existing_data})
                is_done = existing_data.get("status") in ["done", "成交", "failure", "failed_timeout"] or existing_data.get("是否成交") is True
                is_processed = existing_data.get("is_processed", False)
                if is_done and not is_processed:
                    collection.queue_pending(item_id)
            logger.info("Hydrated %s items from database into runtime index", len(db_items))
        except Exception as db_load_error:
            logger.exception("Runtime index hydration failed")

    loaded_count, pending_count = collection.counts_snapshot()
    logger.info("Loaded items=%s pending_detail_tasks=%s", loaded_count, pending_count)

def cleanup_orphaned_files():
    """Rename *.processing and *.processing.failed files back to original"""
    failed_orphans = glob.glob(os.path.join(DATA_DIR, "*.processing.failed"))
    for p in failed_orphans:
        original_base = p.replace(".processing.failed", "")
        try:
             os.rename(p, original_base)
             with open(original_base + ".failed", "w") as f: f.write("recovered")
        except Exception as e:
             logger.exception("Failed to reset orphan file=%s", p)


    # Optimized: Skip aggressive .failed file cleanup on every startup
    # failed_items = glob.glob(os.path.join(DATA_DIR, "item-*.html.failed")) + glob.glob(os.path.join(DATA_DIR, "item-*.txt.failed"))
    # if failed_items:
    #     print(f"Found {len(failed_items)} failed marker files (item-*.failed). Cleaning up...")
    #     for p in failed_items:
    #         try:
    #             os.remove(p)
    #         except Exception as e:
    #             print(f"Failed to remove {p}: {e}")

    orphans = glob.glob(os.path.join(DATA_DIR, "*.processing"))
    if orphans:
        logger.warning("Found orphaned processing files=%s; resetting", len(orphans))
        for p in orphans:
            original = p.replace(".processing", "")
            try:
                os.rename(p, original)
            except Exception as e:
                logger.exception("Failed to reset orphan file=%s", p)

def initialize_runtime():
    with RUNTIME.initialization_lock:
        if RUNTIME.initialized:
            return

        if _restore_solver_challenge_state():
            logger.info(
                f"[SOLVER] Restored persisted challenge {RUNTIME.recovery.snapshot().challenge_id}; "
                "collection remains paused until node confirmation."
            )
        if _restore_solver_scope_states():
            logger.info("Restored independent list/detail challenge latches")

        cleanup_orphaned_files()
        load_data()
        try:
            DB_REPOSITORY.initialize()
            if DB_REPOSITORY.enabled:
                logger.info("Repository initialized for dual-write")
                try:
                    _seed_collection_service()._bootstrap_db_search_tasks()
                    logger.info("Search task bootstrap completed")
                except Exception as bootstrap_error:
                    logger.exception("Search task bootstrap failed")
            else:
                logger.info("Repository disabled; set FAPAI_DB_URL to enable database dual-write")
        except Exception as db_init_error:
            logger.exception("Database initialization failed")

        threading.Thread(target=manual_solver_retry_thread, daemon=True).start()
        logger.info(
            "[SOLVER] Manual-required auto retry monitor started "
            f"(interval: {_manual_solver_retry_interval_seconds()}s, poll: {_manual_solver_retry_poll_seconds()}s)."
        )

        try:
            _sample_nas_auth_recovery()
        except Exception as auth_recovery_error:
            logger.exception("Initial authentication recovery progress sample failed")
        if NAS_AUTH_RECOVERY.enabled:
            threading.Thread(target=nas_auth_recovery_watchdog_thread, daemon=True).start()
            logger.info(
                "[AUTH-RECOVERY] NAS stall recovery watchdog started "
                f"(stall: {NAS_AUTH_RECOVERY.stall_seconds:.0f}s, poll: {NAS_AUTH_RECOVERY_POLL_SECONDS:.0f}s)."
            )

        with RUNTIME.lock:
            RUNTIME.started_at = time.time()
            RUNTIME.initialized = True

def update_file_global(file_path, item_id, new_data):
    try:
        with RUNTIME.file_lock:
            if os.path.exists(file_path):
                all_data = load_json_file(file_path)

                updated = False
                for i, item in enumerate(all_data):
                    if str(item.get("id")) == item_id:
                        all_data[i] = new_data
                        updated = True
                        break

                if updated:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(all_data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.exception("Global file write failed")

def persist_item_to_db(item, event_type, event_payload=None):
    try:
        DB_REPOSITORY.upsert_flat_item(item, event_type=event_type, event_payload=event_payload)
    except Exception as exc:
        logger.exception("Database upsert failed item=%s", item.get("id") or item.get("source", {}).get("item_id"))

def mark_item_deleted_in_db(item_id, reason, payload=None):
    try:
        DB_REPOSITORY.mark_deleted(str(item_id), reason=reason, event_payload=payload)
    except Exception as exc:
        logger.exception("Database mark_deleted failed item=%s", item_id)

def process_single_file(file_path):
    collection = _collection_runtime_index()
    _detail_collection_service().process_html_file(
        file_path,
        get_working_item=_get_working_item,
        get_data_path=get_data_path,
        update_item_in_json=update_item_in_json,
        remove_item_from_json=remove_item_from_json,
        persist_item_to_db=persist_item_to_db,
        mark_item_deleted_in_db=mark_item_deleted_in_db,
        evict_runtime_item=_evict_runtime_item,
        prefer_db_task_reads=_prefer_db_task_reads,
        sync_avm_risk_aliases=sync_avm_risk_aliases,
        extract_auction_data=llm_helper.extract_auction_data,
        extract_avm_risk_features=llm_helper.extract_avm_risk_features,
        log_prediction_event=llm_helper.log_prediction_event,
        current_processing=RUNTIME.processing,
        queue_pending=collection.queue_pending,
        set_seen=collection.set_seen,
        remove_pending=collection.remove_pending,
    )

def update_item_in_json(file_path, item_id, new_data):
    """Helper to update a specific item in a JSON file, or append if new."""
    from src.archive_json_io import read_records, write_records

    with RUNTIME.file_lock:
        data_list = read_records(file_path)

        updated = False
        for i, item in enumerate(data_list):
            if str(item.get("id")) == item_id:
                data_list[i] = new_data
                updated = True
                break

        if not updated:
            data_list.append(new_data)

        write_records(file_path, data_list)

def remove_item_from_json(file_path, item_id):
    """Helper to remove a specific item from a JSON file."""
    if not file_path or not os.path.exists(file_path):
        return
    with RUNTIME.file_lock:
        try:
            data_list = load_json_file(file_path)

            new_list = [item for item in data_list if str(item.get("id")) != item_id]

            if len(new_list) < len(data_list):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(new_list, f, ensure_ascii=False, indent=4)
                logger.info("Removed item=%s from %s", item_id, file_path)
        except Exception as e:
            logger.exception("Error removing item=%s", item_id)

def background_file_processor():
    """
    Periodically checks for item-*.txt AND item-*.html files and processes them.
    Uses global `executor` to limit total concurrency.
    """
    logger.info("Background AI processor started using global executor")

    while True:
        try:
            txt_files = glob.glob(os.path.join(DATA_DIR, "item-*.txt"))

            # Scan new html directory + root (legacy)
            html_files = glob.glob(os.path.join(DATA_DIR, 'html', 'item-*.html'))
            html_files += glob.glob(os.path.join(DATA_DIR, "item-*.html"))

            files = txt_files + html_files

            # Simple check to avoid scan overhead if nothing is there
            if not files:
                time.sleep(1)
                continue

            # Submit tasks
            submitted_count = 0
            for f_path in files:
                # Fast check before lock
                if f_path in RUNTIME.processing:
                    continue

                submit_task(f_path)
                submitted_count += 1

            if submitted_count > 0:
                logger.info("Background scanner submitted tasks=%s", submitted_count)

            time.sleep(1) # Check every second

        except Exception as outer_e:
            logger.exception("Background scanner loop failed")
            time.sleep(5)

__all__ = ["load_json_file", "get_data_path", "get_detail_archive_path", "get_list_payload_archive_path", "archive_list_payload", "_extract_detail_artifacts", "load_data", "cleanup_orphaned_files", "initialize_runtime", "update_file_global", "persist_item_to_db", "mark_item_deleted_in_db", "process_single_file", "update_item_in_json", "remove_item_from_json", "background_file_processor"]
