from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

import requests

from tools import run_hybrid_seed_collection


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeHttpSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, timeout: int):
        self.calls.append({"url": url, "timeout": timeout})
        return _FakeResponse(self.payload)


def test_this_file_does_not_define_duplicate_test_names():
    path = Path(__file__)
    names = re.findall(r"^def (test_[A-Za-z0-9_]+)\(", path.read_text(encoding="utf-8"), flags=re.M)
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    assert duplicates == []


def test_load_hybrid_collection_status_snapshot_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                }
            }
        }
    )

    snapshot = run_hybrid_seed_collection.load_hybrid_collection_status_snapshot(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert snapshot == {
        "hybrid_collection_strategy_guidance": {
            "guidance_status": "prefer_browser_fallback",
            "recommended_mode": "browser",
        }
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_status_snapshot_treats_unknown_collection_stage_as_missing():
    session = _FakeHttpSession(
        {
            "collection_stage": "unknown",
        }
    )

    snapshot = run_hybrid_seed_collection.load_hybrid_collection_status_snapshot(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert snapshot == {}


def test_load_hybrid_collection_strategy_guidance_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                }
            }
        }
    )

    guidance = run_hybrid_seed_collection.load_hybrid_collection_strategy_guidance(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert guidance == {
        "guidance_status": "prefer_browser_fallback",
        "recommended_mode": "browser",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_strategy_guidance_treats_unknown_summary_as_missing():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": "unknown",
            }
        }
    )

    guidance = run_hybrid_seed_collection.load_hybrid_collection_strategy_guidance(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert guidance == {}


def test_load_hybrid_collection_recovery_policy_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                }
            }
        }
    )

    policy = run_hybrid_seed_collection.load_hybrid_collection_recovery_policy(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert policy == {
        "policy_status": "pin_browser_mode_temporarily",
        "effective_recommended_mode": "browser",
        "mode_pin_active": True,
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_lifecycle_state_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "retrial_window_open",
                    "lifecycle_reason": "hybrid_retrial_budget_active",
                    "recommended_follow_up": "continue_hybrid_with_budget_watch",
                    "suggested_mode": "hybrid",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_lifecycle_state_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "lifecycle_state": "retrial_window_open",
        "lifecycle_reason": "hybrid_retrial_budget_active",
        "recommended_follow_up": "continue_hybrid_with_budget_watch",
        "suggested_mode": "hybrid",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_intervention_policy_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "high",
                    "intervention_reason": "high_priority_unresolved_escalation_backlog",
                    "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
                    "suggested_mode": "browser",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_intervention_policy_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "intervention_status": "intervention_required",
        "intervention_required": True,
        "intervention_priority": "high",
        "intervention_reason": "high_priority_unresolved_escalation_backlog",
        "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
        "suggested_mode": "browser",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_intervention_stability_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_intervention_stability_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "stability_status": "escalating",
        "stability_severity": "high",
        "current_intervention_status": "intervention_required",
        "previous_intervention_status": "ready",
        "recent_change_count": 1,
        "last_change_at": "2026-05-18 18:12:00",
        "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_final_guidance_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "preferred_action_hint": "prefer browser and investigate escalating intervention",
                    "suggested_mode": "browser",
                    "intervention_status": "intervention_required",
                    "stability_status": "escalating",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_final_guidance_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "guidance_label": "Escalating intervention",
        "guidance_priority": "high",
        "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        "preferred_action_hint": "prefer browser and investigate escalating intervention",
        "suggested_mode": "browser",
        "intervention_status": "intervention_required",
        "stability_status": "escalating",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_digest_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "attention_required",
                    "digest_priority": "warning",
                    "final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                    "intervention_status": "monitor",
                    "intervention_stability_status": "transitioning",
                    "final_guidance_stability_status": "guidance_recently_shifted",
                    "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_digest_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "digest_status": "attention_required",
        "digest_priority": "warning",
        "final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        "intervention_status": "monitor",
        "intervention_stability_status": "transitioning",
        "final_guidance_stability_status": "guidance_recently_shifted",
        "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_digest_stability_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "warning",
                    "current_digest_status": "attention_required",
                    "current_digest_priority": "warning",
                    "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                    "previous_digest_status": "ready",
                    "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_digest_stability_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "stability_status": "digest_recently_shifted",
        "stability_severity": "warning",
        "current_digest_status": "attention_required",
        "current_digest_priority": "warning",
        "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        "previous_digest_status": "ready",
        "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
        "recent_change_count": 1,
        "last_change_at": "2026-05-18 18:12:00",
        "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_escalation_event_trend_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_escalation_event_trend_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "current_operator_escalation_source": "intervention_stability",
        "previous_distinct_operator_escalation_source": "recovery_policy",
        "recent_source_change_count": 1,
        "last_source_change_at": "2026-05-18 18:24:00",
        "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_escalation_event_stability_summary_uses_status_endpoint():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "current_escalation_kind": "intervention_stability",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                }
            }
        }
    )

    summary = run_hybrid_seed_collection.load_hybrid_collection_operator_escalation_event_stability_summary(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert summary == {
        "stability_status": "source_recently_shifted",
        "stability_severity": "high",
        "current_operator_escalation_source": "intervention_stability",
        "current_escalation_kind": "intervention_stability",
        "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        "previous_operator_escalation_source": "recovery_policy",
        "recent_source_change_count": 1,
        "last_source_change_at": "2026-05-18 18:24:00",
        "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_status_snapshot_cache_scope_reuses_single_status_response_for_multiple_summary_loads():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "attention_required",
                    "digest_priority": "warning",
                    "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
                },
            }
        }
    )

    with run_hybrid_seed_collection.hybrid_collection_status_snapshot_scope():
        guidance = run_hybrid_seed_collection.load_hybrid_collection_strategy_guidance(
            "http://127.0.0.1:8001/api",
            http_session=session,
        )
        policy = run_hybrid_seed_collection.load_hybrid_collection_recovery_policy(
            "http://127.0.0.1:8001/api",
            http_session=session,
        )
        digest = run_hybrid_seed_collection.load_hybrid_collection_operator_digest_summary(
            "http://127.0.0.1:8001/api",
            http_session=session,
        )

    assert guidance["recommended_mode"] == "browser"
    assert policy["policy_status"] == "pin_browser_mode_temporarily"
    assert digest["digest_status"] == "attention_required"
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_load_hybrid_collection_operator_status_bundle_reuses_single_status_response():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                },
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "escalated",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                },
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                },
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "intervention_required",
                },
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                },
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                },
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                },
            }
        }
    )

    bundle = run_hybrid_seed_collection.load_hybrid_collection_operator_status_bundle(
        "http://127.0.0.1:8001/api",
        http_session=session,
    )

    assert bundle == {
        "guidance": {
            "guidance_status": "prefer_browser_fallback",
            "recommended_mode": "browser",
        },
        "recovery_policy": {
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
        },
        "lifecycle_summary": {
            "lifecycle_state": "escalated",
            "suggested_mode": "browser",
        },
        "intervention_summary": {
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
        "intervention_stability_summary": {
            "stability_status": "escalating",
        },
        "final_guidance_summary": {
            "guidance_label": "Escalating intervention",
        },
        "digest_summary": {
            "digest_status": "intervention_required",
        },
        "digest_stability_summary": {
            "stability_status": "digest_recently_shifted",
        },
        "escalation_event_trend_summary": {
            "current_operator_escalation_source": "intervention_stability",
        },
        "escalation_event_stability_summary": {
            "stability_status": "source_recently_shifted",
        },
    }
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_resolve_effective_mode_only_applies_guidance_to_default_hybrid_mode():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance={"guidance_status": "prefer_browser_fallback", "recommended_mode": "browser"},
        recovery_policy={},
        respect_operator_guidance=True,
    )
    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "browser"
    assert applied["guidance_applied"] is True
    assert applied["guidance_status"] == "prefer_browser_fallback"
    assert applied["effective_mode_source"] == "guidance"

    explicit_browserless = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="browserless",
        guidance={"guidance_status": "prefer_browser_fallback", "recommended_mode": "browser"},
        recovery_policy={},
        respect_operator_guidance=True,
    )
    assert explicit_browserless["requested_mode"] == "browserless"
    assert explicit_browserless["effective_mode"] == "browserless"
    assert explicit_browserless["guidance_applied"] is False


def test_resolve_effective_mode_can_enforce_browser_pin_recovery_policy():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance={"guidance_status": "keep_hybrid", "recommended_mode": "hybrid"},
        recovery_policy={
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "challenge_detected",
        },
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "browser"
    assert applied["guidance_applied"] is True
    assert applied["effective_mode_source"] == "recovery_policy"
    assert applied["recovery_policy_status"] == "pin_browser_mode_temporarily"
    assert applied["recovery_policy_applied"] is True


def test_resolve_effective_mode_treats_unknown_guidance_and_recovery_policy_as_missing():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance="unknown",
        recovery_policy="unknown",
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "hybrid"
    assert applied["effective_mode_source"] == "requested_mode"
    assert applied["guidance_applied"] is False
    assert applied["recovery_policy_applied"] is False
    assert applied["guidance"] == {}
    assert applied["recovery_policy"] == {}


def test_resolve_effective_mode_treats_whitespace_unknown_requested_mode_as_default():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode=" unknown ",
        guidance={},
        recovery_policy={},
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert applied["effective_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert applied["effective_mode_source"] == "requested_mode"
    assert "unknown" not in json.dumps(applied)


def test_resolve_effective_mode_omits_whitespace_unknown_guidance_and_recovery_fields():
    applied = run_hybrid_seed_collection.resolve_effective_mode(
        requested_mode="hybrid",
        guidance={
            "guidance_status": " unknown ",
            "recommended_mode": " unknown ",
            "top_guidance_reason": " unknown ",
        },
        recovery_policy={
            "policy_status": " unknown ",
            "priority": " unknown ",
            "effective_recommended_mode": " unknown ",
            "mode_pin_active": "unknown",
            "top_policy_reason": " unknown ",
        },
        respect_operator_guidance=True,
    )

    assert applied["requested_mode"] == "hybrid"
    assert applied["effective_mode"] == "hybrid"
    assert applied["effective_mode_source"] == "requested_mode"
    assert applied["guidance_applied"] is False
    assert applied["recovery_policy_applied"] is False
    assert applied["guidance_status"] is None
    assert applied["recovery_policy_status"] is None
    assert applied["recovery_policy_priority"] is None
    assert applied["recovery_policy_mode_pin_active"] is None
    assert applied["guidance"] == {
        "guidance_status": None,
        "recommended_mode": None,
        "top_guidance_reason": None,
    }
    assert applied["recovery_policy"] == {
        "policy_status": None,
        "priority": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }
    assert "unknown" not in json.dumps(applied)


def test_main_respects_operator_guidance_when_enabled(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "prefer_browser_fallback",
            "recommended_mode": "browser",
            "top_guidance_reason": "challenge_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=8", "page": 8},
            "browser_fallback_opened": True,
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guided",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["requested_mode"] == "hybrid"
    assert payload["effective_mode"] == "browser"
    assert payload["guidance_applied"] is True
    assert payload["guidance_status"] == "prefer_browser_fallback"
    assert payload["effective_mode_source"] == "guidance"
    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload["guidance_status"] == "prefer_browser_fallback"
    assert switch_payload["top_guidance_reason"] == "challenge_detected"
    assert switch_payload["session_id"] == "runner-guided"


def test_main_treats_unknown_guidance_applied_as_missing_for_payload_runtime_and_mode_switch_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": "unknown",
            "recovery_policy_applied": False,
            "guidance_status": "monitor_hybrid_runtime",
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=9", "page": 9},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guidance-applied-unknown",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["effective_mode"] == "hybrid"
    assert stdout_payload["guidance_applied"] is False
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["guidance_applied"] is False
    assert runtime_summary["guidance_applied_count"] == 0
    assert not switch_events_path.exists()


def test_main_omits_literal_unknown_top_guidance_reason_from_mode_switch_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "unknown",
            "recommended_mode": "browser",
            "top_guidance_reason": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=2", "page": 2},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guided-unknown-top-reason",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("guidance_status") != "unknown"
    assert switch_payload.get("top_guidance_reason") != "unknown"


def test_append_mode_switch_events_omits_literal_unknown_status_fields(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "unknown",
            "recovery_policy_status": "unknown",
            "top_guidance_reason": "unknown",
            "reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=3", "page": 3},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-status-fields",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("guidance_status") != "unknown"
    assert switch_payload.get("recovery_policy_status") != "unknown"
    assert switch_payload.get("top_guidance_reason") != "unknown"


def test_append_mode_switch_events_omits_literal_unknown_effective_mode_source(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "unknown",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=4", "page": 4},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-effective-mode-source",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("effective_mode_source") != "unknown"


def test_append_mode_switch_events_omits_literal_unknown_effective_mode(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=5", "page": 5},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-effective-mode",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload.get("effective_mode") != "unknown"
    assert switch_payload["effective_mode_source"] == "guidance"


def test_append_mode_switch_events_omits_literal_unknown_task_page(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=6", "page": "unknown"},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-task-page",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("task_page") != "unknown"


def test_append_mode_switch_events_omits_negative_task_page(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=6", "page": -6},
        },
        switch_events_path,
        session_id="runner-direct-negative-mode-switch-task-page",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("task_page") is None


def test_append_mode_switch_events_omits_literal_unknown_task_url(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "unknown", "page": 6},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-task-url",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload.get("task_url") != "unknown"


def test_append_mode_switch_events_omits_literal_unknown_requested_mode(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": "unknown",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "guidance_status": "prefer_browser_fallback",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=6", "page": 6},
        },
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-requested-mode",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload.get("requested_mode") != "unknown"
    assert switch_payload["effective_mode"] == "browser"


def test_append_mode_switch_events_omits_whitespace_unknown_fields(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        {
            "guidance_applied": True,
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "guidance_status": " unknown ",
            "recovery_policy_status": " unknown ",
            "top_guidance_reason": " unknown ",
            "reason": " unknown ",
            "task": {"url": " unknown ", "page": "unknown"},
        },
        switch_events_path,
        session_id="runner-direct-whitespace-placeholder-mode-switch-fields",
    )

    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload.get("requested_mode") is None
    assert switch_payload.get("effective_mode") is None
    assert switch_payload.get("effective_mode_source") is None
    assert switch_payload.get("guidance_status") is None
    assert switch_payload.get("recovery_policy_status") is None
    assert switch_payload.get("top_guidance_reason") is None
    assert switch_payload.get("task_url") is None
    assert switch_payload.get("task_page") is None
    assert "unknown" not in json.dumps(switch_payload)


def test_append_mode_switch_events_treats_unknown_result_as_missing(tmp_path: Path):
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    run_hybrid_seed_collection.append_mode_switch_events(
        "unknown",
        switch_events_path,
        session_id="runner-direct-unknown-mode-switch-result",
    )

    assert not switch_events_path.exists()


def test_main_reuses_single_status_snapshot_for_operator_summary_loads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "top_policy_reason": "challenge_detected",
                },
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "escalated",
                    "lifecycle_reason": "unresolved_escalation_window_open",
                    "recommended_follow_up": "prefer_browser_and_investigate_escalation",
                    "suggested_mode": "browser",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                },
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "preferred_action_hint": "prefer browser and investigate escalating intervention",
                    "suggested_mode": "browser",
                    "intervention_status": "intervention_required",
                    "stability_status": "escalating",
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        }
    )
    monkeypatch.setattr(run_hybrid_seed_collection.requests, "Session", lambda: session)
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=8", "page": 8},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guided-snapshot",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]


def test_main_can_pin_browser_mode_from_recovery_policy(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "challenge_detected",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=10", "page": 10},
            "browser_fallback_opened": True,
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-recovery-pin",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["requested_mode"] == "hybrid"
    assert payload["effective_mode"] == "browser"
    assert payload["effective_mode_source"] == "recovery_policy"
    assert payload["recovery_policy_status"] == "pin_browser_mode_temporarily"
    switch_lines = switch_events_path.read_text(encoding="utf-8").splitlines()
    assert len(switch_lines) == 1
    switch_payload = json.loads(switch_lines[0])
    assert switch_payload["requested_mode"] == "hybrid"
    assert switch_payload["effective_mode"] == "browser"
    assert switch_payload["top_guidance_reason"] == "challenge_detected"


def test_main_records_recovery_policy_release_transition_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=11", "page": 11},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-release",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["effective_mode"] == "hybrid"
    assert payload["recovery_policy_status"] == "allow_hybrid_retrial"
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload["from_policy_status"] == "pin_browser_mode_temporarily"
    assert transition_payload["to_policy_status"] == "allow_hybrid_retrial"
    assert transition_payload["from_mode_pin_active"] is True
    assert transition_payload["to_mode_pin_active"] is False
    assert transition_payload["requested_mode"] == "hybrid"
    assert transition_payload["effective_mode"] == "hybrid"


def test_append_recovery_policy_transition_events_omits_literal_unknown_effective_mode(tmp_path: Path):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": 60},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-effective-mode",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("effective_mode") != "unknown"


def test_append_recovery_policy_transition_events_omits_literal_unknown_task_page(tmp_path: Path):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": "unknown"},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-task-page",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("task_page") != "unknown"


def test_append_recovery_policy_transition_events_omits_literal_unknown_task_url(tmp_path: Path):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "unknown", "page": 60},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-task-url",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("task_url") != "unknown"


def test_append_recovery_policy_transition_events_omits_literal_unknown_requested_mode(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": "unknown",
            "effective_mode": "hybrid",
            "recovery_policy_status": "allow_hybrid_retrial",
            "recovery_policy_effective_recommended_mode": "hybrid",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": 60},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-requested-mode",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("requested_mode") != "unknown"


def test_append_recovery_policy_transition_events_omits_whitespace_unknown_fields(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "recovery_policy_status": " unknown ",
            "recovery_policy_effective_recommended_mode": " unknown ",
            "recovery_policy_mode_pin_active": False,
            "top_policy_reason": " unknown ",
            "task": {"url": " unknown ", "page": "unknown"},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-whitespace-placeholder-fields",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("to_policy_status") is None
    assert transition_payload.get("to_effective_recommended_mode") is None
    assert transition_payload.get("to_top_policy_reason") is None
    assert transition_payload.get("requested_mode") is None
    assert transition_payload.get("effective_mode") is None
    assert transition_payload.get("task_url") is None
    assert transition_payload.get("task_page") is None
    assert "unknown" not in json.dumps(transition_payload)

    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": False,
        "top_policy_reason": None,
    }


def test_append_recovery_policy_transition_events_treats_unknown_result_as_missing(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        "unknown",
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-transition-unknown-result",
    )

    assert not recovery_events_path.exists()
    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }


