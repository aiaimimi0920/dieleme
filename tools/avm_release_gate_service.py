"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_release_gate_context import *


def generate_release_gate_report(
    data_root: Path,
    eval_report_path: Path,
    gate_report_path: Path,
    window_days: int = 7,
    min_sample_size: int = 1000,
    smoke_sample_size: int = 8,
    reuse_eval_report: bool = False,
    reuse_drift_report: bool = False,
    thresholds: GateThresholds | None = None,
) -> dict[str, Any]:
    thresholds = thresholds or GateThresholds()

    recent_records = _load_recent_canonical_records(data_root, window_days)
    completeness = build_completeness_report(recent_records, thresholds, min_sample_size)

    if reuse_eval_report and eval_report_path.exists():
        eval_report = json.loads(eval_report_path.read_text(encoding="utf-8"))
    else:
        eval_report = generate_eval_report(
            BacktestConfig(
                data_root=data_root,
                report_path=eval_report_path,
                min_train_months=6,
                max_candidates_per_subject=320,
            )
        )
    eval_gate = build_eval_gate(eval_report.get("metrics", {}), thresholds)

    drift_output_path = data_root / "avm" / "drift_alerts.json"
    if reuse_drift_report and drift_output_path.exists():
        drift_report = json.loads(drift_output_path.read_text(encoding="utf-8"))
    else:
        drift_report = generate_drift_report(
            archive_dir=data_root / "archive",
            output_path=drift_output_path,
            window_days=30,
        )
    drift_gate = {
        "alert_count": len(drift_report.get("alerts", [])),
        "pass": len(drift_report.get("alerts", [])) <= thresholds.drift_alert_budget,
    }

    api_smoke = run_api_smoke(data_root, thresholds, smoke_sample_size)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": window_days,
        "thresholds": thresholds.__dict__,
        "analysis_readiness": _analysis_readiness_context(data_root, window_days),
        "completeness": completeness,
        "evaluation": eval_gate,
        "drift": drift_gate,
        "api_smoke": api_smoke,
        "pass": completeness["pass"] and eval_gate["pass"] and api_smoke["pass"] and drift_gate["pass"],
    }
    gate_report_path.parent.mkdir(parents=True, exist_ok=True)
    gate_report_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


__all__ = (
    "generate_release_gate_report",
)
