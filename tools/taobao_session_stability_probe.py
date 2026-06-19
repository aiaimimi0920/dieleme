from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import taobao_login_health


def build_stability_summary(attempt_results: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = [str(result.get("status") or "") for result in attempt_results]
    healthy_flags = [result.get("healthy") is True for result in attempt_results]
    transports = [str(result.get("probe_transport") or "") for result in attempt_results]
    cookie_shapes = [str((result.get("cookie_summary") or {}).get("shape_fingerprint") or "") for result in attempt_results]
    cookie_values = [str((result.get("cookie_summary") or {}).get("value_fingerprint") or "") for result in attempt_results]
    final_urls = [str(result.get("final_url") or "") for result in attempt_results]
    final_hosts = [urlsplit(url).netloc for url in final_urls]
    final_paths = [urlsplit(url).path for url in final_urls]
    final_queries = [urlsplit(url).query for url in final_urls]

    status_changed = len(set(statuses)) > 1
    healthy_changed = len(set(healthy_flags)) > 1
    probe_transport_changed = len(set(transports)) > 1
    cookie_shape_changed = len(set(cookie_shapes)) > 1
    cookie_value_changed = len(set(cookie_values)) > 1
    final_url_changed = len(set(final_urls)) > 1
    final_host_changed = len(set(final_hosts)) > 1
    final_path_changed = len(set(final_paths)) > 1
    final_url_query_changed = len(set(final_queries)) > 1

    if (not status_changed) and (not cookie_value_changed) and final_url_query_changed and (not final_host_changed) and (not final_path_changed):
        suspected_driver = "server_risk_tokens_rotating_without_cookie_change"
    elif status_changed and not cookie_value_changed:
        suspected_driver = "non_cookie_state_or_server_risk_state"
    elif status_changed and cookie_value_changed:
        suspected_driver = "cookie_value_or_server_session_change"
    elif cookie_value_changed:
        suspected_driver = "cookie_value_change_without_status_flip"
    else:
        suspected_driver = "no_state_change_observed"

    return {
        "attempt_count": len(attempt_results),
        "status_changed": status_changed,
        "healthy_changed": healthy_changed,
        "probe_transport_changed": probe_transport_changed,
        "cookie_shape_changed": cookie_shape_changed,
        "cookie_value_changed": cookie_value_changed,
        "final_url_changed": final_url_changed,
        "final_host_changed": final_host_changed,
        "final_path_changed": final_path_changed,
        "final_url_query_changed": final_url_query_changed,
        "distinct_status_count": len(set(statuses)),
        "distinct_cookie_shape_count": len(set(cookie_shapes)),
        "distinct_cookie_value_count": len(set(cookie_values)),
        "suspected_driver": suspected_driver,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repeatedly probe Taobao session stability and summarize cookie/state drift.")
    parser.add_argument("--cdp-endpoint", default=taobao_login_health.DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--check-url", default=taobao_login_health.DEFAULT_CHECK_URL)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    attempts = max(int(args.attempts), 1)
    interval_seconds = max(float(args.interval_seconds), 0.0)

    rows: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        started = time.time()
        result = taobao_login_health.check_taobao_health(
            cdp_endpoint=str(args.cdp_endpoint),
            check_url=str(args.check_url),
            open_login=False,
        )
        rows.append(
            {
                "attempt": attempt,
                "seconds": round(time.time() - started, 2),
                **result,
            }
        )
        if attempt < attempts and interval_seconds > 0:
            time.sleep(interval_seconds)

    payload = {
        "cdp_endpoint": str(args.cdp_endpoint),
        "check_url": str(args.check_url),
        "attempts": rows,
        "summary": build_stability_summary(rows),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