def test_append_recovery_policy_transition_events_records_pin_release_when_only_explicit_false_is_present(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    recovery_state_path.write_text(
        json.dumps(
            {
                "mode_pin_active": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "recovery_policy_mode_pin_active": False,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-policy-pin-release-explicit-false",
    )

    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload["from_mode_pin_active"] is True
    assert transition_payload["to_mode_pin_active"] is False
    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload["mode_pin_active"] is False


def test_append_recovery_policy_transition_events_persists_explicit_false_without_event_when_no_previous_state_exists(
    tmp_path: Path,
):
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"

    run_hybrid_seed_collection.append_recovery_policy_transition_events(
        {
            "recovery_policy_mode_pin_active": False,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=63", "page": 63},
        },
        recovery_state_path,
        recovery_events_path,
        session_id="runner-recovery-policy-explicit-false-no-previous-state",
    )

    assert not recovery_events_path.exists()
    state_payload = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert state_payload["mode_pin_active"] is False


def test_persist_recovery_policy_state_treats_unknown_policy_as_missing(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-recovery-policy-state.json"

    run_hybrid_seed_collection.persist_recovery_policy_state(
        "unknown",
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }


def test_persist_recovery_policy_state_omits_whitespace_unknown_policy_fields(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-recovery-policy-state.json"

    run_hybrid_seed_collection.persist_recovery_policy_state(
        {
            "policy_status": " unknown ",
            "effective_recommended_mode": " unknown ",
            "mode_pin_active": "unknown",
            "top_policy_reason": " unknown ",
        },
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "policy_status": None,
        "effective_recommended_mode": None,
        "mode_pin_active": None,
        "top_policy_reason": None,
    }


def test_main_treats_unknown_recovery_policy_mode_pin_active_as_missing_for_mode_resolution_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "pin_browser_mode_temporarily",
            "effective_recommended_mode": "browser",
            "mode_pin_active": "unknown",
            "top_policy_reason": "challenge_detected",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=12", "page": 12},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-pin-active",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["effective_mode"] == "hybrid"
    assert payload["effective_mode_source"] == "requested_mode"
    assert payload.get("recovery_policy_mode_pin_active") is None
    runtime_summary = payload
    assert runtime_summary.get("recovery_policy_mode_pin_active") is None
    recovery_state = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert recovery_state.get("mode_pin_active") is None
    if recovery_events_path.exists():
        transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
        assert len(transition_lines) == 1
        transition_payload = json.loads(transition_lines[0])
        assert transition_payload["transition_kind"] == "policy_status_changed"
        assert transition_payload["to_mode_pin_active"] is None


def test_main_omits_literal_unknown_recovery_policy_status_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "allow_hybrid_retrial",
                "effective_recommended_mode": "hybrid",
                "mode_pin_active": False,
                "top_policy_reason": "browserless_success_stable",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "unknown",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "challenge_detected",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=15", "page": 15},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-policy-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["browser"]
    recovery_state = json.loads(recovery_state_path.read_text(encoding="utf-8"))
    assert recovery_state.get("policy_status") != "unknown"
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload.get("to_policy_status") != "unknown"
    assert transition_payload["to_mode_pin_active"] is True


def test_main_omits_literal_unknown_previous_recovery_policy_status_from_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "unknown",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=16", "page": 16},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-previous-policy-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("from_policy_status") != "unknown"
    assert transition_payload["to_policy_status"] == "allow_hybrid_retrial"


def test_main_omits_literal_unknown_previous_recovery_policy_effective_mode_from_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "unknown",
                "mode_pin_active": True,
                "top_policy_reason": "challenge_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=17", "page": 17},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-previous-effective-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("from_effective_recommended_mode") != "unknown"
    assert transition_payload["to_effective_recommended_mode"] == "hybrid"


def test_main_omits_literal_unknown_previous_recovery_policy_reason_from_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    recorded_modes: list[str] = []

    recovery_state_path.write_text(
        json.dumps(
            {
                "policy_status": "pin_browser_mode_temporarily",
                "effective_recommended_mode": "browser",
                "mode_pin_active": True,
                "top_policy_reason": "unknown",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "allow_hybrid_retrial",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browser_recovery_window_stabilized",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=18", "page": 18},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--session-id",
            "runner-recovery-unknown-previous-reason",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    assert recorded_modes == ["hybrid"]
    transition_lines = recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(transition_lines) == 1
    transition_payload = json.loads(transition_lines[0])
    assert transition_payload["transition_kind"] == "pin_released"
    assert transition_payload.get("from_top_policy_reason") != "unknown"
    assert transition_payload["to_top_policy_reason"] == "browser_recovery_window_stabilized"


def test_main_omits_literal_unknown_guidance_recommended_mode_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "unknown",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=13", "page": 13},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guidance-unknown-recommended-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("guidance_recommended_mode") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("guidance_recommended_mode") != "unknown"


def test_main_omits_literal_unknown_guidance_status_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "unknown",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=14", "page": 14},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guidance-unknown-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("guidance_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("guidance_status") != "unknown"


def test_main_omits_literal_unknown_guidance_status_from_status_counts(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "unknown",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=15", "page": 15},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-guidance-unknown-status-counts",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("guidance_status_counts") == {}


def test_main_omits_literal_unknown_reason_from_runtime_summary_aggregates(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_fallback_required",
            "reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=16", "page": 16},
            "fallback_url": "https://sf.taobao.com/list/50025969__2.htm?page=16&uni_mode=SNIFF_WORKER",
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-fallback-reason",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("reason_counts") == {}
    assert runtime_summary.get("top_fallback_reason") is None
    assert runtime_summary.get("last_reason") != "unknown"


def test_main_treats_unknown_reason_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_fallback_required",
            "reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=17", "page": 17},
            "fallback_url": "https://sf.taobao.com/list/50025969__2.htm?page=17&uni_mode=SNIFF_WORKER",
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-reason-payload-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("reason") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("last_reason") != "unknown"
    assert runtime_summary.get("reason_counts") == {}


def test_main_records_operator_escalation_event_for_repeated_repin_policy(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Persistent intervention required",
            "guidance_priority": "high",
            "guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "preferred_action_hint": "treat as sustained intervention and investigate backlog",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "persistent_intervention_required",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "persistent_intervention_required",
            "final_guidance_stability_status": "persistent_noninfo_guidance",
            "operator_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "persistent_noninfo_digest",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Operator digest remains non-info with no recent message changes.",
        },
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=16", "page": 16},
            "browser_fallback_opened": True,
        }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", _run_once)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalate-repin",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.strip()
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert recorded_modes == ["browser"]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["effective_mode_source"] == "recovery_policy"
    assert payload["recovery_policy_status"] == "escalate_repeated_repin"
    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "repeated_repin_cycle"
    assert event_payload["policy_status"] == "escalate_repeated_repin"
    assert event_payload["policy_priority"] == "high"
    assert event_payload["top_policy_reason"] == "repeated_repin_cycle_detected"
    assert event_payload["requested_mode"] == "hybrid"
    assert event_payload["effective_mode"] == "browser"
    assert event_payload["operator_escalation_audit_message"] == (
        "Persistent intervention required: treat as sustained intervention and investigate backlog. "
        "[source=recovery_policy, digest=intervention_required, digest_stability=persistent_noninfo_digest]"
    )


def test_main_records_operator_escalation_event_for_intervention_stability(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33", "page": 33},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalate-intervention-stability",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_stability"
    assert event_payload["operator_escalation_source"] == "intervention_stability"
    assert event_payload["requested_mode"] == "hybrid"
    assert event_payload["effective_mode"] == "hybrid"
    assert event_payload["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )


def test_append_operator_escalation_events_omits_literal_unknown_policy_fields(tmp_path: Path):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "recovery_policy_status": "unknown",
            "recovery_policy_priority": "unknown",
            "top_policy_reason": "unknown",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=52", "page": 52},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-policy-fields",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("policy_status") != "unknown"
    assert event_payload.get("policy_priority") != "unknown"
    assert event_payload.get("top_policy_reason") != "unknown"


def test_append_operator_escalation_events_omits_literal_unknown_audit_message(tmp_path: Path):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "operator_escalation_audit_message": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=54", "page": 54},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-audit-message",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("operator_escalation_audit_message") != "unknown"


def test_append_operator_escalation_events_treats_unknown_source_as_missing_for_repeated_repin_policy(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "unknown",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-source-repeated-repin",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "repeated_repin_cycle"
    assert event_payload.get("operator_escalation_source") == "recovery_policy"


def test_append_operator_escalation_events_treats_unknown_result_as_missing(tmp_path: Path):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        "unknown",
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-result",
    )

    assert not operator_escalation_path.exists()


def test_append_operator_escalation_events_omits_literal_unknown_effective_mode_source(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=57", "page": 57},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-effective-mode-source",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("effective_mode_source") != "unknown"


def test_append_operator_escalation_events_omits_literal_unknown_effective_mode(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "guidance",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-effective-mode",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("effective_mode") != "unknown"


def test_append_operator_escalation_events_omits_literal_unknown_task_page(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": "unknown"},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-task-page",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("task_page") != "unknown"


def test_append_operator_escalation_events_omits_literal_unknown_task_url(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "task": {"url": "unknown", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-task-url",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("task_url") != "unknown"


def test_append_operator_escalation_events_omits_literal_unknown_requested_mode(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "requested_mode": "unknown",
            "effective_mode": "browser",
            "effective_mode_source": "guidance",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-unknown-requested-mode",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("requested_mode") != "unknown"


def test_append_operator_escalation_events_omits_whitespace_unknown_optional_fields(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": "intervention_policy",
            "recovery_policy_status": " unknown ",
            "recovery_policy_priority": " unknown ",
            "top_policy_reason": " unknown ",
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "operator_escalation_audit_message": " unknown ",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-whitespace-fields",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "intervention_policy"
    assert event_payload.get("policy_status") is None
    assert event_payload.get("policy_priority") is None
    assert event_payload.get("top_policy_reason") is None
    assert event_payload.get("requested_mode") is None
    assert event_payload.get("effective_mode") is None
    assert event_payload.get("effective_mode_source") is None
    assert event_payload.get("operator_escalation_audit_message") is None
    assert "unknown" not in json.dumps(event_payload)


def test_append_operator_escalation_events_treats_whitespace_unknown_source_as_missing_for_repeated_repin_policy(
    tmp_path: Path,
):
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    run_hybrid_seed_collection.append_operator_escalation_events(
        {
            "operator_escalation_source": " unknown ",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
        },
        operator_escalation_path,
        session_id="runner-escalation-event-whitespace-unknown-source-repeated-repin",
    )

    event_lines = operator_escalation_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["escalation_kind"] == "repeated_repin_cycle"
    assert event_payload.get("operator_escalation_source") == "recovery_policy"


def test_persist_operator_escalation_state_omits_literal_unknown_policy_fields(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-escalation-state.json"

    run_hybrid_seed_collection.persist_operator_escalation_state(
        {
            "policy_status": "escalate_repeated_repin",
            "policy_priority": "unknown",
            "top_policy_reason": "unknown",
            "escalation_kind": "repeated_repin_cycle",
        },
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["policy_status"] == "escalate_repeated_repin"
    assert state_payload.get("policy_priority") != "unknown"
    assert state_payload.get("top_policy_reason") != "unknown"


def test_persist_operator_escalation_state_omits_whitespace_unknown_policy_fields(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-escalation-state.json"

    run_hybrid_seed_collection.persist_operator_escalation_state(
        {
            "policy_status": " unknown ",
            "policy_priority": " unknown ",
            "top_policy_reason": " unknown ",
            "escalation_kind": "repeated_repin_cycle",
        },
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload["escalation_kind"] == "repeated_repin_cycle"
    assert state_payload.get("policy_status") is None
    assert state_payload.get("policy_priority") is None
    assert state_payload.get("top_policy_reason") is None
    assert "unknown" not in json.dumps(state_payload)


def test_persist_operator_escalation_state_treats_unknown_payload_as_missing(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-escalation-state.json"

    run_hybrid_seed_collection.persist_operator_escalation_state(
        "unknown",
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "escalation_kind": None,
        "policy_status": None,
        "policy_priority": None,
        "top_policy_reason": None,
    }


def test_main_records_recovery_from_operator_escalation_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=19", "page": 19},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip().startswith("{")
    assert "Operator recovery" in captured.err
    assert "steady_hybrid" in captured.err
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload["from_policy_status"] == "escalate_repeated_repin"
    assert recovery_payload["to_policy_status"] == "steady_hybrid"
    assert recovery_payload["effective_mode"] == "hybrid"


def test_append_operator_escalation_recovery_events_treats_unknown_result_as_missing(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        "unknown",
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-result",
    )

    assert recovery_events == []
    assert not operator_escalation_recovery_events_path.exists()
    state_payload = json.loads(operator_escalation_state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "escalation_kind": None,
        "policy_status": None,
        "policy_priority": None,
        "top_policy_reason": None,
    }


def test_append_operator_escalation_recovery_events_omits_literal_unknown_task_page(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": "unknown"},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-task-page",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("task_page") != "unknown"


def test_append_operator_escalation_recovery_events_records_clear_for_intervention_policy_state(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "escalation_kind": "intervention_policy",
                "policy_status": "steady_hybrid",
                "policy_priority": "warning",
                "top_policy_reason": "monitor_until_stable",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-intervention-policy",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload["from_escalation_kind"] == "intervention_policy"
    assert recovery_payload["from_policy_status"] == "steady_hybrid"
    assert recovery_payload["to_policy_status"] is None


def test_append_operator_escalation_recovery_events_omits_literal_unknown_task_url(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "hybrid",
            "task": {"url": "unknown", "page": 55},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-task-url",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("task_url") != "unknown"


def test_main_omits_literal_unknown_previous_operator_escalation_policy_status_from_recovery_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "unknown",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=21", "page": 21},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-unknown-prev-policy-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("from_policy_status") != "unknown"
    assert recovery_payload["to_policy_status"] == "steady_hybrid"


def test_append_operator_escalation_recovery_events_omits_literal_unknown_current_policy_status(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": "unknown",
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=53", "page": 53},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-current-policy-status",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("to_policy_status") != "unknown"


def test_append_operator_escalation_recovery_events_omits_literal_unknown_effective_mode(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": None,
            "effective_mode": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": 55},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-unknown-effective-mode",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("effective_mode") != "unknown"


def test_append_operator_escalation_recovery_events_omits_whitespace_unknown_state_and_effective_mode(
    tmp_path: Path,
):
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": " unknown ",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
                "escalation_kind": "repeated_repin_cycle",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    recovery_events = run_hybrid_seed_collection.append_operator_escalation_recovery_events(
        {
            "recovery_policy_status": " unknown ",
            "effective_mode": " unknown ",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": 55},
        },
        operator_escalation_state_path,
        operator_escalation_recovery_events_path,
        session_id="runner-escalation-recovery-whitespace-placeholders",
    )

    assert len(recovery_events) == 1
    recovery_lines = operator_escalation_recovery_events_path.read_text(encoding="utf-8").splitlines()
    assert len(recovery_lines) == 1
    recovery_payload = json.loads(recovery_lines[0])
    assert recovery_payload["transition_kind"] == "escalation_cleared"
    assert recovery_payload.get("from_policy_status") is None
    assert recovery_payload.get("to_policy_status") is None
    assert recovery_payload.get("effective_mode") is None
    assert "unknown" not in json.dumps(recovery_payload)


def test_main_omits_missing_page_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47"},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-no-page",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "page=None" not in recovery_line
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=steady_hybrid" in recovery_line
    assert "mode=hybrid" in recovery_line


def test_main_omits_missing_mode_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=49", "page": 49},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-no-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "mode=unknown" not in recovery_line
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=steady_hybrid" in recovery_line
    assert "page=49" in recovery_line


def test_main_omits_missing_to_status_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": 50},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-no-to-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=unknown" not in recovery_line
    assert "mode=hybrid" in recovery_line
    assert "page=50" in recovery_line


def test_main_omits_unknown_page_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    operator_escalation_state_path.write_text(
        json.dumps(
            {
                "policy_status": "escalate_repeated_repin",
                "policy_priority": "high",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "keep_hybrid",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "steady_hybrid",
            "priority": "info",
            "effective_recommended_mode": "hybrid",
            "mode_pin_active": False,
            "top_policy_reason": "browserless_success_stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": "unknown"},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-unknown-page",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert "page=unknown" not in recovery_line
    assert "from=escalate_repeated_repin" in recovery_line
    assert "to=steady_hybrid" in recovery_line
    assert "mode=hybrid" in recovery_line


def test_emit_operator_recovery_console_summary_omits_empty_parentheses(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert recovery_line == "[OPERATOR] Operator recovery: escalation_cleared"
    assert "()" not in recovery_line


def test_main_omits_empty_parentheses_on_operator_recovery_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda *args, **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "requested_mode",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51"},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "append_operator_escalation_recovery_events",
        lambda *args, **kwargs: [
            {
                "transition_kind": "escalation_cleared",
            }
        ],
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--session-id",
            "runner-escalation-recovered-empty-parts",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    recovery_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator recovery:"))
    assert recovery_line == "[OPERATOR] Operator recovery: escalation_cleared"
    assert "()" not in recovery_line


def test_emit_operator_console_summary_reports_repeated_repin_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "page=17" in captured.err


def test_emit_operator_console_summary_omits_unknown_page_on_non_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": "unknown"},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "page=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_emit_operator_console_summary_treats_unhashable_page_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": []},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Operator escalation:")
    )
    assert "page=" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line


def test_emit_operator_console_summary_treats_unknown_task_payload_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=" not in escalation_line


def test_emit_operator_console_summary_omits_negative_task_page(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": -3},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=" not in escalation_line


def test_emit_operator_console_summary_can_include_audit_message_on_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Escalating intervention: prefer browser and investigate escalating intervention. "
                "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
            ),
            "operator_final_guidance_label": "Escalating intervention",
            "operator_digest_status": "intervention_required",
            "operator_digest_stability_status": "digest_recently_shifted",
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        stability_summary={
            "stability_status": "escalating",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert (
        "[OPERATOR] Operator escalation audit: "
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    ) in captured.err
    assert "Operator escalation" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=intervention_stability" not in escalation_line
    assert "digest_status=intervention_required" not in escalation_line
    assert "digest_stability=digest_recently_shifted" not in escalation_line


def test_emit_operator_console_summary_omits_unknown_page_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Escalating intervention: prefer browser and investigate escalating intervention. "
                "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
            ),
            "operator_final_guidance_label": "Escalating intervention",
            "operator_digest_status": "intervention_required",
            "operator_digest_stability_status": "digest_recently_shifted",
            "task": {"page": "unknown"},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        stability_summary={
            "stability_status": "escalating",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "page=unknown" not in escalation_line
    assert "priority=warning" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line


def test_emit_operator_console_summary_treats_unknown_audit_message_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": "unknown",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 34},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[OPERATOR] Operator escalation audit: unknown" not in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=recovery_policy" in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=34" in escalation_line


def test_emit_operator_console_summary_omits_unknown_reason_value_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Operator escalation "
                "[source=intervention_policy, digest=unknown, digest_stability=unknown]"
            ),
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "suggested_mode": "browser",
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=warning" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unknown" not in escalation_line
    assert "page=33" in escalation_line


def test_emit_operator_console_summary_omits_unknown_priority_value_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Operator escalation "
                "[source=intervention_policy, digest=unknown, digest_stability=unknown]"
            ),
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "page=33" in escalation_line


def test_emit_operator_console_summary_omits_unknown_mode_value_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": (
                "Operator escalation "
                "[source=intervention_policy, digest=unknown, digest_stability=unknown]"
            ),
            "task": {"page": 33},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "mode=unknown" not in escalation_line
    assert "priority=warning" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "page=33" in escalation_line


def test_emit_operator_console_summary_omits_empty_parentheses_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": "Operator escalation [source=intervention_policy]",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33"},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
        stability_summary={},
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line == "[OPERATOR] Operator escalation: intervention_required"
    assert "()" not in escalation_line


def test_operator_escalation_audit_message_omits_unknown_digest_status():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {},
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )

    assert message is not None
    assert "[source=intervention_policy" in message
    assert "digest=unknown" not in message


def test_operator_escalation_source_treats_unknown_summaries_as_missing():
    source = run_hybrid_seed_collection.operator_escalation_source(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
    )

    assert source == "recovery_policy"


def test_operator_escalation_source_strips_known_status_fields():
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {"recovery_policy_status": " escalate_repeated_repin "}
        )
        == "recovery_policy"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            lifecycle_summary={"priority_hint": " high_priority_backlog_present "},
        )
        == "lifecycle_high_priority_backlog"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            intervention_summary={
                "intervention_reason": " high_priority_unresolved_escalation_backlog "
            },
        )
        == "lifecycle_high_priority_backlog"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            stability_summary={"stability_status": " escalating "},
        )
        == "intervention_stability"
    )
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            stability_summary={"stability_status": " flapping "},
            include_flapping=True,
        )
        == "intervention_stability_flapping"
    )


def test_operator_escalation_source_treats_unhashable_intervention_required_as_missing():
    assert (
        run_hybrid_seed_collection.operator_escalation_source(
            {},
            intervention_summary={"intervention_required": []},
        )
        is None
    )


def test_operator_action_hint_treats_unknown_summaries_as_missing():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_effective_recommended_mode": "browser",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
    )

    assert hint == "follow recovery policy escalation guidance; suggested mode=browser"


def test_operator_escalation_audit_message_omits_unknown_digest_stability_status():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {},
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )

    assert message is not None
    assert "[source=intervention_policy" in message
    assert "digest_stability=unknown" not in message


def test_operator_escalation_audit_message_treats_unknown_summaries_as_missing():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
        final_guidance_summary="unknown",
        digest_summary="unknown",
        digest_stability_summary="unknown",
    )

    assert message == "Operator escalation [source=recovery_policy]"


def test_operator_escalation_audit_message_uses_fallback_when_primary_values_are_whitespace_unknown():
    message = run_hybrid_seed_collection.operator_escalation_audit_message(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "operator_final_guidance_message": " unknown ",
            "operator_digest_status": " unknown ",
            "operator_digest_stability_status": " unknown ",
        },
        final_guidance_summary={
            "guidance_message": "Escalating intervention",
        },
        digest_summary={
            "digest_status": "intervention_required",
        },
        digest_stability_summary={
            "stability_status": "digest_recently_shifted",
        },
    )

    assert message == (
        "Escalating intervention "
        "[source=recovery_policy, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert "unknown" not in message


def test_operator_action_hint_uses_fallback_when_primary_suggested_mode_is_whitespace_unknown():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_effective_recommended_mode": " unknown ",
        },
        intervention_summary={
            "suggested_mode": " unknown ",
        },
        lifecycle_summary={
            "suggested_mode": "browser",
        },
    )

    assert hint == "follow recovery policy escalation guidance; suggested mode=browser"
    assert "unknown" not in hint


def test_emit_operator_console_summary_omits_missing_page_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=17"},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err


def test_emit_operator_console_summary_treats_unknown_summaries_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
        lifecycle_summary="unknown",
        intervention_summary="unknown",
        stability_summary="unknown",
        final_guidance_summary="unknown",
        digest_summary="unknown",
        digest_stability_summary="unknown",
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "unknown" not in escalation_line
    assert "page=None" not in captured.err


def test_emit_operator_console_summary_omits_unknown_guidance_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "guidance=unknown" not in captured.err


def test_emit_operator_console_summary_omits_unknown_digest_status_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "digest_status=unknown" not in captured.err


def test_emit_operator_console_summary_omits_unknown_digest_stability_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "digest_stability=unknown" not in captured.err


def test_emit_operator_console_summary_omits_unknown_reason_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_effective_recommended_mode": "browser",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=browser" in captured.err
    assert "reason=unknown" not in captured.err


def test_emit_operator_console_summary_omits_unknown_priority_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_effective_recommended_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=unknown" not in captured.err
    assert "mode=browser" in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err


def test_emit_operator_console_summary_omits_unknown_mode_value(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "task": {"page": 17},
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation" in captured.err
    assert "escalate_repeated_repin" in captured.err
    assert "priority=high" in captured.err
    assert "mode=unknown" not in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err


def test_emit_operator_console_summary_uses_fallback_when_primary_values_are_whitespace_unknown(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": " unknown ",
            "recovery_policy_effective_recommended_mode": " unknown ",
            "top_policy_reason": " unknown ",
            "operator_final_guidance_label": " unknown ",
            "operator_digest_status": " unknown ",
            "operator_digest_stability_status": " unknown ",
            "task": {"page": "unknown"},
        },
        intervention_summary={
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
        final_guidance_summary={
            "guidance_label": "Escalating intervention",
        },
        digest_summary={
            "digest_status": "intervention_required",
        },
        digest_stability_summary={
            "stability_status": "digest_recently_shifted",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=recovery_policy" in escalation_line
    assert "priority=warning" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "guidance=Escalating intervention" in escalation_line
    assert "digest_status=intervention_required" in escalation_line
    assert "digest_stability=digest_recently_shifted" in escalation_line
    assert "page=" not in escalation_line
    assert "unknown" not in escalation_line


def test_emit_operator_console_summary_omits_whitespace_unknown_values_on_audit_line(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {
            "operator_escalation_audit_message": "Operator escalation [source=intervention_policy]",
            "recovery_policy_effective_recommended_mode": " unknown ",
            "recovery_policy_priority": " unknown ",
            "top_policy_reason": " unknown ",
            "task": {"page": "unknown"},
        },
        intervention_summary={
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "suggested_mode": " unknown ",
        },
        stability_summary={
            "stability_status": " unknown ",
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation audit" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line == "[OPERATOR] Operator escalation: intervention_required"
    assert "unknown" not in escalation_line
    assert "()" not in escalation_line


def test_emit_operator_console_summary_treats_whitespace_unknown_status_label_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_console_summary(
        {},
        intervention_summary={
            "intervention_status": " unknown ",
            "intervention_required": True,
        },
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line.startswith("[OPERATOR] Operator escalation: operator_escalation")
    assert "unknown" not in escalation_line


def test_emit_operator_recovery_console_summary_reports_escalation_cleared_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=20" in captured.err


def test_emit_operator_recovery_console_summary_strips_transition_kind(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": " escalation_cleared ",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err


def test_emit_operator_recovery_console_summary_omits_missing_page_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": None,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=None" not in captured.err


def test_emit_operator_recovery_console_summary_omits_negative_page_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": "hybrid",
                "task_page": -20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=" not in captured.err


def test_emit_operator_recovery_console_summary_omits_missing_mode_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": "steady_hybrid",
                "effective_mode": None,
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=steady_hybrid" in captured.err
    assert "mode=unknown" not in captured.err
    assert "page=20" in captured.err


def test_emit_operator_recovery_console_summary_omits_missing_to_status_value(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": "escalate_repeated_repin",
                "to_policy_status": None,
                "effective_mode": "hybrid",
                "task_page": 20,
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator recovery" in captured.err
    assert "escalation_cleared" in captured.err
    assert "from=escalate_repeated_repin" in captured.err
    assert "to=unknown" not in captured.err
    assert "mode=hybrid" in captured.err
    assert "page=20" in captured.err


def test_emit_operator_recovery_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_recovery_console_summary(
        [
            {
                "transition_kind": "escalation_cleared",
                "from_policy_status": " unknown ",
                "to_policy_status": " unknown ",
                "effective_mode": " unknown ",
                "task_page": "unknown",
            }
        ]
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator recovery: escalation_cleared"
    assert "from=" not in captured.err
    assert "to=" not in captured.err
    assert "mode=" not in captured.err
    assert "page=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_lifecycle_console_summary_reports_nonsteady_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "retrial_window_open",
            "lifecycle_reason": "hybrid_retrial_budget_active",
            "recommended_follow_up": "continue_hybrid_with_budget_watch",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "retrial_window_open" in captured.err
    assert "follow_up=continue_hybrid_with_budget_watch" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err
    assert "active_unresolved_priority=None" not in captured.err


def test_emit_operator_lifecycle_console_summary_omits_unknown_follow_up(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "follow_up=unknown" not in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err


def test_emit_operator_lifecycle_console_summary_omits_unknown_active_unresolved_priority(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "reason=recovery_policy_monitoring_active" in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err
    assert "active_unresolved_priority=unknown" not in captured.err
    assert "active_high_priority_unresolved_count=0" in captured.err


def test_emit_operator_lifecycle_console_summary_omits_unknown_suggested_mode(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=unknown" not in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err


def test_emit_operator_lifecycle_console_summary_omits_unknown_active_high_priority_unresolved_count(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "active_high_priority_unresolved_count=" not in captured.err


def test_emit_operator_lifecycle_console_summary_omits_negative_active_high_priority_unresolved_count(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": -2,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "active_high_priority_unresolved_count=" not in captured.err


def test_emit_operator_lifecycle_console_summary_omits_unknown_priority_hint(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=unknown" not in captured.err


def test_emit_operator_lifecycle_console_summary_omits_unknown_reason(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Lifecycle state" in captured.err
    assert "monitor" in captured.err
    assert "reason=unknown" not in captured.err
    assert "follow_up=monitor_until_stable" in captured.err
    assert "suggested_mode=hybrid" in captured.err
    assert "priority_hint=no_active_priority_backlog" in captured.err


def test_emit_operator_lifecycle_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_lifecycle_console_summary_omits_empty_parentheses_when_only_status_is_visible(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "unknown",
            "suggested_mode": "unknown",
            "priority_hint": "unknown",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Lifecycle state: monitor"


def test_emit_operator_lifecycle_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": "monitor",
            "lifecycle_reason": " unknown ",
            "recommended_follow_up": " unknown ",
            "suggested_mode": " unknown ",
            "priority_hint": " unknown ",
            "active_unresolved_priority": " unknown ",
            "active_high_priority_unresolved_count": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Lifecycle state: monitor"
    assert "reason=" not in captured.err
    assert "follow_up=" not in captured.err
    assert "suggested_mode=" not in captured.err
    assert "priority_hint=" not in captured.err
    assert "active_unresolved_priority=" not in captured.err
    assert "active_high_priority_unresolved_count=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_lifecycle_console_summary_treats_whitespace_unknown_state_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_lifecycle_console_summary(
        {
            "lifecycle_state": " unknown ",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_intervention_console_summary_reports_nonready_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "required=True" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "suggested_mode=browser" not in captured.err


def test_emit_operator_intervention_console_summary_omits_unknown_action_hint(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "action_hint=unknown" not in captured.err
    assert "suggested_mode=browser" in captured.err


def test_emit_operator_intervention_console_summary_omits_unknown_suggested_mode(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "action_hint=inspect unresolved high-priority backlog" in captured.err
    assert "suggested_mode=unknown" not in captured.err


def test_emit_operator_final_guidance_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_intervention_console_summary_omits_unknown_priority(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=unknown" not in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "action_hint=inspect unresolved high-priority backlog" in captured.err
    assert "suggested_mode=browser" in captured.err


def test_emit_operator_intervention_console_summary_omits_unknown_reason(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=unknown" not in captured.err
    assert "action_hint=inspect unresolved high-priority backlog" in captured.err
    assert "suggested_mode=browser" in captured.err


def test_emit_operator_intervention_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_intervention_stability_console_summary_treats_unknown_summary_as_missing(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_intervention_console_summary_keeps_suggested_mode_when_action_hint_lacks_mode(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=high_priority_unresolved_escalation_backlog" in captured.err
    assert "suggested_mode=browser" in captured.err


def test_emit_operator_intervention_console_summary_can_suppress_duplicate_reason_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "preferred_operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "suggested_mode": "browser",
        },
        suppress_reason=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=repeated_repin_cycle_detected" not in captured.err
    assert "suggested_mode=browser" not in captured.err


def test_emit_operator_intervention_console_summary_can_suppress_duplicate_priority_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "preferred_operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "suggested_mode": "browser",
        },
        suppress_priority=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" not in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err
    assert "suggested_mode=browser" not in captured.err


def test_emit_operator_intervention_console_summary_can_suppress_duplicate_suggested_mode_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "preferred_operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "suggested_mode": "browser",
        },
        suppress_suggested_mode=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "reason=repeated_repin_cycle_detected" in captured.err
    assert "suggested_mode=browser" not in captured.err


def test_emit_operator_intervention_console_summary_omits_empty_parentheses_when_only_status_is_visible(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": "unknown",
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention status: intervention_required"


def test_emit_operator_intervention_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": "intervention_required",
            "intervention_required": " unknown ",
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "preferred_operator_action_hint": " unknown ",
            "suggested_mode": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention status: intervention_required"
    assert "required=" not in captured.err
    assert "priority=" not in captured.err
    assert "reason=" not in captured.err
    assert "action_hint=" not in captured.err
    assert "suggested_mode=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_intervention_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_console_summary(
        {
            "intervention_status": " unknown ",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_intervention_stability_console_summary_reports_nonstable_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=" not in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_can_suppress_duplicate_action_hint(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
        suppress_action_hint=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" not in captured.err


def test_emit_operator_intervention_stability_console_summary_can_suppress_duplicate_current_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
        suppress_current=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "escalating" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "Intervention stability: escalating" not in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_keeps_status_when_suppression_would_otherwise_blank_line(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "current_intervention_status": "intervention_required",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "unknown",
        },
        suppress_action_hint=True,
        suppress_current=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention stability: escalating"


def test_emit_operator_intervention_stability_console_summary_omits_unknown_action_hint(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "action_hint=unknown" not in captured.err


def test_emit_operator_intervention_stability_console_summary_omits_unknown_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "explanation=unknown" not in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_omits_unknown_severity(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=unknown" not in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Intervention escalated from ready to intervention_required recently." in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_omits_unknown_current(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=unknown" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Intervention escalated from ready to intervention_required recently." in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=warning" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=0" in captured.err
    assert "Intervention is transitioning and currently in monitor." in captured.err

def test_emit_operator_intervention_stability_console_summary_omits_unknown_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "unknown",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_required" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "Intervention escalated from ready to intervention_required recently." in captured.err
    assert "action_hint=prefer browser and investigate escalating intervention" in captured.err


def test_emit_operator_intervention_stability_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": " unknown ",
            "current_intervention_status": " unknown ",
            "previous_intervention_status": " unknown ",
            "recent_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
            "stability_action_hint": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Intervention stability: escalating"
    assert "severity=" not in captured.err
    assert "current=" not in captured.err
    assert "previous=" not in captured.err
    assert "changes=" not in captured.err
    assert "explanation=" not in captured.err
    assert "action_hint=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_intervention_stability_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": " unknown ",
            "stability_severity": "warning",
            "current_intervention_status": "intervention_required",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_final_guidance_console_summary_reports_noninfo_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Escalating intervention" in captured.err
    assert "priority=high" in captured.err
    assert "suggested_mode=browser" in captured.err


def test_emit_operator_final_guidance_console_summary_suppresses_casefolded_info_priority(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Routine guidance",
            "guidance_priority": " Info ",
            "guidance_message": "Routine guidance: continue monitoring.",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_final_guidance_console_summary_omits_unknown_suggested_mode(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=warning" in captured.err
    assert "suggested_mode=unknown" not in captured.err


def test_emit_operator_final_guidance_console_summary_omits_unknown_priority(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "unknown",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=unknown" not in captured.err
    assert "suggested_mode=browser" in captured.err
    assert "suggested_mode=unknown" not in captured.err


def test_emit_operator_final_guidance_console_summary_omits_malformed_priority(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": {"bad": "priority"},
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "suggested_mode": "browser",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=" not in captured.err
    assert "suggested_mode=browser" in captured.err


def test_emit_operator_final_guidance_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_final_guidance_console_summary(
        {
            "guidance_label": " unknown ",
            "guidance_priority": " unknown ",
            "guidance_message": "Transitioning intervention: monitor until stable.",
            "suggested_mode": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Final guidance" in captured.err
    assert "Transitioning intervention: monitor until stable." in captured.err
    assert "priority=" not in captured.err
    assert "suggested_mode=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_digest_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_digest_console_summary_reports_nonready_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "digest_priority": "warning",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    assert "priority=warning" in captured.err
    assert "Transitioning intervention" in captured.err


def test_emit_operator_digest_console_summary_omits_unknown_priority(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    assert "Transitioning intervention" in captured.err
    assert "priority=unknown" not in captured.err


def test_emit_operator_digest_console_summary_omits_unknown_message(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "digest_priority": "warning",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    assert "priority=warning" in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_digest_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "attention_required",
            "digest_priority": " unknown ",
            "operator_digest_message": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator digest: attention_required"
    assert "priority=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_digest_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": " unknown ",
            "digest_priority": "warning",
            "operator_digest_message": "Transitioning intervention: monitor until stable.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_digest_console_summary_can_suppress_duplicate_message_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        suppress_message=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "intervention_required" in captured.err
    assert "priority=high" in captured.err
    assert "Escalating intervention:" not in captured.err


def test_emit_operator_digest_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_console_summary(
        {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        suppress_message=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest" in captured.err
    assert "priority=high" in captured.err
    assert "intervention_required" not in captured.err
    assert "Escalating intervention:" not in captured.err


def test_emit_operator_digest_stability_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_digest_stability_console_summary_reports_nonstable_state_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_digest_stability_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=" not in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_digest_stability_console_summary_can_suppress_duplicate_current_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
        suppress_current=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_digest_stability_console_summary_keeps_status_without_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err


def test_emit_operator_digest_stability_console_summary_omits_unknown_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "explanation=unknown" not in captured.err


def test_emit_operator_digest_stability_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": " unknown ",
            "current_digest_status": " unknown ",
            "previous_digest_status": " unknown ",
            "recent_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator digest stability: digest_recently_shifted"
    assert "severity=" not in captured.err
    assert "current=" not in captured.err
    assert "previous=" not in captured.err
    assert "changes=" not in captured.err
    assert "explanation=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_digest_stability_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": " unknown ",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_digest_stability_console_summary_keeps_status_when_suppression_would_otherwise_blank_line(
    capsys,
):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "current_digest_status": "attention_required",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "unknown",
        },
        suppress_current=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator digest stability: digest_recently_shifted"


def test_emit_operator_digest_stability_console_summary_omits_unknown_severity(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=unknown" not in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_digest_stability_console_summary_omits_unknown_current(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=unknown" not in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_digest_stability_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "persistent_noninfo_digest",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Operator digest remains non-info with no recent message changes.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "severity=high" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=0" in captured.err
    assert "Operator digest remains non-info with no recent message changes." in captured.err

def test_emit_operator_digest_stability_console_summary_omits_unknown_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "unknown",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_digest_stability_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator digest stability" in captured.err
    assert "digest_recently_shifted" not in captured.err
    assert "severity=warning" in captured.err
    assert "current=attention_required" in captured.err
    assert "previous=ready" in captured.err
    assert "changes=1" in captured.err
    assert "Operator digest recently shifted from ready to attention_required." in captured.err


def test_emit_operator_escalation_event_trend_console_summary_reports_source_shift_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err


def test_emit_operator_escalation_event_trend_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err


def test_emit_operator_escalation_event_trend_console_summary_omits_missing_last_changed_at_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": None,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=None" not in captured.err


def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_last_changed_at_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "unknown",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=unknown" not in captured.err


def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err


def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_current_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "unknown",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_escalation_event_trend_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=" not in captured.err
    assert "last_changed_at=2026-05-18 18:24:00" in captured.err


def test_emit_operator_escalation_event_trend_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": " unknown ",
            "recent_source_change_count": "unknown",
            "last_source_change_at": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_escalation_event_trend_console_summary_treats_whitespace_unknown_current_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": " unknown ",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_escalation_event_trend_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_escalation_event_stability_console_summary_treats_unknown_summary_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary("unknown")

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_escalation_event_stability_console_summary_reports_shifted_source_to_stderr(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=" not in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_console_summaries_omit_negative_change_count_value(capsys):
    run_hybrid_seed_collection.emit_operator_intervention_stability_console_summary(
        {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": -1,
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        }
    )
    run_hybrid_seed_collection.emit_operator_digest_stability_console_summary(
        {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": -1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        }
    )
    run_hybrid_seed_collection.emit_operator_escalation_event_trend_console_summary(
        {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -1,
            "last_source_change_at": "2026-05-18 18:24:00",
        }
    )
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Intervention stability" in captured.err
    assert "Operator digest stability" in captured.err
    assert "Operator escalation source trend" in captured.err
    assert "Operator escalation source stability" in captured.err
    assert "changes=" not in captured.err


def test_emit_operator_escalation_event_stability_console_summary_can_suppress_duplicate_source_context(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        suppress_source_context=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" not in captured.err
    assert "previous=recovery_policy" not in captured.err
    assert "changes=1" not in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_can_suppress_duplicate_status_text(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" not in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_missing_previous_value(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "persistent_recovery_policy_source",
            "stability_severity": "high",
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "recovery_policy",
            "previous_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
            "operator_readable_explanation": "Operator escalation source remains recovery_policy with no recent source changes.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=recovery_policy" in captured.err
    assert "previous=None" not in captured.err
    assert "changes=0" in captured.err
    assert "Operator escalation source remains recovery_policy with no recent source changes." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_explanation(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "explanation=unknown" not in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_severity(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "severity=unknown" not in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_current(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "source_recently_shifted" in captured.err
    assert "severity=high" in captured.err
    assert "current=unknown" not in captured.err
    assert "previous=recovery_policy" in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_unknown_previous(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Operator escalation source stability" in captured.err
    assert "severity=high" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "previous=unknown" not in captured.err
    assert "changes=1" in captured.err
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in captured.err


def test_emit_operator_escalation_event_stability_console_summary_omits_whitespace_unknown_details(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
            "stability_severity": " unknown ",
            "current_operator_escalation_source": " unknown ",
            "previous_operator_escalation_source": " unknown ",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[OPERATOR] Operator escalation source stability: source_recently_shifted"
    assert "severity=" not in captured.err
    assert "current=" not in captured.err
    assert "previous=" not in captured.err
    assert "changes=" not in captured.err
    assert "explanation=" not in captured.err
    assert "unknown" not in captured.err


def test_emit_operator_escalation_event_stability_console_summary_treats_whitespace_unknown_status_as_missing(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": " unknown ",
            "stability_severity": "warning",
            "current_operator_escalation_source": "intervention_stability",
        }
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_emit_operator_escalation_event_stability_console_summary_omits_empty_payload_when_everything_is_suppressed(capsys):
    run_hybrid_seed_collection.emit_operator_escalation_event_stability_console_summary(
        {
            "stability_status": "source_recently_shifted",
        },
        suppress_source_context=True,
        suppress_status=True,
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_emits_operator_lifecycle_banner_when_status_summary_available(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "retrial_window_open",
            "lifecycle_reason": "hybrid_retrial_budget_active",
            "recommended_follow_up": "continue_hybrid_with_budget_watch",
            "suggested_mode": "hybrid",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 2,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "hybrid_retrial_budget_active",
            "preferred_operator_action_hint": "continue hybrid with budget watch; suggested mode=hybrid",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "digest_priority": "warning",
            "final_guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "intervention_status": "monitor",
            "intervention_stability_status": "transitioning",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "current_digest_priority": "warning",
            "current_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=24", "page": 24},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-banner",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip().startswith("{")
    assert "Lifecycle state" in captured.err
    assert "retrial_window_open" in captured.err
    assert "priority_hint=high_priority_backlog_present" in captured.err
    assert "active_unresolved_priority=high" in captured.err
    assert "active_high_priority_unresolved_count=2" in captured.err
    assert "Intervention status" in captured.err
    assert "intervention_status" not in captured.err
    assert "required=False" in captured.err
    assert "priority=warning" in captured.err
    assert "reason=hybrid_retrial_budget_active" in captured.err
    assert "Intervention stability" in captured.err
    assert "transitioning" in captured.err
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "previous=None" not in intervention_stability_line
    assert "action_hint=monitor until stable before resuming aggressive intervention" in intervention_stability_line
    assert "Final guidance" not in captured.err
    assert "Transitioning intervention" in captured.err
    assert "Operator digest" in captured.err
    assert "attention_required" in captured.err
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "Transitioning intervention:" not in digest_line
    assert "attention_required" not in digest_line
    assert "priority=warning" in digest_line
    assert "Operator digest stability" in captured.err
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "current=attention_required" not in digest_stability_line
    assert "Operator escalation source trend" in captured.err
    assert "current=intervention_stability" in captured.err
    assert "Operator escalation source stability" in captured.err
    assert "Operator escalation audit" in captured.err
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "source_recently_shifted" not in source_stability_line
    assert "current=intervention_stability" not in source_stability_line
    assert "previous=recovery_policy" not in source_stability_line
    assert "changes=1" not in source_stability_line
    operator_lines = [line for line in captured.err.splitlines() if line.startswith("[OPERATOR]")]
    assert operator_lines[0].startswith("[OPERATOR] Operator digest:")
    assert operator_lines[1].startswith("[OPERATOR] Operator digest stability:")
    assert operator_lines[2].startswith("[OPERATOR] Operator escalation source trend:")
    assert operator_lines[3].startswith("[OPERATOR] Operator escalation source stability:")
    assert operator_lines[4].startswith("[OPERATOR] Operator escalation audit:")
    intervention_status_index = next(i for i, line in enumerate(operator_lines) if line.startswith("[OPERATOR] Intervention status:"))
    intervention_stability_index = next(i for i, line in enumerate(operator_lines) if line.startswith("[OPERATOR] Intervention stability:"))
    lifecycle_index = next(i for i, line in enumerate(operator_lines) if line.startswith("[OPERATOR] Lifecycle state:"))
    assert intervention_status_index > 4
    assert intervention_stability_index > intervention_status_index
    assert lifecycle_index > intervention_stability_index
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_digest_status"] == "attention_required"
    assert stdout_payload["operator_digest_priority"] == "warning"
    assert stdout_payload["operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    assert stdout_payload["operator_digest_stability_status"] == "digest_recently_shifted"
    assert stdout_payload["operator_digest_stability_severity"] == "warning"
    assert stdout_payload["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to attention_required."
    assert stdout_payload["operator_escalation_current_source"] == "intervention_stability"
    assert stdout_payload["operator_escalation_previous_source"] == "recovery_policy"
    assert stdout_payload["operator_escalation_source_change_count"] == 1
    assert stdout_payload["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert stdout_payload["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert stdout_payload["operator_escalation_source_stability_severity"] == "high"
    assert stdout_payload["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["intervention_stability_status"] == "transitioning"
    assert runtime_summary["intervention_stability_severity"] == "warning"
    assert runtime_summary["intervention_stability_explanation"] == "Intervention is transitioning and currently in monitor."
    assert runtime_summary["intervention_stability_action_hint"] == "monitor until stable before resuming aggressive intervention"
    assert runtime_summary["operator_final_guidance_label"] == "Transitioning intervention"
    assert runtime_summary["operator_final_guidance_priority"] == "warning"
    assert runtime_summary["operator_final_guidance_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    assert runtime_summary["operator_digest_status"] == "attention_required"
    assert runtime_summary["operator_digest_priority"] == "warning"
    assert runtime_summary["operator_digest_message"] == "Transitioning intervention: monitor until stable before resuming aggressive intervention."
    assert runtime_summary["operator_digest_stability_status"] == "digest_recently_shifted"
    assert runtime_summary["operator_digest_stability_severity"] == "warning"
    assert runtime_summary["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to attention_required."
    assert runtime_summary["operator_escalation_current_source"] == "intervention_stability"
    assert runtime_summary["operator_escalation_previous_source"] == "recovery_policy"
    assert runtime_summary["operator_escalation_source_change_count"] == 1
    assert runtime_summary["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert runtime_summary["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert runtime_summary["operator_escalation_source_stability_severity"] == "high"
    assert runtime_summary["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."


def test_main_omits_missing_previous_on_source_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "persistent_recovery_policy_source",
            "stability_severity": "high",
            "current_operator_escalation_source": "recovery_policy",
            "current_escalation_kind": "recovery_policy",
            "previous_operator_escalation_source": None,
            "recent_source_change_count": 0,
            "last_source_change_at": None,
            "operator_readable_explanation": "Operator escalation source remains recovery_policy with no recent source changes.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=39", "page": 39},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-no-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "previous=None" not in source_stability_line
    assert "current=recovery_policy" in source_stability_line
    assert "changes=0" in source_stability_line


def test_main_omits_missing_previous_on_source_trend_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=40", "page": 40},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-trend-no-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:"))
    assert "previous=None" not in source_trend_line
    assert "current=intervention_stability" in source_trend_line
    assert "changes=1" in source_trend_line
    assert "last_changed_at=2026-05-18 18:24:00" in source_trend_line


def test_main_omits_missing_last_changed_at_on_source_trend_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": 1,
            "last_source_change_at": None,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=41", "page": 41},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-trend-no-last-changed-at",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:"))
    assert "current=intervention_stability" in source_trend_line
    assert "changes=1" in source_trend_line
    assert "last_changed_at=None" not in source_trend_line


def test_main_omits_unknown_last_changed_at_on_source_trend_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=42", "page": 42},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-trend-unknown-last-changed-at",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:"))
    assert "current=intervention_stability" in source_trend_line
    assert "previous=recovery_policy" in source_trend_line
    assert "changes=1" in source_trend_line
    assert "last_changed_at=unknown" not in source_trend_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_last_changed_at") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_last_changed_at") != "unknown"


def test_main_omits_unknown_previous_on_source_trend_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=41", "page": 41},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-trend-unknown-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:"))
    assert "current=intervention_stability" in source_trend_line
    assert "previous=unknown" not in source_trend_line
    assert "changes=1" in source_trend_line
    assert "last_changed_at=2026-05-18 18:24:00" in source_trend_line


def test_main_omits_unknown_current_on_source_trend_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "unknown",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=42", "page": 42},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-trend-unknown-current",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(
        line.startswith("[OPERATOR] Operator escalation source trend:")
        for line in captured.err.splitlines()
    )


def test_main_omits_unknown_action_hint_on_intervention_status_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=35", "page": 35},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-unknown-action-hint",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "active_unresolved_priority=None" not in lifecycle_line
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "action_hint=unknown" not in intervention_line
    assert "suggested_mode=hybrid" in intervention_line


def test_main_omits_unknown_explanation_on_source_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-unknown-explanation",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "source_recently_shifted" in source_stability_line
    assert "severity=high" in source_stability_line
    assert "current=intervention_stability" in source_stability_line
    assert "previous=recovery_policy" in source_stability_line
    assert "changes=1" in source_stability_line
    assert "explanation=unknown" not in source_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_stability_explanation") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_stability_explanation") != "unknown"


def test_main_omits_literal_unknown_source_stability_explanation_from_payloads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-literal-unknown-explanation-payload",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "explanation=unknown" not in source_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_stability_explanation") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_stability_explanation") != "unknown"


def test_main_keeps_status_on_source_stability_line_when_unknown_explanation_and_source_context_are_suppressed(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-unknown-explanation-duplicate-context",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert source_stability_line == "[OPERATOR] Operator escalation source stability: source_recently_shifted"
    assert "current=intervention_stability" not in source_stability_line
    assert "previous=recovery_policy" not in source_stability_line
    assert "changes=1" not in source_stability_line
    assert "explanation=unknown" not in source_stability_line


def test_main_keeps_status_on_source_stability_line_when_whitespace_unknown_context_is_suppressed(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": " unknown ",
            "previous_distinct_operator_escalation_source": " unknown ",
            "recent_source_change_count": "unknown",
            "last_source_change_at": " unknown ",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": " unknown ",
            "previous_operator_escalation_source": " unknown ",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": " unknown ",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-whitespace-placeholder-context",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Operator escalation source stability:")
    )
    assert source_stability_line == "[OPERATOR] Operator escalation source stability: source_recently_shifted"
    assert "unknown" not in source_stability_line


def test_main_keeps_source_context_on_source_stability_line_when_negative_change_count_hides_trend_line(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "recent_source_change_count": -1,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": "intervention_stability",
            "recent_source_change_count": -1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-negative-change-count-hidden-trend-line",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(
        line.startswith("[OPERATOR] Operator escalation source trend:")
        for line in captured.err.splitlines()
    )
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "current=intervention_stability" in source_stability_line
    assert "changes=" not in source_stability_line
    assert "explanation=unknown" not in source_stability_line


def test_main_keeps_source_context_on_source_stability_line_when_unknown_previous_and_change_count_hide_trend_line(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": "unknown",
            "last_source_change_at": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "unknown",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": 60},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-unknown-previous-and-change-hidden-trend-line",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(
        line.startswith("[OPERATOR] Operator escalation source trend:")
        for line in captured.err.splitlines()
    )
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "current=intervention_stability" in source_stability_line
    assert "previous=unknown" not in source_stability_line
    assert "changes=" not in source_stability_line
    assert "explanation=unknown" not in source_stability_line


def test_main_omits_unknown_severity_on_source_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=60", "page": 60},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-unknown-severity",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "source_recently_shifted" not in source_stability_line
    assert "severity=unknown" not in source_stability_line
    assert "current=intervention_stability" in source_stability_line
    assert "previous=recovery_policy" in source_stability_line
    assert "changes=1" in source_stability_line
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in source_stability_line


def test_main_omits_unknown_current_on_source_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-unknown-current",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "severity=high" in source_stability_line
    assert "current=unknown" not in source_stability_line
    assert "previous=recovery_policy" in source_stability_line
    assert "changes=1" in source_stability_line
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in source_stability_line


def test_main_omits_unknown_previous_on_source_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-source-stability-unknown-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:"))
    assert "severity=high" in source_stability_line
    assert "current=intervention_stability" in source_stability_line
    assert "previous=unknown" not in source_stability_line
    assert "changes=1" in source_stability_line
    assert "Operator escalation source recently shifted from recovery_policy to intervention_stability." in source_stability_line


def test_main_omits_unknown_priority_on_intervention_status_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": False,
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=57", "page": 57},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-unknown-priority",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "priority=unknown" not in intervention_line
    assert "reason=conflicting_runtime_and_lifecycle_hints" in intervention_line
    assert "action_hint=monitor until stable" in intervention_line
    assert "suggested_mode=hybrid" in intervention_line


def test_main_omits_unknown_reason_on_intervention_status_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": False,
            "intervention_priority": "warning",
            "preferred_operator_action_hint": "monitor until stable",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=58", "page": 58},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-unknown-reason",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "priority=warning" in intervention_line
    assert "reason=unknown" not in intervention_line
    assert "action_hint=monitor until stable" in intervention_line
    assert "suggested_mode=hybrid" in intervention_line


def test_main_omits_unknown_explanation_on_intervention_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=54", "page": 54},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-unknown-explanation",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "severity=high" in intervention_stability_line
    assert "current=intervention_required" in intervention_stability_line
    assert "previous=ready" in intervention_stability_line
    assert "changes=1" in intervention_stability_line
    assert "explanation=unknown" not in intervention_stability_line
    assert "action_hint=prefer browser and investigate escalating intervention" in intervention_stability_line


def test_main_omits_literal_unknown_intervention_stability_explanation_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=54", "page": 54},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-literal-unknown-explanation-payload",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "explanation=unknown" not in intervention_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("intervention_stability_explanation") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_stability_explanation") != "unknown"


def test_main_keeps_status_on_intervention_stability_line_when_unknown_explanation_and_current_are_suppressed(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=54", "page": 54},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-unknown-explanation-duplicate-current",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert intervention_stability_line == "[OPERATOR] Intervention stability: escalating, previous=ready, changes=1"
    assert "current=intervention_required" not in intervention_stability_line
    assert "explanation=unknown" not in intervention_stability_line


def test_main_keeps_status_on_intervention_stability_line_when_whitespace_unknown_context_is_suppressed(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": " unknown ",
            "preferred_operator_action_hint": " unknown ",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "current_intervention_status": " unknown ",
            "operator_readable_explanation": " unknown ",
            "stability_action_hint": " unknown ",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=54", "page": 54},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-whitespace-placeholder-context",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Intervention stability:")
    )
    assert intervention_stability_line == "[OPERATOR] Intervention stability: escalating"
    assert "unknown" not in intervention_stability_line


def test_main_omits_unknown_severity_on_intervention_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=55", "page": 55},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-unknown-severity",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "severity=unknown" not in intervention_stability_line
    assert "current=intervention_required" in intervention_stability_line
    assert "previous=ready" in intervention_stability_line
    assert "changes=1" in intervention_stability_line
    assert "Intervention escalated from ready to intervention_required recently." in intervention_stability_line
    assert "action_hint=prefer browser and investigate escalating intervention" in intervention_stability_line


def test_main_omits_unknown_current_on_intervention_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=56", "page": 56},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-unknown-current",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "severity=high" in intervention_stability_line
    assert "current=unknown" not in intervention_stability_line
    assert "previous=ready" in intervention_stability_line
    assert "changes=1" in intervention_stability_line
    assert "Intervention escalated from ready to intervention_required recently." in intervention_stability_line
    assert "action_hint=prefer browser and investigate escalating intervention" in intervention_stability_line

def test_main_omits_unknown_previous_on_intervention_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "unknown",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=57", "page": 57},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-unknown-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "severity=high" in intervention_stability_line
    assert "current=intervention_required" in intervention_stability_line
    assert "previous=unknown" not in intervention_stability_line
    assert "changes=1" in intervention_stability_line
    assert "Intervention escalated from ready to intervention_required recently." in intervention_stability_line
    assert "action_hint=prefer browser and investigate escalating intervention" in intervention_stability_line


def test_main_omits_unknown_follow_up_on_lifecycle_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=42", "page": 42},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-unknown-follow-up",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "follow_up=unknown" not in lifecycle_line
    assert "suggested_mode=hybrid" in lifecycle_line
    assert "priority_hint=no_active_priority_backlog" in lifecycle_line


def test_main_omits_literal_unknown_follow_up_from_runtime_summary(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "unknown",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=42", "page": 42},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-literal-unknown-follow-up-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "follow_up=unknown" not in lifecycle_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_follow_up") != "unknown"


def test_main_omits_unknown_suggested_mode_on_lifecycle_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=43", "page": 43},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-unknown-suggested-mode",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "follow_up=monitor_until_stable" in lifecycle_line
    assert "suggested_mode=unknown" not in lifecycle_line
    assert "priority_hint=no_active_priority_backlog" in lifecycle_line


def test_main_omits_literal_unknown_lifecycle_suggested_mode_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "unknown",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=43", "page": 43},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-literal-unknown-suggested-mode-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "suggested_mode=unknown" not in lifecycle_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_suggested_mode") != "unknown"


def test_main_omits_unknown_suggested_mode_on_final_guidance_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=46", "page": 46},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-final-guidance-unknown-suggested-mode",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    final_guidance_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Final guidance:"))
    assert "priority=warning" in final_guidance_line
    assert "suggested_mode=unknown" not in final_guidance_line


def test_main_treats_unknown_final_guidance_message_as_missing_for_console_and_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "unknown",
            "suggested_mode": "browser",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47", "page": 47},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-final-guidance-unknown-message",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    final_guidance_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Final guidance:"))
    assert "[OPERATOR] Final guidance: unknown" not in final_guidance_line
    assert "Transitioning intervention" in final_guidance_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_final_guidance_message") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_final_guidance_message") != "unknown"


def test_main_treats_unknown_final_guidance_label_as_missing_for_console_and_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "unknown",
            "guidance_priority": "warning",
            "guidance_message": "unknown",
            "suggested_mode": "browser",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47", "page": 47},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-final-guidance-unknown-label",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    final_guidance_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Final guidance:"))
    assert "[OPERATOR] Final guidance: unknown" not in final_guidance_line
    assert "Operator guidance" in final_guidance_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_final_guidance_label") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_final_guidance_label") != "unknown"


def test_main_treats_unknown_final_guidance_message_as_missing_for_escalation_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "unknown",
            "suggested_mode": "browser",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47", "page": 47},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-escalation-final-guidance-unknown-message",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    final_guidance_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Final guidance:"))
    assert "[OPERATOR] Final guidance: unknown" not in final_guidance_line
    assert "Transitioning intervention" in final_guidance_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_final_guidance_message") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_final_guidance_message") != "unknown"


def test_main_treats_unknown_final_guidance_priority_as_missing_for_escalation_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "unknown",
            "guidance_message": "Transitioning intervention: prefer browser and investigate escalating intervention.",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=53", "page": 53},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-escalation-final-guidance-unknown-priority",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    final_guidance_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Final guidance:"))
    assert "priority=unknown" not in final_guidance_line
    assert "suggested_mode=browser" in final_guidance_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_final_guidance_priority") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_final_guidance_priority") != "unknown"


def test_main_omits_unknown_priority_on_digest_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "operator_digest_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=48", "page": 48},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-unknown-priority",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "attention_required" in digest_line
    assert "Transitioning intervention" in digest_line
    assert "priority=unknown" not in digest_line


def test_main_omits_unknown_message_on_digest_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "digest_priority": "warning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-unknown-message",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "attention_required" in digest_line
    assert "priority=warning" in digest_line
    assert "unknown" not in digest_line


def test_main_omits_unknown_priority_hint_on_lifecycle_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=44", "page": 44},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-unknown-priority-hint",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "follow_up=monitor_until_stable" in lifecycle_line
    assert "suggested_mode=hybrid" in lifecycle_line
    assert "priority_hint=unknown" not in lifecycle_line


def test_main_omits_literal_unknown_lifecycle_priority_hint_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "unknown",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=44", "page": 44},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-literal-unknown-priority-hint-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "priority_hint=unknown" not in lifecycle_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_priority_hint") != "unknown"


def test_main_omits_literal_unknown_lifecycle_active_high_priority_unresolved_count_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=44", "page": 44},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-literal-unknown-active-high-priority-count-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "active_high_priority_unresolved_count=" not in lifecycle_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_active_high_priority_unresolved_count") != "unknown"


def test_main_omits_literal_unknown_lifecycle_active_unresolved_priority_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=44", "page": 44},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-literal-unknown-active-unresolved-priority-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "active_unresolved_priority=unknown" not in lifecycle_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_active_unresolved_priority") != "unknown"


def test_main_omits_unknown_reason_on_lifecycle_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=45", "page": 45},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-unknown-reason",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "reason=unknown" not in lifecycle_line
    assert "follow_up=monitor_until_stable" in lifecycle_line
    assert "suggested_mode=hybrid" in lifecycle_line
    assert "priority_hint=no_active_priority_backlog" in lifecycle_line


def test_main_omits_literal_unknown_lifecycle_reason_from_runtime_summary(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=45", "page": 45},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-literal-unknown-reason-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "reason=unknown" not in lifecycle_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_reason") != "unknown"


def test_main_omits_unknown_active_unresolved_priority_on_lifecycle_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47", "page": 47},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-unknown-active-priority",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    lifecycle_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Lifecycle state:"))
    assert "reason=recovery_policy_monitoring_active" in lifecycle_line
    assert "follow_up=monitor_until_stable" in lifecycle_line
    assert "suggested_mode=hybrid" in lifecycle_line
    assert "priority_hint=no_active_priority_backlog" in lifecycle_line
    assert "active_unresolved_priority=unknown" not in lifecycle_line
    assert "active_high_priority_unresolved_count=0" in lifecycle_line


def test_main_omits_unknown_suggested_mode_on_intervention_status_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=38", "page": 38},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-unknown-suggested-mode",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "suggested_mode=unknown" not in intervention_line
    assert "action_hint=monitor until stable" in intervention_line


def test_main_omits_missing_previous_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Persistent intervention required",
            "guidance_priority": "high",
            "guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "preferred_action_hint": "treat as sustained intervention and investigate backlog",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "persistent_intervention_required",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "persistent_intervention_required",
            "final_guidance_stability_status": "persistent_noninfo_guidance",
            "operator_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "persistent_noninfo_digest",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Persistent intervention required: treat as sustained intervention and investigate backlog.",
            "previous_digest_status": None,
            "previous_digest_message": None,
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "Operator digest remains non-info with no recent message changes.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=36", "page": 36},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-stability-no-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "previous=None" not in digest_stability_line
    assert "changes=0" in digest_stability_line
    assert "Operator digest remains non-info with no recent message changes." in digest_stability_line

def test_main_omits_unknown_previous_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "unknown",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": 50},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-stability-unknown-previous",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "severity=warning" in digest_stability_line
    assert "current=attention_required" in digest_stability_line
    assert "previous=unknown" not in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "Operator digest recently shifted from ready to attention_required." in digest_stability_line


def test_main_omits_unknown_explanation_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51", "page": 51},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-stability-unknown-explanation",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" in digest_stability_line
    assert "severity=warning" in digest_stability_line
    assert "current=attention_required" in digest_stability_line
    assert "previous=ready" in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "explanation=unknown" not in digest_stability_line


def test_main_omits_literal_unknown_digest_stability_explanation_from_payloads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51", "page": 51},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-stability-literal-unknown-explanation-payload",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "explanation=unknown" not in digest_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_stability_explanation") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_explanation") != "unknown"


def test_main_omits_unknown_severity_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=52", "page": 52},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-stability-unknown-severity",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    assert "severity=unknown" not in digest_stability_line
    assert "current=attention_required" in digest_stability_line
    assert "previous=ready" in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "Operator digest recently shifted from ready to attention_required." in digest_stability_line


def test_main_omits_unknown_current_on_digest_stability_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=53", "page": 53},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-digest-stability-unknown-current",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    assert "severity=warning" in digest_stability_line
    assert "current=unknown" not in digest_stability_line
    assert "previous=ready" in digest_stability_line
    assert "changes=1" in digest_stability_line
    assert "Operator digest recently shifted from ready to attention_required." in digest_stability_line


def test_main_can_fail_with_dedicated_exit_code_on_operator_escalation(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=18", "page": 18},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-exit",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "Operator escalation" in captured.err
    assert "source=recovery_policy" in captured.err
    assert "Returning dedicated operator escalation exit code 42" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "recovery_policy"
    assert stdout_payload["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["recovery_policy_status"] == "escalate_repeated_repin"
    assert payload["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"


def test_operator_action_hint_omits_unknown_suggested_mode_for_recovery_policy():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        }
    )

    assert hint == "follow recovery policy escalation guidance"
    assert "suggested mode=unknown" not in hint


def test_operator_action_hint_ignores_unknown_preferred_intervention_action_hint():
    hint = run_hybrid_seed_collection.operator_action_hint(
        {
            "recovery_policy_status": "escalate_repeated_repin",
        },
        intervention_summary={
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
    )

    assert hint == "follow recovery policy escalation guidance; suggested mode=browser"
    assert hint != "unknown"


def test_main_omits_unknown_suggested_mode_in_generated_operator_action_hint(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": "monitor_hybrid_runtime",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_mode_pin_active": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=25", "page": 25},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-action-hint-no-suggested-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_action_hint"] == "follow recovery policy escalation guidance"
    assert "suggested mode=unknown" not in stdout_payload["operator_action_hint"]
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_action_hint"] == "follow recovery policy escalation guidance"
    assert "suggested mode=unknown" not in runtime_summary["operator_action_hint"]


def test_main_ignores_unknown_preferred_intervention_action_hint_in_operator_action_hint(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "guidance_applied": False,
            "recovery_policy_applied": True,
            "guidance_status": "monitor_hybrid_runtime",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_mode_pin_active": True,
            "recovery_policy": {
                "effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=26", "page": 26},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-action-hint-unknown-preferred-intervention-hint",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"
    assert stdout_payload["operator_action_hint"] != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_action_hint"] == "follow recovery policy escalation guidance; suggested mode=browser"
    assert runtime_summary["operator_action_hint"] != "unknown"


def test_main_omits_literal_unknown_intervention_action_hint_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-action-hint-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "action_hint=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_action_hint") != "unknown"


def test_main_omits_literal_unknown_intervention_priority_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "unknown",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=29", "page": 29},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-priority-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "priority=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_priority") != "unknown"


def test_main_omits_literal_unknown_intervention_reason_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=30", "page": 30},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-reason-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "reason=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_reason") != "unknown"


def test_main_omits_literal_unknown_intervention_suggested_mode_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=31", "page": 31},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-suggested-mode-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "suggested_mode=unknown" not in intervention_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_suggested_mode") != "unknown"


def test_main_omits_literal_unknown_intervention_stability_action_hint_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-stability-action-hint-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:")
    )
    assert "action_hint=unknown" not in intervention_stability_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_stability_action_hint") != "unknown"


def test_main_omits_literal_unknown_intervention_stability_severity_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "unknown",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33", "page": 33},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-stability-severity-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:")
    )
    assert "severity=unknown" not in intervention_stability_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_stability_severity") != "unknown"


def test_main_omits_literal_unknown_intervention_status_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "unknown",
            "intervention_required": False,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=34", "page": 34},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-status-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Intervention status:") for line in captured.err.splitlines())
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_status") != "unknown"


def test_main_omits_literal_unknown_intervention_stability_status_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "unknown",
            "stability_severity": "warning",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "stability_action_hint": "monitor until stable before resuming aggressive intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=35", "page": 35},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-intervention-stability-status-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Intervention stability:") for line in captured.err.splitlines())
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_stability_status") != "unknown"


def test_main_omits_literal_unknown_lifecycle_state_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "unknown",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=36", "page": 36},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-lifecycle-state-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Lifecycle state:") for line in captured.err.splitlines())
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("lifecycle_state") != "unknown"


def test_main_omits_literal_unknown_digest_status_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "unknown",
            "digest_priority": "warning",
            "operator_digest_message": "Escalating intervention remains unresolved.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=37", "page": 37},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-status-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Operator digest:") for line in captured.err.splitlines())
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_status") != "unknown"


def test_main_omits_literal_unknown_digest_status_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "unknown",
            "digest_priority": "warning",
            "operator_digest_message": "Escalating intervention remains unresolved.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=49", "page": 49},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-status-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Operator digest:") for line in captured.err.splitlines())
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_status") != "unknown"


def test_main_omits_literal_unknown_digest_stability_status_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "unknown",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=38", "page": 38},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-stability-status-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Operator digest stability:") for line in captured.err.splitlines())
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_status") != "unknown"


def test_main_omits_literal_unknown_digest_stability_status_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "unknown",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=47", "page": 47},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-stability-status-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(
        line.startswith("[OPERATOR] Operator digest stability:")
        for line in captured.err.splitlines()
    )
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_stability_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_status") != "unknown"


def test_main_omits_literal_unknown_digest_priority_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "digest_priority": "unknown",
            "operator_digest_message": "Escalating intervention remains unresolved.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=39", "page": 39},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-priority-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "priority=unknown" not in digest_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_priority") != "unknown"


def test_main_omits_literal_unknown_digest_priority_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "digest_priority": "unknown",
            "operator_digest_message": "Escalating intervention remains unresolved.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=50", "page": 50},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-priority-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "priority=unknown" not in digest_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_priority") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_priority") != "unknown"


def test_main_omits_literal_unknown_digest_message_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "attention_required",
            "digest_priority": "warning",
            "operator_digest_message": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=41", "page": 41},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-message-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "unknown" not in digest_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_message") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_message") != "unknown"


def test_main_omits_literal_unknown_source_stability_status_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "unknown",
            "stability_severity": "warning",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=42", "page": 42},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-source-stability-status-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(
        line.startswith("[OPERATOR] Operator escalation source stability:")
        for line in captured.err.splitlines()
    )
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_stability_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_stability_status") != "unknown"


def test_main_omits_literal_unknown_current_source_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "unknown",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=43", "page": 43},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-current-source-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(
        line.startswith("[OPERATOR] Operator escalation source trend:")
        for line in captured.err.splitlines()
    )
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_current_source") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_current_source") != "unknown"


def test_main_omits_literal_unknown_previous_source_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "unknown",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=44", "page": 44},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-previous-source-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    trend_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:")
    )
    assert "previous=unknown" not in trend_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_previous_source") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_previous_source") != "unknown"


def test_main_omits_literal_unknown_operator_escalation_source_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "operator_escalation_source": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=46", "page": 46},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-operator-escalation-source-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert not any(line.startswith("[OPERATOR] Operator escalation:") for line in captured.err.splitlines())
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source") != "unknown"


def test_main_treats_unknown_source_change_count_as_missing_in_payloads_and_source_lines(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": "unknown",
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": "unknown",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=48", "page": 48},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-source-change-count-missing-contract",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:")
    )
    assert "current=intervention_stability" in source_trend_line
    assert "previous=recovery_policy" in source_trend_line
    assert "changes=" not in source_trend_line
    source_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:")
    )
    assert "changes=" not in source_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_change_count") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_change_count") != "unknown"


def test_main_treats_negative_source_change_count_as_missing_in_payloads_and_source_lines(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:24:00",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -3,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=49", "page": 49},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-negative-source-change-count-missing-contract",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_trend_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source trend:")
    )
    assert "current=intervention_stability" in source_trend_line
    assert "previous=recovery_policy" in source_trend_line
    assert "changes=" not in source_trend_line
    source_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:")
    )
    assert "changes=" not in source_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_change_count") == 0
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_change_count") == 0


def test_main_treats_unknown_recent_change_count_as_missing_on_intervention_and_digest_stability_lines(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
            "stability_action_hint": "prefer browser and investigate escalating intervention",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "warning",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": "unknown",
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=52", "page": 52},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-recent-change-count-on-stability-lines",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:")
    )
    assert "changes=" not in intervention_stability_line
    digest_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:")
    )
    assert "changes=" not in digest_stability_line


def test_main_omits_literal_unknown_source_stability_severity_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "unknown",
            "current_operator_escalation_source": "intervention_stability",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=45", "page": 45},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-source-stability-severity-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    source_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation source stability:")
    )
    assert "severity=unknown" not in source_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_source_stability_severity") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source_stability_severity") != "unknown"


def test_main_omits_literal_unknown_digest_stability_severity_from_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "unknown",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=40", "page": 40},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-stability-severity-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:")
    )
    assert "severity=unknown" not in digest_stability_line
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_severity") != "unknown"


def test_main_omits_literal_unknown_digest_stability_severity_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "unknown",
            "current_digest_status": "attention_required",
            "previous_digest_status": "ready",
            "recent_change_count": 1,
            "operator_readable_explanation": "Operator digest recently shifted from ready to attention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=51", "page": 51},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-digest-stability-severity-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    digest_stability_line = next(
        line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:")
    )
    assert "severity=unknown" not in digest_stability_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_digest_stability_severity") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_digest_stability_severity") != "unknown"


def test_main_treats_unknown_audit_message_as_missing_for_console_and_final_guidance(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "guidance": {},
            "recovery_policy": {
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            "lifecycle_summary": {},
            "intervention_summary": {},
            "intervention_stability_summary": {},
            "final_guidance_summary": {
                "guidance_label": "Escalating intervention",
                "guidance_priority": "high",
                "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            },
            "digest_summary": {},
            "digest_stability_summary": {},
            "escalation_event_trend_summary": {},
            "escalation_event_stability_summary": {},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "browser",
            "effective_mode_source": "recovery_policy",
            "guidance_applied": False,
            "recovery_policy_applied": True,
            "guidance_status": "",
            "recovery_policy_status": "escalate_repeated_repin",
            "recovery_policy_priority": "high",
            "recovery_policy_mode_pin_active": True,
            "recovery_policy": {
                "effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=27", "page": 27},
            "browser_fallback_opened": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_source",
        lambda *args, **kwargs: "recovery_policy",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_action_hint",
        lambda *args, **kwargs: "follow recovery policy escalation guidance; suggested mode=browser",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: "unknown",
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-unknown-audit-treated-missing",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("operator_escalation_audit_message") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_audit_message") != "unknown"
    assert "[OPERATOR] Operator escalation audit: unknown" not in captured.err
    assert (
        "[OPERATOR] Final guidance: "
        "Escalating intervention: prefer browser and investigate escalating intervention."
    ) in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "source=recovery_policy" in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    assert "page=27" in escalation_line


def test_main_suppresses_duplicate_intervention_details_after_normalizing_whitespace(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "recovery-policy-state.json"
    recovery_events_path = tmp_path / "recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "operator-escalation-events.jsonl"
    operator_escalation_state_path = tmp_path / "operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "operator-escalation-recovery-events.jsonl"
    operator_intervention_state_path = tmp_path / "operator-intervention-state.json"
    operator_intervention_events_path = tmp_path / "operator-intervention-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "guidance": {},
            "recovery_policy": {
                "policy_status": "escalate_repeated_repin",
                "priority": "high",
                "mode_pin_active": True,
                "effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            "lifecycle_summary": {},
            "intervention_summary": {
                "intervention_status": "intervention_required",
                "intervention_required": True,
                "intervention_priority": " high ",
                "intervention_reason": " repeated_repin_cycle_detected ",
                "suggested_mode": " browser ",
            },
            "intervention_stability_summary": {},
            "final_guidance_summary": {},
            "digest_summary": {},
            "digest_stability_summary": {},
            "escalation_event_trend_summary": {},
            "escalation_event_stability_summary": {},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--runtime-operator-intervention-state-path",
            str(operator_intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(operator_intervention_events_path),
            "--session-id",
            "runner-normalized-duplicate-intervention-details",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    escalation_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Operator escalation:")
    )
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line
    intervention_line = next(
        line
        for line in captured.err.splitlines()
        if line.startswith("[OPERATOR] Intervention status:")
    )
    assert "required=True" in intervention_line
    assert "priority=high" not in intervention_line
    assert "reason=repeated_repin_cycle_detected" not in intervention_line
    assert "suggested_mode=browser" not in intervention_line


def test_main_treats_missing_effective_mode_resolution_as_requested_mode(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "recovery-policy-state.json"
    recovery_events_path = tmp_path / "recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "operator-escalation-events.jsonl"
    operator_escalation_state_path = tmp_path / "operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "operator-escalation-recovery-events.jsonl"
    operator_intervention_state_path = tmp_path / "operator-intervention-state.json"
    operator_intervention_events_path = tmp_path / "operator-intervention-events.jsonl"
    recorded_modes: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": " hybrid ",
            "effective_mode": None,
            "effective_mode_source": " unknown ",
            "guidance_applied": "unknown",
            "recovery_policy_applied": "unknown",
            "guidance_status": " unknown ",
            "guidance": {},
            "recovery_policy": {},
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: (
            recorded_modes.append(kwargs["mode"])
            or {"decision": "idle", "task": None, "message": "done"}
        ),
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--runtime-operator-intervention-state-path",
            str(operator_intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(operator_intervention_events_path),
            "--session-id",
            "runner-missing-effective-mode-resolution",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert recorded_modes == ["hybrid"]
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["requested_mode"] == "hybrid"
    assert stdout_payload["effective_mode"] is None
    assert stdout_payload.get("effective_mode_source") is None
    assert "unknown" not in json.dumps(stdout_payload)
    assert "None" not in json.dumps(stdout_payload)


def test_main_can_fail_with_dedicated_exit_code_on_lifecycle_high_priority_backlog(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 3,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "preferred_operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=19", "page": 19},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-lifecycle-priority-exit",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "Lifecycle state" in captured.err
    assert "Operator escalation" in captured.err
    assert "source=lifecycle_high_priority_backlog" in captured.err
    assert "priority_hint=high_priority_backlog_present" in captured.err
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "reason=high_priority_unresolved_escalation_backlog" in escalation_line
    assert "reason=high_priority_unresolved_escalation_backlog" not in intervention_line
    assert "Returning dedicated operator escalation exit code 42" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert stdout_payload["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert runtime_summary["operator_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert runtime_summary["lifecycle_state"] == "escalated"
    assert runtime_summary["lifecycle_reason"] == "unresolved_escalation_window_open"
    assert runtime_summary["lifecycle_follow_up"] == "prefer_browser_and_investigate_escalation"
    assert runtime_summary["lifecycle_suggested_mode"] == "browser"
    assert runtime_summary["lifecycle_priority_hint"] == "high_priority_backlog_present"
    assert runtime_summary["intervention_status"] == "intervention_required"
    assert runtime_summary["intervention_required"] is True
    assert runtime_summary["intervention_priority"] == "high"
    assert runtime_summary["intervention_reason"] == "high_priority_unresolved_escalation_backlog"
    assert runtime_summary["intervention_action_hint"] == "inspect unresolved high-priority backlog; suggested mode=browser"
    assert runtime_summary["intervention_suggested_mode"] == "browser"


def test_main_omits_missing_page_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=18"},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-page",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "page=None" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_main_omits_unknown_guidance_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=19", "page": 19},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-guidance",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "guidance=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_main_omits_unknown_digest_status_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=20", "page": 20},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-digest-status",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "digest_status=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_main_omits_unknown_digest_stability_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=21", "page": 21},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-digest-stability",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "digest_stability=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_main_omits_unknown_reason_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=22", "page": 22},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-reason",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "reason=unknown" not in escalation_line
    assert "priority=high" in escalation_line
    assert "mode=browser" in escalation_line


def test_main_omits_unknown_status_label_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "unknown",
            "lifecycle_reason": "unknown",
            "recommended_follow_up": "unknown",
            "suggested_mode": "unknown",
            "priority_hint": "unknown",
            "active_unresolved_priority": "unknown",
            "active_high_priority_unresolved_count": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "unknown",
            "intervention_required": True,
            "intervention_priority": "unknown",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "unknown",
            "stability_severity": "unknown",
            "current_intervention_status": "unknown",
            "previous_intervention_status": "unknown",
            "recent_change_count": 0,
            "last_change_at": None,
            "operator_readable_explanation": "unknown",
            "stability_action_hint": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=22", "page": 22},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-status-label",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "[OPERATOR] Operator escalation: unknown" not in escalation_line
    assert "[OPERATOR] Operator escalation: operator_escalation" in escalation_line
    assert "source=intervention_policy" in escalation_line


def test_main_omits_unknown_priority_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=23", "page": 23},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-priority",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_main_omits_literal_unknown_recovery_policy_priority_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "unknown",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=24", "page": 24},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-literal-unknown-recovery-policy-priority-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_priority") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_priority") != "unknown"


def test_main_omits_literal_unknown_recovery_policy_status_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "unknown",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=25", "page": 25},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-recovery-policy-status-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_status") != "unknown"


def test_main_omits_literal_unknown_recovery_policy_effective_recommended_mode_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "unknown",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=27", "page": 27},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-recovery-policy-effective-mode-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_effective_recommended_mode") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_effective_recommended_mode") != "unknown"


def test_main_omits_literal_unknown_top_policy_reason_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=26", "page": 26},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-literal-unknown-top-policy-reason-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "reason=unknown" not in escalation_line
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("top_policy_reason") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("top_policy_reason") != "unknown"


def test_main_omits_literal_unknown_top_guidance_reason_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-top-guidance-reason-payloads",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("top_guidance_reason") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("top_guidance_reason") != "unknown"


def test_build_runtime_summary_omits_literal_unknown_top_guidance_reason():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "top_guidance_reason": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-top-guidance-reason",
        guidance_resolution={
            "guidance": {
                "top_guidance_reason": "unknown",
            }
        },
    )

    assert summary.get("top_guidance_reason") != "unknown"


def test_build_runtime_summary_omits_literal_unknown_operator_escalation_audit_message():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "operator_escalation_audit_message": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-escalation-audit-message",
    )

    assert summary.get("operator_escalation_audit_message") != "unknown"


def test_build_runtime_summary_omits_literal_unknown_operator_action_hint():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "operator_action_hint": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-operator-action-hint",
    )

    assert summary.get("operator_action_hint") != "unknown"


def test_build_runtime_summary_omits_literal_unknown_last_fallback_url():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "fallback_url": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-last-fallback-url",
    )

    assert summary.get("last_fallback_url") != "unknown"


def test_build_runtime_summary_omits_literal_unknown_termination_reason():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "termination_reason": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-termination-reason",
    )

    assert summary.get("termination_reason") != "unknown"


def test_build_runtime_summary_omits_whitespace_unknown_payload_fields():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": " unknown ",
                    "reason": " unknown ",
                    "requested_mode": " unknown ",
                    "effective_mode": " unknown ",
                    "effective_mode_source": " unknown ",
                    "guidance_status": " unknown ",
                    "guidance_recommended_mode": " unknown ",
                    "recovery_policy_status": " unknown ",
                    "recovery_policy_priority": " unknown ",
                    "recovery_policy_effective_recommended_mode": " unknown ",
                    "top_policy_reason": " unknown ",
                    "top_guidance_reason": " unknown ",
                    "operator_escalation_audit_message": " unknown ",
                    "operator_escalation_source": " unknown ",
                    "operator_action_hint": " unknown ",
                    "fallback_url": " unknown ",
                    "collection_result": {"submit_result": "unknown"},
                    "task": {"url": "unknown", "page": "unknown"},
                }
            ],
            "counts": {" unknown ": 1, "browserless_success": 1},
            "reason_counts": {" unknown ": 2, "browserless_success_stable": 1},
            "effective_mode_counts": {" unknown ": 3},
            "guidance_status_counts": {" unknown ": 4},
            "guidance_applied_count": "unknown",
            "iterations": 1,
            "termination_reason": " unknown ",
        },
        requested_mode=" unknown ",
        effective_mode=" unknown ",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-whitespace-placeholders",
        guidance_resolution={
            "guidance_status": " unknown ",
            "effective_mode_source": " unknown ",
            "recovery_policy_status": " unknown ",
            "recovery_policy_priority": " unknown ",
            "guidance": {
                "recommended_mode": " unknown ",
                "top_guidance_reason": " unknown ",
            },
            "recovery_policy": {
                "effective_recommended_mode": " unknown ",
                "top_policy_reason": " unknown ",
            },
        },
        lifecycle_summary={
            "lifecycle_state": " unknown ",
            "lifecycle_reason": " unknown ",
            "recommended_follow_up": " unknown ",
            "suggested_mode": " unknown ",
            "priority_hint": " unknown ",
            "active_unresolved_priority": " unknown ",
            "active_high_priority_unresolved_count": "unknown",
        },
        intervention_summary={
            "intervention_status": " unknown ",
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "preferred_operator_action_hint": " unknown ",
            "suggested_mode": " unknown ",
        },
        intervention_stability_summary={
            "stability_status": " unknown ",
            "stability_severity": " unknown ",
            "operator_readable_explanation": " unknown ",
            "stability_action_hint": " unknown ",
        },
        final_guidance_summary={
            "guidance_label": " unknown ",
            "guidance_priority": " unknown ",
            "guidance_message": " unknown ",
        },
        operator_digest_summary={
            "digest_status": " unknown ",
            "digest_priority": " unknown ",
            "operator_digest_message": " unknown ",
        },
        operator_digest_stability_summary={
            "stability_status": " unknown ",
            "stability_severity": " unknown ",
            "operator_readable_explanation": " unknown ",
        },
        operator_escalation_event_trend_summary={
            "current_operator_escalation_source": " unknown ",
            "previous_distinct_operator_escalation_source": " unknown ",
            "last_source_change_at": " unknown ",
            "recent_source_change_count": "unknown",
        },
        operator_escalation_event_stability_summary={
            "stability_status": " unknown ",
            "stability_severity": " unknown ",
            "operator_readable_explanation": " unknown ",
        },
    )

    assert summary["requested_mode"] == "hybrid"
    assert summary.get("effective_mode") is None
    assert summary.get("last_effective_mode") is None
    assert summary.get("termination_reason") is None
    assert " unknown " not in summary.get("decision_counts", {})
    assert " unknown " not in summary.get("reason_counts", {})
    assert " unknown " not in summary.get("effective_mode_counts", {})
    assert " unknown " not in summary.get("guidance_status_counts", {})
    assert summary.get("guidance_applied_count") == 0
    assert summary.get("last_task") == {"url": None, "page": None}
    assert summary.get("last_submit_result") == {}

    placeholder_fields = [
        "last_decision",
        "last_reason",
        "guidance_status",
        "guidance_recommended_mode",
        "recovery_policy_status",
        "recovery_policy_priority",
        "recovery_policy_effective_recommended_mode",
        "top_policy_reason",
        "top_guidance_reason",
        "operator_escalation_source",
        "operator_escalation_audit_message",
        "operator_action_hint",
        "last_fallback_url",
        "effective_mode_source",
        "lifecycle_state",
        "lifecycle_reason",
        "lifecycle_follow_up",
        "lifecycle_suggested_mode",
        "lifecycle_priority_hint",
        "lifecycle_active_unresolved_priority",
        "intervention_status",
        "intervention_priority",
        "intervention_reason",
        "intervention_action_hint",
        "intervention_suggested_mode",
        "intervention_stability_status",
        "intervention_stability_severity",
        "intervention_stability_explanation",
        "intervention_stability_action_hint",
        "operator_final_guidance_label",
        "operator_final_guidance_priority",
        "operator_final_guidance_message",
        "operator_digest_status",
        "operator_digest_priority",
        "operator_digest_message",
        "operator_digest_stability_status",
        "operator_digest_stability_severity",
        "operator_digest_stability_explanation",
        "operator_escalation_current_source",
        "operator_escalation_previous_source",
        "operator_escalation_source_last_changed_at",
        "operator_escalation_source_stability_status",
        "operator_escalation_source_stability_severity",
        "operator_escalation_source_stability_explanation",
    ]
    for field in placeholder_fields:
        assert summary.get(field) is None


def test_main_omits_whitespace_unknown_status_bundle_fields_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_events_path = tmp_path / "hybrid-operator-escalation-events.jsonl"
    operator_escalation_state_path = tmp_path / "hybrid-operator-escalation-state.json"
    operator_escalation_recovery_events_path = tmp_path / "hybrid-operator-escalation-recovery-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "digest_summary": {
                "digest_status": " unknown ",
                "digest_priority": " unknown ",
                "operator_digest_message": " unknown ",
            },
            "digest_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "operator_readable_explanation": " unknown ",
            },
            "escalation_event_trend_summary": {
                "current_operator_escalation_source": " unknown ",
                "previous_distinct_operator_escalation_source": " unknown ",
                "last_source_change_at": " unknown ",
                "recent_source_change_count": "unknown",
            },
            "escalation_event_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "operator_readable_explanation": " unknown ",
            },
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": " unknown ",
            "reason": " unknown ",
            "fallback_url": " unknown ",
            "browser_fallback_opened": "unknown",
            "task": {"url": "unknown", "page": "unknown"},
            "collection_result": {"submit_result": "unknown"},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_events_path),
            "--runtime-operator-escalation-state-path",
            str(operator_escalation_state_path),
            "--runtime-operator-escalation-recovery-events-path",
            str(operator_escalation_recovery_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-whitespace-placeholders",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))

    for payload in (stdout_payload, runtime_summary):
        assert payload.get("operator_digest_status") is None
        assert payload.get("operator_digest_priority") is None
        assert payload.get("operator_digest_message") is None
        assert payload.get("operator_digest_stability_status") is None
        assert payload.get("operator_digest_stability_severity") is None
        assert payload.get("operator_digest_stability_explanation") is None
        assert payload.get("operator_escalation_current_source") is None
        assert payload.get("operator_escalation_previous_source") is None
        assert payload.get("operator_escalation_source_last_changed_at") is None
        assert payload.get("operator_escalation_source_stability_status") is None
        assert payload.get("operator_escalation_source_stability_severity") is None
        assert payload.get("operator_escalation_source_stability_explanation") is None
    assert stdout_payload.get("decision") is None
    assert stdout_payload.get("reason") is None
    assert stdout_payload.get("fallback_url") is None
    assert stdout_payload.get("task") == {"url": None, "page": None}


def test_build_runtime_summary_treats_unknown_decision_counts_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": "unknown",
            "iterations": 1,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-decision-counts",
    )

    assert summary.get("decision_counts") == {}


def test_build_runtime_summary_treats_unknown_effective_mode_counts_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "effective_mode_counts": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-effective-mode-counts",
    )

    assert summary.get("effective_mode_counts") == {}


