#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm_config import DEFAULT_AVM_CONFIG, AvmConfigManager


def _load_json_dict(
    path: Path,
    fallback: dict[str, Any] | None = None,
    *,
    coerce_non_object_to_fallback: bool = False,
) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(fallback or {})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        if coerce_non_object_to_fallback:
            return copy.deepcopy(fallback or {})
        raise ValueError(f"invalid JSON object at {path}")
    if not isinstance(payload, dict):
        if coerce_non_object_to_fallback:
            return copy.deepcopy(fallback or {})
        raise ValueError(f"invalid JSON object at {path}")
    return payload


def normalize_calibration_targets_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    raw_payload = dict(payload) if isinstance(payload, dict) else {}

    def _normalize_target_rows(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, (list, tuple)):
            return []
        return [item for item in value if isinstance(item, dict)]

    global_risk_targets = _normalize_target_rows(raw_payload.get("global_risk_targets"))
    risk_factor_targets = _normalize_target_rows(raw_payload.get("risk_factor_targets"))
    temporal_targets = _normalize_target_rows(raw_payload.get("temporal_targets"))
    strategy_targets = _normalize_target_rows(raw_payload.get("strategy_targets"))

    top_calibration_target = raw_payload.get("top_calibration_target")
    if not isinstance(top_calibration_target, dict) and top_calibration_target is not None:
        top_calibration_target = None
    top_calibration_target_hint = raw_payload.get("top_calibration_target_hint")
    if not isinstance(top_calibration_target_hint, dict) and top_calibration_target_hint is not None:
        top_calibration_target_hint = None

    return {
        **raw_payload,
        "has_recommendations": bool(global_risk_targets or risk_factor_targets or temporal_targets or strategy_targets),
        "global_risk_targets": global_risk_targets,
        "risk_factor_targets": risk_factor_targets,
        "temporal_targets": temporal_targets,
        "strategy_targets": strategy_targets,
        "top_calibration_target": top_calibration_target,
        "top_calibration_target_hint": top_calibration_target_hint,
        "guidance": raw_payload.get("guidance") if isinstance(raw_payload.get("guidance"), dict) else {},
        "config_patch": raw_payload.get("config_patch") if isinstance(raw_payload.get("config_patch"), dict) else {},
    }


