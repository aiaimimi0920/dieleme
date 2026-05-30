#!/usr/bin/env python3
"""Generate AVM margin-of-safety alerts from recent listings."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm_config import AVM_CONFIG_MANAGER, get_effective_alert_threshold
from src.avm.alert_policy import build_alert_blockers
from tools.avm_data_loader import load_recent_analysis_ready_rows

ARCHIVE_DIR = Path("datas/archive")
OUTPUT_PATH = Path("datas/avm/alerts.json")

PREDICTED_KEYS = (
    "predicted",
    "predicted_price",
    "avm_predicted_price",
    "avm_predicted",
    "预测价格",
    "预测价",
    "AVM估值",
    "市场评估价",
)

STARTING_KEYS = ("starting", "starting_price", "起拍价格", "起拍价")

MALIGNANT_RISK_KEYS = {
    "is_malignant_risk",
    "has_malignant_risk",
    "恶性风险",
    "has_long_lease",
    "has_occupancy_issue",
    "has_major_dispute",
    "has_severe_violation",
    "is_homicide_house",
    "凶宅",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AVM alerts JSON")
    parser.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--recent-days", type=int, default=7, help="Only scan files within N days.")
    parser.add_argument("--threshold", type=float, default=0.2, help="Alert threshold for margin.")
    return parser.parse_args()


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def get_first_numeric(item: dict[str, Any], keys: Iterable[str]) -> float | None:
    for key in keys:
        value = parse_number(item.get(key))
        if value is not None:
            return value
    return None


def has_malignant_risk(item: dict[str, Any]) -> bool:
    for key in MALIGNANT_RISK_KEYS:
        if key in item and bool(item.get(key)):
            return True

    for tags_key in ("risk_tags", "risks", "risk_labels", "风险标签"):
        tags = item.get(tags_key)
        if isinstance(tags, list):
            joined = " ".join(str(tag).lower() for tag in tags)
            if any(token in joined for token in ("malignant", "severe", "重大", "恶性", "凶宅", "占用")):
                return True
        elif isinstance(tags, str):
            lowered = tags.lower()
            if any(token in lowered for token in ("malignant", "severe", "重大", "恶性", "凶宅", "占用")):
                return True

    risk_level = str(item.get("risk_level", "")).strip().lower()
    if risk_level in {"high", "severe", "critical", "重大", "恶性"}:
        return True

    return False


def parse_archive_date(path: Path) -> date | None:
    try:
        return datetime.strptime(path.stem, "%Y-%m-%d").date()
    except ValueError:
        return None


def find_recent_files(archive_dir: Path, recent_days: int) -> list[Path]:
    today = date.today()
    dated_files: list[tuple[date, Path]] = []
    recent: list[Path] = []
    for path in archive_dir.glob("*/*.json"):
        file_date = parse_archive_date(path)
        if not file_date:
            continue
        dated_files.append((file_date, path))
        if (today - file_date) <= timedelta(days=recent_days):
            recent.append(path)

    if recent:
        return sorted(recent)

    if not dated_files:
        return []
    latest_date = max(d for d, _ in dated_files)
    return sorted(path for d, path in dated_files if d == latest_date)


def load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def generate_avm_alerts(
    data_dir: str | Path = "datas",
    output_path: str | Path = OUTPUT_PATH,
    threshold: float | None = 0.2,
    limit: int = 500,
    recent_days: int = 7,
) -> dict[str, Any]:
    archive_dir = Path(data_dir) / "archive"
    output = Path(output_path)
    recent_rows = load_recent_analysis_ready_rows(Path(data_dir), recent_days, prefer_db=True)
    files = find_recent_files(archive_dir, recent_days) if not recent_rows else []

    alerts: list[dict[str, Any]] = []
    scanned = 0
    blocked_reason_counts: dict[str, int] = {}
    effective_threshold = get_effective_alert_threshold(0.2) if threshold is None else threshold

    def _iter_items():
        if recent_rows:
            for row in recent_rows:
                yield row, row.get("__file_path") or "db://recent_rows"
        else:
            for file_path in files:
                for item in load_json_list(file_path):
                    yield item, str(file_path)

    for item, source_file in _iter_items():
        scanned += 1
        predicted = get_first_numeric(item, PREDICTED_KEYS)
        starting = get_first_numeric(item, STARTING_KEYS)
        if not predicted or predicted <= 0 or starting is None:
            continue

        margin = (predicted - starting) / predicted
        blockers = build_alert_blockers(
            margin=margin,
            threshold=effective_threshold,
            is_malignant_risk=has_malignant_risk(item),
            payload=item,
        )
        if blockers:
            for blocker in blockers:
                blocked_reason_counts[blocker] = int(blocked_reason_counts.get(blocker, 0) or 0) + 1
            continue

        alerts.append(
            {
                "id": item.get("id"),
                "source_file": source_file,
                "starting_price": round(starting, 2),
                "predicted_price": round(predicted, 2),
                "margin": round(margin, 6),
                "city": item.get("城市") or item.get("city"),
                "district": item.get("区") or item.get("district"),
                "community": item.get("所属小区") or item.get("community"),
                "listing_time": item.get("交易时间") or item.get("listing_time"),
            }
        )

    alerts.sort(key=lambda x: x["margin"], reverse=True)
    if limit > 0:
        alerts = alerts[:limit]

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recent_days": recent_days,
        "threshold": effective_threshold,
        "scanned_files": [str(f) for f in files] if files else (["db://recent_rows"] if recent_rows else []),
        "scanned_records": scanned,
        "alerts_count": len(alerts),
        "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
        "alerts": alerts,
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    return {
        "output_path": str(output),
        "summary": {
            "scanned_records": scanned,
            "alerts_count": len(alerts),
            "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
            "recent_days": recent_days,
            "threshold": effective_threshold,
        },
        "payload": payload,
    }


def main() -> None:
    args = parse_args()
    result = generate_avm_alerts(
        data_dir=args.archive_dir.parent,
        output_path=args.output,
        threshold=args.threshold,
        recent_days=args.recent_days,
    )

    print(
        f"Generated {result['summary']['alerts_count']} alerts from {result['summary']['scanned_records']} records "
        f"across {len(result['payload']['scanned_files'])} files -> {args.output}"
    )


if __name__ == "__main__":
    main()