def test_build_runtime_summary_treats_unknown_effective_mode_count_values_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "effective_mode_counts": {"hybrid": "unknown"},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-effective-mode-count-values",
    )

    assert summary.get("effective_mode_counts") == {}


def test_build_runtime_summary_treats_unknown_submit_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "collection_result": {
                "probe_summary": {"item_count": 60, "has_script": True},
                "submit_result": "unknown",
            },
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-submit-result",
    )

    assert summary.get("last_submit_result") == {}


def test_build_runtime_summary_treats_unknown_guidance_resolution_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-resolution",
        guidance_resolution="unknown",
    )

    assert summary.get("guidance_status_counts") == {}
    assert summary.get("guidance_applied_count") == 0


def test_build_runtime_summary_treats_unknown_nested_guidance_resolution_summaries_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-resolution-nested",
        guidance_resolution={
            "guidance": "unknown",
            "recovery_policy": "unknown",
        },
    )

    assert summary.get("last_guidance_recommended_mode") is None
    assert summary.get("last_recovery_policy_effective_recommended_mode") is None
    assert summary.get("top_guidance_reason") is None
    assert summary.get("top_policy_reason") is None


def test_build_runtime_summary_treats_negative_status_scalars_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-negative-status-scalars",
        lifecycle_summary={
            "lifecycle_state": "escalated",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": -2,
        },
        operator_escalation_event_trend_summary={
            "current_operator_escalation_source": "recovery_policy",
            "previous_distinct_operator_escalation_source": None,
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:12:00",
        },
    )

    assert summary["lifecycle_active_high_priority_unresolved_count"] == 0
    assert summary["operator_escalation_source_change_count"] == 0


