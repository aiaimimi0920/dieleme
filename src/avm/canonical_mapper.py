"""原始采集数据 -> AVM 规范字段映射层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CanonicalMapper:
    """将原始字段映射到 AVM Canonical 字段。"""

    def map_record(self, raw_record: Dict[str, Any]) -> Dict[str, Any]:
        """返回标准化后的记录（当前为占位实现）。"""
        canonical = dict(raw_record)
        canonical.setdefault("schema_version", "avm.v0")
        return canonical
