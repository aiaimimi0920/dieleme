from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import browserless_seed_probe, taobao_login_health


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two Taobao CDP profiles using safe cookie summaries and health probes.")
    parser.add_argument("--left-cdp-endpoint", required=True)
    parser.add_argument("--right-cdp-endpoint", required=True)
    parser.add_argument("--left-label", default="left")
    parser.add_argument("--right-label", default="right")
    parser.add_argument("--check-url", default=taobao_login_health.DEFAULT_CHECK_URL)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    left_cookies = browserless_seed_probe.export_cdp_cookies(str(args.left_cdp_endpoint))
    right_cookies = browserless_seed_probe.export_cdp_cookies(str(args.right_cdp_endpoint))
    left_summary = dict(browserless_seed_probe.summarize_cookie_snapshot(left_cookies))
    right_summary = dict(browserless_seed_probe.summarize_cookie_snapshot(right_cookies))
    diff = browserless_seed_probe.diff_cookie_snapshots(left_cookies, right_cookies)

    left_health = taobao_login_health.check_taobao_health(
        cdp_endpoint=str(args.left_cdp_endpoint),
        check_url=str(args.check_url),
        open_login=False,
    )
    right_health = taobao_login_health.check_taobao_health(
        cdp_endpoint=str(args.right_cdp_endpoint),
        check_url=str(args.check_url),
        open_login=False,
    )

    payload = {
        "check_url": str(args.check_url),
        "left": {
            "label": str(args.left_label),
            "cdp_endpoint": str(args.left_cdp_endpoint),
            "cookie_summary": left_summary,
            "health": left_health,
        },
        "right": {
            "label": str(args.right_label),
            "cdp_endpoint": str(args.right_cdp_endpoint),
            "cookie_summary": right_summary,
            "health": right_health,
        },
        "diff": {
            "added_domains_on_right": diff["added_domains"],
            "removed_domains_on_right": diff["removed_domains"],
            "added_names_on_right": diff["added_names"],
            "removed_names_on_right": diff["removed_names"],
            "added_keys_on_right": diff["added_keys"],
            "removed_keys_on_right": diff["removed_keys"],
            "shared_key_count": diff["shared_key_count"],
            "shape_fingerprint_equal": diff["shape_fingerprint_equal"],
            "value_fingerprint_equal": diff["value_fingerprint_equal"],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
