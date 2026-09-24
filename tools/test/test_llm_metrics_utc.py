import json
from datetime import datetime, timezone

from src import llm_metrics


def test_prediction_metrics_use_aware_utc_timestamp_and_daily_path(
    tmp_path, monkeypatch
):
    fixed = datetime(2026, 9, 22, 12, 34, 56, tzinfo=timezone.utc)
    monkeypatch.setattr(llm_metrics, "PREDICTION_LOG_DIR", str(tmp_path))
    monkeypatch.setattr(llm_metrics, "_utc_now", lambda: fixed)

    llm_metrics.log_prediction_event("fixture", 12.5, item_id="item-1")

    path = tmp_path / "2026-09-22.log"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["timestamp"] == fixed.isoformat()
    assert llm_metrics._daily_prediction_log_path() == str(path)
