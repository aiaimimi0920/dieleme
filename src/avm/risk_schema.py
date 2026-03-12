"""AVM 风控标签结构定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class RiskTag:
    """单个风控标签。"""

    code: str
    level: str
    description: str = ""


@dataclass
class RiskAssessment:
    """风控评估结果容器。"""

    score: float = 0.0
    tags: List[RiskTag] = field(default_factory=list)
    details: Dict[str, str] = field(default_factory=dict)
