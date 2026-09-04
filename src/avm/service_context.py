from __future__ import annotations

import glob
import json
import os
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from src.avm_config import get_effective_risk_discount_factor, get_effective_weighting

from .canonical_mapper import map_raw_to_canonical
from .feature_builder import build_features
from .engine import get_active_risk_factor_overrides, predict_fair_price
from .quality import price_plausibility
from .risk_schema import RISK_FEATURE_RULES, validate_risk_features

MODEL_VERSION = "avm_multidim_v1"
MAX_CANDIDATE_POOL = 5000
GLOBAL_RECENT_CANDIDATES = 5000

RISK_IMPACT_MAP = {
    "is_occupied": (-0.12, "存在占用，处置周期与交付风险上升"),
    "has_long_lease": (-0.14, "长期租约会拉低可回收价值"),
    "is_restricted_purchase": (-0.03, "限购会压缩潜在买家池并影响流动性"),
    "property_fee_owed": (-0.03, "欠费可能抬升实际支付总价"),
    "tax_is_company_owned": (-0.06, "企业产权可能带来额外税费"),
    "is_fractional_share": (-0.17, "部分产权显著影响流动性"),
    "has_lease_before_mortgage": (0.04, "先抵后租具备一定套利修正"),
}

__all__ = [name for name in globals() if not name.startswith("__")]
