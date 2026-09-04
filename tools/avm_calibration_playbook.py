"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_calibration_context import *


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


__all__ = (
    'resolve_command_chain_artifacts',
    'apply_command_chain_next_action_policy',
)
