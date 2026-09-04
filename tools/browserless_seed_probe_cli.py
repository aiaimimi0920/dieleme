"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.browserless_seed_probe_context import *


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe browserless Taobao seed collection using an attached CDP session.")
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--url", default=DEFAULT_TARGET_URL)
    parser.add_argument("--write-cookie-snapshot", default=None)
    parser.add_argument("--emit-batch-payload", action="store_true")
    args = parser.parse_args(argv)

    cookies = export_cdp_cookies(args.cdp_endpoint)
    if args.write_cookie_snapshot:
        write_cookie_snapshot(cookies, args.write_cookie_snapshot)

    summary = probe_seed_page(args.url, cookies=cookies)
    summary["cookie_count"] = len(cookies)
    if args.emit_batch_payload:
        session = build_session_from_playwright_cookies(cookies)
        response = session.get(
            args.url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://sf.taobao.com/",
            },
            timeout=30,
            allow_redirects=True,
        )
        payload = extract_list_payload(response.text)
        if payload is not None:
            summary["batch_payload"] = build_userscript_like_batch_payload(
                payload,
                source_page_url=response.url,
            )
    print(json.dumps(summary, ensure_ascii=False))
    return 0



__all__ = (
    "main",
)
