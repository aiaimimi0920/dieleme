"""AVM 风控特征校验规则。"""

from __future__ import annotations

from typing import Any

# 23 个风控字段定义
RISK_FEATURE_RULES = {
    "community_name": {"type": "string", "required": True},
    "build_year": {"type": "number", "required": True, "integer": True, "min": 1800, "max": 2100},
    "total_floors": {"type": "number", "required": True, "integer": True, "min": 1, "max": 200},
    "floor_level": {"type": "string", "required": True},
    "has_elevator": {"type": "bool", "required": True},
    "orientation": {
        "type": "enum",
        "required": True,
        "choices": ["南", "南北", "东", "西", "北", "未知"],
    },
    "land_right_type": {
        "type": "enum",
        "required": True,
        "choices": ["出让", "划拨", "未知"],
    },
    "is_occupied": {"type": "bool", "required": True},
    "has_long_lease": {"type": "bool", "required": True},
    "clear_delivery": {"type": "bool", "required": True},
    "tax_burden": {
        "type": "enum",
        "required": True,
        "choices": ["买受人承担全部", "各自承担", "未知"],
    },
    "is_haunted": {"type": "bool", "required": True},
    "housing_type": {
        "type": "enum",
        "required": True,
        "choices": ["住宅", "商业", "办公", "工业", "别墅", "车位", "其他"],
    },
    "has_keys": {"type": "bool", "required": True},
    "property_fee_owed": {"type": "bool", "required": True},
    "special_school_tag": {"type": "bool", "required": True},
    "evaluation_price": {"type": "number", "required": True, "min": 0},
    "layout": {"type": "string", "required": True},
    "is_restricted_purchase": {"type": "bool", "required": True},
    "includes_parking": {"type": "bool", "required": True},
    "is_fractional_share": {"type": "bool", "required": True},
    "tax_is_company_owned": {"type": "bool", "required": True},
    "has_lease_before_mortgage": {"type": "bool", "required": True},
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_risk_features(data: dict) -> tuple[bool, list[str]]:
    """校验风险特征字段。

    Args:
        data: 待校验的特征字典。

    Returns:
        (ok, errors):
            ok 为 True 表示全部通过；False 表示存在错误。
            errors 为错误信息列表。
    """

    errors: list[str] = []

    if not isinstance(data, dict):
        return False, ["data 必须是 dict"]

    for field, rule in RISK_FEATURE_RULES.items():
        value = data.get(field)

        if value is None:
            if rule.get("required", False):
                errors.append(f"{field}: 缺失必填字段")
            continue

        field_type = rule["type"]

        if field_type == "bool":
            if not isinstance(value, bool):
                errors.append(f"{field}: 期望 bool，实际为 {type(value).__name__}")

        elif field_type == "enum":
            if value not in rule["choices"]:
                errors.append(
                    f"{field}: 非法枚举值 {value!r}，允许值 {rule['choices']}"
                )

        elif field_type == "number":
            if not _is_number(value):
                errors.append(f"{field}: 期望数值，实际为 {type(value).__name__}")
                continue

            if rule.get("integer") and not isinstance(value, int):
                errors.append(f"{field}: 期望整数，实际为 {value!r}")

            min_v = rule.get("min")
            max_v = rule.get("max")
            if min_v is not None and value < min_v:
                errors.append(f"{field}: 值 {value} 小于最小值 {min_v}")
            if max_v is not None and value > max_v:
                errors.append(f"{field}: 值 {value} 大于最大值 {max_v}")

        elif field_type == "string":
            if not isinstance(value, str):
                errors.append(f"{field}: 期望字符串，实际为 {type(value).__name__}")

        else:
            errors.append(f"{field}: 未知规则类型 {field_type!r}")

    unknown_fields = sorted(set(data.keys()) - set(RISK_FEATURE_RULES.keys()))
    if unknown_fields:
        errors.append(f"存在未定义字段: {unknown_fields}")

    return len(errors) == 0, errors


__all__ = ["RISK_FEATURE_RULES", "validate_risk_features"]
