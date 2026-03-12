"""AVM 估值引擎占位实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class AVMResult:
    """估值结果结构。"""

    estimated_price: float | None = None
    confidence: float = 0.0
    components: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AVMEngine:
    """估值计算入口（当前仅提供基础返回结构）。"""

    def estimate(self, features: Dict[str, Any]) -> AVMResult:
        """执行估值并返回结果（占位逻辑）。"""
        return AVMResult(
            estimated_price=None,
            confidence=0.0,
            components={"feature_count": len(features)},
        )
