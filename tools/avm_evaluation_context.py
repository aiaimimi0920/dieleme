#!/usr/bin/env python3
"""AVM 多维主链时间切分回测与评估报告生成工具。"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from src.avm.canonical_mapper import map_raw_to_canonical
from src.avm.feature_builder import build_features
from src.avm.engine import predict_fair_price
from src.avm.quality import price_plausibility
from src.avm.risk_schema import RISK_FEATURE_RULES, validate_risk_features
from tools.avm_data_loader import load_analysis_ready_rows, load_raw_record_rows

RISK_DIAGNOSTIC_FLAGS = [
    "is_occupied",
    "has_long_lease",
    "property_fee_owed",
    "is_restricted_purchase",
    "is_fractional_share",
]


@dataclass
class BacktestConfig:
    data_root: Path
    report_path: Path
    min_train_months: int = 6
    max_candidates_per_subject: int = 320
    diagnostic_case_limit: int = 30



__all__ = tuple(name for name in globals() if not name.startswith("__"))
