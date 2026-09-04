from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def get_data_path(date_str_or_obj):
    """
    Helper to get the correct archive path: datas/archive/YYYY/YYYY-MM-DD.json
    """
    if isinstance(date_str_or_obj, str):
        try:
            dt = datetime.datetime.strptime(date_str_or_obj[:10], "%Y-%m-%d")
        except:
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
        except:
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
    global SEEN_IDS, PENDING_TASKS
    active_data_root = os.fspath(data_root or DATA_DIR)
    SEEN_IDS = {}
    PENDING_TASKS = []

    if not os.path.exists(active_data_root):
        os.makedirs(active_data_root)

    print("Loading data...")

    prefer_db_runtime_index = DB_REPOSITORY.enabled and _runtime_env_flag("FAPAI_DB_PREFER_RUNTIME_INDEX", True)
    if prefer_db_runtime_index:
        try:
            counts = _db_counts_snapshot()
            total_count = counts["db_total_ids"]
            if total_count:
                pending_count = counts["db_pending_ids"]
                print("[DB] Runtime index is in lazy DB-first mode; pending items will be cached on demand.")
                print(f"Loaded {len(SEEN_IDS)} runtime-cached items. Total DB items: {total_count}. Pending detail tasks in DB: {pending_count}.")
                return
            print("[DB] DB-first runtime index requested, but repository is empty; falling back to JSON scan.")
        except Exception as db_load_error:
            print(f"[DB] DB-first runtime index failed, falling back to JSON scan: {db_load_error}")

    # 1. Scan root JSONs (priority config, current files)
    try:
        root_files = glob.glob(os.path.join(active_data_root, '*.json'))
    except:
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(active_data_root, 'archive', '**', '*.json')
        archive_files = glob.glob(archive_pattern, recursive=True)
    except:
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

    print(f"Loading data from {len(files)} files...")

    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)

            items = []
            if isinstance(content, list):
                items = content
            elif isinstance(content, dict):
                items = [content]

            for item in items:
                item_id = str(item.get("id"))
                if not item_id:
                    continue
                sync_collection_record(item)

                with DATA_LOCK:
                    SEEN_IDS[item_id] = {
                        "file_path": file_path,
                        "data": item
                    }

                    is_done = item.get("status") in ["done", "成交", "failure", "failed_timeout"] or item.get("是否成交") is True
                    is_processed = item.get("is_processed", False)

                    # QUEUE LOGIC: If it's a valid item (done/failed) AND not processed, queue it.
                    if is_done and not is_processed:
                        PENDING_TASKS.append(item_id)
        except Exception as e:
            # print(f"Error loading {file_path}: {e}")
            pass

    if DB_REPOSITORY.enabled:
        try:
            db_items = DB_REPOSITORY.iter_flat_items()
            for item in db_items:
                item_id = str(item.get("id") or item.get("item_id"))
                if not item_id:
                    continue
                sync_collection_record(item)
                existing = SEEN_IDS.get(item_id, {})
                existing_data = dict(existing.get("data", {}))
                existing_data.update(item)
                sync_collection_record(existing_data)
                file_path = existing.get("file_path")
                if not file_path:
                    file_path = get_data_path(existing_data.get("auction_date") or datetime.datetime.now())
                with DATA_LOCK:
                    SEEN_IDS[item_id] = {"file_path": file_path, "data": existing_data}
                    is_done = existing_data.get("status") in ["done", "成交", "failure", "failed_timeout"] or existing_data.get("是否成交") is True
                    is_processed = existing_data.get("is_processed", False)
                    if is_done and not is_processed and item_id not in PENDING_TASKS:
                        PENDING_TASKS.append(item_id)
            print(f"Hydrated {len(db_items)} items from database into runtime index.")
        except Exception as db_load_error:
            print(f"[DB] Runtime index hydration failed: {db_load_error}")

    print(f"Loaded {len(SEEN_IDS)} items. {len(PENDING_TASKS)} pending detail tasks.")

def cleanup_orphaned_files():
    """Rename *.processing and *.processing.failed files back to original"""
    failed_orphans = glob.glob(os.path.join(DATA_DIR, "*.processing.failed"))
    for p in failed_orphans:
        original_base = p.replace(".processing.failed", "")
        try:
             os.rename(p, original_base)
             with open(original_base + ".failed", "w") as f: f.write("recovered")
        except Exception as e:
             print(f"Failed to reset {p}: {e}")


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
        print(f"Found {len(orphans)} orphaned processing files. Resetting...")
        for p in orphans:
            original = p.replace(".processing", "")
            try:
                os.rename(p, original)
            except Exception as e:
                print(f"Failed to reset {p}: {e}")

