"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.taobao_health_context import *


def check_taobao_health(
    *,
    cdp_endpoint: str = DEFAULT_CDP_ENDPOINT,
    check_url: str = DEFAULT_CHECK_URL,
    open_login: bool = False,
    trigger_captcha_solver: bool = False,
    api_base_url: str = DEFAULT_API_BASE_URL,
    fetch_page_func: FetchPageFunc | None = None,
    open_page_func: OpenPageFunc | None = None,
    report_captcha_func: ReportCaptchaFunc | None = None,
) -> dict[str, object]:
    fetch_page = fetch_page_func or fetch_page_via_cdp
    open_page = open_page_func or open_page_via_cdp
    report_captcha = report_captcha_func or report_captcha_via_api

    if fetch_page_func is None:
        try:
            result = fetch_health_samples_via_cdp_cookie_http(cdp_endpoint, (check_url,))[0]
        except Exception:
            result = None
        else:
            if result.get("healthy") is not True:
                if trigger_captcha_solver and result.get("status") in {PUNISH_PAGE, CAPTCHA_PAGE, CHALLENGE_REQUIRED, UNKNOWN_BLOCKED}:
                    solver_target_url = build_captcha_solver_target_url(str(result.get("final_url") or check_url))
                    if open_page_func is None:
                        try:
                            result["captcha_worker_queue_report"] = dict(queue_captcha_task_via_cdp(cdp_endpoint, solver_target_url))
                        except Exception as exc:
                            result["captcha_worker_queue_report"] = {"status": "queue_failed", "error": str(exc)}
                        result["captcha_worker_url"] = str(
                            result["captcha_worker_queue_report"].get("worker_url")
                            or build_captcha_worker_master_url()
                        )
                    else:
                        result["captcha_worker_url"] = open_page(cdp_endpoint, build_captcha_worker_master_url())
                    opened_url = open_page(cdp_endpoint, solver_target_url)
                    result["opened_url"] = opened_url
                    result["captcha_solver_target_url"] = solver_target_url
                    try:
                        result["captcha_solver_report"] = dict(report_captcha(api_base_url, cdp_endpoint, solver_target_url))
                        result["captcha_solver_triggered"] = True
                    except Exception as exc:
                        result["captcha_solver_triggered"] = False
                        result["captcha_solver_error"] = str(exc)
                elif open_login:
                    opened_url = open_page(cdp_endpoint, build_login_url(check_url))
                    result["opened_url"] = opened_url
            return dict(redact_taobao_health_output(result))

    try:
        html, final_url = fetch_page(cdp_endpoint, check_url)
    except Exception as exc:
        return _build_cdp_unreachable_result(cdp_endpoint=cdp_endpoint, check_url=check_url, error=str(exc))

    result = _build_taobao_health_result(
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
        html=html,
        final_url=final_url,
    )
    if result.get("healthy") is not True:
        if trigger_captcha_solver and result.get("status") in {PUNISH_PAGE, CAPTCHA_PAGE, CHALLENGE_REQUIRED, UNKNOWN_BLOCKED}:
            solver_target_url = build_captcha_solver_target_url(str(result.get("final_url") or check_url))
            if open_page_func is None:
                try:
                    result["captcha_worker_queue_report"] = dict(queue_captcha_task_via_cdp(cdp_endpoint, solver_target_url))
                except Exception as exc:
                    result["captcha_worker_queue_report"] = {"status": "queue_failed", "error": str(exc)}
                result["captcha_worker_url"] = str(
                    result["captcha_worker_queue_report"].get("worker_url")
                    or build_captcha_worker_master_url()
                )
            else:
                result["captcha_worker_url"] = open_page(cdp_endpoint, build_captcha_worker_master_url())
            opened_url = open_page(cdp_endpoint, solver_target_url)
            result["opened_url"] = opened_url
            result["captcha_solver_target_url"] = solver_target_url
            try:
                result["captcha_solver_report"] = dict(report_captcha(api_base_url, cdp_endpoint, solver_target_url))
                result["captcha_solver_triggered"] = True
            except Exception as exc:
                result["captcha_solver_triggered"] = False
                result["captcha_solver_error"] = str(exc)
        elif open_login:
            opened_url = open_page(cdp_endpoint, build_login_url(check_url))
            result["opened_url"] = opened_url
    return dict(redact_taobao_health_output(result))