def test_build_runtime_summary_treats_unknown_last_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": ["unknown"],
            "counts": {},
            "iterations": 1,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-last-result",
    )

    assert summary.get("last_task") == {}
    assert summary.get("last_decision") is None


def test_build_runtime_summary_treats_unknown_operator_escalation_last_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": ["unknown"],
            "counts": {},
            "iterations": 1,
            "termination_reason": "operator_escalation",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-operator-escalation-last-result",
    )

    assert summary.get("operator_escalation_source") is None
    assert summary.get("operator_escalation_audit_message") is None
    assert summary.get("operator_escalation_source_change_count") is None


def test_build_runtime_summary_treats_unknown_result_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result="unknown",
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-result",
    )

    assert summary.get("last_task") == {}
    assert summary.get("last_decision") is None


def test_persist_operator_intervention_state_treats_unknown_summary_as_missing(
    tmp_path: Path,
):
    state_path = tmp_path / "hybrid-operator-intervention-state.json"

    run_hybrid_seed_collection.persist_operator_intervention_state(
        "unknown",
        state_path,
    )

    state_payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert state_payload == {
        "intervention_status": None,
        "intervention_required": None,
        "intervention_priority": None,
        "intervention_reason": None,
        "preferred_operator_action_hint": None,
        "suggested_mode": None,
    }


