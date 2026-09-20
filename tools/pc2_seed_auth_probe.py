"""Fresh list access using PC2's imported session, with no challenge solving."""
from tools import browserless_seed_probe
from src.collection.adapters.taobao_auth_target import auth_target, seed_payload_is_authenticated


def seed_payload_authenticated(html, final_url, target_url):
    try:
        payload = browserless_seed_probe.extract_list_payload(html)
        summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
        return seed_payload_is_authenticated(payload, summary, final_url=final_url, target_url=target_url)
    except (ValueError, TypeError, AttributeError):
        return False


def probe_seed_access(cdp_endpoint, target_url):
    target_url = auth_target("seed", target_url)
    # A new page proves a fresh request rather than reusing a stale cached DOM.
    # Close only this probe-owned page; preserve every existing operator tab.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(cdp_endpoint, timeout=15000)
        page = None
        try:
            if not browser.contexts:
                return False
            page = browser.contexts[0].new_page()
            response = page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            if response is None or response.status >= 400:
                return False
            return seed_payload_authenticated(page.content(), page.url, target_url)
        finally:
            if page is not None:
                page.close()
            # Disconnect the client from the external browser, not Browser.close.
