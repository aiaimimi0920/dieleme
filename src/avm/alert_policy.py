from __future__ import annotations

from typing import Any


def extract_risk_validation(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    direct = payload.get("risk_validation")
    if isinstance(direct, dict):
        return direct
    prediction = payload.get("prediction")
    if isinstance(prediction, dict) and isinstance(prediction.get("risk_validation"), dict):
        return prediction["risk_validation"]
    return {}


def manual_review_required(payload: dict[str, Any] | None) -> bool:
    payload = payload or {}
    if bool(payload.get("manual_review_recommended")):
        return True
    prediction = payload.get("prediction")
    if isinstance(prediction, dict) and bool(prediction.get("manual_review_recommended")):
        return True
    return False


def build_alert_blockers(
    *,
    margin: float | None,
    threshold: float,
    is_malignant_risk: bool,
    payload: dict[str, Any] | None = None,
) -> list[str]:
    blockers: list[str] = []
    if margin is None or margin < threshold:
        blockers.append("margin_below_threshold")
    if is_malignant_risk:
        blockers.append("malignant_risk")
    if manual_review_required(payload):
        blockers.append("manual_review_required")

    risk_validation = extract_risk_validation(payload)
    if risk_validation:
        if int(risk_validation.get("invalid_field_count") or 0) > 0:
            blockers.append("risk_validation_invalid")
        elif not bool(risk_validation.get("ok", True)):
            blockers.append("risk_validation_incomplete")

    return blockers
