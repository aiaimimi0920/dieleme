from __future__ import annotations

from datetime import datetime
import json
import os
import threading


PREDICTION_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "datas", "avm", "logs")


PREDICTION_LOG_LOCK = threading.Lock()


API_METRICS_LOCK = threading.Lock()


API_METRICS = {
    "total": 0,
    "success": 0,
    "total_response_time_ms": 0.0,
}


def _daily_prediction_log_path(now=None):
    """Build daily log path: datas/avm/logs/YYYY-MM-DD.log."""
    dt = now or datetime.now()
    filename = f"{dt.strftime('%Y-%m-%d')}.log"
    return os.path.join(PREDICTION_LOG_DIR, filename)


def log_prediction_event(task_type, duration_ms, recall_count=None, final_confidence=None, success=True, failure_reason=None, item_id=None):
    """Append one JSON-line prediction record into daily AVM log."""
    record = {
        "timestamp": datetime.now().isoformat(),
        "task_type": task_type,
        "item_id": str(item_id) if item_id is not None else None,
        "duration_ms": round(float(duration_ms), 2) if duration_ms is not None else None,
        "recall_count": recall_count,
        "final_confidence": final_confidence,
        "success": bool(success),
        "failure_reason": failure_reason,
    }

    try:
        os.makedirs(PREDICTION_LOG_DIR, exist_ok=True)
        log_path = _daily_prediction_log_path()
        with PREDICTION_LOG_LOCK:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[LOG] Failed to write prediction log: {e}")


def record_api_metrics(success, response_time_ms):
    """Accumulate API success stats and response-time stats."""
    with API_METRICS_LOCK:
        API_METRICS["total"] += 1
        if success:
            API_METRICS["success"] += 1
        API_METRICS["total_response_time_ms"] += max(float(response_time_ms or 0.0), 0.0)


def get_api_metrics():
    """Expose API success rate and average response time."""
    with API_METRICS_LOCK:
        total = API_METRICS["total"]
        success = API_METRICS["success"]
        total_ms = API_METRICS["total_response_time_ms"]

    success_rate = (success / total * 100.0) if total else 0.0
    avg_ms = (total_ms / total) if total else 0.0
    return {
        "total_calls": total,
        "success_calls": success,
        "success_rate": round(success_rate, 2),
        "avg_response_time_ms": round(avg_ms, 2),
    }


__all__ = ['PREDICTION_LOG_DIR', 'PREDICTION_LOG_LOCK', 'API_METRICS_LOCK', 'API_METRICS', '_daily_prediction_log_path', 'log_prediction_event', 'record_api_metrics', 'get_api_metrics']