def initialize_runtime(start_watchdog=True, ensure_browser=True):
    global RUNTIME_INITIALIZED, AVM_SERVICE_START_TIME
    if RUNTIME_INITIALIZED:
        return

    if _restore_solver_challenge_state():
        print(
            f"[SOLVER] Restored persisted challenge {SOLVER_CHALLENGE_ID}; "
            "collection remains paused until node confirmation."
        )
    if _restore_solver_scope_states():
        print("[SOLVER] Restored independent list/detail challenge latches.")

    cleanup_orphaned_files()
    load_data()
    try:
        DB_REPOSITORY.initialize()
        if DB_REPOSITORY.enabled:
            print("[DB] Repository initialized for dual-write.")
            try:
                _seed_collection_service()._bootstrap_db_search_tasks()
                print("[DB] Search task bootstrap completed.")
            except Exception as bootstrap_error:
                print(f"[DB] Search task bootstrap failed: {bootstrap_error}")
        else:
            print("[DB] Repository disabled (set FAPAI_DB_URL to enable database dual-write).")
    except Exception as db_init_error:
        print(f"[DB] Initialization failed: {db_init_error}")

    if start_watchdog:
        threading.Thread(target=watchdog_thread, daemon=True).start()
        print("[WATCHDOG] Service continuity watchdog started (timeout: 10 minutes).")

    threading.Thread(target=manual_solver_retry_thread, daemon=True).start()
    print(
        "[SOLVER] Manual-required auto retry monitor started "
        f"(interval: {_manual_solver_retry_interval_seconds()}s, poll: {_manual_solver_retry_poll_seconds()}s)."
    )

    try:
        _sample_nas_auth_recovery()
    except Exception as auth_recovery_error:
        print(f"[AUTH-RECOVERY] Initial progress sample failed: {auth_recovery_error!r}")
    if NAS_AUTH_RECOVERY.enabled:
        threading.Thread(target=nas_auth_recovery_watchdog_thread, daemon=True).start()
        print(
            "[AUTH-RECOVERY] NAS stall recovery watchdog started "
            f"(stall: {NAS_AUTH_RECOVERY.stall_seconds:.0f}s, poll: {NAS_AUTH_RECOVERY_POLL_SECONDS:.0f}s)."
        )

    if ensure_browser:
        threading.Thread(target=check_and_launch_browser, daemon=True).start()

    AVM_SERVICE_START_TIME = time.time()
    RUNTIME_INITIALIZED = True

def update_file_global(file_path, item_id, new_data):
    try:
        with FILE_LOCK:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    all_data = json.load(f)

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
        print(f"File write error (global): {e}")

def persist_item_to_db(item, event_type, event_payload=None):
    try:
        DB_REPOSITORY.upsert_flat_item(item, event_type=event_type, event_payload=event_payload)
    except Exception as exc:
        print(f"[DB] upsert failed item={item.get('id') or item.get('source', {}).get('item_id')}: {exc}")

def mark_item_deleted_in_db(item_id, reason, payload=None):
    try:
        DB_REPOSITORY.mark_deleted(str(item_id), reason=reason, event_payload=payload)
    except Exception as exc:
        print(f"[DB] mark_deleted failed item={item_id}: {exc}")

def process_single_file(file_path):
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
        current_processing=CURRENT_PROCESSING,
        seen_ids=SEEN_IDS,
        pending_tasks=PENDING_TASKS,
    )

def update_item_in_json(file_path, item_id, new_data):
    """Helper to update a specific item in a JSON file, or append if new."""
    with FILE_LOCK:
        data_list = []
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data_list = json.load(f)
            except:
                data_list = []

        updated = False
        for i, item in enumerate(data_list):
            if str(item.get("id")) == item_id:
                data_list[i] = new_data
                updated = True
                break

        if not updated:
            data_list.append(new_data)

        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_list, f, ensure_ascii=False, indent=4)

def remove_item_from_json(file_path, item_id):
    """Helper to remove a specific item from a JSON file."""
    if not file_path or not os.path.exists(file_path):
        return
    with FILE_LOCK:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data_list = json.load(f)

            new_list = [item for item in data_list if str(item.get("id")) != item_id]

            if len(new_list) < len(data_list):
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(new_list, f, ensure_ascii=False, indent=4)
                print(f"Removed item {item_id} from {file_path}")
        except Exception as e:
            print(f"Error removing item {item_id}: {e}")

def background_file_processor():
    """
    Periodically checks for item-*.txt AND item-*.html files and processes them.
    Uses global `executor` to limit total concurrency.
    """
    print("Background AI Processor Started (using global executor).")

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
                if f_path in CURRENT_PROCESSING:
                    continue

                submit_task(f_path)
                submitted_count += 1

            if submitted_count > 0:
                print(f"Background scanner submitted {submitted_count} new tasks.")

            time.sleep(1) # Check every second

        except Exception as outer_e:
            print(f"Background Loop Error: {outer_e}")
            time.sleep(5)

__all__ = ["get_data_path", "get_detail_archive_path", "get_list_payload_archive_path", "archive_list_payload", "_extract_detail_artifacts", "load_data", "cleanup_orphaned_files", "initialize_runtime", "update_file_global", "persist_item_to_db", "mark_item_deleted_in_db", "process_single_file", "update_item_in_json", "remove_item_from_json", "background_file_processor"]
