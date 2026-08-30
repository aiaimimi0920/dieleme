from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import requests


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
    with _build_session() as session:
        try:
            request_options: dict[str, Any] = {"timeout": timeout}
            if headers:
                request_options["headers"] = dict(headers)
            response = session.get(url, **request_options)
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
) -> Any:
    with _build_session() as session:
        try:
            request_options: dict[str, Any] = {
                "json": dict(payload),
                "timeout": timeout,
            }
            if headers:
                request_options["headers"] = dict(headers)
            response = session.post(url, **request_options)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OSError(str(exc)) from exc
        return response.json()
