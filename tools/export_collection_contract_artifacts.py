from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.collection_template import get_collection_template


DEFAULT_TEMPLATE_PATH = Path("docs/analysis/final-collection-template.json")
DEFAULT_FIELDS_PATH = Path("docs/analysis/final-collection-fields.csv")


def _flatten_field_rows(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for group in contract.get("groups", []):
        for field in group.get("fields", []):
            rows.append(
                {
                    "group_id": group.get("id"),
                    "group_label": group.get("label"),
                    "goal": group.get("goal"),
                    "key": field.get("key"),
                    "label": field.get("label"),
                    "priority": field.get("priority"),
                    "section": field.get("section"),
                    "source_stage": field.get("source_stage"),
                    "current_keys": "|".join(field.get("current_keys") or []),
                    "used_by": "|".join(field.get("used_by") or []),
                    "current_capture_status": field.get("current_capture_status"),
                    "example": json.dumps(field.get("example"), ensure_ascii=False) if field.get("example") is not None else "",
                    "note": field.get("note"),
                }
            )
    return rows


def export_contract_artifacts(
    template_path: Path = DEFAULT_TEMPLATE_PATH,
    fields_path: Path = DEFAULT_FIELDS_PATH,
) -> Dict[str, Any]:
    contract = get_collection_template()

    template_path.parent.mkdir(parents=True, exist_ok=True)
    fields_path.parent.mkdir(parents=True, exist_ok=True)

    template_payload = {
        "_meta": {
            "version": contract.get("version"),
            "frozen_contract": contract.get("frozen_contract"),
            "contract_status": contract.get("contract_status"),
        },
        "template": contract.get("final_template"),
    }
    template_path.write_text(json.dumps(template_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    field_rows = _flatten_field_rows(contract)
    fieldnames = [
        "group_id",
        "group_label",
        "goal",
        "key",
        "label",
        "priority",
        "section",
        "source_stage",
        "current_keys",
        "used_by",
        "current_capture_status",
        "example",
        "note",
    ]
    with fields_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(field_rows)

    return {
        "template_path": str(template_path).replace("\\", "/"),
        "fields_path": str(fields_path).replace("\\", "/"),
        "template_sections": list((contract.get("final_template") or {}).keys()),
        "field_count": len(field_rows),
        "version": contract.get("version"),
    }


def main() -> None:
    result = export_contract_artifacts()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