def check_taobao_health_samples(
    *,
    cdp_endpoint: str = DEFAULT_CDP_ENDPOINT,
    sample_urls: Sequence[str],
    open_login: bool = False,
    trigger_captcha_solver: bool = False,
    api_base_url: str = DEFAULT_API_BASE_URL,
    fetch_page_func: FetchPageFunc | None = None,
    open_page_func: OpenPageFunc | None = None,
    report_captcha_func: ReportCaptchaFunc | None = None,
) -> dict[str, object]:
    urls = tuple(str(url).strip() for url in sample_urls if str(url).strip())
    if not urls:
        urls = (DEFAULT_CHECK_URL,)

    sample_results: list[dict[str, object]] = []
    if fetch_page_func is None:
        try:
            sample_results = fetch_health_samples_via_cdp_cookie_http(cdp_endpoint, urls)
        except Exception as exc:
            cookie_probe_error = str(exc)
            try:
                page_results = fetch_pages_via_cdp(cdp_endpoint, urls)
            except Exception:
                sample_results = [
                    _build_cdp_unreachable_result(
                        cdp_endpoint=cdp_endpoint,
                        check_url=url,
                        error=cookie_probe_error,
                    )
                    for url in urls
                ]
            else:
                sample_results = [
                    _build_taobao_health_result(
                        cdp_endpoint=cdp_endpoint,
                        check_url=url,
                        html=html,
                        final_url=final_url,
                    )
                    for url, (html, final_url) in zip(urls, page_results)
                ]
    else:
        for url in urls:
            result = check_taobao_health(
                cdp_endpoint=cdp_endpoint,
                check_url=url,
                open_login=False,
                fetch_page_func=fetch_page_func,
                open_page_func=open_page_func,
            )
            sample_results.append(result)

    healthy_samples = sum(1 for result in sample_results if result.get("healthy") is True)
    blocked_samples = len(sample_results) - healthy_samples
    first_blocked = next((result for result in sample_results if result.get("healthy") is not True), None)
    first_actionable_blocked = next(
        (
            result
            for result in sample_results
            if result.get("healthy") is not True and str(result.get("status")) != CDP_UNREACHABLE
        ),
        first_blocked,
    )
    first_status = str(first_actionable_blocked.get("status")) if first_actionable_blocked else HEALTHY_LIST_PAYLOAD
    all_samples_cdp_unreachable = bool(sample_results) and all(
        str(result.get("status")) == CDP_UNREACHABLE for result in sample_results
    )

    if healthy_samples:
        status = PARTIAL_AVAILABLE if blocked_samples else HEALTHY_LIST_PAYLOAD
        action = "none"
        healthy = True
    elif all_samples_cdp_unreachable:
        status = CDP_UNREACHABLE
        action = "start_or_repair_taobao_cdp_browser"
        healthy = False
    else:
        status = ALL_SAMPLES_BLOCKED
        action = "complete_taobao_security_verification"
        healthy = False

    result: dict[str, object] = {
        "status": status,
        "healthy": healthy,
        "action": action,
        "cdp_endpoint": cdp_endpoint,
        "sample_count": len(sample_results),
        "healthy_samples": healthy_samples,
        "blocked_samples": blocked_samples,
        "sample_results": sample_results,
    }
    hint_url = urls[0]
    result["operator_hint"] = build_operator_hint(
        status=first_status if not healthy else status,
        cdp_endpoint=cdp_endpoint,
        check_url=hint_url,
    )
    if not healthy and status != CDP_UNREACHABLE:
        open_page = open_page_func or open_page_via_cdp
        if trigger_captcha_solver:
            report_captcha = report_captcha_func or report_captcha_via_api
            solver_source = first_actionable_blocked or first_blocked
            solver_target_url = build_captcha_solver_target_url(str(solver_source.get("final_url") if solver_source else hint_url))
            if open_page_func is None:
                try:
                    result["captcha_worker_queue_report"] = dict(queue_captcha_task_via_cdp(cdp_endpoint, solver_target_url))
                except Exception as exc:
                    result["captcha_worker_queue_report"] = {"status": "queue_failed", "error": str(exc)}
                result["captcha_worker_url"] = str(
                    result["captcha_worker_queue_report"].get("worker_url")
                    or build_captcha_worker_master_url()
                )
            else:
                result["captcha_worker_url"] = open_page(cdp_endpoint, build_captcha_worker_master_url())
            result["opened_url"] = open_page(cdp_endpoint, solver_target_url)
            result["captcha_solver_target_url"] = solver_target_url
            try:
                result["captcha_solver_report"] = dict(report_captcha(api_base_url, cdp_endpoint, solver_target_url))
                result["captcha_solver_triggered"] = True
            except Exception as exc:
                result["captcha_solver_triggered"] = False
                result["captcha_solver_error"] = str(exc)
        elif open_login:
            result["opened_url"] = open_page(cdp_endpoint, build_login_url(hint_url))
    return dict(redact_taobao_health_output(result))


def wait_for_taobao_health(
    *,
    cdp_endpoint: str,
    check_url: str,
    open_login: bool,
    trigger_captcha_solver: bool,
    api_base_url: str,
    wait_seconds: int,
    poll_seconds: int,
    sleep_func: SleepFunc = time.sleep,
) -> dict[str, object]:
    deadline = time.monotonic() + max(wait_seconds, 0)
    attempts = 0
    opened = False
    while True:
        attempts += 1
        result = check_taobao_health(
            cdp_endpoint=cdp_endpoint,
            check_url=check_url,
            open_login=open_login and not opened,
            trigger_captcha_solver=trigger_captcha_solver,
            api_base_url=api_base_url,
        )
        opened = opened or "opened_url" in result
        result["attempts"] = attempts
        if result.get("healthy") is True:
            return result
        if wait_seconds <= 0 or time.monotonic() >= deadline:
            return result
        sleep_func(max(poll_seconds, 1))


def wait_for_taobao_health_samples(
    *,
    cdp_endpoint: str,
    sample_urls: Sequence[str],
    open_login: bool,
    trigger_captcha_solver: bool,
    api_base_url: str,
    wait_seconds: int,
    poll_seconds: int,
    sleep_func: SleepFunc = time.sleep,
) -> dict[str, object]:
    deadline = time.monotonic() + max(wait_seconds, 0)
    attempts = 0
    opened = False
    urls = tuple(sample_urls)
    while True:
        attempts += 1
        result = check_taobao_health_samples(
            cdp_endpoint=cdp_endpoint,
            sample_urls=urls,
            open_login=open_login and not opened,
            trigger_captcha_solver=trigger_captcha_solver,
            api_base_url=api_base_url,
        )
        opened = opened or "opened_url" in result
        result["attempts"] = attempts
        if result.get("healthy") is True:
            return result
        if wait_seconds <= 0 or time.monotonic() >= deadline:
            return result
        sleep_func(max(poll_seconds, 1))


__all__ = (
    'check_taobao_health',
    'check_taobao_health_samples',
    'wait_for_taobao_health',
    'wait_for_taobao_health_samples',
)
