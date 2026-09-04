"""Shared imports, constants, and data types for the split tool."""

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

__all__ = (
    'argparse',
    'copy',
    'json',
    'Path',
    'Any',
    'REPO_ROOT',
    'sys',
    'DEFAULT_AVM_CONFIG',
    'AvmConfigManager',
    'KNOWN_STEP_CONTRACT_DEFAULTS',
    'STAGE_SEMANTICS_DEFAULTS',
)
