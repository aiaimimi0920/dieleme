import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.avm.normalize import parse_money_to_yuan
from src.avm.alert_policy import build_alert_blockers
from src.avm_config import DEFAULT_AVM_CONFIG
from src.avm.risk_schema import RISK_FEATURE_RULES, validate_risk_features
from src.avm.service import AVMService
from src.storage.repository import create_repository_from_env
from tools.avm_data_loader import iter_analysis_ready_rows, iter_raw_record_rows
from tools.build_avm_features import build_avm_features
from tools.build_canonical_dataset import build_canonical_dataset
from tools.generate_avm_alerts import generate_avm_alerts
from tools.evaluate_avm import BacktestConfig, generate_report
from tools.avm_release_gate import GateThresholds, build_eval_gate, generate_release_gate_report
from tools.apply_avm_calibration_patch import (
    apply_command_chain_next_action_policy,
    apply_avm_calibration_patch,
    normalize_calibration_targets_payload,
    resolve_command_chain_artifacts,
    summarize_bundle_command_summary,
    summarize_patch_command_chain,
    summarize_patch_follow_up_command,
    summarize_patch_next_action,
    summarize_patch_next_action_command,
    summarize_patch_risk,
)
from tools.suggest_avm_calibration_targets import suggest_calibration_targets


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


