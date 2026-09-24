from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests

from src.collection_api_credentials import (
    CREDENTIAL_HEADERS,
    request_headers,
    request_verify,
)


def _build_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    return session


def fetch_json(
    url: str,
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
) -> Any:
    headers = request_headers(url, headers)
    with _build_session() as session:
        try:
            request_options: dict[str, Any] = {
                "timeout": timeout,
                "allow_redirects": False,
            }
            if headers:
                request_options["headers"] = dict(headers)
            verify = request_verify(url)
            if verify is not True:
                request_options["verify"] = verify
            response = session.get(url, **request_options)
            if 300 <= response.status_code < 400:
                raise OSError("Internal API redirects are not permitted")
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OSError(str(exc)) from exc
        return response.json()


def post_json(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
    session: requests.Session | None = None,
) -> Any:
    headers = request_headers(url, headers, method="POST")
    if session is None:
        with _build_session() as owned:
            return _post(owned, url, payload, timeout=timeout, headers=headers)
    return _post(session, url, payload, timeout=timeout, headers=headers)


def _post(
    session: requests.Session,
    url: str,
    payload: Mapping[str, object],
    *,
    timeout: float,
    headers: Mapping[str, str],
) -> object:
    try:
        request_options = {
            "json": dict(payload),
            "timeout": timeout,
            "allow_redirects": False,
        }
        # Requests merges per-call headers into session defaults. Suppress stale
        # role credentials without mutating a session also used for provider I/O.
        clean_headers: dict[str, str | None] = {
            name: None
            for name in getattr(session, "headers", {})
            if name.lower() in CREDENTIAL_HEADERS
        }
        clean_headers.update(headers)
        if clean_headers:
            request_options["headers"] = clean_headers
        verify = request_verify(url)
        if verify is not True or getattr(session, "verify", True) is not True:
            request_options["verify"] = verify
        response = session.post(url, **request_options)
        if 300 <= response.status_code < 400:
            raise OSError("Internal API redirects are not permitted")
        response.raise_for_status()
    except requests.RequestException as exc:
        raise OSError(str(exc)) from exc
    result: object = response.json()
    return result
