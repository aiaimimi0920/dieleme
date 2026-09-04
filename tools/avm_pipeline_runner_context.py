import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.normalize import parse_money_to_yuan
from src.avm.alert_policy import build_alert_blockers
from src.avm_config import DEFAULT_AVM_CONFIG
from src.avm.risk_schema import RISK_FEATURE_RULES, validate_risk_features
from src.avm.service import AVMService
from src.storage.repository import create_repository_from_env
from tools.avm_data_loader import iter_analysis_ready_rows, iter_raw_record_rows
from tools.build_avm_features import build_avm_features
from tools.build_canonical_dataset import build_canonical_dataset
from tools.generate_avm_alerts import generate_avm_alerts
from tools.evaluate_avm import BacktestConfig, generate_report
from tools.avm_release_gate import GateThresholds, build_eval_gate, generate_release_gate_report
from tools.apply_avm_calibration_patch import (
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    normalize_calibration_targets_payload,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_command_chain,
    summarize_patch_follow_up_command,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)
from tools.suggest_avm_calibration_targets import suggest_calibration_targets


__all__ = tuple(name for name in globals() if not name.startswith("__"))