def _run_risk_stage(data_dir: str, output_path: str, summary_path: str) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    records = 0
    valid = 0
    invalid = 0
    missing_counter = {field: 0 for field in RISK_FEATURE_RULES.keys()}
    with open(output_path, "w", encoding="utf-8") as fout:
        for row in iter_raw_record_rows(Path(data_dir), prefer_db=True):
            if not isinstance(row, dict):
                continue

            risk = _extract_risk_fields(row)
            ok, errors = validate_risk_features(risk)
            records += 1
            if ok:
                valid += 1
            else:
                invalid += 1
            for key, value in risk.items():
                if value is None:
                    missing_counter[key] += 1

            fout.write(
                json.dumps(
                    {
                        "item_id": str(row.get("id") or row.get("唯一id") or row.get("item_id") or ""),
                        "risk_features": risk,
                        "validation_ok": ok,
                        "error_count": len(errors),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    summary = {
        "total_records": records,
        "valid_records": valid,
        "invalid_records": invalid,
        "missing_field_count": missing_counter,
    }
    with open(summary_path, "w", encoding="utf-8") as fsum:
        json.dump(summary, fsum, ensure_ascii=False, indent=2)

    return {"output_path": output_path, "summary_path": summary_path, "summary": summary}


def _run_predict_stage(data_dir: str, output_path: str, limit: int) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    service = AVMService(data_dir=data_dir, repository=create_repository_from_env())
    rows = _load_candidates(data_dir, limit=limit)

    total = 0
    predicted = 0
    with_price = 0

    with open(output_path, "w", encoding="utf-8") as fout:
        for row in rows:
            item_id = str(row.get("id") or row.get("唯一id") or row.get("item_id") or "")
            if not item_id:
                continue
            result = service.predict_by_item_data(row)
            total += 1
            if result.get("predicted_price"):
                predicted += 1

            starting_price = parse_money_to_yuan(row.get("起拍价格") or row.get("starting_price") or row.get("initialPrice"))
            if starting_price:
                with_price += 1

            rec = {
                "item_id": item_id,
                "starting_price": starting_price,
                "prediction": result,
            }
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = {
        "total_candidates": total,
        "predicted_count": predicted,
        "with_starting_price": with_price,
    }
    return {"output_path": output_path, "summary": summary}


def _run_alert_stage(predictions_path: str, output_path: str, threshold: float) -> Dict[str, Any]:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    alerts: List[Dict[str, Any]] = []
    total = 0
    blocked_reason_counts: Dict[str, int] = {}

    with open(predictions_path, "r", encoding="utf-8") as fin:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            total += 1
            row = json.loads(line)
            pred = (row.get("prediction") or {}).get("predicted_price")
            starting = row.get("starting_price")
            if not pred or not starting:
                continue
            margin = (pred - starting) / pred
            blockers = build_alert_blockers(
                margin=margin,
                threshold=threshold,
                is_malignant_risk=bool((row.get("prediction") or {}).get("is_malignant_risk")),
                payload=row.get("prediction") if isinstance(row.get("prediction"), dict) else row,
            )
            if blockers:
                for blocker in blockers:
                    blocked_reason_counts[blocker] = int(blocked_reason_counts.get(blocker, 0) or 0) + 1
                continue
            alerts.append(
                {
                    "item_id": row.get("item_id"),
                    "predicted_price": pred,
                    "starting_price": starting,
                    "margin_of_safety": round(margin, 4),
                    "confidence": (row.get("prediction") or {}).get("confidence"),
                    "comparable_count": (row.get("prediction") or {}).get("comparable_count"),
                }
            )

    alerts.sort(key=lambda x: x["margin_of_safety"], reverse=True)
    payload = {
        "threshold": threshold,
        "count": len(alerts),
        "evaluated": total,
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "alerts": alerts,
    }
    with open(output_path, "w", encoding="utf-8") as fout:
        json.dump(payload, fout, ensure_ascii=False, indent=2)

    return {
        "output_path": output_path,
        "summary": {
            "evaluated": total,
            "alerts": len(alerts),
            "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        },
    }


def _run_evaluate_stage(data_dir: str, output_path: str) -> Dict[str, Any]:
    report = generate_report(
        BacktestConfig(
            data_root=Path(data_dir),
            report_path=Path(output_path),
        )
    )
    return {
        "output_path": output_path,
        "summary": {
            "backtest_sample_count": report["data_summary"]["backtest_sample_count"],
            "valuation_mode_sample_counts": report["data_summary"]["valuation_mode_sample_counts"],
        },
        "report": report,
    }


def _run_calibration_stage(eval_report_path: str, output_path: str) -> Dict[str, Any]:
    report = json.loads(Path(eval_report_path).read_text(encoding="utf-8"))
    result = normalize_calibration_targets_payload(suggest_calibration_targets(report.get("metrics", {}) or {}))
    gate_eval = build_eval_gate(report.get("metrics", {}) or {}, GateThresholds())
    global_risk_targets = list(result.get("global_risk_targets") or [])
    risk_factor_targets = list(result.get("risk_factor_targets") or [])
    temporal_targets = list(result.get("temporal_targets") or [])
    strategy_targets = list(result.get("strategy_targets") or [])
    has_recommendations = bool(global_risk_targets or risk_factor_targets or temporal_targets or strategy_targets)
    top_target = result.get("top_calibration_target") if isinstance(result.get("top_calibration_target"), dict) else {}
    top_target_hint = result.get("top_calibration_target_hint") if isinstance(result.get("top_calibration_target_hint"), dict) else {}
    recommended_bundle = top_target_hint.get("recommended_bundle") if isinstance(top_target_hint.get("recommended_bundle"), dict) else {}
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if recommended_bundle:
        config_path = Path(output_path).with_name("config.json")
        if config_path.exists() and not _json_file_is_object(config_path):
            with tempfile.TemporaryDirectory() as tmpdir:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
                bundle_preview = apply_avm_calibration_patch(
                    config_path=temp_config_path,
                    calibration_path=Path(output_path),
                    write_back=False,
                    target_types=list(recommended_bundle.get("target_types") or []),
                    target_names=list(recommended_bundle.get("target_names") or []),
                )
        else:
            bundle_preview = apply_avm_calibration_patch(
                config_path=config_path,
                calibration_path=Path(output_path),
                write_back=False,
                target_types=list(recommended_bundle.get("target_types") or []),
                target_names=list(recommended_bundle.get("target_names") or []),
            )
    else:
        bundle_preview = {}
    recommended_bundle_primary_change, recommended_bundle_secondary_changes = _bundle_change_summary(bundle_preview)
    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = _bundle_command_summary(top_target_hint)
    recommended_bundle_risk = summarize_patch_risk(bundle_preview)
    recommended_bundle_next_action = summarize_patch_next_action(recommended_bundle_risk, bundle_preview)
    next_action_command = summarize_patch_next_action_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
    )
    follow_up_command = summarize_patch_follow_up_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
        verify_command=recommended_bundle_verify_command,
    )
    command_chain = summarize_patch_command_chain(
        next_action_command=str(next_action_command.get("next_action_command") or ""),
        next_action_command_kind=str(next_action_command.get("next_action_command_kind") or "none"),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(follow_up_command.get("follow_up_command_kind") or "none"),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, Path(output_path).parent.parent)
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        "output_path": output_path,
        "summary": {
            "has_recommendations": has_recommendations,
            "global_risk_target_count": len(global_risk_targets),
            "risk_factor_target_count": len(risk_factor_targets),
            "temporal_target_count": len(temporal_targets),
            "strategy_target_count": len(strategy_targets),
            "guidance_status": str((result.get("guidance") or {}).get("status") or "unknown"),
            "coordinate_strategy_watchlist": list(gate_eval.get("coordinate_strategy_watchlist") or []),
            "top_coordinate_strategy_group": gate_eval.get("top_coordinate_strategy_group"),
            "top_target_name": str(top_target.get("name") or ""),
            "top_target_type": str(top_target.get("target_type") or ""),
            "top_target_hint_status": str(top_target_hint.get("status") or "unknown"),
            "top_target_playbook_id": str(top_target_hint.get("playbook_id") or "unknown"),
            "recommended_bundle_id": str(recommended_bundle.get("bundle_id") or ""),
            "recommended_bundle_changed_key_count": int(bundle_preview.get("changed_key_count") or 0),
            "recommended_bundle_primary_change": recommended_bundle_primary_change,
            "recommended_bundle_secondary_changes": recommended_bundle_secondary_changes,
            "recommended_bundle_preview_command": recommended_bundle_preview_command,
            "recommended_bundle_write_command": recommended_bundle_write_command,
            "recommended_bundle_verify_command": recommended_bundle_verify_command,
            "recommended_bundle_gate_command": recommended_bundle_gate_command,
            "recommended_bundle_risk_level": str(recommended_bundle_risk.get("risk_level") or "none"),
            "recommended_bundle_risk_reasons": list(recommended_bundle_risk.get("risk_reasons") or []),
            "recommended_bundle_next_action": str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
            "recommended_bundle_next_action_reasons": list(recommended_bundle_next_action.get("next_action_reasons") or []),
            "recommended_bundle_next_action_command": str(next_action_command.get("next_action_command") or ""),
            "recommended_bundle_next_action_command_kind": str(next_action_command.get("next_action_command_kind") or "none"),
            "recommended_bundle_follow_up_command": str(follow_up_command.get("follow_up_command") or ""),
            "recommended_bundle_follow_up_command_kind": str(follow_up_command.get("follow_up_command_kind") or "none"),
            "recommended_bundle_command_chain": command_chain,
        },
        "report": result,
    }


def _run_gate_stage(data_dir: str, eval_report_path: str, output_path: str) -> Dict[str, Any]:
    report = generate_release_gate_report(
        data_root=Path(data_dir),
        eval_report_path=Path(eval_report_path),
        gate_report_path=Path(output_path),
        smoke_sample_size=0,
        reuse_eval_report=True,
    )
    evaluation = report.get("evaluation") if isinstance(report.get("evaluation"), dict) else {}
    calibration_targets_path = Path(data_dir) / "avm" / "calibration_targets.json"
    raw_embedded_calibration_targets = (
        evaluation.get("calibration_targets") if isinstance(evaluation.get("calibration_targets"), dict) else {}
    )
    loaded_calibration_targets: dict[str, Any] = {}
    if calibration_targets_path.exists():
        try:
            raw_loaded_calibration_targets = json.loads(calibration_targets_path.read_text(encoding="utf-8"))
            if isinstance(raw_loaded_calibration_targets, dict):
                loaded_calibration_targets = normalize_calibration_targets_payload(raw_loaded_calibration_targets)
        except json.JSONDecodeError:
            loaded_calibration_targets = {}
    if loaded_calibration_targets:
        def _merge_calibration_targets(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
            merged = dict(fallback)
            for key, value in preferred.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = _merge_calibration_targets(value, merged[key])
                else:
                    merged[key] = value
            return merged

        calibration_targets = normalize_calibration_targets_payload(
            _merge_calibration_targets(raw_embedded_calibration_targets, loaded_calibration_targets)
            if raw_embedded_calibration_targets
            else loaded_calibration_targets
        )
    else:
        calibration_targets = normalize_calibration_targets_payload(raw_embedded_calibration_targets)
    top_target = calibration_targets.get("top_calibration_target") if isinstance(calibration_targets.get("top_calibration_target"), dict) else {}
    top_target_hint = calibration_targets.get("top_calibration_target_hint") if isinstance(calibration_targets.get("top_calibration_target_hint"), dict) else {}
    guidance = calibration_targets.get("guidance") if isinstance(calibration_targets.get("guidance"), dict) else {}
    global_risk_targets = list(calibration_targets.get("global_risk_targets") or [])
    risk_factor_targets = list(calibration_targets.get("risk_factor_targets") or [])
    temporal_targets = list(calibration_targets.get("temporal_targets") or [])
    strategy_targets = list(calibration_targets.get("strategy_targets") or [])
    recommended_bundle = top_target_hint.get("recommended_bundle") if isinstance(top_target_hint.get("recommended_bundle"), dict) else {}
    config_path = Path(data_dir) / "avm" / "config.json"
    use_temp_config_path = config_path.exists() and not _json_file_is_object(config_path)

    def _build_bundle_preview(config_preview_path: Path, calibration_path: Path) -> dict[str, Any]:
        if not recommended_bundle:
            return {}
        return apply_avm_calibration_patch(
            config_path=config_preview_path,
            calibration_path=calibration_path,
            write_back=False,
            target_types=list(recommended_bundle.get("target_types") or []),
            target_names=list(recommended_bundle.get("target_names") or []),
        )

    use_temp_calibration_path = (
        not calibration_targets_path.exists()
        or calibration_targets != loaded_calibration_targets
    )
    if use_temp_calibration_path or use_temp_config_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            if use_temp_calibration_path:
                temp_calibration_path = Path(tmpdir) / "calibration_targets.json"
                temp_calibration_path.write_text(json.dumps(calibration_targets, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_calibration_path = calibration_targets_path
            if use_temp_config_path:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_config_path = config_path
            bundle_preview = _build_bundle_preview(temp_config_path, temp_calibration_path)
    else:
        bundle_preview = _build_bundle_preview(config_path, calibration_targets_path)
    recommended_bundle_primary_change, recommended_bundle_secondary_changes = _bundle_change_summary(bundle_preview)
    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = _bundle_command_summary(top_target_hint)
    recommended_bundle_risk = summarize_patch_risk(bundle_preview)
    recommended_bundle_next_action = summarize_patch_next_action(recommended_bundle_risk, bundle_preview)
    next_action_command = summarize_patch_next_action_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
    )
    follow_up_command = summarize_patch_follow_up_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
        verify_command=recommended_bundle_verify_command,
    )
    command_chain = summarize_patch_command_chain(
        next_action_command=str(next_action_command.get("next_action_command") or ""),
        next_action_command_kind=str(next_action_command.get("next_action_command_kind") or "none"),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(follow_up_command.get("follow_up_command_kind") or "none"),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, Path(data_dir))
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        "output_path": output_path,
        "summary": {
            "has_recommendations": bool(calibration_targets.get("has_recommendations")),
            "pass": bool(report.get("pass")),
            "evaluation_pass": bool((report.get("evaluation") or {}).get("pass")),
            "completeness_pass": bool((report.get("completeness") or {}).get("pass")),
            "drift_pass": bool((report.get("drift") or {}).get("pass")),
            "guidance_status": str(guidance.get("status") or "unknown"),
            "global_risk_target_count": len(global_risk_targets),
            "risk_factor_target_count": len(risk_factor_targets),
            "temporal_target_count": len(temporal_targets),
            "strategy_target_count": len(strategy_targets),
            "coordinate_strategy_watchlist": list((evaluation.get("coordinate_strategy_watchlist") or [])),
            "top_coordinate_strategy_group": evaluation.get("top_coordinate_strategy_group"),
            "top_target_name": str(top_target.get("name") or ""),
            "top_target_type": str(top_target.get("target_type") or ""),
            "top_target_hint_status": str(top_target_hint.get("status") or "unknown"),
            "top_target_playbook_id": str(top_target_hint.get("playbook_id") or "unknown"),
            "recommended_bundle_id": str(recommended_bundle.get("bundle_id") or ""),
            "recommended_bundle_changed_key_count": int(bundle_preview.get("changed_key_count") or 0),
            "recommended_bundle_primary_change": recommended_bundle_primary_change,
            "recommended_bundle_secondary_changes": recommended_bundle_secondary_changes,
            "recommended_bundle_preview_command": recommended_bundle_preview_command,
            "recommended_bundle_write_command": recommended_bundle_write_command,
            "recommended_bundle_verify_command": recommended_bundle_verify_command,
            "recommended_bundle_gate_command": recommended_bundle_gate_command,
            "recommended_bundle_risk_level": str(recommended_bundle_risk.get("risk_level") or "none"),
            "recommended_bundle_risk_reasons": list(recommended_bundle_risk.get("risk_reasons") or []),
            "recommended_bundle_next_action": str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
            "recommended_bundle_next_action_reasons": list(recommended_bundle_next_action.get("next_action_reasons") or []),
            "recommended_bundle_next_action_command": str(next_action_command.get("next_action_command") or ""),
            "recommended_bundle_next_action_command_kind": str(next_action_command.get("next_action_command_kind") or "none"),
            "recommended_bundle_follow_up_command": str(follow_up_command.get("follow_up_command") or ""),
            "recommended_bundle_follow_up_command_kind": str(follow_up_command.get("follow_up_command_kind") or "none"),
            "recommended_bundle_command_chain": command_chain,
        },
        "report": report,
    }


def run_pipeline(data_dir: str, alerts_threshold: float, predict_limit: int) -> Dict[str, Any]:
    canonical_dir = os.path.join(data_dir, "canonical")
    avm_dir = os.path.join(data_dir, "avm")

    canonical_path = os.path.join(canonical_dir, "canonical.jsonl")
    feature_path = os.path.join(avm_dir, "features.jsonl")
    feature_stats_path = os.path.join(avm_dir, "feature_stats.json")
    risk_path = os.path.join(avm_dir, "risk.jsonl")
    risk_summary_path = os.path.join(avm_dir, "risk_summary.json")
    predictions_path = os.path.join(avm_dir, "predictions.jsonl")
    alerts_path = os.path.join(avm_dir, "alerts.json")
    eval_report_path = os.path.join(avm_dir, "eval_report.json")
    calibration_targets_path = os.path.join(avm_dir, "calibration_targets.json")
    gate_report_path = os.path.join(avm_dir, "release_gate.json")

    stage_results: List[Tuple[str, Dict[str, Any]]] = []

    canonical_result = build_canonical_dataset(data_dir=data_dir, output_dir=canonical_dir)
    stage_results.append(
        (
            "canonical",
            {
                "path": canonical_result["canonical_path"],
                "summary": {
                    "total_records": canonical_result["records_total"],
                    "success_records": canonical_result["records_total"] - canonical_result["failed_records"],
                    "failed_records": canonical_result["failed_records"],
                },
            },
        )
    )

    risk_result = _run_risk_stage(data_dir=data_dir, output_path=risk_path, summary_path=risk_summary_path)
    stage_results.append(("risk", {"path": risk_result["output_path"], "summary": risk_result["summary"]}))

    feature_result = build_avm_features(
        canonical_path=canonical_path,
        output_path=feature_path,
        stats_path=feature_stats_path,
    )
    stage_results.append(("feature", {"path": feature_result["features_path"], "summary": feature_result["stats"]}))

    predict_result = _run_predict_stage(data_dir=data_dir, output_path=predictions_path, limit=predict_limit)
    stage_results.append(("predict", {"path": predict_result["output_path"], "summary": predict_result["summary"]}))

    alert_result = _run_alert_stage(predictions_path=predictions_path, output_path=alerts_path, threshold=alerts_threshold)
    stage_results.append(("alert", {"path": alert_result["output_path"], "summary": alert_result["summary"]}))

    evaluate_result = _run_evaluate_stage(data_dir=data_dir, output_path=eval_report_path)
    stage_results.append(("evaluate", {"path": evaluate_result["output_path"], "summary": evaluate_result["summary"]}))

    calibration_result = _run_calibration_stage(eval_report_path=eval_report_path, output_path=calibration_targets_path)
    stage_results.append(("calibration", {"path": calibration_result["output_path"], "summary": calibration_result["summary"]}))

    gate_result = _run_gate_stage(data_dir=data_dir, eval_report_path=eval_report_path, output_path=gate_report_path)
    stage_results.append(("gate", {"path": gate_result["output_path"], "summary": gate_result["summary"]}))

    return {"data_dir": data_dir, "stages": [{"name": name, **payload} for name, payload in stage_results]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AVM pipeline: canonical -> risk -> feature -> predict -> alert -> evaluate -> calibration -> gate")
    parser.add_argument("--data-dir", default="datas", help="Data directory")
    parser.add_argument("--alerts-threshold", type=float, default=0.15, help="Alert margin threshold")
    parser.add_argument("--predict-limit", type=int, default=500, help="Max candidate rows for prediction stage")
    args = parser.parse_args()

    result = run_pipeline(data_dir=args.data_dir, alerts_threshold=args.alerts_threshold, predict_limit=args.predict_limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
