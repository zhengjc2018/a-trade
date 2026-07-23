"""web/reload_client.py 测试。"""
import os
import socketserver
import threading

import pytest


def _start_mock_server(sock_path, response):
    class H(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            self.wfile.write(response)

    class S(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    if os.path.exists(sock_path):
        os.remove(sock_path)
    server = S(sock_path, H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def _short_sock():
    base = "/tmp/atrade-rl-test"
    if os.path.exists(base):
        os.remove(base)
    return base


@pytest.fixture(autouse=True)
def cleanup():
    yield
    for p in ["/tmp/atrade-rl-test"]:
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_request_reload_parses_ok(monkeypatch):
    sock_path = _short_sock()
    monkeypatch.setattr("atrade.web.reload_client._socket_path", lambda: sock_path)
    _start_mock_server(sock_path, b"OK {'holdings': 2}\n")

    from atrade.web.reload_client import request_reload
    result = request_reload()
    assert result["holdings"] == 2


def test_request_reload_returns_raw_on_non_dict(monkeypatch):
    sock_path = _short_sock()
    monkeypatch.setattr("atrade.web.reload_client._socket_path", lambda: sock_path)
    _start_mock_server(sock_path, b"OK raw-text-here\n")

    from atrade.web.reload_client import request_reload
    result = request_reload()
    assert result == {"raw": "raw-text-here"}


def test_request_reload_raises_on_err(monkeypatch):
    sock_path = _short_sock()
    monkeypatch.setattr("atrade.web.reload_client._socket_path", lambda: sock_path)
    _start_mock_server(sock_path, b"ERR something broke\n")

    from atrade.web.reload_client import request_reload
    with pytest.raises(RuntimeError):
        request_reload()


def test_request_reload_raises_on_no_socket(monkeypatch):
    sock_path = "/tmp/atrade-nonexistent-sock-xyz"
    monkeypatch.setattr("atrade.web.reload_client._socket_path", lambda: sock_path)

    from atrade.web.reload_client import request_reload
    with pytest.raises((ConnectionRefusedError, FileNotFoundError, OSError)):
        request_reload()


def test_request_reload_raises_on_unexpected(monkeypatch):
    sock_path = _short_sock()
    monkeypatch.setattr("atrade.web.reload_client._socket_path", lambda: sock_path)
    _start_mock_server(sock_path, b"WHAT IS THIS\n")

    from atrade.web.reload_client import request_reload
    with pytest.raises(RuntimeError, match="unexpected"):
        request_reload()
