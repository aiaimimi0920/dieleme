import json

from pathlib import Path

from tools import avm_release_gate as gate_module

from tools.avm_release_gate import GateThresholds, build_eval_gate, generate_release_gate_report

def _write_month(path: Path, month: str, rows):
    year = month.split("-")[0]
    target_dir = path / "archive" / year
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{month}-01.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


__all__ = [name for name in globals() if not name.startswith("__")]
