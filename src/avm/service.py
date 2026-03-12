"""AVM 服务编排层，占位且未接入主链路。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .canonical_mapper import CanonicalMapper
from .engine import AVMEngine, AVMResult
from .feature_builder import FeatureBuilder
from .risk_schema import RiskAssessment


@dataclass
class AVMService:
    """封装 AVM 执行流程：映射 -> 特征 -> 估值。"""

    mapper: CanonicalMapper = CanonicalMapper()
    feature_builder: FeatureBuilder = FeatureBuilder()
    engine: AVMEngine = AVMEngine()

    def evaluate(self, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        """返回统一响应结构（占位实现）。"""
        canonical = self.mapper.map_record(raw_record)
        features = self.feature_builder.build(canonical)
        estimate: AVMResult = self.engine.estimate(features)
        risk = RiskAssessment()
        return {
            "canonical": canonical,
            "features": features,
            "estimate": estimate,
            "risk": risk,
        }
