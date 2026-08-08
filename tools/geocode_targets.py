#!/usr/bin/env python3
"""geocoding 目标的归一化、去重与配额优先级排序。

这一层不依赖任何 geocoding 服务商，用于在选定服务商之前把工作量算清楚：
哪些「城市+区+小区」需要编码、按什么顺序编码、调用 N 次能覆盖多少行。

背景：线上 228,959 行 latitude/longitude 全为 NULL。既有的
`backfill_recent_coordinates.py` 走 centroid 兜底，从已有坐标池推导，
而坐标池是空的，所以无效。必须从地址反查。

按小区聚合是关键取舍：唯一「城市+区+小区」组合 77,764 个，而唯一
full_address 有 206,643 个。前者调用量少 2.7 倍，且小区级精度正好是
AVM 做同小区比价需要的粒度，比门牌号精度更稳（法拍公告的门牌写法很不统一）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 装饰性分隔符会干扰地理编码匹配，例如“隆鑫·印象城邦”
_DECORATIVE_CHARS = re.compile(r"[·•∙・·\s]+")

DEFAULT_COVERAGE_LIMITS = (1000, 5000, 10000, 20000, 30000, 50000)


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text in {"UNK", "None", "null"}:
        return ""
    return _DECORATIVE_CHARS.sub("", text)


def build_geocode_query(*, city: Any, district: Any, community_name: Any) -> str:
    """拼出送给 geocoding 服务的查询串。

    城市和小区都必须有：缺城市会让同名小区跨城误匹配（全国重名小区极多），
    缺小区就退化成区级中心点，对同小区比价没有价值。区可以缺。
    """
    city_text = _clean(city)
    community_text = _clean(community_name)
    if not city_text or not community_text:
        return ""
    return f"{city_text}{_clean(district)}{community_text}"


def build_target_key(*, city: Any, district: Any, community_name: Any) -> str:
    """去重键。同一小区可能因为区字段有无而重复出现，额度不该花在重复调用上。"""
    return build_geocode_query(city=city, district=district, community_name=community_name)


def prioritize_targets(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """按行数降序排列去重后的目标。

    降序是为了让有限的免费额度先覆盖最多的行：实测 Top 5,000 覆盖 39.5%，
    Top 20,000 覆盖 65.4%，所以增量编码的边际收益前期很高。
    """
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        city = row.get("city")
        district = row.get("district")
        community_name = row.get("community_name")
        key = build_target_key(city=city, district=district, community_name=community_name)
        if not key:
            continue
        try:
            row_count = int(row.get("row_count") or 0)
        except (TypeError, ValueError):
            row_count = 0
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "key": key,
                "query": key,
                "city": _clean(city),
                "district": _clean(district),
                "community_name": _clean(community_name),
                "row_count": row_count,
            }
        else:
            existing["row_count"] += row_count

    targets = list(merged.values())
    targets.sort(key=lambda item: (-item["row_count"], item["key"]))
    return targets


def summarize_coverage(
    targets: Sequence[Mapping[str, Any]],
    *,
    limits: Sequence[int] = DEFAULT_COVERAGE_LIMITS,
) -> dict[str, Any]:
    """回答“调用 N 次覆盖多少行”，用于选服务商和排期。"""
    total_rows = sum(int(t.get("row_count") or 0) for t in targets)
    coverage: dict[int, dict[str, Any]] = {}
    for limit in limits:
        taken = targets[: max(int(limit), 0)]
        rows = sum(int(t.get("row_count") or 0) for t in taken)
        coverage[int(limit)] = {
            "calls": len(taken),
            "rows": rows,
            "pct": round(100.0 * rows / total_rows, 2) if total_rows else 0.0,
        }
    return {
        "total_targets": len(targets),
        "total_rows": total_rows,
        "coverage": coverage,
    }


def load_targets_from_db() -> list[dict[str, Any]]:
    from src.storage.repository import create_repository_from_env
    from sqlalchemy import text

    repo = create_repository_from_env()
    if not repo.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set to collect geocode targets")
    repo.initialize()

    sql = text(
        """
        select city, district, community_name, count(*) as row_count
        from property_listing
        where community_name is not null and community_name <> ''
          and city is not null and city <> ''
          and (latitude is null or longitude is null)
        group by city, district, community_name
        """
    )
    with repo.session_factory() as session:
        return [
            {
                "city": row[0],
                "district": row[1],
                "community_name": row[2],
                "row_count": row[3],
            }
            for row in session.execute(sql)
        ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="统计并排序待 geocoding 的小区目标")
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("datas/avm/geocode_targets.json"),
        help="排序后的目标清单落盘位置",
    )
    parser.add_argument("--limit", type=int, default=0, help="只输出前 N 个目标，0 表示全部")
    parser.add_argument("--summary-only", action="store_true", help="只打印覆盖统计，不落盘")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    targets = prioritize_targets(load_targets_from_db())
    summary = summarize_coverage(targets)

    print(f"待编码目标: {summary['total_targets']}")
    print(f"可覆盖行数: {summary['total_rows']}")
    for limit, stat in sorted(summary["coverage"].items()):
        print(f"  前 {limit:>6} 次调用 -> {stat['rows']:>7} 行 ({stat['pct']}%)")

    if args.summary_only:
        return 0

    payload = {
        "summary": summary,
        "targets": targets[: args.limit] if args.limit > 0 else targets,
    }
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"已写入 {args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
