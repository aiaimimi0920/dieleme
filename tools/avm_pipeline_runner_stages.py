"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_pipeline_runner_context import *


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


__all__ = (
    "_run_risk_stage",
    "_run_predict_stage",
    "_run_alert_stage",
    "_run_evaluate_stage",
)
