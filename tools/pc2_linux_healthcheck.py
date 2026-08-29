from __future__ import annotations

import argparse
import json
import os
import socket
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen


def _read_json(url: str) -> dict[str, object]:
    with urlopen(url, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected an object from {url}")
    return payload


def _process_exists(fragment: str) -> bool:
    proc_root = Path("/proc")
    for command_line_path in proc_root.glob("[0-9]*/cmdline"):
        try:
            command_line = command_line_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace")
        except OSError:
            continue
        if fragment in command_line:
            return True
    return False


def _check_rfb_server(host: str = "127.0.0.1", port: int = 5900) -> None:
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.settimeout(5)
        banner = bytearray()
        while len(banner) < 12:
            chunk = connection.recv(12 - len(banner))
            if not chunk:
                break
            banner.extend(chunk)
    if len(banner) != 12 or not banner.startswith(b"RFB ") or not banner.endswith(b"\n"):
        raise RuntimeError(f"invalid RFB banner from {host}:{port}")


def check_browser() -> None:
    cdp_endpoint = str(os.environ.get("FAPAI_CDP_ENDPOINT") or "http://127.0.0.1:9223").rstrip("/")
    version = _read_json(f"{cdp_endpoint}/json/version")
    if not version.get("webSocketDebuggerUrl"):
        raise RuntimeError("CDP websocket endpoint is missing")
    public_port = int(str(os.environ.get("FAPAI_CDP_PUBLIC_PORT") or "9224"))
    public_version = _read_json(f"http://127.0.0.1:{public_port}/json/version")
    if not public_version.get("webSocketDebuggerUrl"):
        raise RuntimeError("public CDP relay websocket endpoint is missing")
    with socket.create_connection(("127.0.0.1", 6080), timeout=5):
        pass
    _check_rfb_server()
    if not _process_exists("x0tigervncserver"):
        raise RuntimeError("TigerVNC server process is missing")
    if not _process_exists("websockify"):
        raise RuntimeError("noVNC WebSocket relay process is missing")
    if not _process_exists("tools/pc2_local_solver.py"):
        raise RuntimeError("PC2 local solver process is missing")


def check_worker() -> None:
    os.kill(1, 0)
    api_base_url = str(os.environ.get("FAPAI_API_BASE_URL") or "http://192.168.15.200:8001/api").rstrip("/")
    status = _read_json(urljoin(f"{api_base_url}/", "status"))
    if not status.get("db_mode"):
        raise RuntimeError("central API is not running in DB mode")
    output_root = Path("/data/output")
    if not output_root.is_dir() or not os.access(output_root, os.W_OK):
        raise RuntimeError("worker output root is not writable")


def main() -> int:
    parser = argparse.ArgumentParser(description="Health check for the Debian PC2 browser and collection workers.")
    parser.add_argument("--mode", choices=("browser", "worker"), required=True)
    args = parser.parse_args()
    if args.mode == "browser":
        check_browser()
    else:
        check_worker()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
