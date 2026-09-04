#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.engine import get_effective_risk_factor_map
from src.avm_config import get_effective_risk_discount_factor, get_effective_weighting
from tools.apply_avm_calibration_patch import normalize_calibration_targets_payload



__all__ = tuple(name for name in globals() if not name.startswith("__"))
