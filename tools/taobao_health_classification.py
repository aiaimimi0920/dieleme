"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.taobao_health_context import *


def build_login_url(redirect_url: str) -> str:
    return f"https://login.taobao.com/member/login.jhtml?redirectURL={quote(redirect_url, safe='')}"


def build_captcha_solver_target_url(target_url: str) -> str:
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return target_url
    path = parsed.path
    while "//" in path:
        path = path.replace("//", "/")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == "__captcha_solver_bg" for key, _value in query):
        query.append(("__captcha_solver_bg", "1"))
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query, doseq=True), parsed.fragment))


def build_captcha_worker_master_url() -> str:
    return "https://sf.taobao.com/?__captcha_worker_master=1"


def report_captcha_via_api(
    api_base_url: str,
    cdp_endpoint: str,
    target_url: str,
    *,
    manual_only: bool = False,
    scope: str | None = None,
) -> Mapping[str, object]:
    endpoint_suffix = "/report_manual_captcha" if manual_only else "/report_captcha"
    endpoint = api_base_url.rstrip("/") + endpoint_suffix
    report_cdp_endpoint = resolve_captcha_report_cdp_endpoint(cdp_endpoint)
    payload: dict[str, object] = {
        "url": target_url,
        "cdp_endpoint": report_cdp_endpoint,
        "timestamp": int(time.time() * 1000),
    }
    node_id = str(os.environ.get("FAPAI_NODE_ID") or "").strip()
    if node_id:
        payload["node_id"] = node_id
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope in {"seed", "detail"}:
        payload["scope"] = normalized_scope
    if manual_only:
        payload["manual_only"] = True
    try:
        loaded = post_json(endpoint, payload, timeout=10)
    except OSError as exc:
        return {"status": "request_failed", "error": str(exc)}
    return loaded if isinstance(loaded, dict) else {"status": "unknown_response", "raw": loaded}


def resolve_captcha_report_cdp_endpoint(cdp_endpoint: str) -> str:
    for name in CAPTCHA_REPORT_CDP_ENV_NAMES:
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip()
    return cdp_endpoint


def redact_taobao_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_INLINE_PATTERNS:
        redacted = pattern.sub("taobao_security_value=<redacted>", redacted)
    return redacted


def redact_taobao_sensitive_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return redact_taobao_sensitive_text(url)
    query = urlencode(
        [
            (key, redact_taobao_sensitive_text(value))
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_QUERY_KEYS
        ],
        doseq=True,
    )
    return redact_taobao_sensitive_text(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)))


