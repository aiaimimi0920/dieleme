"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_pipeline_runner_context import *


def _bundle_change_summary(bundle_preview: Dict[str, Any]) -> Tuple[str, List[str]]:
    changed_keys = list(bundle_preview.get("changed_keys") or [])
    if not changed_keys:
        return "", []
    return str(changed_keys[0]), [str(key) for key in changed_keys[1:]]


def _bundle_command_summary(top_target_hint: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return summarize_bundle_command_summary(top_target_hint)


def _json_file_is_object(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(payload, dict)
    except Exception:
        return False


def _load_candidates(data_dir: str, limit: int) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in iter_analysis_ready_rows(Path(data_dir), prefer_db=True):
        if not isinstance(row, dict):
            continue
        rows.append(row)
        if limit > 0 and len(rows) >= limit:
            break
    return rows


def _extract_risk_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    return {field: row.get(field) for field in RISK_FEATURE_RULES.keys()}



__all__ = (
    "_bundle_change_summary",
    "_bundle_command_summary",
    "_json_file_is_object",
    "_load_candidates",
    "_extract_risk_fields",
)
