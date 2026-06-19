from __future__ import annotations

import argparse
import select
import socket
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ForwardSpec:
    listen_host: str
    listen_port: int
    target_host: str
    target_port: int


def _split_host_port(value: str) -> tuple[str, int]:
    host, sep, raw_port = value.rpartition(":")
    if not sep or not host or not raw_port:
        raise ValueError(f"expected host:port, got {value!r}")
    port = int(raw_port)
    if port <= 0 or port > 65535:
        raise ValueError(f"invalid port in {value!r}")
    return host, port


def parse_forward_spec(value: str) -> ForwardSpec:
    listen, sep, target = str(value or "").partition("=")
    if not sep:
        raise ValueError(f"expected listen_host:listen_port=target_host:target_port, got {value!r}")
    listen_host, listen_port = _split_host_port(listen.strip())
    target_host, target_port = _split_host_port(target.strip())
    return ForwardSpec(
        listen_host=listen_host,
        listen_port=listen_port,
        target_host=target_host,
        target_port=target_port,
    )


def _pipe(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 60)
            if not readable:
                continue
            for source in readable:
                data = source.recv(64 * 1024)
                if not data:
                    return
                target = right if source is left else left
                target.sendall(data)
    finally:
        for sock in sockets:
            try:
                sock.close()
            except OSError:
                pass


def serve_forward(spec: ForwardSpec) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((spec.listen_host, spec.listen_port))
    server.listen(128)
    print(
        f"forwarding {spec.listen_host}:{spec.listen_port} -> {spec.target_host}:{spec.target_port}",
        flush=True,
    )
    while True:
        client, _addr = server.accept()
        try:
            target = socket.create_connection((spec.target_host, spec.target_port), timeout=15)
        except OSError:
            client.close()
            continue
        threading.Thread(target=_pipe, args=(client, target), daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Small TCP forwarder for Docker Desktop worker containers.")
    parser.add_argument(
        "--forward",
        action="append",
        required=True,
        help="Forward spec: listen_host:listen_port=target_host:target_port",
    )
    args = parser.parse_args()
    specs = [parse_forward_spec(value) for value in args.forward]
    for spec in specs:
        threading.Thread(target=serve_forward, args=(spec,), daemon=True).start()
    threading.Event().wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
