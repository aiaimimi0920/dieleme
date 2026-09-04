from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _verify_control_plane_token(headers) -> tuple[bool, dict[str, Any] | None]:
    expected = str(os.getenv("FAPAI_CONTROL_PLANE_TOKEN") or "").strip()
    if not expected:
        return True, None
    actual = str(headers.get("X-FAPAI-Control-Token") or "").strip()
    if actual == expected:
        return True, None
    return False, {
        "code": "AVM_CONTROL_PLANE_FORBIDDEN",
        "message": "control-plane token 校验失败",
        "details": {},
    }

def _json_payload_type_name(payload: Any) -> str:
    if payload is None:
        return "null"
    if isinstance(payload, dict):
        return "object"
    if isinstance(payload, list):
        return "list"
    if isinstance(payload, bool):
        return "boolean"
    if isinstance(payload, (int, float)):
        return "number"
    if isinstance(payload, str):
        return "string"
    return type(payload).__name__

def _evict_runtime_item(item_id):
    item_id = str(item_id)
    with DATA_LOCK:
        SEEN_IDS.pop(item_id, None)
        if item_id in PENDING_TASKS:
            PENDING_TASKS.remove(item_id)

def _reset_structured_sections_for_resync(item):
    for key in ("source", "archive", "auction", "location", "property", "legal_context", "risk_flags", "audit"):
        item.pop(key, None)

_FLAT_OVERRIDE_ALIAS_MAP = {
    "status": "status",
    "状态": "status",
    "交易时间": "auction_date",
    "auction_date": "auction_date",
    "成交价格": "transaction_price",
    "currentPrice": "transaction_price",
    "transaction_price": "transaction_price",
    "起拍价格": "starting_price",
    "initialPrice": "starting_price",
    "starting_price": "starting_price",
    "保证金": "deposit",
    "deposit": "deposit",
    "竞拍人数": "apply_count",
    "applyCount": "apply_count",
    "apply_count": "apply_count",
    "出价次数": "bid_count",
    "bidCount": "bid_count",
    "bid_count": "bid_count",
    "出价人数": "bidder_count",
    "bidderCount": "bidder_count",
    "bidder_count": "bidder_count",
    "地点": "full_address",
    "完整地址": "full_address",
    "full_address": "full_address",
    "城市": "city",
    "city": "city",
    "区": "district",
    "district": "district",
    "最靠近商圈": "business_area",
    "business_area": "business_area",
    "所属小区": "community_name",
    "community_name": "community_name",
    "纬度": "latitude",
    "latitude": "latitude",
    "经度": "longitude",
    "longitude": "longitude",
    "建筑面积": "area_sqm",
    "建设面积": "area_sqm",
    "area_sqm": "area_sqm",
    "产权建筑面积": "gross_area_sqm",
    "原始建筑面积": "gross_area_sqm",
    "gross_area_sqm": "gross_area_sqm",
    "产权份额比例": "ownership_share_ratio",
    "ownership_share_ratio": "ownership_share_ratio",
}

def _apply_flat_override_patch(item, patch):
    for patch_key, target_key in _FLAT_OVERRIDE_ALIAS_MAP.items():
        if patch_key in patch and patch.get(patch_key) not in (None, ""):
            item[target_key] = patch.get(patch_key)

def _get_working_item(item_id, include_processed=False):
    item_id = str(item_id)
    entry = SEEN_IDS.get(item_id)
    if entry:
        return {
            "data": entry["data"],
            "file_path": entry["file_path"],
            "cached": True,
        }
    if DB_REPOSITORY.enabled:
        try:
            item = DB_REPOSITORY.get_flat_item(item_id)
        except Exception as error:
            print(f"[DB] Working item fetch failed item={item_id}: {error}")
            return None
        if not item:
            return None
        sync_collection_record(item)
        if item.get("is_processed") and not include_processed:
            return None
        return {
            "data": item,
            "file_path": get_data_path(item.get("auction_date") or datetime.datetime.now()),
            "cached": False,
        }
    return None

LAST_REQUEST_TIME = time.time()

WATCHDOG_TIMEOUT = 10 * 60

WATCHDOG_CHECK_INTERVAL = 60

def watchdog_thread():
    """Monitor for service continuity. If no requests for 10 minutes, restart Edge with recovery URLs."""
    global LAST_REQUEST_TIME
    import subprocess

    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL)

        elapsed = time.time() - LAST_REQUEST_TIME
        if elapsed > WATCHDOG_TIMEOUT:
            print(f"[WATCHDOG] No requests for {int(elapsed)}s. Triggering recovery...")

            # Disabled: Do not kill user's browser or open recovery windows
            # This was interrupting user's active browser sessions
            print("[WATCHDOG] Auto-recovery disabled to avoid interrupting user browser.")
            return

