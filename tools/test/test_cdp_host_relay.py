from tools.cdp_host_relay import (
    client_ip_allowed,
    parse_allowed_client_cidrs,
    rewrite_http_host_header,
)


def test_rewrite_http_host_header_for_cdp_service_name() -> None:
    request = (
        b"GET /json/version HTTP/1.1\r\n"
        b"Host: pc2-browser-solver:9224\r\n"
        b"Connection: close\r\n\r\n"
    )

    rewritten = rewrite_http_host_header(request, "127.0.0.1:9223")

    assert b"Host: 127.0.0.1:9223\r\n" in rewritten
    assert b"Host: pc2-browser-solver:9224" not in rewritten
    assert rewritten.startswith(b"GET /json/version HTTP/1.1\r\n")


def test_rewrite_http_host_header_is_case_insensitive() -> None:
    request = b"GET /devtools/browser/id HTTP/1.1\r\nhOsT: localhost:9224\r\n\r\n"

    rewritten = rewrite_http_host_header(request, "127.0.0.1:9223")

    assert rewritten == (
        b"GET /devtools/browser/id HTTP/1.1\r\n"
        b"Host: 127.0.0.1:9223\r\n\r\n"
    )


def test_rewrite_http_host_header_leaves_hostless_request_unchanged() -> None:
    request = b"GET /json/version HTTP/1.0\r\n\r\n"

    assert rewrite_http_host_header(request, "127.0.0.1:9223") == request


def test_cdp_relay_defaults_to_loopback_clients() -> None:
    networks = parse_allowed_client_cidrs([])

    assert client_ip_allowed(("127.0.0.1", 40000), networks) is True
    assert client_ip_allowed(("::1", 40000, 0, 0), networks) is True
    assert client_ip_allowed(("192.168.15.55", 40000), networks) is False


def test_cdp_relay_accepts_only_configured_remote_clients() -> None:
    networks = parse_allowed_client_cidrs(
        ["172.16.0.0/12,192.168.15.20/32", "192.168.15.200/32"]
    )

    assert client_ip_allowed(("172.19.0.4", 40000), networks) is True
    assert client_ip_allowed(("192.168.15.20", 40000), networks) is True
    assert client_ip_allowed(("192.168.15.200", 40000), networks) is True
    assert client_ip_allowed(("192.168.15.55", 40000), networks) is False
    assert client_ip_allowed(("::ffff:192.168.15.200", 40000, 0, 0), networks) is True
