"""Slow requests must not block unrelated collection API clients."""

import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler

import pytest

from src.collection_http_server import CollectionHTTPServer


@pytest.fixture
def listener():
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        timeout = 0.3

        def do_GET(self):
            if self.path == "/slow":
                entered.set()
                assert release.wait(5)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    with CollectionHTTPServer(("127.0.0.1", 0), Handler) as httpd:
        thread = threading.Thread(
            target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            yield httpd, entered, release
        finally:
            release.set()
            httpd.shutdown()
            thread.join(timeout=3)
            assert not thread.is_alive()


def get(address, path):
    connection = HTTPConnection(*address, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_blocking_handler_does_not_block_another_request(listener):
    httpd, entered, release = listener
    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(get, httpd.server_address, "/slow")
        try:
            assert entered.wait(2)
            assert get(httpd.server_address, "/ready") == (200, b"ok")
            assert not slow.done()
        finally:
            release.set()
        assert slow.result(timeout=2) == (200, b"ok")


def test_partial_headers_timeout_without_holding_other_requests(listener):
    httpd, _, _ = listener
    with socket.create_connection(httpd.server_address, timeout=2) as slow:
        slow.sendall(b"GET /slow HTTP/1.1\r\nHost:")
        assert get(httpd.server_address, "/ready") == (200, b"ok")
        assert slow.recv(1) == b""