def test_build_runtime_summary_treats_unknown_iterations_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-iterations",
    )

    assert summary.get("iterations") == 1


def test_build_runtime_summary_treats_negative_iterations_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": -1,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-negative-iterations",
    )

    assert summary.get("iterations") == 1


def test_build_runtime_summary_treats_unknown_guidance_applied_count_as_zero():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "guidance_applied_count": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-applied-count",
    )

    assert summary.get("guidance_applied_count") == 0


def test_build_runtime_summary_treats_negative_guidance_applied_count_as_zero():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "guidance_applied_count": -2,
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-negative-guidance-applied-count",
    )

    assert summary.get("guidance_applied_count") == 0


def test_build_runtime_summary_treats_unknown_guidance_status_counts_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "guidance_status_counts": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-status-counts",
    )

    assert summary.get("guidance_status_counts") == {}


def test_build_runtime_summary_treats_unknown_guidance_status_count_values_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "guidance_status_counts": {"monitor_hybrid_runtime": "unknown"},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-guidance-status-count-values",
    )

    assert summary.get("guidance_status_counts") == {}


def test_build_runtime_summary_treats_unknown_reason_counts_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "reason_counts": "unknown",
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-reason-counts",
    )

    assert summary.get("reason_counts") == {}
    assert summary.get("top_fallback_reason") is None


def test_build_runtime_summary_treats_unknown_reason_count_values_as_missing():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "mode": "loop",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=28", "page": 28},
                }
            ],
            "counts": {"browserless_success": 1},
            "iterations": 1,
            "reason_counts": {"challenge_detected": "unknown"},
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=False,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="summary-unknown-reason-count-values",
    )

    assert summary.get("reason_counts") == {}
    assert summary.get("top_fallback_reason") is None


def test_main_treats_unknown_submit_result_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=66", "page": 66},
            "collection_result": {
                "probe_summary": {"item_count": 60, "has_script": True},
                "submit_result": "unknown",
            },
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-submit-result-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["collection_result"]["submit_result"] == {}
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("last_submit_result") == {}


def test_main_omits_unknown_idle_message_from_payload(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "idle",
            "message": " unknown ",
            "task": None,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-main-idle-message",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["message"] is None
    assert "unknown" not in json.dumps(stdout_payload)


def test_main_treats_unknown_fallback_url_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "fallback_url": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=64", "page": 64},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-fallback-url-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("fallback_url") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("last_fallback_url") != "unknown"


def test_main_omits_unknown_run_once_error_from_payloads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "api_unavailable",
            "reason": "dispatch_endpoint_unreachable",
            "error": " unknown ",
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-run-once-error-placeholder-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["error"] is None
    assert "unknown" not in json.dumps(stdout_payload)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert "unknown" not in json.dumps(runtime_summary)


def test_main_omits_unknown_run_once_task_message_from_payloads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task_message": " unknown ",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=67", "page": 67},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-run-once-task-message-placeholder-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["task_message"] is None
    assert "unknown" not in json.dumps(stdout_payload)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert "unknown" not in json.dumps(runtime_summary)


def test_main_omits_unknown_mode_on_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    recovery_state_path = tmp_path / "hybrid-recovery-policy-state.json"
    recovery_events_path = tmp_path / "hybrid-recovery-policy-events.jsonl"
    operator_escalation_path = tmp_path / "hybrid-operator-escalation-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browser_worker_dispatched",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=24", "page": 24},
            "browser_fallback_opened": True,
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-recovery-policy-state-path",
            str(recovery_state_path),
            "--runtime-recovery-policy-events-path",
            str(recovery_events_path),
            "--runtime-operator-escalation-events-path",
            str(operator_escalation_path),
            "--session-id",
            "runner-escalation-no-mode",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=high" in escalation_line
    assert "mode=unknown" not in escalation_line
    assert "reason=repeated_repin_cycle_detected" in escalation_line


def test_main_omits_unknown_reason_on_audit_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "operator_escalation_active",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-audit-escalation-no-reason",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert "[OPERATOR] Operator escalation audit:" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=warning" in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unknown" not in escalation_line
    assert "page=32" in escalation_line


def test_main_omits_unknown_priority_on_audit_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "operator_escalation_active",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_reason": "unresolved_escalation_window_open",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=34", "page": 34},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-audit-escalation-no-priority",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert "[OPERATOR] Operator escalation audit:" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "priority=unknown" not in escalation_line
    assert "mode=browser" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "page=34" in escalation_line


def test_main_omits_unknown_mode_on_audit_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "operator_escalation_active",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=35", "page": 35},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-audit-escalation-no-mode",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert "[OPERATOR] Operator escalation audit:" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert "mode=unknown" not in escalation_line
    assert "priority=warning" in escalation_line
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "page=35" in escalation_line