def redact_taobao_health_output(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): redact_taobao_health_output(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_taobao_health_output(item) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return redact_taobao_sensitive_url(value)
        return redact_taobao_sensitive_text(value)
    return value


def _operator_host_endpoint(cdp_endpoint: str) -> str:
    return cdp_endpoint.replace("192.168.65.254", "127.0.0.1")


def _helper_command(*, cdp_endpoint: str, check_url: str, wait_seconds: int) -> str:
    return (
        'python tools\\taobao_login_health.py '
        f'--cdp-endpoint "{cdp_endpoint}" '
        f'--check-url "{check_url}" '
        f"--open-login --wait-seconds {wait_seconds}"
    )


def _summary_flag(summary: Mapping[str, object], key: str) -> bool:
    return summary.get(key) is True


def classify_taobao_health(
    html: str,
    *,
    final_url: str,
    list_summary: Mapping[str, object] | None = None,
    payload_present: bool,
) -> dict[str, object]:
    summary = list_summary or {}
    text = html or ""
    lowered_text = text.lower()
    lowered_url = (final_url or "").lower()

    has_login = (
        _summary_flag(summary, "body_has_login")
        or "login.taobao.com" in lowered_url
        or "login.m.taobao.com" in lowered_url
        or "havanaone/login" in lowered_url
    )
    has_punish = (
        _summary_flag(summary, "body_has_punish")
        or "_____tmd_____" in lowered_url
        or "_____tmd_____" in lowered_text
        or "/punish" in lowered_url
        or "/punish" in lowered_text
        or "x5secdata=" in lowered_text
    )
    has_captcha = (
        _summary_flag(summary, "body_has_captcha")
        or (
            not payload_present
            and (
                "captcha" in lowered_text
                or "验证码" in text
                or "霸下通用 web 页面-验证码" in text
            )
        )
    )
    has_challenge = (
        _summary_flag(summary, "body_has_challenge")
        or "challenge" in lowered_url
        or (
            not payload_present
            and (
                "challenge" in lowered_text
                or "anti-bot" in lowered_text
                or "霸下" in text
            )
        )
    )

    if payload_present and not (has_login or has_punish or has_captcha or has_challenge):
        return {
            "status": HEALTHY_LIST_PAYLOAD,
            "healthy": True,
            "action": "none",
            "final_url": final_url,
        }
    if has_punish:
        return {
            "status": PUNISH_PAGE,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_captcha:
        return {
            "status": CAPTCHA_PAGE,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_challenge:
        return {
            "status": CHALLENGE_REQUIRED,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_login:
        return {
            "status": LOGIN_REQUIRED,
            "healthy": False,
            "action": "complete_taobao_login",
            "final_url": final_url,
        }
    return {
        "status": UNKNOWN_BLOCKED,
        "healthy": False,
        "action": "inspect_taobao_session",
        "final_url": final_url,
    }


def build_operator_hint(
    *,
    status: str,
    cdp_endpoint: str,
    check_url: str,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
) -> dict[str, object]:
    required = status != HEALTHY_LIST_PAYLOAD
    helper_command = _helper_command(cdp_endpoint=cdp_endpoint, check_url=check_url, wait_seconds=wait_seconds)
    host_helper_command = _helper_command(
        cdp_endpoint=_operator_host_endpoint(cdp_endpoint),
        check_url=check_url,
        wait_seconds=wait_seconds,
    )
    return {
        "required": required,
        "status": status,
        "action": "run_taobao_login_health_helper" if required else "none",
        "helper_command": helper_command,
        "host_helper_command": host_helper_command,
        "login_url": build_login_url(check_url),
        "message": (
            "Complete Taobao QR login or official security verification in the Edge CDP browser, "
            "then wait for this helper to report healthy."
            if required
            else "Taobao/SF list page is readable through the current CDP session."
        ),
    }


def _probe_summary_and_payload(html: str, final_url: str) -> tuple[dict[str, object], bool]:
    from tools import browserless_seed_probe

    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    payload_present = browserless_seed_probe.extract_list_payload(html) is not None
    return dict(summary), payload_present


def _build_taobao_health_result(
    *,
    cdp_endpoint: str,
    check_url: str,
    html: str,
    final_url: str,
) -> dict[str, object]:
    list_summary, payload_present = _probe_summary_and_payload(html, final_url)
    result = classify_taobao_health(
        html,
        final_url=final_url,
        list_summary=list_summary,
        payload_present=payload_present,
    )
    result.update(
        {
            "cdp_endpoint": cdp_endpoint,
            "check_url": check_url,
            "list_summary": list_summary,
        }
    )
    result["operator_hint"] = build_operator_hint(
        status=str(result["status"]),
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
    )
    return result


def _build_cdp_unreachable_result(*, cdp_endpoint: str, check_url: str, error: str) -> dict[str, object]:
    result: dict[str, object] = {
        "status": CDP_UNREACHABLE,
        "healthy": False,
        "action": "start_or_repair_taobao_cdp_browser",
        "cdp_endpoint": cdp_endpoint,
        "check_url": check_url,
        "error": error,
    }
    result["operator_hint"] = build_operator_hint(
        status=CDP_UNREACHABLE,
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
    )
    return result


def _build_taobao_health_result_from_summary(
    *,
    cdp_endpoint: str,
    check_url: str,
    final_url: str,
    list_summary: Mapping[str, object],
    payload_present: bool,
    probe_transport: str | None = None,
    cookie_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = classify_taobao_health(
        "",
        final_url=final_url,
        list_summary=list_summary,
        payload_present=payload_present,
    )
    result.update(
        {
            "cdp_endpoint": cdp_endpoint,
            "check_url": check_url,
            "list_summary": dict(list_summary),
        }
    )
    result["operator_hint"] = build_operator_hint(
        status=str(result["status"]),
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
    )
    if probe_transport:
        result["probe_transport"] = probe_transport
    if cookie_summary:
        result["cookie_summary"] = dict(cookie_summary)
    return result


def resolve_playwright_cdp_endpoint(cdp_endpoint: str) -> str:
    normalized = str(cdp_endpoint or "").strip()
    try:
        hostname = (urlsplit(normalized).hostname or "").lower()
    except ValueError:
        return normalized
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        return normalized

    from tools import browserless_seed_probe

    return browserless_seed_probe._resolve_cdp_endpoint(normalized)


__all__ = (
    'build_login_url',
    'build_captcha_solver_target_url',
    'build_captcha_worker_master_url',
    'report_captcha_via_api',
    'resolve_captcha_report_cdp_endpoint',
    'redact_taobao_sensitive_text',
    'redact_taobao_sensitive_url',
    'redact_taobao_health_output',
    '_operator_host_endpoint',
    '_helper_command',
    '_summary_flag',
    'classify_taobao_health',
    'build_operator_hint',
    '_probe_summary_and_payload',
    '_build_taobao_health_result',
    '_build_cdp_unreachable_result',
    '_build_taobao_health_result_from_summary',
    'resolve_playwright_cdp_endpoint',
)
