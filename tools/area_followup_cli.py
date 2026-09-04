"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.area_followup_context import *


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve area-missing jobs produced by live_batch_smoke.py.")
    parser.add_argument("--queue", type=Path, default=Path("output/live_batch_smoke/area_followup_queue.json"))
    parser.add_argument("--output-dir", type=Path, default=None, help="Artifact root. Defaults to queue parent.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cdp-endpoint", default=None, help="Optional Chrome CDP endpoint. When set, fetch notice_detail pages with logged-in cookies.")
    parser.add_argument("--apply-patches", action="store_true", help="Apply resolved area_followup_patch.json files into each item final.json.")
    parser.add_argument("--push-area-result", default=None, help="POST resolved patches to this area_result API URL.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.apply_patches:
        root = args.output_dir or args.queue.parent
        summary = apply_resolved_patches(root, limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.push_area_result:
        root = args.output_dir or args.queue.parent
        summary = push_resolved_patches(root, api_url=args.push_area_result, limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["failed_count"] == 0 else 2
    http_session = build_http_session_from_cdp(args.cdp_endpoint) if args.cdp_endpoint else None
    summary = run_queue(args.queue, output_dir=args.output_dir, limit=args.limit, http_session=http_session)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["unresolved_jobs"] == 0 else 2


__all__ = (
    "parse_args",
    "main",
)