def manual_solver_retry_thread():
    """Retry the automated solver at a controlled interval while manual verification is required."""
    while True:
        try:
            result = _trigger_manual_solver_retry_if_due()
            if result.get("queued"):
                solver_request = result.get("solver_request") if isinstance(result.get("solver_request"), dict) else {}
                print(
                    "[SOLVER] Manual-required auto retry queued "
                    f"(attempt {result.get('attempt')}, target={solver_request.get('target_url')})."
                )
        except Exception as error:
            print(f"[SOLVER] Manual-required auto retry monitor failed: {error}")
        time.sleep(_manual_solver_retry_poll_seconds())

def check_and_launch_browser():
    """Check if debug port 9222 is open, if not, launch browser."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 9222))
    sock.close()

    if result != 0:
        print("[STARTUP] Debug port 9222 not open. Auto-launch disabled to avoid interrupting user browser.")

JOBS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jobs")

def _seed_collection_service():
    return SeedCollectionService(
        repository=DB_REPOSITORY,
        jobs_dir=JOBS_DIR,
        data_root=DATA_DIR,
        adapter=collection_adapter_from_env(default="taobao_judicial"),
    )

def _detail_collection_service(data_root=None):
    return DetailCollectionService(
        data_root=data_root or DATA_DIR,
        repository=DB_REPOSITORY,
        adapter=collection_adapter_from_env(default="taobao_judicial"),
    )

def submit_task(file_path):
    """
    Thread-safe task submission helper.
    Ensures we don't submit the same file twice.
    """
    with DATA_LOCK:
        if file_path in CURRENT_PROCESSING:
            return
        CURRENT_PROCESSING.add(file_path)

    try:
        # Submit to global executor
        future = executor.submit(process_single_file, file_path)
        # Ensure cleanup
        future.add_done_callback(lambda f: CURRENT_PROCESSING.discard(file_path))
    except Exception as e:
        print(f"Failed to submit task {file_path}: {e}")
        CURRENT_PROCESSING.discard(file_path)

def parse_price(raw_value):
    """Parse price-like fields to float (RMB Yuan)."""
    if raw_value is None:
        return None

    if isinstance(raw_value, (int, float)):
        return float(raw_value)

    if not isinstance(raw_value, str):
        return None

    text = raw_value.strip().replace(",", "")
    if not text:
        return None

    multiplier = 1.0
    if "亿" in text:
        multiplier = 100000000.0
    elif "万元" in text or "万" in text:
        multiplier = 10000.0

    numeric_text = re.sub(r"[^0-9.]", "", text)
    if not numeric_text:
        return None

    try:
        return float(numeric_text) * multiplier
    except ValueError:
        return None

def get_starting_price(item):
    return (
        parse_price(item.get("starting_price"))
        or parse_price(item.get("起拍价格"))
    )

def get_predicted_price(item):
    return (
        parse_price(item.get("predicted_price"))
        or parse_price(item.get("估值"))
        or parse_price(item.get("市场评估价"))
        or parse_price(item.get("evaluation_price"))
        or parse_price(item.get("transaction_price"))
        or parse_price(item.get("成交价格"))
    )

def compute_margin(predicted_price, starting_price):
    """margin = (predicted_price - starting_price) / predicted_price"""
    if not predicted_price or predicted_price <= 0 or starting_price is None:
        return None
    return (predicted_price - starting_price) / predicted_price

def _safe_int(value):
    parsed = parse_price(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except (TypeError, ValueError):
        return None

def _get_risk_payload(item):
    payload = item.get("avm_risk_features")
    return payload if isinstance(payload, dict) else {}

def _risk_value(item, key):
    if item.get(key) is not None:
        return item.get(key)
    return _get_risk_payload(item).get(key)

def sync_avm_risk_aliases(item):
    risk_payload = _get_risk_payload(item)
    if not risk_payload:
        return item

    for key in RISK_ALIAS_KEYS:
        value = risk_payload.get(key)
        if value in (None, ""):
            continue
        item.setdefault(key, value)

    if risk_payload.get("community_name") and not item.get("所属小区"):
        item["所属小区"] = risk_payload["community_name"]
    if risk_payload.get("housing_type") and not item.get("housing_type"):
        item["housing_type"] = risk_payload["housing_type"]
    return item

def build_sniff_stub(item):
    return _seed_collection_service().build_seed_stub(item, parse_price=parse_price, safe_int=_safe_int)

def handle_seed_batch_submission(data):
    return _seed_collection_service().submit_batch(
        data,
        parse_price=parse_price,
        safe_int=_safe_int,
        prefer_db_task_reads=_prefer_db_task_reads,
        get_seen_entry=lambda item_id: SEEN_IDS.get(item_id),
        get_flat_item=lambda item_id: DB_REPOSITORY.get_flat_item(item_id) if DB_REPOSITORY.enabled else None,
        get_data_path=get_data_path,
        update_file_global=update_file_global,
        persist_item_to_db=persist_item_to_db,
        evict_runtime_item=_evict_runtime_item,
        seen_ids=SEEN_IDS,
        pending_tasks=PENDING_TASKS,
        archive_list_payload=archive_list_payload,
    )

def extract_risk_signals(item):
    major_risks = []

    for key, label in MALIGNANT_RISK_LABELS.items():
        if _risk_value(item, key) is True:
            major_risks.append(label)

    if _risk_value(item, "clear_delivery") is False:
        major_risks.append("法院不负责清场交付")

    if _risk_value(item, "land_right_type") == "划拨":
        major_risks.append("土地性质为划拨")

    return major_risks

def build_avm_result(item_id, item):
    predicted_price = get_predicted_price(item)
    starting_price = get_starting_price(item)
    margin = compute_margin(predicted_price, starting_price)
    major_risks = extract_risk_signals(item)

    return {
        "id": str(item_id),
        "predicted_price": predicted_price,
        "starting_price": starting_price,
        "margin": margin,
        "is_malignant_risk": len(major_risks) > 0,
        "major_risks": major_risks,
        "risk_summary": "；".join(major_risks) if major_risks else "未发现恶性风控标签",
    }

def _prediction_confidence_bucket(confidence):
    if confidence is None:
        return "unknown"
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return "unknown"
    if value >= 0.75:
        return "high"
    if value >= 0.45:
        return "medium"
    return "low"

def summarize_screen_results(results):
    strategy_counts = {}
    coordinate_strategy_counts = {}
    confidence_bucket_counts = {}
    blocked_reason_counts = {}
    malignant_count = 0
    alert_candidate_count = 0
    manual_review_count = 0
    manual_review_blocked_count = 0
    risk_validation_blocked_count = 0
    margin_values = []

    for result in results:
        prediction = result.get("prediction") or {}
        strategy = str(prediction.get("strategy") or "unknown")
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        trace = prediction.get("trace") or {}
        coordinate_strategy = str(trace.get("subject_coordinate_strategy") or "unknown")
        coordinate_strategy_counts[coordinate_strategy] = coordinate_strategy_counts.get(coordinate_strategy, 0) + 1

        bucket = _prediction_confidence_bucket(prediction.get("confidence"))
        confidence_bucket_counts[bucket] = confidence_bucket_counts.get(bucket, 0) + 1
        if prediction.get("manual_review_recommended"):
            manual_review_count += 1
        blockers = result.get("alert_blockers") or []
        for blocker in blockers:
            blocked_reason_counts[blocker] = blocked_reason_counts.get(blocker, 0) + 1
        if "manual_review_required" in blockers:
            manual_review_blocked_count += 1
        if "risk_validation_incomplete" in blockers or "risk_validation_invalid" in blockers:
            risk_validation_blocked_count += 1

        if result.get("is_malignant_risk"):
            malignant_count += 1
        if result.get("meets_alert_threshold"):
            alert_candidate_count += 1

        margin = result.get("margin")
        if isinstance(margin, (int, float)):
            margin_values.append(float(margin))

    average_margin = round(sum(margin_values) / len(margin_values), 4) if margin_values else None
    top_result_id = results[0]["id"] if results else None

    return {
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "coordinate_strategy_counts": dict(sorted(coordinate_strategy_counts.items())),
        "confidence_bucket_counts": dict(sorted(confidence_bucket_counts.items())),
        "malignant_risk_count": malignant_count,
        "alert_candidate_count": alert_candidate_count,
        "manual_review_count": manual_review_count,
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "manual_review_blocked_count": manual_review_blocked_count,
        "risk_validation_blocked_count": risk_validation_blocked_count,
        "average_margin": average_margin,
        "top_result_id": top_result_id,
    }

def write_avm_alerts(alerts):
    if not alerts:
        return

    os.makedirs(AVM_DIR, exist_ok=True)

    with FILE_LOCK:
        existing = []
        if os.path.exists(AVM_ALERTS_PATH):
            try:
                with open(AVM_ALERTS_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        existing = loaded
            except Exception:
                existing = []

        existing_by_id = {str(alert.get("id")): alert for alert in existing}
        for alert in alerts:
            existing_by_id[str(alert["id"])] = alert

        with open(AVM_ALERTS_PATH, "w", encoding="utf-8") as f:
            json.dump(list(existing_by_id.values()), f, ensure_ascii=False, indent=2)

__all__ = ["_verify_control_plane_token", "_json_payload_type_name", "_evict_runtime_item", "_reset_structured_sections_for_resync", "_FLAT_OVERRIDE_ALIAS_MAP", "_apply_flat_override_patch", "_get_working_item", "LAST_REQUEST_TIME", "WATCHDOG_TIMEOUT", "WATCHDOG_CHECK_INTERVAL", "watchdog_thread", "manual_solver_retry_thread", "check_and_launch_browser", "JOBS_DIR", "_seed_collection_service", "_detail_collection_service", "submit_task", "parse_price", "get_starting_price", "get_predicted_price", "compute_margin", "_safe_int", "_get_risk_payload", "_risk_value", "sync_avm_risk_aliases", "build_sniff_stub", "handle_seed_batch_submission", "extract_risk_signals", "build_avm_result", "_prediction_confidence_bucket", "summarize_screen_results", "write_avm_alerts"]