def test_main_omits_empty_parentheses_on_audit_operator_escalation_line(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=38"},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-audit-escalation-empty-parts",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    assert escalation_line == "[OPERATOR] Operator escalation: intervention_required"
    assert "()" not in escalation_line


def test_main_omits_unknown_digest_status_in_operator_escalation_audit_message(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=36", "page": 36},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-audit-message-no-digest-status",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert "digest=unknown" not in captured.err
    stdout_payload = json.loads(captured.out)
    assert "digest=unknown" not in stdout_payload["operator_escalation_audit_message"]
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert "digest=unknown" not in runtime_summary["operator_escalation_audit_message"]


def test_main_omits_unknown_digest_stability_in_operator_escalation_audit_message(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=37", "page": 37},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-audit-message-no-digest-stability",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert "digest_stability=unknown" not in captured.err
    stdout_payload = json.loads(captured.out)
    assert "digest_stability=unknown" not in stdout_payload["operator_escalation_audit_message"]
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert "digest_stability=unknown" not in runtime_summary["operator_escalation_audit_message"]


def test_main_can_fail_with_dedicated_exit_code_on_intervention_required_summary(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=31", "page": 31},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-exit",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "Intervention status" in captured.err
    assert "intervention_required" in captured.err
    assert "Operator escalation" in captured.err
    assert "source=intervention_policy" in captured.err
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "reason=unresolved_escalation_window_open" in escalation_line
    assert "reason=unresolved_escalation_window_open" not in intervention_line
    assert "priority=warning" in escalation_line
    assert "priority=warning" not in intervention_line
    assert "mode=browser" in escalation_line
    assert "suggested_mode=browser" not in intervention_line
    assert "Returning dedicated operator escalation exit code 42" in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "intervention_policy"
    assert stdout_payload["operator_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_escalation_source"] == "intervention_policy"
    assert runtime_summary["operator_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert runtime_summary["intervention_status"] == "intervention_required"
    assert runtime_summary["intervention_required"] is True
    assert runtime_summary["intervention_priority"] == "warning"
    assert runtime_summary["intervention_reason"] == "unresolved_escalation_window_open"
    assert runtime_summary["intervention_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert runtime_summary["intervention_suggested_mode"] == "browser"


def test_main_can_fail_with_dedicated_exit_code_on_intervention_stability_summary(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=33", "page": 33},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-exit",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 42
    assert captured.out.strip().startswith("{")
    assert "[OPERATOR] Final guidance:" not in captured.err
    assert "Operator escalation" in captured.err
    assert "source=intervention_stability" in captured.err
    digest_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest:"))
    assert "Escalating intervention:" not in digest_line
    assert "intervention_required" not in digest_line
    assert "priority=high" in digest_line
    digest_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator digest stability:"))
    assert "digest_recently_shifted" not in digest_stability_line
    assert "current=intervention_required" not in digest_stability_line
    escalation_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Operator escalation:"))
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "source=intervention_stability" not in escalation_line
    assert "guidance=Escalating intervention" not in escalation_line
    assert "digest_status=intervention_required" not in escalation_line
    assert "digest_stability=digest_recently_shifted" not in escalation_line
    assert "action_hint=prefer browser and investigate escalation; suggested mode=browser" in intervention_line
    assert "escalating" not in intervention_stability_line
    assert "action_hint=prefer browser and investigate escalation; suggested mode=browser" not in intervention_stability_line
    assert "current=intervention_required" not in intervention_stability_line
    assert "action_hint=unknown" not in intervention_stability_line
    assert "Escalating intervention: prefer browser and investigate escalating intervention." in captured.err
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["operator_escalation_source"] == "intervention_stability"
    assert stdout_payload["operator_final_guidance_label"] == "Escalating intervention"
    assert stdout_payload["operator_final_guidance_priority"] == "high"
    assert stdout_payload["operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert stdout_payload["operator_digest_stability_status"] == "digest_recently_shifted"
    assert stdout_payload["operator_digest_stability_severity"] == "high"
    assert stdout_payload["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to intervention_required."
    assert stdout_payload["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert (
        "[OPERATOR] Operator escalation audit: "
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    ) in captured.err
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["operator_escalation_source"] == "intervention_stability"
    assert runtime_summary["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )


def test_main_does_not_fail_with_dedicated_exit_code_on_flapping_intervention_stability_summary(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable; suggested mode=hybrid",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "flapping",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": "intervention_required",
            "recent_change_count": 3,
            "last_change_at": "2026-05-18 18:18:00",
            "operator_readable_explanation": "Intervention status changed multiple times recently.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=34", "page": 34},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-intervention-stability-flapping",
            "--mode",
            "hybrid",
            "--fail-on-operator-escalation",
            "--operator-escalation-exit-code",
            "42",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip().startswith("{")
    assert "Intervention stability" in captured.err
    intervention_stability_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention stability:"))
    assert "Intervention stability: flapping" not in intervention_stability_line
    assert "severity=warning" in intervention_stability_line
    assert "previous=intervention_required" in intervention_stability_line
    assert "changes=3" in intervention_stability_line
    assert "Intervention status changed multiple times recently." in intervention_stability_line
    assert "Operator escalation" not in captured.err
    stdout_payload = json.loads(captured.out)
    assert "operator_escalation_source" not in stdout_payload
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("operator_escalation_source") is None


def test_main_records_operator_intervention_transition_event(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload["from_intervention_status"] == "ready"
    assert event_payload["to_intervention_status"] == "intervention_required"
    assert event_payload["from_intervention_required"] is False
    assert event_payload["to_intervention_required"] is True
    assert event_payload["from_intervention_priority"] == "info"
    assert event_payload["to_intervention_priority"] == "warning"
    assert event_payload["to_intervention_reason"] == "unresolved_escalation_window_open"
    assert event_payload["to_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert event_payload["to_suggested_mode"] == "browser"
    assert event_payload["to_final_guidance_label"] == "Escalating intervention"
    assert event_payload["to_final_guidance_priority"] == "high"
    assert event_payload["to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload["intervention_status"] == "intervention_required"
    assert state_payload["intervention_required"] is True
    assert state_payload["intervention_priority"] == "warning"
    assert state_payload["intervention_reason"] == "unresolved_escalation_window_open"


def test_append_operator_intervention_transition_events_omits_literal_unknown_effective_mode(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "effective_mode": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
        },
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-unknown-effective-mode",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("effective_mode") != "unknown"


def test_append_operator_intervention_transition_events_omits_whitespace_unknown_fields(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "effective_mode": " unknown ",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
        },
        {
            "intervention_status": " unknown ",
            "intervention_required": True,
            "intervention_priority": " unknown ",
            "intervention_reason": " unknown ",
            "preferred_operator_action_hint": " unknown ",
            "suggested_mode": " unknown ",
        },
        {
            "guidance_label": " unknown ",
            "guidance_priority": " unknown ",
            "guidance_message": " unknown ",
        },
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-whitespace-placeholders",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("to_intervention_status") is None
    assert event_payload.get("to_intervention_priority") is None
    assert event_payload.get("to_intervention_reason") is None
    assert event_payload.get("to_action_hint") is None
    assert event_payload.get("to_suggested_mode") is None
    assert event_payload.get("to_final_guidance_label") is None
    assert event_payload.get("to_final_guidance_priority") is None
    assert event_payload.get("to_final_guidance_message") is None
    assert event_payload.get("effective_mode") is None
    assert "unknown" not in json.dumps(event_payload)

    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("intervention_status") is None
    assert state_payload.get("intervention_required") is True
    assert state_payload.get("intervention_priority") is None
    assert state_payload.get("intervention_reason") is None
    assert state_payload.get("preferred_operator_action_hint") is None
    assert state_payload.get("suggested_mode") is None
    assert "unknown" not in json.dumps(state_payload)


def test_append_operator_intervention_transition_events_omits_literal_unknown_task_page(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": "unknown"},
        },
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-unknown-task-page",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("task_page") != "unknown"


def test_append_operator_intervention_transition_events_omits_literal_unknown_task_url(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "effective_mode": "hybrid",
            "task": {"url": "unknown", "page": 59},
        },
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-unknown-task-url",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("task_url") != "unknown"


def test_append_operator_intervention_transition_events_treats_unknown_result_as_missing(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        "unknown",
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-unknown-result",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("effective_mode") is None
    assert event_payload.get("task_url") is None
    assert event_payload.get("task_page") is None


def test_append_operator_intervention_transition_events_treats_unknown_final_guidance_summary_as_missing(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "effective_mode": "hybrid",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=59", "page": 59},
        },
        {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        "unknown",
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-event-unknown-final-guidance-summary",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "status_changed"
    assert event_payload.get("to_final_guidance_label") is None
    assert event_payload.get("to_final_guidance_priority") is None
    assert event_payload.get("to_final_guidance_message") is None


def test_append_operator_intervention_transition_events_records_required_flag_clear_when_only_explicit_false_is_present(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_required": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
        },
        {
            "intervention_required": False,
        },
        {},
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-required-flag-cleared",
    )

    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["transition_kind"] == "required_flag_changed"
    assert event_payload["from_intervention_required"] is True
    assert event_payload["to_intervention_required"] is False
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload["intervention_required"] is False


def test_append_operator_intervention_transition_events_persists_explicit_false_without_event_when_no_previous_state_exists(
    tmp_path: Path,
):
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    run_hybrid_seed_collection.append_operator_intervention_transition_events(
        {
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
        },
        {
            "intervention_required": False,
        },
        {},
        intervention_state_path,
        intervention_events_path,
        session_id="runner-intervention-explicit-false-no-previous-state",
    )

    assert not intervention_events_path.exists()
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload["intervention_required"] is False


def test_main_omits_literal_unknown_final_guidance_priority_from_intervention_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "unknown",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-guidance-priority",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["to_final_guidance_label"] == "Escalating intervention"
    assert event_payload.get("to_final_guidance_priority") != "unknown"
    assert event_payload["to_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."


def test_main_omits_literal_unknown_final_guidance_message_from_intervention_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "unknown",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-guidance-message",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["to_final_guidance_label"] == "Escalating intervention"
    assert event_payload["to_final_guidance_priority"] == "high"
    assert event_payload.get("to_final_guidance_message") != "unknown"


def test_main_omits_literal_unknown_final_guidance_label_from_intervention_transition_event(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "unknown",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-guidance-label",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload.get("to_final_guidance_label") != "unknown"
    assert event_payload["to_final_guidance_priority"] == "high"
    assert (
        event_payload["to_final_guidance_message"]
        == "Escalating intervention: prefer browser and investigate escalating intervention."
    )


def test_main_omits_literal_unknown_intervention_suggested_mode_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-suggested-mode",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload.get("to_suggested_mode") != "unknown"
    assert event_payload["to_action_hint"] == "prefer browser and investigate escalation"
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("suggested_mode") != "unknown"


def test_main_omits_literal_unknown_intervention_action_hint_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "unknown",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-action-hint",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload.get("to_action_hint") != "unknown"
    assert event_payload["to_suggested_mode"] == "browser"
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("preferred_operator_action_hint") != "unknown"


def test_main_omits_literal_unknown_intervention_priority_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "unknown",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-priority",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload.get("to_intervention_priority") != "unknown"
    assert event_payload["to_action_hint"] == "prefer browser and investigate escalation"
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("intervention_priority") != "unknown"


def test_main_omits_literal_unknown_intervention_reason_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unknown",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-reason",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload.get("to_intervention_reason") != "unknown"
    assert event_payload["to_intervention_priority"] == "warning"
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("intervention_reason") != "unknown"


def test_main_omits_literal_unknown_intervention_status_from_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "escalated",
            "lifecycle_reason": "unresolved_escalation_window_open",
            "recommended_follow_up": "prefer_browser_and_investigate_escalation",
            "suggested_mode": "browser",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "unknown",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation",
            "suggested_mode": "browser",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-status",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload.get("to_intervention_status") != "unknown"
    assert event_payload["to_intervention_priority"] == "warning"
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("intervention_status") != "unknown"


def test_main_treats_unknown_intervention_required_as_missing_on_transition_event_and_state(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"
    intervention_state_path = tmp_path / "hybrid-operator-intervention-state.json"
    intervention_events_path = tmp_path / "hybrid-operator-intervention-events.jsonl"

    intervention_state_path.write_text(
        json.dumps(
            {
                "intervention_status": "ready",
                "intervention_required": False,
                "intervention_priority": "info",
                "intervention_reason": "browserless_fast_path_stable",
                "preferred_operator_action_hint": "keep hybrid; suggested mode=hybrid",
                "suggested_mode": "hybrid",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": "unknown",
            "intervention_priority": "warning",
            "intervention_reason": "recovery_policy_monitoring_active",
            "preferred_operator_action_hint": "monitor until stable",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=32", "page": 32},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--runtime-operator-intervention-state-path",
            str(intervention_state_path),
            "--runtime-operator-intervention-events-path",
            str(intervention_events_path),
            "--session-id",
            "runner-intervention-event-unknown-required",
            "--mode",
            "hybrid",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip().startswith("{")
    event_lines = intervention_events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 1
    event_payload = json.loads(event_lines[0])
    assert event_payload["to_intervention_status"] == "monitor"
    assert event_payload["to_intervention_required"] is False
    state_payload = json.loads(intervention_state_path.read_text(encoding="utf-8"))
    assert state_payload.get("intervention_required") is None


def test_main_treats_unknown_intervention_required_as_missing_for_console_runtime_and_escalation(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {
            "lifecycle_state": "monitor",
            "lifecycle_reason": "recovery_policy_monitoring_active",
            "recommended_follow_up": "monitor_until_stable",
            "suggested_mode": "hybrid",
            "priority_hint": "warning",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {
            "intervention_status": "monitor",
            "intervention_required": "unknown",
            "intervention_priority": "warning",
            "intervention_reason": "recovery_policy_monitoring_active",
            "preferred_operator_action_hint": "monitor until stable",
            "suggested_mode": "hybrid",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {
            "stability_status": "transitioning",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention is transitioning and currently in monitor.",
            "stability_action_hint": "monitor until stable",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_label": "Transitioning intervention",
            "guidance_priority": "warning",
            "guidance_message": "Transitioning intervention: monitor until stable before resuming aggressive intervention.",
            "preferred_action_hint": "monitor until stable before resuming aggressive intervention",
            "suggested_mode": "hybrid",
            "intervention_status": "monitor",
            "stability_status": "transitioning",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-intervention-required-runtime",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    intervention_line = next(line for line in captured.err.splitlines() if line.startswith("[OPERATOR] Intervention status:"))
    assert "required=True" not in intervention_line
    assert "required=" not in intervention_line
    assert "[OPERATOR] Operator escalation:" not in captured.err
    stdout_payload = json.loads(captured.out)
    assert "operator_escalation_source" not in stdout_payload
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("intervention_required") is None
    assert runtime_summary.get("operator_escalation_source") is None


def test_build_next_task_request_url_uses_collection_seed_endpoint():
    url = run_hybrid_seed_collection.build_next_task_request_url(
        "http://127.0.0.1:8001/api",
        session_id="runner-a",
    )

    parsed = urlparse(url)
    assert parsed.path == "/api/collection/seeds/next_task"
    assert parse_qs(parsed.query) == {"session_id": ["runner-a"]}


def test_build_browser_fallback_url_adds_sniff_worker_mode():
    url = run_hybrid_seed_collection.build_browser_fallback_url(
        "https://sf.taobao.com/list/50025969__2.htm?location_code=110101&page=1"
    )

    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "sf.taobao.com"
    assert parse_qs(parsed.query)["uni_mode"] == ["SNIFF_WORKER"]
    assert parse_qs(parsed.query)["location_code"] == ["110101"]


def test_claim_next_seed_task_uses_http_endpoint():
    session = _FakeHttpSession({"task": {"url": "https://sf.taobao.com/x"}, "message": "ok"})

    payload = run_hybrid_seed_collection.claim_next_seed_task(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        http_session=session,
    )

    assert payload == {"task": {"url": "https://sf.taobao.com/x"}, "message": "ok"}
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/collection/seeds/next_task?session_id=runner-a",
            "timeout": 30,
        }
    ]


def test_run_once_returns_idle_when_no_task_is_available():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": None, "message": "所有嗅探任务已完成"},
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "idle",
        "message": "所有嗅探任务已完成",
        "task": None,
    }


def test_run_once_omits_unknown_idle_message():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": None, "message": " unknown "},
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "idle",
        "message": None,
        "task": None,
    }
    assert "unknown" not in json.dumps(result)


def test_run_once_treats_whitespace_unknown_task_url_as_idle():
    calls = {"export": 0, "hybrid": 0}

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": " unknown ", "page": "unknown"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: calls.__setitem__("export", calls["export"] + 1),
        hybrid_collect_fn=lambda *_args, **_kwargs: calls.__setitem__("hybrid", calls["hybrid"] + 1),
    )

    assert result == {
        "decision": "idle",
        "message": "ok",
        "task": {"url": None, "page": None},
    }
    assert calls == {"export": 0, "hybrid": 0}
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_malformed_task_payload():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": " unknown ", "message": "ok"},
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "idle",
        "message": "ok",
        "task": {},
    }
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_task_metadata():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {
            "task": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "page": 1,
                "source": " unknown ",
            },
            "message": "ok",
        },
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "browserless_success", "reason": None},
    )

    assert result["task"]["source"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_returns_api_unavailable_when_dispatch_endpoint_is_down():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: (_ for _ in ()).throw(requests.exceptions.ConnectionError("boom")),
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "api_unavailable",
        "reason": "dispatch_endpoint_unreachable",
        "error": "boom",
    }


def test_run_once_omits_unknown_api_error_message():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: (_ for _ in ()).throw(requests.exceptions.ConnectionError(" unknown ")),
        export_cookies_fn=lambda *_args, **_kwargs: [],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "should_not_run"},
    )

    assert result == {
        "decision": "api_unavailable",
        "reason": "dispatch_endpoint_unreachable",
        "error": None,
    }
    assert "unknown" not in json.dumps(result)


def test_run_once_executes_browserless_collection_when_task_is_available():
    calls = {}

    def _hybrid_collect(url: str, *, cookies, submit: bool, api_base: str):
        calls["url"] = url
        calls["cookies"] = cookies
        calls["submit"] = submit
        calls["api_base"] = api_base
        return {"decision": "browserless_success", "reason": None}

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=_hybrid_collect,
    )

    assert result["decision"] == "browserless_success"
    assert result["task"]["url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert calls == {
        "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        "cookies": [{"name": "cookie2", "value": "abc"}],
        "submit": True,
        "api_base": "http://127.0.0.1:8001/api",
    }


def test_run_once_treats_malformed_collection_result_as_missing():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: "unknown",
    )

    assert result["decision"] is None
    assert result["reason"] is None
    assert result["collection_result"] == {}
    assert result["task"]["url"] == "https://sf.taobao.com/list/50025969__2.htm?page=1"
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_collection_decision_and_reason():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": " unknown ",
            "reason": " unknown ",
        },
    )

    assert result["decision"] is None
    assert result["reason"] is None
    assert result["collection_result"] == {"decision": None, "reason": None}
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_collection_error_message():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "error": " unknown ",
            "message": " unknown ",
        },
    )

    assert result["collection_result"]["error"] is None
    assert result["collection_result"]["message"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_collection_cookie_count():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "cookie_count": "unknown",
        },
    )

    assert result["collection_result"]["cookie_count"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_probe_summary_url_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "final_url": " unknown ",
                "first_urls": [" unknown ", "https://sf.taobao.com/item/1"],
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["final_url"] is None
    assert probe_summary["first_urls"] == [None, "https://sf.taobao.com/item/1"]
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_probe_summary_first_ids():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "first_ids": [" unknown ", "12345"],
            },
        },
    )

    assert result["collection_result"]["probe_summary"]["first_ids"] == [None, "12345"]
    assert "unknown" not in json.dumps(result)


def test_run_once_treats_unknown_probe_summary_list_fields_as_empty():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "first_ids": "unknown",
                "first_urls": "unknown",
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["first_ids"] == []
    assert probe_summary["first_urls"] == []
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_malformed_probe_summary_list_elements():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "first_ids": [True, 123, 123.5, " unknown ", float("nan"), {"bad": "id"}],
                "first_urls": [False, 123, " https://sf.taobao.com/item/1 "],
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["first_ids"] == [None, 123, None, None, None, None]
    assert probe_summary["first_urls"] == [None, None, "https://sf.taobao.com/item/1"]


def test_run_once_omits_unknown_probe_summary_scalar_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "status": " unknown ",
                "item_count": "unknown",
                "cookie_count": "unknown",
                "has_script": "unknown",
                "body_has_login": "unknown",
                "body_has_captcha": "unknown",
                "body_has_punish": "unknown",
                "body_has_challenge": "unknown",
                "body_snippet": " unknown ",
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None
    assert probe_summary["has_script"] is None
    assert probe_summary["body_has_login"] is None
    assert probe_summary["body_has_captcha"] is None
    assert probe_summary["body_has_punish"] is None
    assert probe_summary["body_has_challenge"] is None
    assert probe_summary["body_snippet"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_non_finite_probe_summary_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "status": float("inf"),
                "item_count": float("-inf"),
                "cookie_count": float("nan"),
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None


def test_run_once_omits_fractional_probe_summary_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "status": 200.5,
                "item_count": 2.5,
                "cookie_count": 1.5,
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None


def test_run_once_omits_decimal_fractional_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "cookie_count": Decimal("4.5"),
            "probe_summary": {
                "status": Decimal("200.5"),
                "item_count": Decimal("2.5"),
                "cookie_count": Decimal("1.5"),
            },
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "bidCount": Decimal("1.5"), "auction_round": Decimal("2.5")}],
            },
            "progress_payload": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "page_num": Decimal("1.5"),
                "total_pages": Decimal("2.5"),
            },
            "submit_result": {
                "batch": {"status": "ok", "new": Decimal("3.5")},
            },
        },
    )

    collection_result = result["collection_result"]
    probe_summary = collection_result["probe_summary"]
    assert collection_result["cookie_count"] is None
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None
    item = collection_result["batch_payload"]["items"][0]
    assert item["bidCount"] is None
    assert item["auction_round"] is None
    assert collection_result["progress_payload"]["page_num"] is None
    assert collection_result["progress_payload"]["total_pages"] is None
    assert collection_result["submit_result"]["batch"]["new"] is None


def test_run_once_omits_non_finite_probe_summary_bool_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "has_script": float("nan"),
                "body_has_login": float("inf"),
                "body_has_captcha": float("-inf"),
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["has_script"] is None
    assert probe_summary["body_has_login"] is None
    assert probe_summary["body_has_captcha"] is None


def test_run_once_omits_ambiguous_numeric_probe_summary_bool_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "has_script": 2,
                "body_has_login": -1,
                "body_has_captcha": 0.5,
                "body_has_punish": 1,
                "body_has_challenge": 0,
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["has_script"] is None
    assert probe_summary["body_has_login"] is None
    assert probe_summary["body_has_captcha"] is None
    assert probe_summary["body_has_punish"] is True
    assert probe_summary["body_has_challenge"] is False


def test_run_once_normalizes_decimal_bool_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "has_script": Decimal("1"),
                "body_has_login": Decimal("0"),
                "body_has_captcha": Decimal("0.5"),
            },
            "progress_payload": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "has_next": Decimal("1"),
                "is_empty": Decimal("0"),
                "zero_bid_detected": Decimal("2"),
            },
            "submit_result": {"progress": {"status": "ok", "updated": Decimal("1")}},
        },
    )

    collection_result = result["collection_result"]
    probe_summary = collection_result["probe_summary"]
    assert probe_summary["has_script"] is True
    assert probe_summary["body_has_login"] is False
    assert probe_summary["body_has_captcha"] is None
    progress_payload = collection_result["progress_payload"]
    assert progress_payload["has_next"] is True
    assert progress_payload["is_empty"] is False
    assert progress_payload["zero_bid_detected"] is None
    assert collection_result["submit_result"]["progress"]["updated"] is True


def test_run_once_omits_unknown_probe_summary_nested_batch_payload_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {
                "batch_payload": {
                    "source_page_url": " unknown ",
                    "items": "unknown",
                },
            },
        },
    )

    batch_payload = result["collection_result"]["probe_summary"]["batch_payload"]
    assert batch_payload["source_page_url"] is None
    assert batch_payload["items"] == []
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_submit_result_status_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "submit_result": {
                "batch": {
                    "status": " unknown ",
                    "message": " unknown ",
                    "error": " unknown ",
                },
                "progress": {
                    "status": "ok",
                    "message": "done",
                    "error": " unknown ",
                },
            },
        },
    )

    submit_result = result["collection_result"]["submit_result"]
    assert submit_result["batch"]["status"] is None
    assert submit_result["batch"]["message"] is None
    assert submit_result["batch"]["error"] is None
    assert submit_result["progress"]["status"] == "ok"
    assert submit_result["progress"]["message"] == "done"
    assert submit_result["progress"]["error"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_submit_result_typed_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "submit_result": {
                "batch": {"status": "ok", "new": "unknown"},
                "progress": {"status": "ok", "updated": "unknown"},
            },
        },
    )

    submit_result = result["collection_result"]["submit_result"]
    assert submit_result["batch"]["new"] is None
    assert submit_result["progress"]["updated"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_collection_progress_payload_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {"source_page_url": " unknown ", "items": []},
            "progress_payload": {
                "url": " unknown ",
                "page_num": "unknown",
                "total_pages": "unknown",
                "has_next": "unknown",
            },
        },
    )

    collection_result = result["collection_result"]
    assert collection_result["batch_payload"]["source_page_url"] is None
    assert collection_result["progress_payload"]["url"] is None
    assert collection_result["progress_payload"]["page_num"] is None
    assert collection_result["progress_payload"]["total_pages"] is None
    assert collection_result["progress_payload"]["has_next"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_batch_payload_url_alias_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": " unknown ",
                "page_url": " unknown ",
                "url": " unknown ",
                "items": [],
            },
        },
    )

    batch_payload = result["collection_result"]["batch_payload"]
    assert batch_payload["source_page_url"] is None
    assert batch_payload["page_url"] is None
    assert batch_payload["url"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_treats_unknown_batch_payload_items_as_empty():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": "unknown",
            },
        },
    )

    assert result["collection_result"]["batch_payload"]["items"] == []
    assert "unknown" not in json.dumps(result)


