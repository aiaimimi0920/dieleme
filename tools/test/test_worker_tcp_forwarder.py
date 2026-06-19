from __future__ import annotations

import pytest

from tools.worker_tcp_forwarder import ForwardSpec, parse_forward_spec


def test_parse_forward_spec() -> None:
    assert parse_forward_spec("0.0.0.0:15532=192.168.15.200:55432") == ForwardSpec(
        listen_host="0.0.0.0",
        listen_port=15532,
        target_host="192.168.15.200",
        target_port=55432,
    )


def test_parse_forward_spec_rejects_missing_target() -> None:
    with pytest.raises(ValueError):
        parse_forward_spec("0.0.0.0:15532")
