from __future__ import annotations

from .service_context import *  # noqa: F401,F403


class AVMReviewMixin:
    @staticmethod
    def _margin_level(ratio: Optional[float]) -> str:
        if ratio is None:
            return "UNKNOWN"
        if ratio >= 0.2:
            return "HIGH"
        if ratio >= 0.08:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _manual_review_reasons(subject: Dict[str, Any], prediction: Dict[str, Any]) -> List[str]:
        reasons: List[str] = []
        strategy = str(prediction.get("strategy") or "")
        confidence = float(prediction.get("confidence") or 0.0)
        trace = prediction.get("trace") or {}
        risk_validation = prediction.get("risk_validation") or {}
        housing_type = str(subject.get("housing_type") or "")
        community_name = str(subject.get("community_name") or "")
        business_area = str(subject.get("business_area") or "")

        if strategy in {"district_fallback", "city_fallback", "global_fallback"}:
            reasons.append("broad_fallback_strategy")
        if confidence < 0.35:
            reasons.append("low_confidence")
        if housing_type in {"其他", "商业", "办公", "车位"}:
            reasons.append("special_asset_type")
        if community_name in {"", "UNK"}:
            reasons.append("missing_community")
        if business_area in {"", "UNK"} and strategy in {"business_area_fallback", "district_fallback", "city_fallback", "global_fallback"}:
            reasons.append("missing_business_area")
        if str(trace.get("subject_coordinate_strategy") or "") == "missing":
            reasons.append("missing_coordinates")
        if float(trace.get("uncertainty_blend") or 0.0) >= 0.3:
            reasons.append("high_uncertainty_blend")
        if float(trace.get("area_scale_severity") or 0.0) >= 0.15:
            reasons.append("large_area_scale_guard")
        if float(trace.get("locality_severity") or 0.0) >= 0.08:
            reasons.append("low_tier_locality_guard")
        if bool(trace.get("weak_market_engagement")):
            reasons.append("weak_market_engagement")
        if int(trace.get("trimmed_outlier_count") or 0) >= 5:
            reasons.append("many_trimmed_outliers")
        if int(risk_validation.get("missing_required_count") or 0) > 0:
            reasons.append("risk_feature_incomplete")
        if int(risk_validation.get("invalid_field_count") or 0) > 0:
            reasons.append("risk_feature_invalid")
        return reasons

    def _attach_manual_review(self, subject: Dict[str, Any], prediction: Dict[str, Any]) -> None:
        reasons = self._manual_review_reasons(subject, prediction)
        prediction["manual_review_recommended"] = bool(reasons)
        prediction["manual_review_reasons"] = reasons

    @staticmethod
    def _confidence_interval(predicted_price: Optional[float], confidence: float) -> Dict[str, float] | None:
        if predicted_price is None or predicted_price <= 0:
            return None
        width_ratio = max(0.04, min(0.25, 0.22 * (1 - confidence) + 0.05))
        lower = round(predicted_price * (1 - width_ratio), 2)
        upper = round(predicted_price * (1 + width_ratio), 2)
        return {"p10": lower, "p90": upper}

    @staticmethod
    def _normalize_evaluate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        subject = payload.get("subject") if isinstance(payload.get("subject"), dict) else {}
        auction = payload.get("auction") if isinstance(payload.get("auction"), dict) else {}
        risk_flags = payload.get("risk_flags") if isinstance(payload.get("risk_flags"), dict) else {}
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}

        normalized: Dict[str, Any] = {
            "item_id": payload.get("item_id") or payload.get("id") or payload.get("request_id") or "request_subject",
            "city": subject.get("city"),
            "district": subject.get("district"),
            "business_area": subject.get("business_area") or subject.get("biz_circle"),
            "community_name": subject.get("community_name"),
            "latitude": subject.get("latitude"),
            "longitude": subject.get("longitude"),
            "area_sqm": subject.get("area_sqm"),
            "gross_area_sqm": subject.get("gross_area_sqm"),
            "ownership_share_ratio": subject.get("ownership_share_ratio"),
            "build_year": subject.get("build_year"),
            "total_floors": subject.get("total_floors"),
            "floor_level": subject.get("floor_level") or subject.get("floor"),
            "housing_type": subject.get("housing_type") or "住宅",
            "has_elevator": subject.get("has_elevator"),
            "orientation": subject.get("orientation"),
            "layout": subject.get("layout"),
            "includes_parking": subject.get("includes_parking"),
            "special_school_tag": subject.get("special_school_tag"),
            "has_keys": subject.get("has_keys"),
            "bid_count": subject.get("bid_count"),
            "apply_count": subject.get("apply_count"),
            "starting_price": auction.get("starting_price"),
            "auction_date": auction.get("auction_date"),
            "actual_paid_price": auction.get("actual_paid_price"),
            "evaluation_price": auction.get("evaluation_price"),
            "deposit": auction.get("deposit"),
            "auction_round": auction.get("auction_round"),
            "tax_burden": risk_flags.get("tax_burden", auction.get("tax_burden")),
            "valuation_mode": options.get("valuation_mode") or payload.get("valuation_mode") or "current_market",
        }

        normalized.update(risk_flags)
        if "has_property_fee_arrears" in risk_flags and "property_fee_owed" not in normalized:
            normalized["property_fee_owed"] = risk_flags.get("has_property_fee_arrears")
        return normalized

    @staticmethod
    def _build_risk_validation(subject: Dict[str, Any]) -> Dict[str, Any]:
        risk_data = {field: subject.get(field) for field in RISK_FEATURE_RULES.keys()}
        ok, errors = validate_risk_features(risk_data)
        required_fields = [field for field, rule in RISK_FEATURE_RULES.items() if rule.get("required")]
        missing_required_fields = [field for field in required_fields if risk_data.get(field) is None]
        invalid_fields = sorted(
            {
                error.split(":", 1)[0]
                for error in errors
                if ":" in error and "缺失必填字段" not in error and not error.startswith("存在未定义字段")
            }
        )
        feature_completeness = 1.0
        if required_fields:
            feature_completeness = max(0.0, (len(required_fields) - len(missing_required_fields)) / len(required_fields))
        missing_ratio = 0.0 if not required_fields else len(missing_required_fields) / len(required_fields)
        invalid_ratio = 0.0 if not required_fields else min(len(invalid_fields) / len(required_fields), 1.0)
        confidence_factor = max(0.7, 1.0 - 0.18 * missing_ratio - 0.22 * invalid_ratio)
        return {
            "ok": ok,
            "missing_required_count": len(missing_required_fields),
            "invalid_field_count": len(invalid_fields),
            "feature_completeness": round(feature_completeness, 4),
            "missing_required_fields": missing_required_fields,
            "invalid_fields": invalid_fields,
            "errors": errors,
            "confidence_factor": round(confidence_factor, 4),
        }

    @staticmethod
    def _public_risk_validation_payload(risk_validation: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "ok": bool(risk_validation.get("ok")),
            "missing_required_count": int(risk_validation.get("missing_required_count") or 0),
            "invalid_field_count": int(risk_validation.get("invalid_field_count") or 0),
            "feature_completeness": float(risk_validation.get("feature_completeness") or 0.0),
            "missing_required_fields": list(risk_validation.get("missing_required_fields") or []),
            "invalid_fields": list(risk_validation.get("invalid_fields") or []),
        }

    @staticmethod
    def _build_risk_adjustments(subject: Dict[str, Any]) -> List[Dict[str, Any]]:
        adjustments: List[Dict[str, Any]] = []
        for key, (impact, description) in RISK_IMPACT_MAP.items():
            if subject.get(key) is True:
                adjustments.append(
                    {
                        "tag": key,
                        "impact": impact,
                        "description": description,
                    }
                )
        return adjustments

    def evaluate_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self._evaluate_requests += 1
        started = time.perf_counter()
        normalized = self._normalize_evaluate_payload(payload)
        prediction = self.predict_by_item_data(normalized)
        risk_validation_internal = self._build_risk_validation(normalized)
        risk_validation = self._public_risk_validation_payload(risk_validation_internal)

        predicted_price = prediction.get("predicted_price")
        predicted_unit_price = prediction.get("predicted_unit_price")
        confidence = float(prediction.get("confidence") or 0.0) * float(risk_validation_internal["confidence_factor"])
        confidence = max(0.0, min(confidence, 1.0))
        starting_price = normalized.get("starting_price")
        margin_ratio = prediction.get("margin_of_safety")
        margin_amount = None
        if predicted_price and starting_price:
            try:
                margin_amount = round(float(predicted_price) - float(starting_price), 2)
            except (TypeError, ValueError):
                margin_amount = None

        response = {
            "request_id": payload.get("request_id"),
            "model_version": MODEL_VERSION,
            "valuation": {
                "estimated_fair_price": predicted_price,
                "estimated_unit_price": predicted_unit_price,
                "price_confidence": round(confidence, 4),
                "confidence_interval": self._confidence_interval(predicted_price, confidence),
            },
            "margin_of_safety": {
                "amount": margin_amount,
                "ratio": margin_ratio,
                "level": self._margin_level(margin_ratio),
            },
            "risk_adjustments": self._build_risk_adjustments(normalized),
            "risk_validation": risk_validation,
            "manual_review": {
                "recommended": bool(prediction.get("manual_review_recommended")),
                "reasons": list(prediction.get("manual_review_reasons") or []),
            },
            "trace": {
                "neighbor_sample_count": prediction.get("comparable_count"),
                "subject_coordinate_strategy": prediction.get("trace", {}).get("subject_coordinate_strategy"),
                "strategy": prediction.get("strategy"),
                "valuation_mode": prediction.get("trace", {}).get("valuation_mode"),
                "temporal_reference_mode": prediction.get("trace", {}).get("temporal_reference_mode"),
                "temporal_target_date": prediction.get("trace", {}).get("temporal_target_date"),
                "future_dated_comparable_count_excluded": prediction.get("trace", {}).get("future_dated_comparable_count_excluded"),
                "top_factors": prediction.get("top_factors", []),
            },
        }
        if risk_validation["missing_required_count"] > 0 and "risk_feature_incomplete" not in response["manual_review"]["reasons"]:
            response["manual_review"]["reasons"].append("risk_feature_incomplete")
        if risk_validation["invalid_field_count"] > 0 and "risk_feature_invalid" not in response["manual_review"]["reasons"]:
            response["manual_review"]["reasons"].append("risk_feature_invalid")
        if risk_validation["missing_required_count"] > 0 or risk_validation["invalid_field_count"] > 0:
            response["manual_review"]["recommended"] = True
        self._evaluate_total_ms += (time.perf_counter() - started) * 1000
        return response


__all__ = ["AVMReviewMixin"]
