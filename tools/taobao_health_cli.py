"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.taobao_health_context import *


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check and repair Taobao/SF login health through the existing Edge CDP profile.")
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--check-url", default=DEFAULT_CHECK_URL)
    parser.add_argument("--sample-url", action="append", default=[])
    parser.add_argument("--open-login", action="store_true")
    parser.add_argument("--trigger-captcha-solver", action="store_true")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sample_urls = tuple(str(url) for url in getattr(args, "sample_url", []) if str(url).strip())
    if sample_urls:
        result = wait_for_taobao_health_samples(
            cdp_endpoint=str(args.cdp_endpoint),
            sample_urls=sample_urls,
            open_login=bool(args.open_login),
            trigger_captcha_solver=bool(args.trigger_captcha_solver),
            api_base_url=str(args.api_base_url),
            wait_seconds=int(args.wait_seconds),
            poll_seconds=int(args.poll_seconds),
        )
    else:
        result = wait_for_taobao_health(
            cdp_endpoint=str(args.cdp_endpoint),
            check_url=str(args.check_url),
            open_login=bool(args.open_login),
            trigger_captcha_solver=bool(args.trigger_captcha_solver),
            api_base_url=str(args.api_base_url),
            wait_seconds=int(args.wait_seconds),
            poll_seconds=int(args.poll_seconds),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("healthy") is True:
        return 0
    if result.get("status") == CDP_UNREACHABLE:
        return 1
    return 2


__all__ = (
    '_build_parser',
    'main',
)
