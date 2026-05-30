from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_CATEGORIES = ("50025969", "200782003")
DEFAULT_SORT_ORDER = ("2", "1", "0", "3", "4", "5")


def load_priority_codes(jobs_dir: str | Path) -> List[str]:
    jobs_root = Path(jobs_dir)
    priority_file = jobs_root / "priority.json"
    if not priority_file.exists():
        return []
    try:
        payload = json.loads(priority_file.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [str(code).strip() for code in payload if str(code).strip()]


def load_all_location_codes(data_root: str | Path) -> List[str]:
    all_locations_file = Path(data_root) / "all_locations.json"
    if not all_locations_file.exists():
        return []
    try:
        payload = json.loads(all_locations_file.read_text(encoding="utf-8"))
    except Exception:
        return []

    codes: List[str] = []

    def _extract(nodes: List[Dict[str, Any]]) -> None:
        for node in nodes:
            code = str(node.get("code", "")).strip()
            if len(code) == 6:
                codes.append(code)
            children = node.get("children", [])
            if isinstance(children, list) and children:
                _extract(children)

    if isinstance(payload, list):
        _extract(payload)
    return codes


def iter_job_snapshots(jobs_dir: str | Path) -> List[Dict[str, Any]]:
    jobs_root = Path(jobs_dir)
    snapshots: List[Dict[str, Any]] = []
    if not jobs_root.exists():
        return snapshots

    for path in jobs_root.glob("*.json"):
        if path.name == "priority.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for loc_code, loc_data in payload.items():
            if loc_code == "all_done" or not isinstance(loc_data, dict):
                continue
            for category, cat_data in loc_data.items():
                if not isinstance(cat_data, dict):
                    continue
                now_session_id = cat_data.get("now_session_id", "")
                last_update_time = cat_data.get("last_update_time", "")
                for sort_param, st_data in (cat_data.get("st_param") or {}).items():
                    if not isinstance(st_data, dict):
                        continue
                    snapshots.append(
                        {
                            "location_code": str(loc_code),
                            "category": str(category),
                            "sort_param": str(sort_param),
                            "pages": list(st_data.get("pages", []) or []),
                            "max_page": st_data.get("max_page", -1),
                            "is_done": bool(st_data.get("is_done", False)),
                            "need_try": bool(st_data.get("need_try", True)),
                            "dispatched_page": st_data.get("dispatched_page", 0),
                            "now_session_id": now_session_id,
                            "last_update_time": last_update_time,
                            "category_all_done": bool(cat_data.get("all_done", False)),
                        }
                    )
    return snapshots
