"""AVM 特征工程占位实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class FeatureBuilder:
    """将规范数据构建为模型输入特征。"""

    def build(self, canonical_record: Dict[str, Any]) -> Dict[str, Any]:
        """构建用于估值引擎的特征字典（当前为透传占位）。"""
        return dict(canonical_record)