def merge_avm_config_patch(config: dict[str, Any], patch: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = copy.deepcopy(config)
    changed_keys: list[str] = []

    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            for child_key, child_value in value.items():
                if merged[key].get(child_key) != child_value:
                    changed_keys.append(f"{key}.{child_key}")
                merged[key][child_key] = child_value
        else:
            if merged.get(key) != value:
                changed_keys.append(str(key))
            merged[key] = value

    return merged, changed_keys


def _build_changed_path_details(config: dict[str, Any], merged: dict[str, Any], changed_keys: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    changed_paths: dict[str, dict[str, Any]] = {}
    rollback_patch: dict[str, Any] = {}

    for path in changed_keys:
        segments = path.split(".")
        before: Any = config
        after: Any = merged
        for segment in segments:
            before = before.get(segment) if isinstance(before, dict) else None
            after = after.get(segment) if isinstance(after, dict) else None
        changed_paths[path] = {"before": before, "after": after}

        cursor = rollback_patch
        for segment in segments[:-1]:
            cursor = cursor.setdefault(segment, {})
        cursor[segments[-1]] = before

    return changed_paths, rollback_patch


KNOWN_STEP_CONTRACT_DEFAULTS: dict[str, dict[str, str]] = {
    "preview": {
        "default_command": "",
        "default_follow_up_kind": "write",
        "runnable_without_existing_artifact": "true",
        "stage_span": "write_then_evaluate",
        "expected_signal": "inspect_changed_keys_and_risk_summary",
        "success_criterion": "ready_for_write_decision",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_check_timing": "pre_step",
    },
    "write": {
        "default_command": "",
        "default_follow_up_kind": "verify",
        "runnable_without_existing_artifact": "true",
        "stage_span": "write_then_evaluate",
        "expected_signal": "config_patch_applied",
        "success_criterion": "ready_for_eval_rerun",
        "surface": "local_cli",
        "artifact_kind": "config",
        "artifact_owner": "apply_avm_calibration_patch",
        "artifact": "datas/avm/config.json",
        "artifact_check_timing": "post_step",
    },
    "verify": {
        "default_command": "python tools/evaluate_avm.py",
        "default_follow_up_kind": "gate",
        "runnable_without_existing_artifact": "false",
        "stage_span": "evaluate_then_gate",
        "expected_signal": "eval_report_refreshed",
        "success_criterion": "ready_for_gate_rerun",
        "surface": "local_cli",
        "artifact_kind": "report",
        "artifact_owner": "evaluate_avm",
        "artifact": "datas/avm/eval_report.json",
        "artifact_check_timing": "post_step",
    },
    "gate": {
        "default_command": "python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report",
        "default_follow_up_kind": "",
        "runnable_without_existing_artifact": "false",
        "stage_span": "gate_only",
        "expected_signal": "release_gate_refreshed",
        "success_criterion": "ready_for_operator_review",
        "surface": "local_cli",
        "artifact_kind": "gate",
        "artifact_owner": "avm_release_gate",
        "artifact": "datas/avm/release_gate.json",
        "artifact_check_timing": "post_step",
    },
}


def _known_step_contract_defaults(step_kind: str) -> dict[str, str]:
    return dict(KNOWN_STEP_CONTRACT_DEFAULTS.get(str(step_kind or "").strip(), {}))


STAGE_SEMANTICS_DEFAULTS: dict[str, dict[str, Any]] = {
    "preview_then_split": {
        "priority": "now",
        "group_id": "preview-and-split",
        "group_label": "Preview and split",
        "badge": "now-preview-then-split",
        "sort_key": "0-preview-then-split",
        "display_order": 0,
        "lane": "current",
        "lane_label": "Current",
    },
    "write_then_evaluate": {
        "priority": "now",
        "group_id": "bundle-write-and-evaluate",
        "group_label": "Bundle write and evaluate",
        "badge": "now-write-then-evaluate",
        "sort_key": "1-write-then-evaluate",
        "display_order": 1,
        "lane": "current",
        "lane_label": "Current",
    },
    "evaluate_then_gate": {
        "priority": "next",
        "group_id": "evaluate-and-gate",
        "group_label": "Evaluate and gate",
        "badge": "next-evaluate-then-gate",
        "sort_key": "2-evaluate-then-gate",
        "display_order": 2,
        "lane": "upcoming",
        "lane_label": "Upcoming",
    },
    "gate_only": {
        "priority": "later",
        "group_id": "gate-rerun-only",
        "group_label": "Gate rerun only",
        "badge": "later-gate-only",
        "sort_key": "3-gate-only",
        "display_order": 3,
        "lane": "deferred",
        "lane_label": "Deferred",
    },
}


def _stage_semantics_defaults(stage_span: str) -> dict[str, Any]:
    return dict(STAGE_SEMANTICS_DEFAULTS.get(str(stage_span or "").strip(), {}))


def summarize_patch_risk(preview_payload: dict[str, Any]) -> dict[str, Any]:
    changed_keys = [str(key) for key in preview_payload.get("changed_keys") or [] if str(key)]
    if not changed_keys:
        return {"risk_level": "none", "risk_reasons": []}

    risk_reasons: list[str] = []
    if len(changed_keys) >= 2:
        risk_reasons.append("multiple_changed_keys")

    has_risk_discount = "risk_discount_factor" in changed_keys
    has_weighting = any(key.startswith("weighting.") for key in changed_keys)
    risk_flag_count = sum(1 for key in changed_keys if key.startswith("risk_factor_overrides."))

    if has_risk_discount and has_weighting:
        risk_reasons.append("cross_knob_bundle")
    if risk_flag_count >= 2:
        risk_reasons.append("multi_flag_bundle")
    if len(changed_keys) >= 3:
        risk_reasons.append("broad_patch_surface")

    if "broad_patch_surface" in risk_reasons:
        risk_level = "high"
    elif risk_reasons:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {"risk_level": risk_level, "risk_reasons": risk_reasons}


def summarize_patch_next_action(risk_summary: dict[str, Any], preview_payload: dict[str, Any]) -> dict[str, Any]:
    changed_keys = [str(key) for key in preview_payload.get("changed_keys") or [] if str(key)]
    changed_key_count = int(preview_payload.get("changed_key_count") or len(changed_keys))
    risk_level = str(risk_summary.get("risk_level") or "none")
    if changed_key_count <= 0:
        return {"next_action": "no_action_required", "next_action_reasons": []}
    if risk_level == "low":
        return {"next_action": "safe_to_write_then_verify", "next_action_reasons": ["low_risk_bundle"]}
    if risk_level == "medium":
        return {"next_action": "preview_only_first", "next_action_reasons": ["medium_risk_bundle"]}
    if risk_level == "high":
        return {"next_action": "split_bundle_or_single_target_first", "next_action_reasons": ["high_risk_bundle"]}
    return {"next_action": "preview_only_first", "next_action_reasons": ["unknown_risk_bundle"]}


def summarize_patch_next_action_command(
    next_action_summary: dict[str, Any],
    *,
    preview_command: str = "",
    write_command: str = "",
) -> dict[str, Any]:
    def _normalize_preview_like_command(command: str) -> str:
        normalized_command = str(command or "").strip()
        if normalized_command.endswith(" --write"):
            return normalized_command[:-8].rstrip()
        return normalized_command

    def _normalize_write_like_command(command: str) -> str:
        normalized_command = _normalize_preview_like_command(command)
        if not normalized_command:
            return ""
        return f"{normalized_command} --write"

    def _derive_preview_from_write(command: str) -> str:
        normalized_command = str(command or "").strip()
        if normalized_command.endswith(" --write"):
            return normalized_command[:-8].rstrip()
        return ""

    next_action = str(next_action_summary.get("next_action") or "no_action_required")
    if next_action == "safe_to_write_then_verify":
        normalized_write_command = _normalize_write_like_command(str(write_command or ""))
        if not normalized_write_command:
            normalized_write_command = _normalize_write_like_command(str(preview_command or ""))
        return {"next_action_command": normalized_write_command, "next_action_command_kind": "write"}
    if next_action in {"preview_only_first", "split_bundle_or_single_target_first"}:
        normalized_preview_command = _normalize_preview_like_command(str(preview_command or ""))
        if not normalized_preview_command:
            normalized_preview_command = _derive_preview_from_write(str(write_command or ""))
        return {"next_action_command": normalized_preview_command, "next_action_command_kind": "preview"}
    return {"next_action_command": "", "next_action_command_kind": "none"}


def summarize_patch_follow_up_command(
    next_action_summary: dict[str, Any],
    *,
    preview_command: str = "",
    write_command: str = "",
    verify_command: str = "",
) -> dict[str, Any]:
    def _normalize_write_like_command(command: str) -> str:
        normalized_command = str(command or "").strip()
        if not normalized_command:
            return ""
        if normalized_command.endswith(" --write"):
            normalized_command = normalized_command[:-8].rstrip()
        return f"{normalized_command} --write"

    next_action = str(next_action_summary.get("next_action") or "no_action_required")
    if next_action == "safe_to_write_then_verify":
        normalized_verify_command = str(verify_command or "").strip()
        return {
            "follow_up_command": normalized_verify_command,
            "follow_up_command_kind": "verify" if normalized_verify_command else "none",
        }
    if next_action == "preview_only_first":
        synthesized_write_command = _normalize_write_like_command(str(write_command or ""))
        if not synthesized_write_command and preview_command:
            synthesized_write_command = _normalize_write_like_command(str(preview_command or ""))
        return {"follow_up_command": synthesized_write_command, "follow_up_command_kind": "write" if synthesized_write_command else "none"}
    return {"follow_up_command": "", "follow_up_command_kind": "none"}


def summarize_patch_command_chain(
    *,
    next_action_command: str = "",
    next_action_command_kind: str = "none",
    follow_up_command: str = "",
    follow_up_command_kind: str = "none",
    verify_command: str = "",
    gate_command: str = "",
) -> list[dict[str, str]]:
    def _normalize_command(kind: str, command: str) -> str:
        normalized_kind = str(kind or "").strip()
        normalized_command = str(command or "").strip()
        if normalized_kind == "preview" and normalized_command.endswith(" --write"):
            return normalized_command[:-8].rstrip()
        if normalized_kind == "write" and normalized_command and not normalized_command.endswith(" --write"):
            return f"{normalized_command} --write"
        return normalized_command
    entry_kinds = {
        str(next_action_command_kind or "").strip(),
        str(follow_up_command_kind or "").strip(),
    }
    raw_entries = [
        (next_action_command_kind, next_action_command),
        (follow_up_command_kind, follow_up_command),
    ]
    normalized_follow_up_kind = str(follow_up_command_kind or "").strip()
    normalized_follow_up_command = str(follow_up_command or "").strip()
    has_verify_stage = bool(str(verify_command or "").strip()) or (
        normalized_follow_up_kind == "verify" and bool(normalized_follow_up_command)
    )
    if entry_kinds.intersection({"write", "verify"}):
        raw_entries.append(("verify", verify_command))
        if has_verify_stage:
            raw_entries.append(("gate", gate_command))
    normalized_entries: list[dict[str, str]] = []
    for kind, command in raw_entries:
        normalized_kind = str(kind or "").strip()
        normalized_command = _normalize_command(normalized_kind, str(command or ""))
        normalized_entries.append({"kind": normalized_kind, "command": normalized_command})

    preview_entry = next((entry for entry in normalized_entries if entry["kind"] == "preview"), None)
    write_entry = next((entry for entry in normalized_entries if entry["kind"] == "write"), None)
    if preview_entry and not preview_entry["command"] and write_entry and write_entry["command"].endswith(" --write"):
        preview_entry["command"] = write_entry["command"][:-8].rstrip()
    if write_entry and not write_entry["command"] and preview_entry and preview_entry["command"]:
        write_entry["command"] = _normalize_command("write", preview_entry["command"])

    command_chain: list[dict[str, str]] = []
    seen_kinds: set[str] = set()
    for entry in normalized_entries:
        normalized_kind = entry["kind"]
        normalized_command = entry["command"]
        if not normalized_command or normalized_kind in {"", "none"}:
            continue
        if normalized_kind in seen_kinds:
            continue
        seen_kinds.add(normalized_kind)
        defaults = _known_step_contract_defaults(normalized_kind)
        command_chain.append(
            {
                "kind": normalized_kind,
                "command": normalized_command,
                "expected_signal": str(defaults.get("expected_signal") or ""),
                "success_criterion": str(defaults.get("success_criterion") or ""),
                "surface": str(defaults.get("surface") or ""),
                "artifact_kind": str(defaults.get("artifact_kind") or ""),
                "artifact_owner": str(defaults.get("artifact_owner") or ""),
                "artifact": str(defaults.get("artifact") or ""),
                "artifact_state": "unknown",
            }
        )
    return command_chain


def summarize_bundle_command_summary(top_target_hint: dict[str, Any] | None) -> tuple[str, str, str, str]:
    commands = list((top_target_hint or {}).get("suggested_bundle_commands") or [])
    preview_command = str(commands[0]) if len(commands) >= 1 else ""
    write_command = str(commands[1]) if len(commands) >= 2 else ""
    verify_command = str(commands[2]) if len(commands) >= 3 else ""
    gate_command = str(commands[3]) if len(commands) >= 4 else ""
    recommended_bundle = (top_target_hint or {}).get("recommended_bundle")

    if not preview_command and not write_command and isinstance(recommended_bundle, dict):
        target_types = [str(item) for item in recommended_bundle.get("target_types") or [] if str(item)]
        target_names = [str(item) for item in recommended_bundle.get("target_names") or [] if str(item)]
        if target_types or target_names:
            command_parts = ["python", "tools/apply_avm_calibration_patch.py"]
            for target_type in target_types:
                command_parts.extend(["--target-type", target_type])
            for target_name in target_names:
                command_parts.extend(["--target-name", target_name])
            preview_command = " ".join(command_parts)

    if isinstance(recommended_bundle, dict):
        if not verify_command:
            verify_command = str(_known_step_contract_defaults("verify").get("default_command") or "")
        if not gate_command:
            gate_command = str(_known_step_contract_defaults("gate").get("default_command") or "")

    if not preview_command and write_command.endswith(" --write"):
        preview_command = write_command[:-8].rstrip()
    if preview_command.endswith(" --write"):
        preview_command = preview_command[:-8].rstrip()
    if write_command and not write_command.endswith(" --write"):
        write_command = f"{write_command} --write"
    if not write_command and preview_command:
        write_command = f"{preview_command} --write"
    return preview_command, write_command, verify_command, gate_command


def resolve_command_chain_artifacts(command_chain: list[dict[str, Any]], data_root: Path) -> list[dict[str, Any]]:
    resolved_chain: list[dict[str, Any]] = []
    base_root = Path(data_root)
    def _normalize_indexed_command(step_kind: str, command: str) -> str:
        normalized_kind = str(step_kind or "").strip()
        normalized_command = str(command or "").strip()
        if normalized_kind == "preview" and normalized_command.endswith(" --write"):
            return normalized_command[:-8].rstrip()
        return normalized_command
    command_by_kind: dict[str, str] = {}
    for item in command_chain:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        command = _normalize_indexed_command(kind, str(item.get("command") or ""))
        if kind and command:
            command_by_kind[kind] = command
    for known_kind in KNOWN_STEP_CONTRACT_DEFAULTS:
        defaults = _known_step_contract_defaults(known_kind)
        default_command = str(defaults.get("default_command") or "").strip()
        if default_command:
            command_by_kind.setdefault(known_kind, default_command)
    preview_command = str(command_by_kind.get("preview") or "").strip()
    if preview_command:
        indexed_write_command = str(command_by_kind.get("write") or "").strip()
        if indexed_write_command and not indexed_write_command.endswith(" --write"):
            command_by_kind["write"] = f"{indexed_write_command} --write"
    if preview_command and not str(command_by_kind.get("write") or "").strip():
        command_by_kind["write"] = preview_command if preview_command.endswith(" --write") else f"{preview_command} --write"
    write_command = str(command_by_kind.get("write") or "").strip()
    if write_command and not str(command_by_kind.get("preview") or "").strip():
        if write_command.endswith(" --write"):
            command_by_kind["preview"] = write_command[:-8].rstrip()
    kind_by_command: dict[str, str] = {}
    for kind, command in command_by_kind.items():
        normalized_command = str(command or "").strip()
        if normalized_command:
            kind_by_command[normalized_command] = kind

    def _follow_up_expected_signal(command: str) -> str:
        normalized_command = str(command or "").strip()
        if not normalized_command:
            return ""
        follow_up_kind = str(kind_by_command.get(normalized_command) or "").strip()
        defaults = _known_step_contract_defaults(follow_up_kind)
        return str(defaults.get("expected_signal") or "")

    def _follow_up_success_criterion(command: str) -> str:
        normalized_command = str(command or "").strip()
        if not normalized_command:
            return ""
        follow_up_kind = str(kind_by_command.get(normalized_command) or "").strip()
        defaults = _known_step_contract_defaults(follow_up_kind)
        return str(defaults.get("success_criterion") or "")

    def _terminal_outcome(*, current_success_criterion: str, follow_up_success_criterion: str) -> str:
        normalized_follow_up = str(follow_up_success_criterion or "").strip()
        if normalized_follow_up:
            return normalized_follow_up
        return str(current_success_criterion or "").strip()

    def _stage_span(*, step_kind: str, follow_up_command: str) -> str:
        defaults = _known_step_contract_defaults(step_kind)
        normalized_stage_span = str(defaults.get("stage_span") or "").strip()
        if normalized_stage_span:
            return normalized_stage_span
        normalized_follow_up = str(follow_up_command or "").strip()
        if normalized_follow_up == command_by_kind.get("verify", ""):
            return "write_then_evaluate"
        if normalized_follow_up == command_by_kind.get("gate", ""):
            return "evaluate_then_gate"
        return "unknown"

    def _artifact_check_timing(step_kind: str) -> str:
        defaults = _known_step_contract_defaults(step_kind)
        return str(defaults.get("artifact_check_timing") or "unknown")

    def _known_step_kind(step_kind: str) -> bool:
        return bool(_known_step_contract_defaults(step_kind))

    def _runnable_without_existing_artifact(step_kind: str) -> bool:
        defaults = _known_step_contract_defaults(step_kind)
        return str(defaults.get("runnable_without_existing_artifact") or "").strip().lower() == "true"

    def _backfill_known_step_contract_metadata(cloned: dict[str, Any], step_kind: str) -> None:
        defaults = _known_step_contract_defaults(step_kind)
        if not defaults:
            return
        cloned["command"] = str(command_by_kind.get(step_kind) or cloned.get("command") or defaults.get("default_command") or "")
        if step_kind == "write" and str(cloned["command"]).strip() and not str(cloned["command"]).strip().endswith(" --write"):
            cloned["command"] = f'{str(cloned["command"]).strip()} --write'
        cloned["expected_signal"] = str(cloned.get("expected_signal") or defaults.get("expected_signal") or "")
        cloned["success_criterion"] = str(cloned.get("success_criterion") or defaults.get("success_criterion") or "")
        cloned["surface"] = str(cloned.get("surface") or defaults.get("surface") or "")
        cloned["artifact_kind"] = str(cloned.get("artifact_kind") or defaults.get("artifact_kind") or "")
        cloned["artifact_owner"] = str(cloned.get("artifact_owner") or defaults.get("artifact_owner") or "")
        if not str(cloned.get("artifact") or "").strip():
            cloned["artifact"] = str(defaults.get("artifact") or "")

    def _default_follow_up_command(step_kind: str) -> str:
        defaults = _known_step_contract_defaults(step_kind)
        follow_up_kind = str(defaults.get("default_follow_up_kind") or "").strip()
        if not follow_up_kind:
            return ""
        return command_by_kind.get(follow_up_kind, "")

    def _apply_playbook_metadata(
        cloned: dict[str, Any],
        *,
        current_success_criterion: str,
        step_kind: str,
        follow_up_command: str,
    ) -> None:
        normalized_follow_up_command = str(follow_up_command or "").strip()
        cloned["step_ready_follow_up_command"] = normalized_follow_up_command
        cloned["step_ready_follow_up_expected_signal"] = _follow_up_expected_signal(normalized_follow_up_command)
        cloned["step_ready_follow_up_success_criterion"] = _follow_up_success_criterion(normalized_follow_up_command)
        cloned["step_ready_terminal_outcome"] = _terminal_outcome(
            current_success_criterion=current_success_criterion,
            follow_up_success_criterion=cloned["step_ready_follow_up_success_criterion"],
        )
        cloned["step_ready_stage_span"] = _stage_span(
            step_kind=step_kind,
            follow_up_command=normalized_follow_up_command,
        )
        stage_defaults = _stage_semantics_defaults(cloned["step_ready_stage_span"])
        cloned["step_ready_priority"] = str(stage_defaults.get("priority") or "unknown")
        cloned["step_ready_badge"] = str(stage_defaults.get("badge") or "unknown")
        cloned["step_ready_group_id"] = str(stage_defaults.get("group_id") or "unknown")
        cloned["step_ready_group_label"] = str(stage_defaults.get("group_label") or "Unknown")
        cloned["step_ready_sort_key"] = str(stage_defaults.get("sort_key") or "unknown")
        display_order = stage_defaults.get("display_order")
        cloned["step_ready_display_order"] = int(display_order if display_order is not None else 99)
        cloned["step_ready_lane"] = str(stage_defaults.get("lane") or "unknown")
        cloned["step_ready_lane_label"] = str(stage_defaults.get("lane_label") or "Unknown")

    for item in command_chain:
        if not isinstance(item, dict):
            continue
        cloned = dict(item)
        step_kind = str(cloned.get("kind") or "")
        artifact_inferred = False
        original_artifact = str(cloned.get("artifact") or "")
        _backfill_known_step_contract_metadata(cloned, step_kind)
        artifact = str(cloned.get("artifact") or "")
        artifact_inferred = bool(artifact and not original_artifact.strip())
        current_success_criterion = str(cloned.get("success_criterion") or "")
        if artifact:
            artifact_path = Path(artifact)
            if artifact_path.parts and artifact_path.parts[0] == "datas":
                artifact_path = base_root.joinpath(*artifact_path.parts[1:])
            cloned["artifact_resolved_path"] = str(artifact_path)
            cloned["artifact_check_command"] = f'Get-Content "{artifact_path}"'
            cloned["artifact_check_timing"] = _artifact_check_timing(step_kind)
            if artifact_path.exists():
                if step_kind == "verify":
                    cloned["artifact_freshness"] = "stale"
                    cloned["artifact_freshness_reason"] = "pre_bundle_eval_report"
                    cloned["artifact_next_expected_transition"] = "stale->current"
                    cloned["artifact_ready_for_step"] = False
                    cloned["step_ready_summary"] = "blocked_by_eval_rerun"
                    cloned["step_ready_recommended_action"] = "rerun_evaluate"
                    cloned["step_ready_action_command"] = command_by_kind.get("verify", str(cloned.get("command") or ""))
                    _apply_playbook_metadata(
                        cloned,
                        current_success_criterion=current_success_criterion,
                        step_kind=step_kind,
                        follow_up_command=command_by_kind.get("gate", ""),
                    )
                    cloned["artifact_state"] = "stale"
                    cloned["artifact_state_reason"] = "pre_bundle_eval_report"
                elif step_kind == "gate":
                    cloned["artifact_freshness"] = "stale"
                    cloned["artifact_freshness_reason"] = "pre_bundle_gate_report"
                    cloned["artifact_next_expected_transition"] = "stale->current"
                    cloned["artifact_ready_for_step"] = False
                    cloned["step_ready_summary"] = "blocked_by_gate_rerun"
                    cloned["step_ready_recommended_action"] = "rerun_release_gate"
                    cloned["step_ready_action_command"] = command_by_kind.get("gate", str(cloned.get("command") or ""))
                    _apply_playbook_metadata(
                        cloned,
                        current_success_criterion=current_success_criterion,
                        step_kind=step_kind,
                        follow_up_command="",
                    )
                    cloned["artifact_state"] = "stale"
                    cloned["artifact_state_reason"] = "pre_bundle_gate_report"
                else:
                    cloned["artifact_freshness"] = "current"
                    cloned["artifact_freshness_reason"] = "artifact_current"
                    cloned["artifact_next_expected_transition"] = "current->current"
                    cloned["artifact_ready_for_step"] = True
                    cloned["step_ready_summary"] = "ready_now"
                    cloned["step_ready_recommended_action"] = "proceed_now"
                    cloned["step_ready_action_command"] = str(cloned.get("command") or "")
                    _apply_playbook_metadata(
                        cloned,
                        current_success_criterion=current_success_criterion,
                        step_kind=step_kind,
                        follow_up_command=_default_follow_up_command(step_kind),
                    )
                    cloned["artifact_state"] = "present"
                    cloned["artifact_state_reason"] = "artifact_present"
            elif artifact_inferred and _known_step_kind(step_kind) and _runnable_without_existing_artifact(step_kind):
                cloned["artifact_freshness"] = "pending_write"
                cloned["artifact_freshness_reason"] = "waiting_for_bundle_write"
                cloned["artifact_next_expected_transition"] = "pending_write->current"
                cloned["artifact_ready_for_step"] = True
                cloned["step_ready_summary"] = "ready_now"
                cloned["step_ready_recommended_action"] = "proceed_now"
                cloned["step_ready_action_command"] = str(cloned.get("command") or "")
                _apply_playbook_metadata(
                    cloned,
                    current_success_criterion=current_success_criterion,
                    step_kind=step_kind,
                    follow_up_command=_default_follow_up_command(step_kind),
                )
                cloned["artifact_state"] = "missing"
                cloned["artifact_state_reason"] = "config_not_written_yet"
            elif step_kind == "verify":
                cloned["artifact_freshness"] = "pending_rerun"
                cloned["artifact_freshness_reason"] = "waiting_for_eval_rerun"
                cloned["artifact_next_expected_transition"] = "pending_rerun->current"
                cloned["artifact_ready_for_step"] = False
                cloned["step_ready_summary"] = "blocked_by_eval_rerun"
                cloned["step_ready_recommended_action"] = "rerun_evaluate"
                cloned["step_ready_action_command"] = command_by_kind.get("verify", str(cloned.get("command") or ""))
                _apply_playbook_metadata(
                    cloned,
                    current_success_criterion=current_success_criterion,
                    step_kind=step_kind,
                    follow_up_command=command_by_kind.get("gate", ""),
                )
                cloned["artifact_state"] = "not_ready_yet"
                cloned["artifact_state_reason"] = "eval_not_rerun_yet"
            elif step_kind == "gate":
                cloned["artifact_freshness"] = "pending_rerun"
                cloned["artifact_freshness_reason"] = "waiting_for_gate_rerun"
                cloned["artifact_next_expected_transition"] = "pending_rerun->current"
                cloned["artifact_ready_for_step"] = False
                cloned["step_ready_summary"] = "blocked_by_gate_rerun"
                cloned["step_ready_recommended_action"] = "rerun_release_gate"
                cloned["step_ready_action_command"] = command_by_kind.get("gate", str(cloned.get("command") or ""))
                _apply_playbook_metadata(
                    cloned,
                    current_success_criterion=current_success_criterion,
                    step_kind=step_kind,
                    follow_up_command="",
                )
                cloned["artifact_state"] = "not_ready_yet"
                cloned["artifact_state_reason"] = "gate_not_rerun_yet"
            else:
                cloned["artifact_freshness"] = "pending_write"
                cloned["artifact_freshness_reason"] = "waiting_for_bundle_write"
                cloned["artifact_next_expected_transition"] = "pending_write->current"
                cloned["artifact_ready_for_step"] = True
                cloned["step_ready_summary"] = "ready_now"
                cloned["step_ready_recommended_action"] = "proceed_now"
                cloned["step_ready_action_command"] = str(cloned.get("command") or "")
                _apply_playbook_metadata(
                    cloned,
                    current_success_criterion=current_success_criterion,
                    step_kind=step_kind,
                    follow_up_command=_default_follow_up_command(step_kind),
                )
                cloned["artifact_state"] = "missing"
                cloned["artifact_state_reason"] = "config_not_written_yet"
        else:
            cloned["artifact_resolved_path"] = ""
            cloned["artifact_check_command"] = ""
            cloned["artifact_check_timing"] = _artifact_check_timing(step_kind)
            cloned["artifact_freshness"] = "unknown"
            cloned["artifact_freshness_reason"] = "artifact_path_missing"
            cloned["artifact_next_expected_transition"] = "unknown"
            if step_kind in {"preview", "write", "verify", "gate"}:
                cloned["artifact_ready_for_step"] = True
                cloned["step_ready_summary"] = "ready_now"
                cloned["step_ready_recommended_action"] = "proceed_now"
                cloned["step_ready_action_command"] = str(cloned.get("command") or "")
                _apply_playbook_metadata(
                    cloned,
                    current_success_criterion=current_success_criterion,
                    step_kind=step_kind,
                    follow_up_command=_default_follow_up_command(step_kind),
                )
            else:
                cloned["artifact_ready_for_step"] = False
                cloned["step_ready_summary"] = "unknown"
                cloned["step_ready_recommended_action"] = "inspect_artifact_state"
                cloned["step_ready_action_command"] = cloned["artifact_check_command"]
                _apply_playbook_metadata(
                    cloned,
                    current_success_criterion=current_success_criterion,
                    step_kind=step_kind,
                    follow_up_command=_default_follow_up_command(step_kind),
                )
            cloned["artifact_state"] = "missing"
            cloned["artifact_state_reason"] = "artifact_path_missing"
        if _known_step_kind(step_kind) and not str(cloned.get("command") or "").strip():
            cloned["artifact_ready_for_step"] = False
            cloned["step_ready_summary"] = "unknown"
            cloned["step_ready_recommended_action"] = "inspect_artifact_state"
            cloned["step_ready_action_command"] = str(cloned.get("artifact_check_command") or "")
            cloned["step_ready_follow_up_command"] = ""
            cloned["step_ready_follow_up_expected_signal"] = ""
            cloned["step_ready_follow_up_success_criterion"] = ""
            cloned["step_ready_terminal_outcome"] = current_success_criterion
        resolved_chain.append(cloned)
    return resolved_chain


def apply_command_chain_next_action_policy(
    command_chain: list[dict[str, Any]],
    *,
    next_action: str,
) -> list[dict[str, Any]]:
    normalized_next_action = str(next_action or "").strip()
    if normalized_next_action != "split_bundle_or_single_target_first":
        return command_chain

    adjusted_chain: list[dict[str, Any]] = []
    for index, item in enumerate(command_chain):
        if not isinstance(item, dict):
            adjusted_chain.append(item)
            continue
        cloned = dict(item)
        if index == 0 and str(cloned.get("kind") or "").strip() == "preview":
            stage_defaults = _stage_semantics_defaults("preview_then_split")
            cloned["step_ready_follow_up_command"] = ""
            cloned["step_ready_follow_up_expected_signal"] = ""
            cloned["step_ready_follow_up_success_criterion"] = ""
            cloned["step_ready_terminal_outcome"] = str(cloned.get("success_criterion") or "")
            cloned["step_ready_stage_span"] = "preview_then_split"
            cloned["step_ready_priority"] = str(stage_defaults.get("priority") or "unknown")
            cloned["step_ready_badge"] = str(stage_defaults.get("badge") or "unknown")
            cloned["step_ready_group_id"] = str(stage_defaults.get("group_id") or "unknown")
            cloned["step_ready_group_label"] = str(stage_defaults.get("group_label") or "Unknown")
            cloned["step_ready_sort_key"] = str(stage_defaults.get("sort_key") or "unknown")
            display_order = stage_defaults.get("display_order")
            cloned["step_ready_display_order"] = int(display_order if display_order is not None else 99)
            cloned["step_ready_lane"] = str(stage_defaults.get("lane") or "unknown")
            cloned["step_ready_lane_label"] = str(stage_defaults.get("lane_label") or "Unknown")
        adjusted_chain.append(cloned)
    return adjusted_chain


def _normalize_filter_values(
    *,
    singular: str | None = None,
    plural: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    values: list[str] = []
    if singular:
        values.append(str(singular))
    for value in plural or []:
        if value:
            values.append(str(value))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _build_applied_filter_payload(target_types: list[str], target_names: list[str]) -> dict[str, Any] | None:
    if not target_types and not target_names:
        return None
    if len(target_types) <= 1 and len(target_names) <= 1:
        return {
            "target_type": target_types[0] if target_types else None,
            "target_name": target_names[0] if target_names else None,
        }
    return {
        "target_types": target_types or None,
        "target_names": target_names or None,
    }


def _build_target_patch_entries(calibration_report: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for row in calibration_report.get("temporal_targets", []) or []:
        if not isinstance(row, dict):
            continue
        suggested_next_value = row.get("suggested_next_value")
        if suggested_next_value is None:
            continue
        entries.append(
            {
                "target_type": "temporal",
                "target_name": str(row.get("name") or "time_decay"),
                "patch": {"weighting": {"time_decay": suggested_next_value}},
            }
        )

    for row in calibration_report.get("global_risk_targets", []) or []:
        if not isinstance(row, dict):
            continue
        suggested_next_value = row.get("suggested_next_value")
        if suggested_next_value is None:
            continue
        entries.append(
            {
                "target_type": "global_risk",
                "target_name": str(row.get("name") or "risk_discount_factor"),
                "patch": {"risk_discount_factor": suggested_next_value},
            }
        )

    for row in calibration_report.get("risk_factor_targets", []) or []:
        if not isinstance(row, dict):
            continue
        target_name = str(row.get("name") or "")
        suggested_next_factor = row.get("suggested_next_factor")
        if not target_name or suggested_next_factor is None:
            continue
        entries.append(
            {
                "target_type": "risk_flag",
                "target_name": target_name,
                "patch": {"risk_factor_overrides": {target_name: suggested_next_factor}},
            }
        )

    return entries


def _select_config_patch(
    calibration_report: dict[str, Any],
    *,
    target_type: str | None = None,
    target_name: str | None = None,
    target_types: list[str] | tuple[str, ...] | None = None,
    target_names: list[str] | tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    config_patch = calibration_report.get("config_patch") if isinstance(calibration_report.get("config_patch"), dict) else {}
    normalized_target_types = _normalize_filter_values(singular=target_type, plural=target_types)
    normalized_target_names = _normalize_filter_values(singular=target_name, plural=target_names)
    if not normalized_target_types and not normalized_target_names:
        return config_patch, []

    filtered_entries: list[tuple[int, dict[str, Any]]] = []
    for ordinal, entry in enumerate(_build_target_patch_entries(calibration_report)):
        entry_type = str(entry.get("target_type") or "")
        entry_name = str(entry.get("target_name") or "")
        if normalized_target_types and entry_type not in normalized_target_types:
            continue
        if normalized_target_names and entry_name not in normalized_target_names:
            continue
        filtered_entries.append((ordinal, entry))

    def _entry_sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        ordinal, entry = item
        entry_type = str(entry.get("target_type") or "")
        entry_name = str(entry.get("target_name") or "")
        type_index = normalized_target_types.index(entry_type) if normalized_target_types and entry_type in normalized_target_types else 0
        name_index = normalized_target_names.index(entry_name) if normalized_target_names and entry_name in normalized_target_names else 0
        return type_index, name_index, ordinal

    filtered_entries.sort(key=_entry_sort_key)

    matched_targets: list[dict[str, str]] = []
    filtered_patch: dict[str, Any] = {}
    for _, entry in filtered_entries:
        entry_type = str(entry.get("target_type") or "")
        entry_name = str(entry.get("target_name") or "")
        filtered_patch, _ = merge_avm_config_patch(filtered_patch, entry.get("patch") or {})
        matched_targets.append({"target_type": entry_type, "target_name": entry_name})

    return filtered_patch, matched_targets


def apply_avm_calibration_patch(
    *,
    config_path: Path,
    calibration_path: Path,
    write_back: bool = False,
    target_type: str | None = None,
    target_name: str | None = None,
    target_types: list[str] | tuple[str, ...] | None = None,
    target_names: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    current_config = _load_json_dict(
        config_path,
        fallback=DEFAULT_AVM_CONFIG,
        coerce_non_object_to_fallback=True,
    )
    try:
        AvmConfigManager(str(config_path))._validate_config(current_config)
    except Exception:
        current_config = copy.deepcopy(DEFAULT_AVM_CONFIG)
    calibration_report = _load_json_dict(calibration_path, fallback={})
    normalized_target_types = _normalize_filter_values(singular=target_type, plural=target_types)
    normalized_target_names = _normalize_filter_values(singular=target_name, plural=target_names)
    config_patch, matched_targets = _select_config_patch(
        calibration_report,
        target_types=normalized_target_types,
        target_names=normalized_target_names,
    )

    merged_config, changed_keys = merge_avm_config_patch(current_config, config_patch)
    changed_paths, rollback_patch = _build_changed_path_details(current_config, merged_config, changed_keys)
    AvmConfigManager(str(config_path))._validate_config(merged_config)

    if write_back:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(merged_config, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "config_path": str(config_path),
        "calibration_path": str(calibration_path),
        "write_back": bool(write_back),
        "applied": bool(write_back and changed_keys),
        "applied_filter": _build_applied_filter_payload(normalized_target_types, normalized_target_names),
        "matched_targets": matched_targets,
        "changed_key_count": len(changed_keys),
        "changed_keys": changed_keys,
        "changed_paths": changed_paths,
        "rollback_patch": rollback_patch,
        "top_calibration_target": calibration_report.get("top_calibration_target"),
        "guidance": calibration_report.get("guidance"),
        "config_patch": config_patch,
        "current_config": current_config,
        "merged_config": merged_config,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview or apply AVM calibration config_patch to datas/avm/config.json")
    parser.add_argument("--config", type=Path, default=Path("datas/avm/config.json"))
    parser.add_argument("--calibration", type=Path, default=Path("datas/avm/calibration_targets.json"))
    parser.add_argument("--write", action="store_true", help="Write merged config back to --config; default is dry-run preview only")
    parser.add_argument(
        "--target-type",
        dest="target_types",
        choices=["temporal", "global_risk", "risk_flag"],
        action="append",
        help="Only apply patch entries for the selected calibration target type; repeat to include multiple target types",
    )
    parser.add_argument(
        "--target-name",
        dest="target_names",
        action="append",
        help="Only apply patch entries for the selected calibration target name; repeat to include multiple target names",
    )
    args = parser.parse_args()

    result = apply_avm_calibration_patch(
        config_path=args.config,
        calibration_path=args.calibration,
        write_back=args.write,
        target_types=args.target_types,
        target_names=args.target_names,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
