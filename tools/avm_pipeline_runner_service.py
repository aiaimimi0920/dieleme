"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_pipeline_runner_context import *


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


__all__ = (
    "run_pipeline",
)