def test_run_once_omits_unknown_batch_payload_item_metadata_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    "unknown",
                    {
                        "id": "unknown",
                        "title": " unknown ",
                        "source_title": " unknown ",
                        "url": " unknown ",
                        "status": " unknown ",
                        "location": " unknown ",
                        "full_address": " unknown ",
                        "city": " unknown ",
                        "district": " unknown ",
                        "currentPrice": "unknown",
                        "initialPrice": "unknown",
                        "transaction_price": "unknown",
                        "starting_price": "unknown",
                        "deposit": "unknown",
                        "auction_date": " unknown ",
                        "auction_start_time": " unknown ",
                        "startTime": " unknown ",
                        "end": " unknown ",
                        "bidCount": "unknown",
                        "bid_count": "unknown",
                        "bidderCount": "unknown",
                        "bidder_count": "unknown",
                        "applyCount": "unknown",
                        "apply_count": "unknown",
                        "watchCount": "unknown",
                        "watch_count": "unknown",
                        "remindCount": "unknown",
                        "reminder_count": "unknown",
                        "viewCount": "unknown",
                        "view_count": "unknown",
                        "latitude": "unknown",
                        "longitude": "unknown",
                        "coordinate_source": "unknown",
                        "auction_round": " unknown ",
                        "housing_type": " unknown ",
                        "source_page_url": " unknown ",
                        "page_url": " unknown ",
                        "source_url": " unknown ",
                        "source_platform": " unknown ",
                        "source_item_id": "unknown",
                        "list_payload_path": " unknown ",
                        "is_processed": "unknown",
                    },
                ],
            },
        },
    )

    items = result["collection_result"]["batch_payload"]["items"]
    assert items[0] == {}
    assert items[1]["id"] is None
    assert items[1]["title"] is None
    assert items[1]["source_title"] is None
    assert items[1]["url"] is None
    assert items[1]["status"] is None
    assert items[1]["location"] is None
    assert items[1]["full_address"] is None
    assert items[1]["city"] is None
    assert items[1]["district"] is None
    assert items[1]["currentPrice"] is None
    assert items[1]["initialPrice"] is None
    assert items[1]["transaction_price"] is None
    assert items[1]["starting_price"] is None
    assert items[1]["deposit"] is None
    assert items[1]["auction_date"] is None
    assert items[1]["auction_start_time"] is None
    assert items[1]["startTime"] is None
    assert items[1]["end"] is None
    assert items[1]["bidCount"] is None
    assert items[1]["bid_count"] is None
    assert items[1]["bidderCount"] is None
    assert items[1]["bidder_count"] is None
    assert items[1]["applyCount"] is None
    assert items[1]["apply_count"] is None
    assert items[1]["watchCount"] is None
    assert items[1]["watch_count"] is None
    assert items[1]["remindCount"] is None
    assert items[1]["reminder_count"] is None
    assert items[1]["viewCount"] is None
    assert items[1]["view_count"] is None
    assert items[1]["latitude"] is None
    assert items[1]["longitude"] is None
    assert items[1]["coordinate_source"] is None
    assert items[1]["auction_round"] is None
    assert items[1]["housing_type"] is None
    assert items[1]["source_page_url"] is None
    assert items[1]["page_url"] is None
    assert items[1]["source_url"] is None
    assert items[1]["source_platform"] is None
    assert items[1]["source_item_id"] is None
    assert items[1]["list_payload_path"] is None
    assert items[1]["is_processed"] is None
    assert "unknown" not in json.dumps(result)


def test_run_once_preserves_batch_payload_item_numeric_auction_round():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "auction_round": 2}],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["auction_round"] == 2


def test_run_once_preserves_batch_payload_item_text_auction_round():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "auction_round": "first_round"}],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["auction_round"] == "first_round"


def test_run_once_omits_fractional_batch_payload_item_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "bidCount": 1.5, "auction_round": 2.5}],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["bidCount"] is None
    assert item["auction_round"] is None


def test_run_once_omits_bool_batch_payload_item_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    {
                        "id": "item-1",
                        "bidCount": True,
                        "auction_round": True,
                        "latitude": True,
                        "longitude": False,
                    }
                ],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["bidCount"] is None
    assert item["auction_round"] is None
    assert item["latitude"] is None
    assert item["longitude"] is None


def test_run_once_omits_bool_batch_payload_item_identifier_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    {"id": True, "source_item_id": False},
                    {"id": float("nan"), "source_item_id": {"bad": "id"}},
                ],
            },
        },
    )

    items = result["collection_result"]["batch_payload"]["items"]
    assert items[0]["id"] is None
    assert items[0]["source_item_id"] is None
    assert items[1]["id"] is None
    assert items[1]["source_item_id"] is None


def test_run_once_omits_negative_numeric_identifier_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {"first_ids": [-1, "-2", 3]},
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": -1, "source_item_id": -2}],
            },
        },
    )

    collection_result = result["collection_result"]
    assert collection_result["probe_summary"]["first_ids"] == [None, "-2", 3]
    item = collection_result["batch_payload"]["items"][0]
    assert item["id"] is None
    assert item["source_item_id"] is None


def test_run_once_normalizes_decimal_identifier_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {"first_ids": [Decimal("123"), Decimal("123.5"), Decimal("-1")]},
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    {"id": Decimal("123"), "source_item_id": Decimal("456")},
                    {"id": Decimal("123.5"), "source_item_id": Decimal("-1")},
                ],
            },
        },
    )

    collection_result = result["collection_result"]
    assert collection_result["probe_summary"]["first_ids"] == [123, None, None]
    items = collection_result["batch_payload"]["items"]
    assert items[0]["id"] == 123
    assert items[0]["source_item_id"] == 456
    assert items[1]["id"] is None
    assert items[1]["source_item_id"] is None


def test_run_once_returns_browser_fallback_and_can_open_browser():
    opened: list[tuple[str, Path, int]] = []

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "browser_fallback_required", "reason": "challenge_detected"},
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["reason"] == "challenge_detected"
    assert result["fallback_url"].startswith("https://sf.taobao.com/list/50025969__2.htm?page=1")
    assert "uni_mode=SNIFF_WORKER" in result["fallback_url"]
    assert result["browser_fallback_opened"] is True
    assert opened == [
        (
            result["fallback_url"],
            Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
            9223,
        )
    ]


def test_run_once_treats_whitespace_unknown_mode_as_default_hybrid_for_browser_fallback():
    opened: list[tuple[str, Path, int]] = []

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode=" unknown ",
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browser_fallback_required",
            "reason": "challenge_detected",
        },
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["browser_fallback_opened"] is True
    assert opened == [
        (
            result["fallback_url"],
            Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
            9223,
        )
    ]


def test_run_once_browser_mode_opens_worker_without_browserless_probe():
    opened: list[tuple[str, Path, int]] = []
    calls = {"export": 0, "hybrid": 0}

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="browser",
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: calls.__setitem__("export", calls["export"] + 1),
        hybrid_collect_fn=lambda *_args, **_kwargs: calls.__setitem__("hybrid", calls["hybrid"] + 1),
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_worker_dispatched"
    assert result["fallback_url"].startswith("https://sf.taobao.com/list/50025969__2.htm?page=1")
    assert "uni_mode=SNIFF_WORKER" in result["fallback_url"]
    assert result["browser_fallback_opened"] is True
    assert calls == {"export": 0, "hybrid": 0}
    assert opened == [
        (
            result["fallback_url"],
            Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
            9223,
        )
    ]


def test_run_once_browserless_mode_does_not_open_browser_on_fallback():
    opened: list[tuple[str, Path, int]] = []

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="browserless",
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "browser_fallback_required", "reason": "challenge_detected"},
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["reason"] == "challenge_detected"
    assert result["browser_fallback_opened"] is False
    assert opened == []


def test_run_loop_continues_through_success_idle_and_fallback_results():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "idle", "message": "no task", "task": None},
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/b"},
                "fallback_url": "https://sf.taobao.com/list/b?uni_mode=SNIFF_WORKER",
                "browser_fallback_opened": True,
            },
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=3,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 3
    assert summary["counts"] == {
        "browserless_success": 1,
        "idle": 1,
        "browser_fallback_required": 1,
    }
    assert len(summary["results"]) == 3
    assert sleeps == [7, 11]


def test_run_loop_treats_unknown_result_as_missing():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-unknown-result",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        run_once_fn=lambda **_: "unknown",
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {}
    assert summary["results"][0].get("decision") is None
    assert summary["results"][0].get("task") is None


def test_run_loop_omits_whitespace_unknown_result_and_guidance_fields(monkeypatch):
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "guidance_applied": "unknown",
            "recovery_policy_applied": "unknown",
            "guidance_status": " unknown ",
            "recovery_policy_status": " unknown ",
            "recovery_policy_priority": " unknown ",
            "recovery_policy_mode_pin_active": "unknown",
            "guidance": {
                "recommended_mode": " unknown ",
                "top_guidance_reason": " unknown ",
            },
            "recovery_policy": {
                "effective_recommended_mode": " unknown ",
                "top_policy_reason": " unknown ",
            },
        },
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-whitespace-placeholder-fields",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        run_once_fn=lambda **_: {
            "decision": " unknown ",
            "reason": " unknown ",
            "fallback_url": " unknown ",
            "browser_fallback_opened": "unknown",
            "task": {"url": " unknown ", "page": "unknown"},
            "collection_result": {"submit_result": "unknown"},
        },
        sleep_fn=lambda *_args: None,
    )

    result = summary["results"][0]
    assert summary["counts"] == {}
    assert summary["reason_counts"] == {}
    assert summary["effective_mode_counts"] == {}
    assert summary["guidance_status_counts"] == {}
    assert result.get("decision") is None
    assert result.get("reason") is None
    assert result.get("fallback_url") is None
    assert result.get("requested_mode") == "hybrid"
    assert result.get("effective_mode") is None
    assert result.get("effective_mode_source") is None
    assert result.get("guidance_status") is None
    assert result.get("guidance_recommended_mode") is None
    assert result.get("top_guidance_reason") is None
    assert result.get("top_policy_reason") is None
    assert result.get("recovery_policy_status") is None
    assert result.get("recovery_policy_priority") is None
    assert result.get("recovery_policy_mode_pin_active") is None
    assert result.get("recovery_policy_effective_recommended_mode") is None
    assert result.get("task") == {"url": None, "page": None}
    assert result.get("collection_result") == {"submit_result": {}}
    assert "unknown" not in json.dumps(result)


def test_run_loop_omits_unknown_idle_message():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-idle-message",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        run_once_fn=lambda **_: {
            "decision": "idle",
            "message": " unknown ",
            "task": None,
        },
        sleep_fn=lambda *_args: None,
    )

    result = summary["results"][0]
    assert result["message"] is None
    assert "unknown" not in json.dumps(result)


def test_run_loop_tracks_reason_counts_and_escalates_after_consecutive_fallbacks():
    results = iter(
        [
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/a"},
            },
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/b"},
            },
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/c"},
            },
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        fallback_sleep_seconds=13,
        max_consecutive_fallbacks=2,
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 2
    assert summary["counts"] == {"browser_fallback_required": 2}
    assert summary["reason_counts"] == {"challenge_detected": 2}
    assert summary["termination_reason"] == "fallback_escalation_threshold_reached"
    assert sleeps == [13]


def test_run_loop_passes_mode_through_to_default_run_once():
    recorded: list[str] = []

    def _run_once(**kwargs):
        recorded.append(kwargs["mode"])
        return {"decision": "idle", "task": None, "message": "done"}

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="browser",
        max_runs=1,
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert recorded == ["browser"]


def test_run_loop_treats_whitespace_unknown_mode_as_default_hybrid():
    recorded: list[str] = []

    def _run_once(**kwargs):
        recorded.append(kwargs["mode"])
        return {"decision": "idle", "task": None, "message": "done"}

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode=" unknown ",
        max_runs=1,
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert recorded == [run_hybrid_seed_collection.DEFAULT_MODE]
    assert summary["results"][0]["requested_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert summary["results"][0]["effective_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert "unknown" not in json.dumps(summary)


def test_run_loop_treats_unknown_mode_resolution_as_default_hybrid(monkeypatch):
    recorded: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **_kwargs: {
            "requested_mode": " unknown ",
            "effective_mode": " unknown ",
            "effective_mode_source": " unknown ",
            "guidance_applied": "unknown",
            "guidance_status": " unknown ",
            "guidance": {},
            "recovery_policy": {},
        },
    )

    def _run_once(**kwargs):
        recorded.append(kwargs["mode"])
        return {"decision": "idle", "task": None, "message": "done"}

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode=" unknown ",
        max_runs=1,
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert recorded == [run_hybrid_seed_collection.DEFAULT_MODE]
    assert summary["results"][0]["requested_mode"] == run_hybrid_seed_collection.DEFAULT_MODE
    assert summary["results"][0]["effective_mode"] is None
    assert summary["results"][0]["effective_mode_source"] is None
    assert "unknown" not in json.dumps(summary)


def test_run_loop_can_reload_operator_guidance_and_switch_effective_mode():
    recorded_modes: list[str] = []
    guidances = iter(
        [
            {"guidance_status": "keep_hybrid", "recommended_mode": "hybrid"},
            {"guidance_status": "prefer_browser_fallback", "recommended_mode": "browser"},
        ]
    )
    results = iter(
        [
            {"decision": "idle", "task": None, "message": "round-1"},
            {"decision": "browser_worker_dispatched", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )

    def _run_once(**kwargs):
        recorded_modes.append(kwargs["mode"])
        return next(results)

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        mode="hybrid",
        max_runs=2,
        respect_operator_guidance=True,
        load_guidance_fn=lambda *_args, **_kwargs: next(guidances),
        load_recovery_policy_fn=lambda *_args, **_kwargs: {},
        run_once_fn=_run_once,
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 2
    assert recorded_modes == ["hybrid", "browser"]
    assert summary["effective_mode_counts"] == {"hybrid": 1, "browser": 1}
    assert summary["guidance_applied_count"] == 1
    assert summary["guidance_status_counts"] == {
        "keep_hybrid": 1,
        "prefer_browser_fallback": 1,
    }
    assert summary["results"][0]["effective_mode"] == "hybrid"
    assert summary["results"][1]["effective_mode"] == "browser"
    assert summary["results"][1]["guidance_applied"] is True


def test_run_loop_stops_when_stop_on_fallback_is_requested():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {"url": "https://sf.taobao.com/list/b"},
                "fallback_url": "https://sf.taobao.com/list/b?uni_mode=SNIFF_WORKER",
                "browser_fallback_opened": True,
            },
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/c"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_fallback=True,
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 2
    assert summary["counts"] == {
        "browserless_success": 1,
        "browser_fallback_required": 1,
    }
    assert len(summary["results"]) == 2
    assert sleeps == [7]


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {
                "decision": "browser_worker_dispatched",
                "task": {"url": "https://sf.taobao.com/list/b"},
                "recovery_policy_status": "escalate_repeated_repin",
                "recovery_policy_priority": "high",
                "recovery_policy_effective_recommended_mode": "browser",
                "top_policy_reason": "repeated_repin_cycle_detected",
            },
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/c"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        load_guidance_fn=lambda *_args, **_kwargs: {
            "guidance_status": "monitor_hybrid_runtime",
            "recommended_mode": "hybrid",
            "top_guidance_reason": "mixed_runtime_signals",
        },
        load_recovery_policy_fn=lambda *_args, **_kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "recovery_policy"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "recovery_policy"
    assert sleeps == []


def test_run_loop_omits_mixed_case_unknown_operator_escalation_audit_message(monkeypatch):
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "operator_escalation_audit_message",
        lambda *args, **kwargs: " Unknown ",
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-placeholder-audit",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        load_guidance_fn=lambda *_args, **_kwargs: {},
        load_recovery_policy_fn=lambda *_args, **_kwargs: {
            "policy_status": "escalate_repeated_repin",
            "priority": "high",
            "effective_recommended_mode": "browser",
            "mode_pin_active": True,
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
        run_once_fn=lambda **_: {
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/a"},
        },
        sleep_fn=lambda *_args: None,
    )

    assert summary["termination_reason"] == "operator_escalation"
    result = summary["results"][0]
    assert result.get("operator_escalation_source") == "recovery_policy"
    assert result.get("operator_escalation_audit_message") is None
    assert summary.get("operator_escalation_audit_message") is None


def test_run_loop_reuses_single_status_snapshot_when_guidance_and_escalation_checks_are_enabled():
    session = _FakeHttpSession(
        {
            "collection_stage": {
                "hybrid_collection_strategy_guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "hybrid_collection_recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "priority": "high",
                    "top_policy_reason": "challenge_detected",
                },
                "hybrid_collection_lifecycle_state_summary": {
                    "lifecycle_state": "escalated",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_policy_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "hybrid_collection_operator_final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "suggested_mode": "browser",
                },
                "hybrid_collection_operator_digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "hybrid_collection_operator_digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "hybrid_collection_operator_escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "hybrid_collection_operator_escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        }
    )
    sleeps: list[float] = []

    original_session_factory = run_hybrid_seed_collection.requests.Session
    run_hybrid_seed_collection.requests.Session = lambda: session
    try:
        summary = run_hybrid_seed_collection.run_loop(
            api_base="http://127.0.0.1:8001/api",
            session_id="runner-loop-snapshot",
            cdp_endpoint="http://127.0.0.1:9223",
            submit=True,
            max_runs=10,
            idle_sleep_seconds=11,
            success_sleep_seconds=7,
            fallback_sleep_seconds=13,
            stop_on_operator_escalation=True,
            respect_operator_guidance=True,
            run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            sleep_fn=sleeps.append,
        )
    finally:
        run_hybrid_seed_collection.requests.Session = original_session_factory

    assert summary["termination_reason"] == "operator_escalation"
    assert session.calls == [
        {
            "url": "http://127.0.0.1:8001/api/status",
            "timeout": 30,
        }
    ]
    assert sleeps == []


def test_run_loop_can_use_operator_status_bundle_when_default_status_loads_are_active():
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-bundle",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: (
            bundle_calls.append("called")
            or {
                "guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "priority": "high",
                    "top_policy_reason": "challenge_detected",
                },
                "lifecycle_summary": {
                    "lifecycle_state": "escalated",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                    "suggested_mode": "browser",
                },
                "intervention_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "suggested_mode": "browser",
                },
                "digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        ),
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "operator_escalation"
    assert bundle_calls == ["called"]
    assert sleeps == []


def test_run_loop_treats_unknown_operator_status_bundle_nested_summaries_as_missing():
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-bundle-unknown",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        respect_operator_guidance=True,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: (
            bundle_calls.append("called")
            or {
                "guidance": "unknown",
                "recovery_policy": "unknown",
                "lifecycle_summary": "unknown",
                "intervention_summary": "unknown",
                "intervention_stability_summary": "unknown",
                "final_guidance_summary": "unknown",
                "digest_summary": "unknown",
                "digest_stability_summary": "unknown",
                "escalation_event_trend_summary": "unknown",
                "escalation_event_stability_summary": "unknown",
            }
        ),
        load_guidance_fn=lambda *args, **kwargs: {},
        load_recovery_policy_fn=lambda *args, **kwargs: {},
        load_lifecycle_summary_fn=lambda *args, **kwargs: {},
        load_intervention_summary_fn=lambda *args, **kwargs: {},
        load_stability_summary_fn=lambda *args, **kwargs: {},
        load_final_guidance_summary_fn=lambda *args, **kwargs: {},
        load_digest_summary_fn=lambda *args, **kwargs: {},
        load_digest_stability_summary_fn=lambda *args, **kwargs: {},
        load_escalation_event_trend_summary_fn=lambda *args, **kwargs: {},
        load_escalation_event_stability_summary_fn=lambda *args, **kwargs: {},
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert bundle_calls == ["called"]
    assert sleeps == []


def test_run_loop_omits_whitespace_unknown_operator_status_bundle_fields():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-bundle-whitespace-placeholder",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {
            "escalation_event_trend_summary": {
                "current_operator_escalation_source": " unknown ",
                "previous_distinct_operator_escalation_source": " unknown ",
                "recent_source_change_count": "unknown",
                "last_source_change_at": " unknown ",
            },
            "escalation_event_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "current_operator_escalation_source": " unknown ",
                "previous_operator_escalation_source": " unknown ",
                "recent_source_change_count": "unknown",
                "operator_readable_explanation": " unknown ",
            },
            "digest_stability_summary": {
                "stability_status": " unknown ",
                "stability_severity": " unknown ",
                "operator_readable_explanation": " unknown ",
            },
        },
        run_once_fn=lambda **_: {
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/a"},
        },
        sleep_fn=lambda *_args: None,
    )

    result = summary["results"][0]
    assert result.get("operator_digest_stability_status") is None
    assert result.get("operator_digest_stability_severity") is None
    assert result.get("operator_digest_stability_explanation") is None
    assert result.get("operator_escalation_current_source") is None
    assert result.get("operator_escalation_previous_source") is None
    assert result.get("operator_escalation_source_last_changed_at") is None
    assert result.get("operator_escalation_source_stability_status") is None
    assert result.get("operator_escalation_source_stability_severity") is None
    assert result.get("operator_escalation_source_stability_explanation") is None
    assert result.get("operator_escalation_source") is None
    assert "unknown" not in json.dumps(result)


def test_run_loop_omits_whitespace_unknown_result_operator_escalation_source():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-result-whitespace-placeholder-source",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {},
        run_once_fn=lambda **_: {
            "decision": "browserless_success",
            "task": {"url": "https://sf.taobao.com/list/a"},
            "operator_escalation_source": " unknown ",
        },
        sleep_fn=lambda *_args: None,
    )

    assert summary["termination_reason"] == "max_runs_reached"
    result = summary["results"][0]
    assert result.get("operator_escalation_source") is None
    assert "unknown" not in json.dumps(result)


def test_run_loop_treats_unknown_nested_guidance_resolution_summaries_as_missing(monkeypatch):
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
            "guidance": "unknown",
            "recovery_policy": "unknown",
        },
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-guidance-resolution-unknown",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        respect_operator_guidance=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {},
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert summary["results"][0].get("guidance_recommended_mode") is None
    assert summary["results"][0].get("top_guidance_reason") is None
    assert summary["results"][0].get("top_policy_reason") is None
    assert summary["results"][0].get("recovery_policy_effective_recommended_mode") is None


def test_run_loop_treats_unknown_direct_status_loader_summaries_as_missing():
    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-direct-status-unknown",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        stop_on_operator_escalation=True,
        load_operator_status_bundle_fn=lambda *args, **kwargs: {},
        load_lifecycle_summary_fn=lambda *args, **kwargs: "unknown",
        load_intervention_summary_fn=lambda *args, **kwargs: "unknown",
        load_stability_summary_fn=lambda *args, **kwargs: "unknown",
        load_final_guidance_summary_fn=lambda *args, **kwargs: "unknown",
        load_digest_summary_fn=lambda *args, **kwargs: "unknown",
        load_digest_stability_summary_fn=lambda *args, **kwargs: "unknown",
        load_escalation_event_trend_summary_fn=lambda *args, **kwargs: "unknown",
        load_escalation_event_stability_summary_fn=lambda *args, **kwargs: "unknown",
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=lambda *_args: None,
    )

    assert summary["iterations"] == 1
    assert summary["termination_reason"] == "max_runs_reached"
    assert summary.get("operator_escalation_source") is None
    assert summary.get("operator_digest_status") is None


