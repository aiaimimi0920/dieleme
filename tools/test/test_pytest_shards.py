from __future__ import annotations

import socket

import pytest

from conftest import _network_host_is_local
from scripts.run_pytest_shards import (
    _resolve_artifact_path,
    assign_shards,
    main,
    parse_collection_test_files,
)


def test_collection_output_is_normalized_and_deduplicated() -> None:
    output = """
tools\\test\\test_alpha.py::test_one
tools/test/test_alpha.py::test_two
tests/test_beta.py::test_three
3 tests collected
"""

    assert parse_collection_test_files(output) == [
        "tests/test_beta.py",
        "tools/test/test_alpha.py",
    ]


def test_collection_parser_ignores_non_node_warning_text() -> None:
    output = "warning: request owner::method is deprecated\n"

    assert parse_collection_test_files(output) == []


def test_weighted_shards_are_deterministic_and_keep_every_file() -> None:
    files = [
        "tools/test/test_run_hybrid_seed_collection.py",
        "tools/test/test_seed_collector.py",
        "tools/test/test_small_a.py",
        "tools/test/test_small_b.py",
    ]

    first = assign_shards(files, 2)
    second = assign_shards(list(reversed(files)), 2)

    assert first == second
    assert sorted(path for shard in first for path in shard) == sorted(files)
    assert "tools/test/test_run_hybrid_seed_collection.py" in first[0]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("api.localhost", False),
        ("127.0.0.1", True),
        ("::1", True),
        ("catalog.example", False),
        ("192.168.1.2", False),
    ],
)
def test_offline_network_policy_only_allows_loopback(host: str, expected: bool) -> None:
    assert _network_host_is_local(host) is expected


def test_external_dns_is_blocked_by_default() -> None:
    with pytest.raises(OSError, match="external DNS disabled"):
        socket.getaddrinfo("catalog.example", 443)


def test_external_connect_ex_is_blocked_by_default() -> None:
    sock = socket.socket()
    try:
        with pytest.raises(OSError, match="connect_ex"):
            sock.connect_ex(("203.0.113.1", 443))
    finally:
        sock.close()


def test_external_udp_is_blocked_by_default() -> None:
    sock = socket.socket(type=socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError, match="sendto"):
            sock.sendto(b"offline", ("203.0.113.1", 53))
    finally:
        sock.close()


@pytest.mark.skipif(not hasattr(socket.socket, "sendmsg"), reason="sendmsg unavailable")
def test_external_sendmsg_is_blocked_by_default() -> None:
    sock = socket.socket(type=socket.SOCK_DGRAM)
    try:
        with pytest.raises(OSError, match="sendmsg"):
            sock.sendmsg([b"offline"], [], 0, ("203.0.113.1", 53))
    finally:
        sock.close()


def test_offline_runner_rejects_live_network_override() -> None:
    with pytest.raises(ValueError, match="cannot enable live network"):
        main(["--", "--allow-live-network"])


def test_shard_artifacts_cannot_escape_repository(tmp_path) -> None:
    with pytest.raises(ValueError, match="must stay under"):
        _resolve_artifact_path(tmp_path / "outside.json")
