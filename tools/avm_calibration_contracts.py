"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_context import *


def _known_step_contract_defaults(step_kind: str) -> dict[str, str]:
    return dict(KNOWN_STEP_CONTRACT_DEFAULTS.get(str(step_kind or "").strip(), {}))


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


__all__ = (
    '_known_step_contract_defaults',
    '_stage_semantics_defaults',
    'summarize_patch_risk',
    'summarize_patch_next_action',
    'summarize_patch_next_action_command',
    'summarize_patch_follow_up_command',
    'summarize_patch_command_chain',
    'summarize_bundle_command_summary',
)