def test_run_loop_uses_default_operator_status_bundle_when_default_loaders_are_active(monkeypatch):
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: (
            bundle_calls.append("called")
            or {
                "guidance": {
                    "guidance_status": "prefer_browser_fallback",
                    "recommended_mode": "browser",
                    "top_guidance_reason": "challenge_detected",
                },
                "recovery_policy": {
                    "policy_status": "pin_browser_mode_temporarily",
                    "effective_recommended_mode": "browser",
                    "mode_pin_active": True,
                    "priority": "high",
                    "top_policy_reason": "challenge_detected",
                },
                "lifecycle_summary": {
                    "lifecycle_state": "escalated",
                    "priority_hint": "non_high_priority_backlog_present",
                    "active_unresolved_priority": "warning",
                    "active_high_priority_unresolved_count": 0,
                    "suggested_mode": "browser",
                },
                "intervention_summary": {
                    "intervention_status": "intervention_required",
                    "intervention_required": True,
                    "intervention_priority": "warning",
                    "intervention_reason": "unresolved_escalation_window_open",
                    "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
                    "suggested_mode": "browser",
                },
                "intervention_stability_summary": {
                    "stability_status": "escalating",
                    "stability_severity": "high",
                    "current_intervention_status": "intervention_required",
                    "previous_intervention_status": "ready",
                    "recent_change_count": 1,
                    "last_change_at": "2026-05-18 18:12:00",
                    "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
                },
                "final_guidance_summary": {
                    "guidance_label": "Escalating intervention",
                    "guidance_priority": "high",
                    "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                    "suggested_mode": "browser",
                },
                "digest_summary": {
                    "digest_status": "intervention_required",
                    "digest_priority": "high",
                    "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
                },
                "digest_stability_summary": {
                    "stability_status": "digest_recently_shifted",
                    "stability_severity": "high",
                    "current_digest_status": "intervention_required",
                    "previous_digest_status": "ready",
                    "recent_change_count": 1,
                    "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
                },
                "escalation_event_trend_summary": {
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_distinct_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
                },
                "escalation_event_stability_summary": {
                    "stability_status": "source_recently_shifted",
                    "stability_severity": "high",
                    "current_operator_escalation_source": "intervention_stability",
                    "previous_operator_escalation_source": "recovery_policy",
                    "recent_source_change_count": 1,
                    "last_source_change_at": "2026-05-18 18:24:00",
                    "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
                },
            }
        ),
    )

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-default-bundle",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        respect_operator_guidance=True,
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "operator_escalation"
    assert bundle_calls == ["called"]
    assert sleeps == []


def test_run_loop_skips_operator_status_bundle_when_status_dependent_features_are_disabled():
    sleeps: list[float] = []
    bundle_calls: list[str] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-no-status",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=1,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=False,
        respect_operator_guidance=False,
        load_operator_status_bundle_fn=lambda *args, **kwargs: (
            bundle_calls.append("called") or {"guidance": {"recommended_mode": "browser"}}
        ),
        run_once_fn=lambda **_: {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "max_runs_reached"
    assert bundle_calls == []
    assert sleeps == []


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_lifecycle_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 2,
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert sleeps == []


def test_run_loop_treats_non_dict_operator_escalation_last_result_as_missing():
    class _ResultLike:
        def __init__(self, payload):
            self.payload = dict(payload)

        def __contains__(self, key):
            return key in self.payload

        def __setitem__(self, key, value):
            self.payload[key] = value

        def get(self, key, default=None):
            return self.payload.get(key, default)

        def pop(self, key, default=None):
            return self.payload.pop(key, default)

    result = _ResultLike({"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}})
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-weird-operator-escalation-result",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "high_priority_backlog_present",
            "active_unresolved_priority": "high",
            "active_high_priority_unresolved_count": 2,
        },
        run_once_fn=lambda **_: result,
        sleep_fn=sleeps.append,
    )

    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "lifecycle_high_priority_backlog"
    assert summary["operator_escalation_audit_message"] == "Operator escalation [source=lifecycle_high_priority_backlog]"
    assert summary["operator_escalation_source_change_count"] is None
    assert sleeps == []


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_intervention_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "browser",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "intervention_policy"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "intervention_policy"
    assert summary["results"][0]["operator_action_hint"] == "prefer browser and investigate escalation; suggested mode=browser"
    assert sleeps == []


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_intervention_stability_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "browser",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        load_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        },
        load_final_guidance_summary_fn=lambda *_args, **_kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
        load_digest_summary_fn=lambda *_args, **_kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        load_digest_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
        },
        load_escalation_event_trend_summary_fn=lambda *_args, **_kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
        load_escalation_event_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": 1,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "intervention_stability"
    assert summary["operator_final_guidance_label"] == "Escalating intervention"
    assert summary["operator_final_guidance_priority"] == "high"
    assert summary["operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["operator_digest_status"] == "intervention_required"
    assert summary["operator_digest_priority"] == "high"
    assert summary["operator_digest_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["operator_digest_stability_status"] == "digest_recently_shifted"
    assert summary["operator_digest_stability_severity"] == "high"
    assert summary["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to intervention_required."
    assert summary["operator_escalation_current_source"] == "intervention_stability"
    assert summary["operator_escalation_previous_source"] == "recovery_policy"
    assert summary["operator_escalation_source_change_count"] == 1
    assert summary["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert summary["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert summary["operator_escalation_source_stability_severity"] == "high"
    assert summary["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    assert summary["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "intervention_stability"
    assert summary["results"][0]["operator_final_guidance_label"] == "Escalating intervention"
    assert summary["results"][0]["operator_final_guidance_priority"] == "high"
    assert summary["results"][0]["operator_final_guidance_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["results"][0]["operator_digest_status"] == "intervention_required"
    assert summary["results"][0]["operator_digest_priority"] == "high"
    assert summary["results"][0]["operator_digest_message"] == "Escalating intervention: prefer browser and investigate escalating intervention."
    assert summary["results"][0]["operator_digest_stability_status"] == "digest_recently_shifted"
    assert summary["results"][0]["operator_digest_stability_severity"] == "high"
    assert summary["results"][0]["operator_digest_stability_explanation"] == "Operator digest recently shifted from ready to intervention_required."
    assert summary["results"][0]["operator_escalation_current_source"] == "intervention_stability"
    assert summary["results"][0]["operator_escalation_previous_source"] == "recovery_policy"
    assert summary["results"][0]["operator_escalation_source_change_count"] == 1
    assert summary["results"][0]["operator_escalation_source_last_changed_at"] == "2026-05-18 18:24:00"
    assert summary["results"][0]["operator_escalation_source_stability_status"] == "source_recently_shifted"
    assert summary["results"][0]["operator_escalation_source_stability_severity"] == "high"
    assert summary["results"][0]["operator_escalation_source_stability_explanation"] == "Operator escalation source recently shifted from recovery_policy to intervention_stability."
    assert summary["results"][0]["operator_escalation_audit_message"] == (
        "Escalating intervention: prefer browser and investigate escalating intervention. "
        "[source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]"
    )
    assert sleeps == []


def test_run_loop_treats_negative_operator_escalation_source_change_count_as_missing():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop-negative-source-change",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "escalated",
            "priority_hint": "non_high_priority_backlog_present",
            "active_unresolved_priority": "warning",
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "browser",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "intervention_required",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "unresolved_escalation_window_open",
            "preferred_operator_action_hint": "prefer browser and investigate escalation; suggested mode=browser",
            "suggested_mode": "browser",
        },
        load_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "escalating",
            "stability_severity": "high",
            "current_intervention_status": "intervention_required",
            "previous_intervention_status": "ready",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Intervention escalated from ready to intervention_required recently.",
        },
        load_final_guidance_summary_fn=lambda *_args, **_kwargs: {
            "guidance_label": "Escalating intervention",
            "guidance_priority": "high",
            "guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "preferred_action_hint": "prefer browser and investigate escalating intervention",
            "suggested_mode": "browser",
            "intervention_status": "intervention_required",
            "stability_status": "escalating",
        },
        load_digest_summary_fn=lambda *_args, **_kwargs: {
            "digest_status": "intervention_required",
            "digest_priority": "high",
            "final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "final_guidance_stability_status": "guidance_recently_shifted",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
        load_digest_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "digest_recently_shifted",
            "stability_severity": "high",
            "current_digest_status": "intervention_required",
            "current_digest_priority": "high",
            "current_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "previous_digest_status": "ready",
            "previous_digest_message": "Stable ready state: keep hybrid and continue monitoring.",
            "recent_change_count": 1,
            "last_change_at": "2026-05-18 18:12:00",
            "operator_readable_explanation": "Operator digest recently shifted from ready to intervention_required.",
        },
        load_escalation_event_trend_summary_fn=lambda *_args, **_kwargs: {
            "current_operator_escalation_source": "intervention_stability",
            "previous_distinct_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:24:00",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
        },
        load_escalation_event_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "source_recently_shifted",
            "stability_severity": "high",
            "current_operator_escalation_source": "intervention_stability",
            "current_escalation_kind": "intervention_stability",
            "current_operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=intervention_stability, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "previous_operator_escalation_source": "recovery_policy",
            "recent_source_change_count": -3,
            "last_source_change_at": "2026-05-18 18:24:00",
            "operator_readable_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["operator_escalation_source_change_count"] == 0
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source_change_count"] == 0
    assert sleeps == []


def test_run_loop_stops_when_stop_on_operator_escalation_is_requested_from_flapping_intervention_stability_summary():
    results = iter(
        [
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/a"}},
            {"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/b"}},
        ]
    )
    sleeps: list[float] = []

    summary = run_hybrid_seed_collection.run_loop(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-loop",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        max_runs=10,
        idle_sleep_seconds=11,
        success_sleep_seconds=7,
        fallback_sleep_seconds=13,
        stop_on_operator_escalation=True,
        load_lifecycle_summary_fn=lambda *_args, **_kwargs: {
            "lifecycle_state": "monitor",
            "priority_hint": "no_active_priority_backlog",
            "active_unresolved_priority": None,
            "active_high_priority_unresolved_count": 0,
            "suggested_mode": "hybrid",
        },
        load_intervention_summary_fn=lambda *_args, **_kwargs: {
            "intervention_status": "monitor",
            "intervention_required": True,
            "intervention_priority": "warning",
            "intervention_reason": "conflicting_runtime_and_lifecycle_hints",
            "preferred_operator_action_hint": "monitor until stable; suggested mode=hybrid",
            "suggested_mode": "hybrid",
        },
        load_stability_summary_fn=lambda *_args, **_kwargs: {
            "stability_status": "flapping",
            "stability_severity": "warning",
            "current_intervention_status": "monitor",
            "previous_intervention_status": "intervention_required",
            "recent_change_count": 3,
            "last_change_at": "2026-05-18 18:18:00",
            "operator_readable_explanation": "Intervention status changed multiple times recently.",
        },
        run_once_fn=lambda **_: next(results),
        sleep_fn=sleeps.append,
    )

    assert summary["iterations"] == 1
    assert summary["counts"] == {
        "browserless_success": 1,
    }
    assert summary["termination_reason"] == "operator_escalation"
    assert summary["operator_escalation_source"] == "intervention_stability_flapping"
    assert len(summary["results"]) == 1
    assert summary["results"][0]["operator_escalation_source"] == "intervention_stability_flapping"
    assert summary["results"][0]["operator_action_hint"] == "monitor until stable; suggested mode=hybrid"
    assert sleeps == []


def test_run_hybrid_seed_collection_script_can_run_help_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "run_hybrid_seed_collection.py"), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    assert "browserless-first" in result.stdout
    assert "--loop" in result.stdout
    assert "--mode" in result.stdout


def test_main_persists_hybrid_runtime_summary_for_loop_runs(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    fake_result = {
        "mode": "loop",
        "iterations": 2,
        "counts": {
            "browserless_success": 1,
            "browser_fallback_required": 1,
        },
        "reason_counts": {"challenge_detected": 1},
        "termination_reason": "stop_on_fallback",
        "results": [
            {
                "decision": "browserless_success",
                "reason": None,
                "task": {
                    "url": "https://sf.taobao.com/list/50025969__2.htm?page=6",
                    "page": 6,
                    "location_code": "440112",
                    "category": "50025969",
                },
                "collection_result": {
                    "probe_summary": {
                        "item_count": 60,
                        "has_script": True,
                        "body_has_challenge": False,
                        "body_has_punish": False,
                    },
                    "submit_result": {
                        "batch": {"status": "ok", "new": 60},
                        "progress": {"status": "ok"},
                    },
                },
            },
            {
                "decision": "browser_fallback_required",
                "reason": "challenge_detected",
                "task": {
                    "url": "https://sf.taobao.com/list/50025969__2.htm?page=7",
                    "page": 7,
                    "location_code": "440112",
                    "category": "50025969",
                },
                "fallback_url": "https://sf.taobao.com/list/50025969__2.htm?page=7&uni_mode=SNIFF_WORKER",
                "browser_fallback_opened": True,
                "collection_result": {
                    "probe_summary": {
                        "item_count": 0,
                        "has_script": False,
                        "body_has_challenge": True,
                        "body_has_punish": True,
                    }
                },
            },
        ],
    }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_loop", lambda **kwargs: fake_result)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--loop",
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--session-id",
            "runner-loop",
            "--mode",
            "hybrid",
            "--submit",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["runner_mode"] == "hybrid"
    assert payload["loop_mode"] is True
    assert payload["submit_enabled"] is True
    assert payload["session_id"] == "runner-loop"
    assert payload["decision_counts"] == {
        "browserless_success": 1,
        "browser_fallback_required": 1,
    }
    assert payload["reason_counts"] == {"challenge_detected": 1}
    assert payload["termination_reason"] == "stop_on_fallback"
    assert payload["last_decision"] == "browser_fallback_required"
    assert payload["last_reason"] == "challenge_detected"
    assert payload["last_task"]["page"] == 7
    assert payload["last_probe_summary"]["body_has_challenge"] is True
    assert payload["last_browser_fallback_opened"] is True
    history_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 1
    history_payload = json.loads(history_lines[0])
    assert history_payload["runner_mode"] == "hybrid"
    assert history_payload["decision_counts"]["browserless_success"] == 1
    assert history_payload["decision_counts"]["browser_fallback_required"] == 1
    assert history_payload["top_fallback_reason"] == "challenge_detected"


def test_build_runtime_summary_omits_unknown_collection_nested_payloads():
    summary = run_hybrid_seed_collection.build_runtime_summary(
        result={
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=7", "page": 7},
            "collection_result": {
                "probe_summary": {
                    "final_url": " unknown ",
                    "first_urls": [" unknown ", "https://sf.taobao.com/item/1"],
                },
                "submit_result": {
                    "batch": {"status": " unknown ", "message": " unknown "},
                    "progress": {"status": "ok", "error": " unknown "},
                },
            },
        },
        requested_mode="hybrid",
        effective_mode="hybrid",
        submit=True,
        api_base="http://127.0.0.1:8001/api",
        cdp_endpoint="http://127.0.0.1:9223",
        session_id="runner-runtime-nested-placeholder-payloads",
    )

    assert summary["last_probe_summary"]["final_url"] is None
    assert summary["last_probe_summary"]["first_urls"] == [None, "https://sf.taobao.com/item/1"]
    assert summary["last_submit_result"]["batch"]["status"] is None
    assert summary["last_submit_result"]["batch"]["message"] is None
    assert summary["last_submit_result"]["progress"]["status"] == "ok"
    assert summary["last_submit_result"]["progress"]["error"] is None
    assert "unknown" not in json.dumps(summary)


def test_main_appends_runtime_history_without_overwriting_existing_entries(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    history_path.write_text(
        json.dumps({"generated_at": "2026-05-18 18:00:00", "session_id": "old-run"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    fake_result = {
        "decision": "browserless_success",
        "reason": None,
        "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=8", "page": 8},
        "collection_result": {
            "probe_summary": {
                "item_count": 60,
                "has_script": True,
                "body_has_challenge": False,
                "body_has_punish": False,
            },
            "submit_result": {
                "batch": {"status": "ok", "new": 60},
                "progress": {"status": "ok"},
            },
        },
    }

    monkeypatch.setattr(run_hybrid_seed_collection, "run_once", lambda **kwargs: fake_result)

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--session-id",
            "runner-single",
            "--mode",
            "browserless",
            "--submit",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.strip()
    history_lines = history_path.read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 2
    old_payload = json.loads(history_lines[0])
    new_payload = json.loads(history_lines[1])
    assert old_payload["session_id"] == "old-run"
    assert new_payload["session_id"] == "runner-single"
    assert new_payload["runner_mode"] == "browserless"
    assert new_payload["decision_counts"] == {"browserless_success": 1}


def test_main_omits_literal_unknown_effective_mode_from_payloads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "unknown",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=61", "page": 61},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-effective-mode-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("effective_mode") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("effective_mode") != "unknown"
    assert runtime_summary.get("last_effective_mode") != "unknown"
    assert "unknown" not in dict(runtime_summary.get("effective_mode_counts") or {})


def test_main_omits_whitespace_unknown_effective_mode_from_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": " unknown ",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-whitespace-placeholder-effective-mode-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("effective_mode") is None
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("effective_mode") is None
    assert runtime_summary.get("last_effective_mode") is None
    assert "unknown" not in dict(runtime_summary.get("effective_mode_counts") or {})


def test_main_treats_unknown_operator_status_bundle_nested_summaries_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {
            "guidance": "unknown",
            "recovery_policy": "unknown",
            "lifecycle_summary": "unknown",
            "intervention_summary": "unknown",
            "intervention_stability_summary": "unknown",
            "final_guidance_summary": "unknown",
            "digest_summary": "unknown",
            "digest_stability_summary": "unknown",
            "escalation_event_trend_summary": "unknown",
            "escalation_event_stability_summary": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=64", "page": 64},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-operator-status-bundle-nested-summaries",
            "--mode",
            "hybrid",
            "--respect-operator-guidance",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_action_hint") is None
    assert runtime_summary.get("operator_escalation_audit_message") is None
    assert runtime_summary.get("operator_digest_status") is None
    assert runtime_summary.get("operator_digest_stability_status") is None


def test_main_loop_mode_treats_unknown_direct_status_loader_summaries_as_missing(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_loop",
        lambda **kwargs: {
            "mode": "loop",
            "iterations": 1,
            "counts": {"browserless_success": 1},
            "reason_counts": {},
            "effective_mode_counts": {"hybrid": 1},
            "guidance_status_counts": {},
            "guidance_applied_count": 0,
            "termination_reason": "max_runs_reached",
            "results": [{"decision": "browserless_success", "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=66", "page": 66}}],
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: "unknown",
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: "unknown",
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--loop",
            "--max-runs",
            "1",
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-loop-mode-direct-status-unknown",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_escalation_source") is None
    assert runtime_summary.get("operator_digest_status") is None
    assert runtime_summary.get("operator_digest_stability_status") is None


def test_main_loop_mode_treats_whitespace_unknown_audit_message_as_missing(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_loop",
        lambda **kwargs: {
            "mode": "loop",
            "iterations": 1,
            "counts": {"browserless_success": 1},
            "reason_counts": {},
            "effective_mode_counts": {"hybrid": 1},
            "guidance_status_counts": {},
            "guidance_applied_count": 0,
            "termination_reason": "max_runs_reached",
            "operator_escalation_audit_message": " unknown ",
            "results": [
                {
                    "decision": "browserless_success",
                    "task": {
                        "url": "https://sf.taobao.com/list/50025969__2.htm?page=67",
                        "page": 67,
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_lifecycle_state_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_policy_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_intervention_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_final_guidance_summary",
        lambda *args, **kwargs: {
            "guidance_priority": "high",
            "guidance_message": "Continue monitoring hybrid collection health.",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_digest_stability_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_trend_summary",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_escalation_event_stability_summary",
        lambda *args, **kwargs: {},
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--loop",
            "--max-runs",
            "1",
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-loop-whitespace-placeholder-audit",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("operator_escalation_audit_message") is None
    assert runtime_summary.get("operator_escalation_audit_message") is None
    assert "[OPERATOR] Operator escalation audit: unknown" not in captured.err
    assert "[OPERATOR] Final guidance: Continue monitoring hybrid collection health." in captured.err


def test_main_treats_unknown_nested_guidance_resolution_summaries_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
            "guidance": "unknown",
            "recovery_policy": "unknown",
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=65", "page": 65},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-guidance-resolution-nested-summaries-main",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("guidance_recommended_mode") is None
    assert stdout_payload.get("top_guidance_reason") is None
    assert stdout_payload.get("top_policy_reason") is None
    assert stdout_payload.get("recovery_policy_effective_recommended_mode") is None
    assert runtime_summary.get("last_guidance_recommended_mode") is None
    assert runtime_summary.get("top_guidance_reason") is None
    assert runtime_summary.get("top_policy_reason") is None
    assert runtime_summary.get("last_recovery_policy_effective_recommended_mode") is None


def test_main_omits_literal_unknown_effective_mode_source_from_payloads(tmp_path: Path, monkeypatch, capsys):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "unknown",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=62", "page": 62},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-effective-mode-source-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("effective_mode_source") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("effective_mode_source") != "unknown"


def test_main_treats_unknown_requested_mode_as_default_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "unknown",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=63", "page": 63},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-requested-mode-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("requested_mode") == "hybrid"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("requested_mode") == "hybrid"


def test_main_treats_unknown_decision_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "unknown",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=65", "page": 65},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-decision-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("decision") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("last_decision") != "unknown"
    assert runtime_summary.get("decision_counts") == {}


def test_main_omits_literal_unknown_recovery_policy_status_from_guidance_resolution_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": "unknown",
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=63", "page": 63},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-recovery-policy-status-guidance-resolution-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_status") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_status") != "unknown"


def test_main_omits_literal_unknown_recovery_policy_priority_from_guidance_resolution_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": "unknown",
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=64", "page": 64},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-recovery-policy-priority-guidance-resolution-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_priority") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_priority") != "unknown"


def test_main_omits_literal_unknown_recovery_policy_effective_mode_from_guidance_resolution_payloads(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
            "recovery_policy": {
                "effective_recommended_mode": "unknown",
            },
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=65", "page": 65},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-recovery-policy-effective-mode-guidance-resolution-payloads",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload.get("recovery_policy_effective_recommended_mode") != "unknown"
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary.get("recovery_policy_effective_recommended_mode") != "unknown"


def test_main_treats_unknown_browser_fallback_opened_as_missing_for_payload_and_runtime(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "browser_fallback_opened": "unknown",
            "task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=66", "page": 66},
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-browser-fallback-opened",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["browser_fallback_opened"] is False
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["last_browser_fallback_opened"] is False


def test_main_treats_unknown_result_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: "unknown",
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-unknown-result-payload-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert stdout_payload.get("decision") is None
    assert stdout_payload.get("task") is None
    assert runtime_summary["last_task"] == {}
    assert runtime_summary["last_decision"] is None


def test_main_treats_unknown_task_page_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=88",
                "page": "unknown",
            },
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-task-page-payload-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["task"]["page"] is None
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["last_task"]["page"] is None


def test_main_treats_negative_task_page_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=88",
                "page": -88,
            },
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-negative-task-page-payload-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["task"]["page"] is None
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["last_task"]["page"] is None


def test_main_treats_unknown_task_url_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": {
                "url": "unknown",
                "page": 89,
            },
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-task-url-payload-runtime-summary",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["task"]["url"] is None
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["last_task"]["url"] is None


def test_main_treats_unknown_task_payload_as_missing_for_payload_and_runtime_summary(
    tmp_path: Path, monkeypatch, capsys
):
    output_path = tmp_path / "hybrid-runtime.json"
    history_path = tmp_path / "hybrid-runtime-history.jsonl"
    switch_events_path = tmp_path / "hybrid-mode-switch-events.jsonl"

    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_operator_status_bundle",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_strategy_guidance",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "load_hybrid_collection_recovery_policy",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "resolve_effective_mode",
        lambda **kwargs: {
            "requested_mode": "hybrid",
            "effective_mode": "hybrid",
            "effective_mode_source": "requested_mode",
            "guidance_applied": False,
            "recovery_policy_applied": False,
            "guidance_status": None,
            "recovery_policy_status": None,
            "recovery_policy_priority": None,
            "recovery_policy_mode_pin_active": False,
        },
    )
    monkeypatch.setattr(
        run_hybrid_seed_collection,
        "run_once",
        lambda **kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "task": "unknown",
            "collection_result": {"probe_summary": {"item_count": 60, "has_script": True}},
        },
    )

    exit_code = run_hybrid_seed_collection.main(
        [
            "--runtime-summary-path",
            str(output_path),
            "--runtime-history-path",
            str(history_path),
            "--runtime-switch-events-path",
            str(switch_events_path),
            "--session-id",
            "runner-literal-unknown-task-payload",
            "--mode",
            "hybrid",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    stdout_payload = json.loads(captured.out)
    assert stdout_payload["task"] == {}
    runtime_summary = json.loads(output_path.read_text(encoding="utf-8"))
    assert runtime_summary["last_task"] == {}
