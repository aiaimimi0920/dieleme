import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DIR = PROJECT_ROOT / "datas" / "canonical"
REPORT_PATH = CANONICAL_DIR / "quality_report.json"

# 关键字段类型约束（可按业务继续扩展）
EXPECTED_TYPES: Dict[str, tuple] = {
    "id": (int, str),
    "item_id": (int, str),
    "source_item_id": (int, str),
    "城市": (str,),
    "区": (str,),
    "所属小区": (str,),
    "标题": (str,),
    "url": (str,),
    "建筑面积": (int, float),
    "单价": (int, float),
    "成交价格": (int, float),
    "评估价": (int, float),
    "起拍价": (int, float),
    "交易时间": (str,),
    "拍卖时间": (str,),
    "是否成交": (bool,),
}


def _iter_items(raw: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
        return

    if isinstance(raw, dict):
        # 格式 1: {"item_id": {...}, ...}
        if all(isinstance(v, dict) for v in raw.values()):
            for value in raw.values():
                yield value
            return

        # 格式 2: 单对象
        yield raw


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def _value_looks_invalid(field: str, value: Any) -> bool:
    # 通用非法值
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"n/a", "na", "null", "none", "未知", "待补充", "-", "--"}:
            return True

    # 数值字段业务规则
    if field in {"建筑面积", "单价", "成交价格", "评估价", "起拍价"}:
        if not isinstance(value, (int, float)):
            return False
        return value <= 0

    if field in {"url"}:
        return not (isinstance(value, str) and value.startswith(("http://", "https://")))

    if field in {"交易时间", "拍卖时间"}:
        if not isinstance(value, str):
            return False
        # 仅做轻量校验：必须包含年月日分隔样式之一
        return not any(token in value for token in ["-", "/", "年"])

    return False


def analyze_data_quality() -> None:
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)

    json_files = sorted(
        path for path in CANONICAL_DIR.rglob("*.json") if path.resolve() != REPORT_PATH.resolve()
    )

    field_stats = defaultdict(
        lambda: {
            "non_empty": 0,
            "type_error": 0,
            "invalid_value": 0,
            "checked_non_empty": 0,
        }
    )

    total_records = 0
    scanned_files = 0

    for file_path in json_files:
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"[WARN] malformed json, skip: {file_path}")
            continue
        except Exception as exc:
            print(f"[WARN] read failed, skip: {file_path}, err={exc}")
            continue

        items = list(_iter_items(raw))
        if not items:
            continue

        scanned_files += 1
        total_records += len(items)

        for item in items:
            for field in set(item.keys()) | set(EXPECTED_TYPES.keys()):
                value = item.get(field)
                field_stats[field]["checked_non_empty"] += 1

                if _is_empty(value):
                    continue

                field_stats[field]["non_empty"] += 1

                expected = EXPECTED_TYPES.get(field)
                if expected and not isinstance(value, expected):
                    field_stats[field]["type_error"] += 1
                    continue

                if _value_looks_invalid(field, value):
                    field_stats[field]["invalid_value"] += 1

    by_field: List[Dict[str, Any]] = []
    for field, stats in field_stats.items():
        checked = stats["checked_non_empty"]
        non_empty = stats["non_empty"]
        type_error = stats["type_error"]
        invalid_value = stats["invalid_value"]

        non_empty_rate = (non_empty / checked) if checked else 0.0
        type_error_rate = (type_error / non_empty) if non_empty else 0.0
        invalid_value_rate = (invalid_value / non_empty) if non_empty else 0.0

        # 问题分: 越高越差（用于字段优先治理排序）
        problem_score = (1 - non_empty_rate) + type_error_rate + invalid_value_rate

        by_field.append(
            {
                "field": field,
                "non_empty_rate": round(non_empty_rate, 4),
                "type_error_rate": round(type_error_rate, 4),
                "invalid_value_rate": round(invalid_value_rate, 4),
                "sample_size": checked,
                "problem_score": round(problem_score, 4),
            }
        )

    by_field.sort(key=lambda x: (-x["problem_score"], x["field"]))
    top5_problem_fields = by_field[:5]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "canonical_dir": str(CANONICAL_DIR),
        "total_files": len(json_files),
        "scanned_files": scanned_files,
        "total_records": total_records,
        "top5_problem_fields": top5_problem_fields,
        "fields": by_field,
    }

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Quality report written: {REPORT_PATH}")
    if top5_problem_fields:
        print("Top5 problem fields:")
        for idx, field_info in enumerate(top5_problem_fields, start=1):
            print(
                f"  {idx}. {field_info['field']} | "
                f"non_empty={field_info['non_empty_rate']:.2%}, "
                f"type_error={field_info['type_error_rate']:.2%}, "
                f"invalid={field_info['invalid_value_rate']:.2%}"
            )


if __name__ == "__main__":
    analyze_data_quality()
