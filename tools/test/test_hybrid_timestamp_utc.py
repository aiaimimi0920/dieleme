import json
from datetime import datetime, timezone

from src import server


def test_hybrid_timestamp_parser_normalizes_legacy_and_iso_values():
    expected = datetime(2026, 5, 19, 0, 40, tzinfo=timezone.utc)
    assert server._parse_utc_timestamp("2026-05-19 00:40:00") == expected
    assert server._parse_utc_timestamp("2026-05-19T00:40:00Z") == expected
    assert server._parse_utc_timestamp("2026-05-19T02:40:00+02:00") == expected
    assert server._parse_utc_timestamp("not-a-timestamp") is None


def test_unresolved_hybrid_window_uses_aware_utc_duration(monkeypatch):
    monkeypatch.setattr(
        server,
        "_utc_now",
        lambda: datetime(2026, 5, 19, 0, 2, tzinfo=timezone.utc),
    )
    summary = server._hybrid_collection_unresolved_escalation_window_summary(
        {
            "available": True,
            "last_event_at": "2026-05-19T00:00:00Z",
            "top_policy_status": "escalate_repeated_repin",
        },
        {"available": False},
    )
    assert summary["window_open"] is True
    assert summary["current_window_duration_seconds"] == 120
    assert summary["current_window_duration_minutes"] == 2.0


def test_recovery_latency_accepts_mixed_aware_iso_timestamps(tmp_path):
    avm_root = tmp_path / "avm"
    avm_root.mkdir()
    (avm_root / "hybrid_seed_operator_escalation_events.jsonl").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19T00:30:00+00:00",
                "policy_status": "escalate_repeated_repin",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (avm_root / "hybrid_seed_operator_escalation_recovery_events.jsonl").write_text(
        json.dumps(
            {
                "generated_at": "2026-05-19T00:31:30Z",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = server._hybrid_collection_recovery_latency_summary(tmp_path)

    assert summary["available"] is True
    assert summary["matched_escalation_at"] == "2026-05-19T00:30:00+00:00"
    assert summary["last_recovery_latency_seconds"] == 90
    assert summary["last_recovery_latency_minutes"] == 1.5
