import glob
import json
import os
import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from src.avm_config import get_effective_risk_discount_factor, get_effective_weighting

from .canonical_mapper import map_raw_to_canonical
from .feature_builder import build_features
from .engine import get_active_risk_factor_overrides, predict_fair_price
from .quality import price_plausibility
from .risk_schema import RISK_FEATURE_RULES, validate_risk_features

MODEL_VERSION = "avm_multidim_v1"
MAX_CANDIDATE_POOL = 5000
GLOBAL_RECENT_CANDIDATES = 5000

RISK_IMPACT_MAP = {
    "is_occupied": (-0.12, "存在占用，处置周期与交付风险上升"),
    "has_long_lease": (-0.14, "长期租约会拉低可回收价值"),
    "is_restricted_purchase": (-0.03, "限购会压缩潜在买家池并影响流动性"),
    "property_fee_owed": (-0.03, "欠费可能抬升实际支付总价"),
    "tax_is_company_owned": (-0.06, "企业产权可能带来额外税费"),
    "is_fractional_share": (-0.17, "部分产权显著影响流动性"),
    "has_lease_before_mortgage": (0.04, "先抵后租具备一定套利修正"),
}


class AVMService:
    def __init__(self, data_dir: str = "datas", repository: Any = None) -> None:
        self.data_dir = data_dir
        self.repository = repository
        self._feature_cache: List[Dict[str, Any]] | None = None
        self._feature_cache_signature: Tuple[Tuple[str, float], ...] | None = None
        self._centroid_cache: Dict[str, Tuple[float, float]] | None = None
        self._centroid_cache_signature: Tuple[Any, ...] | None = None
        self._candidate_indexes: Dict[str, Any] | None = None
        self._candidate_indexes_signature: Tuple[Any, ...] | None = None
        self._feature_cache_hits = 0
        self._feature_cache_misses = 0
        self._predict_requests = 0
        self._evaluate_requests = 0
        self._lookup_requests = 0
        self._predict_total_ms = 0.0
        self._evaluate_total_ms = 0.0
        self._lookup_total_ms = 0.0
        self._strategy_counts: Dict[str, int] = {}
        self._quality_filtered_records = 0

    @staticmethod
    def model_version() -> str:
        return MODEL_VERSION

    @staticmethod
    def _normalize_valuation_mode(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text == "current_market":
            return "current_market"
        if text == "historical_strict":
            return "historical_strict"
        return "current_market"

    @staticmethod
    def _normalized_group_value(value: Any) -> str:
        text = str(value or "").strip()
        if not text or text == "UNK":
            return ""
        return text

    @staticmethod
    def _has_valid_coordinates(record: Dict[str, Any]) -> bool:
        lat = record.get("latitude")
        lon = record.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return False
        return 3.0 <= float(lat) <= 54.5 and 73.0 <= float(lon) <= 136.0

    def _coordinate_group_keys(self, record: Dict[str, Any]) -> List[Tuple[str, str]]:
        community = self._normalized_group_value(record.get("community_name"))
        business_area = self._normalized_group_value(record.get("business_area"))
        district = self._normalized_group_value(record.get("district"))
        city = self._normalized_group_value(record.get("city"))

        keys: List[Tuple[str, str]] = []
        if community:
            keys.append(("community_centroid", f"community::{community}"))
        if city and district and business_area:
            keys.append(("business_area_centroid", f"business::{city}::{district}::{business_area}"))
        if city and district:
            keys.append(("district_centroid", f"district::{city}::{district}"))
        if city:
            keys.append(("city_centroid", f"city::{city}"))
        return keys

    def _build_coordinate_centroids(self, dataset: List[Dict[str, Any]]) -> Dict[str, Tuple[float, float]]:
        aggregates: Dict[str, List[float]] = {}
        for record in dataset:
            if not self._has_valid_coordinates(record):
                continue

            lat = float(record["latitude"])
            lon = float(record["longitude"])
            for _, key in self._coordinate_group_keys(record):
                bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
                bucket[0] += lat
                bucket[1] += lon
                bucket[2] += 1.0

        centroids: Dict[str, Tuple[float, float]] = {}
        for key, (lat_sum, lon_sum, count) in aggregates.items():
            if count <= 0:
                continue
            centroids[key] = (round(lat_sum / count, 6), round(lon_sum / count, 6))
        return centroids

    def _enrich_coordinates(self, record: Dict[str, Any], centroids: Dict[str, Tuple[float, float]]) -> Dict[str, Any]:
        enriched = dict(record)
        if self._has_valid_coordinates(enriched):
            enriched["coordinate_strategy"] = "observed"
            return enriched

        for strategy, key in self._coordinate_group_keys(enriched):
            centroid = centroids.get(key)
            if centroid is None:
                continue
            enriched["latitude"], enriched["longitude"] = centroid
            enriched["coordinate_strategy"] = strategy
            return enriched

        enriched["coordinate_strategy"] = "missing"
        return enriched

    def _iter_data_files(self) -> List[str]:
        candidates = glob.glob(os.path.join(self.data_dir, "*.json"))
        archive_candidates = glob.glob(os.path.join(self.data_dir, "archive", "**", "*.json"), recursive=True)
        files = candidates + archive_candidates

        skip_names = {
            "all_locations.json",
            "sniff_progress.json",
            "collected_locations.json",
            "model_config.json",
            "tuning_history.json",
            "seen_ids.json",
        }
        return [path for path in files if os.path.basename(path) not in skip_names]

    def _iter_raw_record_stream(self) -> Iterator[Dict[str, Any]]:
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                if hasattr(self.repository, "yield_flat_items"):
                    yielded_any = False
                    for item in self.repository.yield_flat_items():
                        yielded_any = True
                        if isinstance(item, dict):
                            yield item
                    if yielded_any:
                        return
                records = self.repository.iter_flat_items()
                if records:
                    for item in records:
                        if isinstance(item, dict):
                            yield item
                    return
            except Exception:
                pass
        for path in self._iter_data_files():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            yield item
            except Exception:
                continue

    def _iter_raw_records(self) -> List[Dict[str, Any]]:
        return list(self._iter_raw_record_stream())

    def _iter_feature_source_stream(self) -> Iterator[Dict[str, Any]]:
        if self.repository and getattr(self.repository, "enabled", False) and hasattr(self.repository, "yield_feature_source_rows"):
            try:
                if hasattr(self.repository, "yield_analysis_ready_rows"):
                    yielded_ready = False
                    for item in self.repository.yield_analysis_ready_rows():
                        yielded_ready = True
                        if isinstance(item, dict):
                            yield item
                    if yielded_ready:
                        return
                yielded_any = False
                for item in self.repository.yield_feature_source_rows():
                    yielded_any = True
                    if isinstance(item, dict):
                        yield item
                if yielded_any:
                    return
            except Exception:
                pass

        for raw in self._iter_raw_record_stream():
            try:
                yield map_raw_to_canonical(raw)
            except Exception:
                continue

    def _dataset_signature(self) -> Tuple[Any, ...]:
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                count_value, max_synced = self.repository.dataset_signature()
                if count_value > 0:
                    return ("db", count_value, max_synced)
            except Exception:
                pass
        files = self._iter_data_files()
        return tuple(sorted((path, os.path.getmtime(path)) for path in files if os.path.exists(path)))

    @staticmethod
    def _record_sort_key(record: Dict[str, Any]) -> Tuple[str, str]:
        return (str(record.get("auction_date") or ""), str(record.get("item_id") or ""))

    def _build_candidate_indexes(self, dataset: List[Dict[str, Any]], signature: Tuple[Any, ...]) -> Dict[str, Any]:
        if self._candidate_indexes is not None and self._candidate_indexes_signature == signature:
            return self._candidate_indexes

        community_index: Dict[str, List[Dict[str, Any]]] = {}
        business_index: Dict[str, List[Dict[str, Any]]] = {}
        district_index: Dict[str, List[Dict[str, Any]]] = {}
        city_index: Dict[str, List[Dict[str, Any]]] = {}

        ordered = sorted(dataset, key=self._record_sort_key, reverse=True)
        for record in ordered:
            community = self._normalized_group_value(record.get("community_name"))
            business_area = self._normalized_group_value(record.get("business_area"))
            district = self._normalized_group_value(record.get("district"))
            city = self._normalized_group_value(record.get("city"))

            if community:
                community_index.setdefault(community, []).append(record)
            if city and district and business_area:
                business_index.setdefault(f"{city}::{district}::{business_area}", []).append(record)
            if city and district:
                district_index.setdefault(f"{city}::{district}", []).append(record)
            if city:
                city_index.setdefault(city, []).append(record)

        indexes = {
            "community": community_index,
            "business": business_index,
            "district": district_index,
            "city": city_index,
            "global_recent": ordered[:GLOBAL_RECENT_CANDIDATES],
        }
        self._candidate_indexes = indexes
        self._candidate_indexes_signature = signature
        return indexes

    def _build_feature_dataset(self) -> List[Dict[str, Any]]:
        signature = self._dataset_signature()
        if self._feature_cache is not None and signature == self._feature_cache_signature:
            self._feature_cache_hits += 1
            return list(self._feature_cache)

        self._feature_cache_misses += 1
        dataset: List[Dict[str, Any]] = []
        filtered_count = 0
        for canonical in self._iter_feature_source_stream():
            try:
                f = build_features(canonical)
            except Exception:
                continue
            passed, _ = price_plausibility(f)
            if not passed:
                filtered_count += 1
                continue
            dataset.append(f)
        centroids = self._build_coordinate_centroids(dataset)
        dataset = [self._enrich_coordinates(record, centroids) for record in dataset]
        self._feature_cache = list(dataset)
        self._feature_cache_signature = signature
        self._centroid_cache = centroids
        self._centroid_cache_signature = signature
        self._build_candidate_indexes(dataset, signature)
        self._quality_filtered_records = filtered_count
        return dataset

    def ensure_coordinate_cache(self, allow_file_fallback: bool = True) -> Dict[str, Tuple[float, float]]:
        signature = self._dataset_signature()
        if self._centroid_cache is not None and signature == self._centroid_cache_signature:
            return dict(self._centroid_cache)

        if self.repository and getattr(self.repository, "enabled", False) and hasattr(self.repository, "build_coordinate_centroids"):
            try:
                centroids = self.repository.build_coordinate_centroids()
                self._centroid_cache = centroids
                self._centroid_cache_signature = signature
                if centroids:
                    return dict(centroids)
            except Exception:
                pass

        aggregates: Dict[str, List[float]] = {}
        if self.repository and getattr(self.repository, "enabled", False) and hasattr(self.repository, "yield_coordinate_rows"):
            try:
                for feature in self.repository.yield_coordinate_rows():
                    if not self._has_valid_coordinates(feature):
                        continue
                    lat = float(feature["latitude"])
                    lon = float(feature["longitude"])
                    for _, key in self._coordinate_group_keys(feature):
                        bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
                        bucket[0] += lat
                        bucket[1] += lon
                        bucket[2] += 1.0
            except Exception:
                aggregates = {}

        if allow_file_fallback and not aggregates:
            for raw in self._iter_raw_record_stream():
                try:
                    feature = map_raw_to_canonical(raw)
                except Exception:
                    continue
                if not self._has_valid_coordinates(feature):
                    continue
                lat = float(feature["latitude"])
                lon = float(feature["longitude"])
                for _, key in self._coordinate_group_keys(feature):
                    bucket = aggregates.setdefault(key, [0.0, 0.0, 0.0])
                    bucket[0] += lat
                    bucket[1] += lon
                    bucket[2] += 1.0

        centroids: Dict[str, Tuple[float, float]] = {}
        for key, (lat_sum, lon_sum, count) in aggregates.items():
            if count <= 0:
                continue
            centroids[key] = (round(lat_sum / count, 6), round(lon_sum / count, 6))

        self._centroid_cache = centroids
        self._centroid_cache_signature = signature
        return dict(centroids)

    def _candidate_pool(self, subject: Dict[str, Any], dataset: List[Dict[str, Any]], signature: Tuple[Any, ...]) -> List[Dict[str, Any]]:
        if len(dataset) <= MAX_CANDIDATE_POOL:
            return dataset

        indexes = self._build_candidate_indexes(dataset, signature)
        candidates: Dict[str, Dict[str, Any]] = {}

        community = self._normalized_group_value(subject.get("community_name"))
        business_area = self._normalized_group_value(subject.get("business_area"))
        district = self._normalized_group_value(subject.get("district"))
        city = self._normalized_group_value(subject.get("city"))

        def _extend(records: Iterable[Dict[str, Any]]) -> None:
            for record in records:
                candidates[str(record.get("item_id"))] = record

        if community:
            _extend(indexes["community"].get(community, []))
        if city and district and business_area:
            _extend(indexes["business"].get(f"{city}::{district}::{business_area}", []))
        if city and district:
            _extend(indexes["district"].get(f"{city}::{district}", []))
        if city:
            _extend(indexes["city"].get(city, []))
        if len(candidates) < MAX_CANDIDATE_POOL:
            _extend(indexes["global_recent"])

        ordered = sorted(candidates.values(), key=self._record_sort_key, reverse=True)
        return ordered[:MAX_CANDIDATE_POOL]

    def predict_by_item_data(self, item_data: Dict[str, Any]) -> Dict[str, Any]:
        self._predict_requests += 1
        started = time.perf_counter()
        signature = self._dataset_signature()
        if self._centroid_cache is None:
            self.ensure_coordinate_cache(allow_file_fallback=not bool(self.repository and getattr(self.repository, "enabled", False)))
        subject = build_features(map_raw_to_canonical(item_data))
        subject["valuation_mode"] = self._normalize_valuation_mode(item_data.get("valuation_mode"))
        subject = self._enrich_coordinates(subject, self._centroid_cache or {})
        candidate_dataset: List[Dict[str, Any]] = []
        candidate_source = "feature_cache"

        if self.repository and getattr(self.repository, "enabled", False):
            try:
                if hasattr(self.repository, "iter_analysis_candidate_rows"):
                    repo_rows = self.repository.iter_analysis_candidate_rows(
                        subject,
                        total_limit=MAX_CANDIDATE_POOL,
                    )
                elif hasattr(self.repository, "iter_feature_candidate_rows"):
                    repo_rows = self.repository.iter_feature_candidate_rows(
                        subject,
                        total_limit=MAX_CANDIDATE_POOL,
                    )
                else:
                    repo_rows = []
            except Exception:
                repo_rows = []
            if repo_rows:
                candidate_source = "repository_analysis_candidates" if hasattr(self.repository, "iter_analysis_candidate_rows") else "repository_candidates"
                candidate_dataset = [build_features(row) for row in repo_rows]

        if not candidate_dataset:
            dataset = self._build_feature_dataset()
            candidate_dataset = self._candidate_pool(subject, dataset, signature)

        comparable_dataset = [
            record
            for record in candidate_dataset
            if str(record.get("item_id")) != str(subject.get("item_id"))
        ]
        result = predict_fair_price(subject, comparable_dataset)
        result["risk_validation"] = self._public_risk_validation_payload(self._build_risk_validation(subject))
        result["item_id"] = str(subject.get("item_id"))
        result["id"] = str(subject.get("item_id"))
        result.setdefault("trace", {})
        result["trace"]["subject_coordinate_strategy"] = subject.get("coordinate_strategy", "missing")
        result["trace"]["candidate_source"] = candidate_source
        self._attach_manual_review(subject, result)
        strategy = str(result.get("strategy") or "unknown")
        self._strategy_counts[strategy] = self._strategy_counts.get(strategy, 0) + 1

        starting_price = subject.get("starting_price")
        predicted_price = result.get("predicted_price")
        if starting_price and predicted_price:
            try:
                result["margin_of_safety"] = round(
                    (float(predicted_price) - float(starting_price)) / float(predicted_price),
                    4,
                )
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        result.setdefault("trace", {})
        result["trace"]["candidate_pool_size"] = len(candidate_dataset)
        self._predict_total_ms += (time.perf_counter() - started) * 1000
        return result

    def predict_by_item_id(self, item_id: str) -> Dict[str, Any]:
        self._lookup_requests += 1
        started = time.perf_counter()
        subject: Optional[Dict[str, Any]] = None
        if self.repository and getattr(self.repository, "enabled", False):
            try:
                subject = self.repository.get_flat_item(str(item_id))
            except Exception:
                subject = None
        if subject is None:
            for raw in self._iter_raw_record_stream():
                raw_id = raw.get("id") or raw.get("唯一id") or raw.get("item_id")
                if str(raw_id) == str(item_id):
                    subject = raw
                    break
        if not subject:
            self._lookup_total_ms += (time.perf_counter() - started) * 1000
            return {"error": "item_not_found", "item_id": str(item_id)}
        result = self.predict_by_item_data(subject)
        self._lookup_total_ms += (time.perf_counter() - started) * 1000
        return result

    def _summarize_dataset(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        observed = 0
        centroid_filled = 0
        missing = 0
        coordinate_strategy_counts: Dict[str, int] = {}
        risk_validation_counts = {"ok": 0, "incomplete": 0, "invalid": 0}
        risk_feature_completeness_total = 0.0
        for record in dataset:
            strategy = record.get("coordinate_strategy")
            strategy_key = str(strategy or "missing")
            coordinate_strategy_counts[strategy_key] = coordinate_strategy_counts.get(strategy_key, 0) + 1
            if strategy == "observed":
                observed += 1
            elif strategy == "missing":
                missing += 1
            else:
                centroid_filled += 1
            risk_validation = self._build_risk_validation(record)
            if risk_validation["invalid_field_count"] > 0:
                risk_validation_counts["invalid"] += 1
            elif risk_validation["ok"]:
                risk_validation_counts["ok"] += 1
            else:
                risk_validation_counts["incomplete"] += 1
            risk_feature_completeness_total += float(risk_validation["feature_completeness"])
        return {
            "dataset_size": len(dataset),
            "coordinate_observed": observed,
            "coordinate_centroid_filled": centroid_filled,
            "coordinate_missing": missing,
            "coordinate_strategy_counts": dict(sorted(coordinate_strategy_counts.items())),
            "risk_validation_counts": risk_validation_counts,
            "risk_feature_completeness_avg": round(
                risk_feature_completeness_total / max(len(dataset), 1),
                4,
            ),
        }

    def health_snapshot(self, lightweight: bool = False) -> Dict[str, Any]:
        dataset_summary = {
            "dataset_size": 0,
            "coordinate_observed": 0,
            "coordinate_centroid_filled": 0,
            "coordinate_missing": 0,
            "coordinate_strategy_counts": {},
            "risk_validation_counts": {"ok": 0, "incomplete": 0, "invalid": 0},
            "risk_feature_completeness_avg": 0.0,
        }
        feature_cache_ready = self._feature_cache is not None
        if self._feature_cache is not None:
            dataset_summary = self._summarize_dataset(self._feature_cache)
        elif not lightweight:
            dataset = self._build_feature_dataset()
            dataset_summary = self._summarize_dataset(dataset)
            feature_cache_ready = self._feature_cache is not None

        return {
            **dataset_summary,
            "analysis_ready_count": self.repository.count_analysis_ready_items()
            if self.repository and getattr(self.repository, "enabled", False) and hasattr(self.repository, "count_analysis_ready_items")
            else 0,
            "centroid_bucket_count": len(self._centroid_cache or {}),
            "candidate_index_ready": self._candidate_indexes is not None,
            "candidate_index_bucket_count": sum(
                len(index_map)
                for index_map in (
                    (self._candidate_indexes or {}).get("community", {}),
                    (self._candidate_indexes or {}).get("business", {}),
                    (self._candidate_indexes or {}).get("district", {}),
                    (self._candidate_indexes or {}).get("city", {}),
                )
            ),
            "candidate_pool_limit": MAX_CANDIDATE_POOL,
            "model_version": MODEL_VERSION,
            "feature_cache_ready": feature_cache_ready,
            "feature_cache_hits": self._feature_cache_hits,
            "feature_cache_misses": self._feature_cache_misses,
            "feature_cache_hit_rate": round(
                self._feature_cache_hits / max(self._feature_cache_hits + self._feature_cache_misses, 1),
                4,
            ),
            "predict_requests": self._predict_requests,
            "evaluate_requests": self._evaluate_requests,
            "lookup_requests": self._lookup_requests,
            "avg_predict_time_ms": round(self._predict_total_ms / max(self._predict_requests, 1), 2),
            "avg_evaluate_time_ms": round(self._evaluate_total_ms / max(self._evaluate_requests, 1), 2),
            "avg_lookup_time_ms": round(self._lookup_total_ms / max(self._lookup_requests, 1), 2),
            "strategy_counts": dict(sorted(self._strategy_counts.items())),
            "quality_filtered_records": self._quality_filtered_records,
            "active_weighting": get_effective_weighting(),
            "active_risk_discount_factor": get_effective_risk_discount_factor(0.9),
            "active_risk_factor_override_count": len(get_active_risk_factor_overrides()),
            "active_risk_factor_overrides": get_active_risk_factor_overrides(),
        }

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
