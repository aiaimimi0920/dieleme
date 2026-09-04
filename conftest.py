from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


_AVM_HTTP_CONTRACT = "test_avm_http_contract.py"
_STATEFUL_TERMS = (
    "captcha",
    "collection",
    "maintenance",
    "manual_review",
    "recovery",
    "solver",
)
_SLOW_TERMS = (
    "async",
    "captcha",
    "job",
    "poll",
    "recovery",
    "solver",
)


def pytest_itemcollected(item: pytest.Item) -> None:
    path = Path(str(item.path))
    if path.name != _AVM_HTTP_CONTRACT:
        item.add_marker(pytest.mark.quick)
        return

    item.add_marker(pytest.mark.integration)
    name = item.name.lower()
    if any(term in name for term in _STATEFUL_TERMS):
        item.add_marker(pytest.mark.stateful)
    if any(term in name for term in _SLOW_TERMS):
        item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def _use_fast_local_server_poll(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Avoid the BaseServer 500 ms shutdown tax in the AVM HTTP harness."""

    if Path(str(request.node.path)).name != _AVM_HTTP_CONTRACT:
        yield
        return

    from src.server import ReusableTCPServer

    original_serve_forever = ReusableTCPServer.serve_forever

    def serve_forever(server: Any, poll_interval: float = 0.01) -> None:
        original_serve_forever(server, poll_interval=poll_interval)

    monkeypatch.setattr(ReusableTCPServer, "serve_forever", serve_forever)
    yield
