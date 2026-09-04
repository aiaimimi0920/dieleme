import json

from pathlib import Path

import pytest

from tools.apply_avm_calibration_patch import (
    _known_step_contract_defaults,
    _stage_semantics_defaults,
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_command_chain,
    summarize_patch_follow_up_command,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)

def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

__all__ = [name for name in globals() if not name.startswith("__")]
