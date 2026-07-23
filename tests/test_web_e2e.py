"""End-to-end: web PUT → mock scheduler reload → JSON file updated."""
import json
import os
import socketserver
import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fake_scheduler(monkeypatch, tmp_path):
    """启动 fake scheduler socket，响应 reload。"""
    sock_path = "/tmp/atrade-e2e-sock"
    if os.path.exists(sock_path):
        os.remove(sock_path)
    monkeypatch.setenv("A_TRADE_RELOAD_SOCK", sock_path)
    monkeypatch.setattr("atrade.web.reload_client._socket_path", lambda: sock_path)

    class H(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            self.wfile.write(b"OK {'holdings': 1, 't_symbols': 1}\n")

    class S(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    server = S(sock_path, H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    h_path = tmp_path / "h.json"
    h_path.write_text(json.dumps({
        "holdings": [{"symbol": "600522", "name": "中天科技",
                      "cost_price": 62.0, "quantity": 200,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", h_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    yield sock_path

    if os.path.exists(sock_path):
        os.remove(sock_path)


def test_put_then_reload_updates_file(fake_scheduler):
    from atrade.web.app import app
    c = TestClient(app)

    r = c.put("/api/holdings/600522", json={"cost_price": 65.5})
    assert r.status_code == 200
    assert r.json()["cost_price"] == 65.5

    r = c.post("/api/reload")
    assert r.status_code == 200
    assert r.json()["holdings"] == 1


def test_put_then_get_reflects_change(fake_scheduler):
    from atrade.web.app import app
    c = TestClient(app)

    c.put("/api/holdings/600522", json={"quantity": 300})
    r = c.get("/api/holdings")
    assert r.status_code == 200
    holdings = r.json()
    target = next(h for h in holdings if h["symbol"] == "600522")
    assert target["quantity"] == 300


def test_disable_via_enabled_false(fake_scheduler):
    from atrade.web.app import app
    c = TestClient(app)

    r = c.put("/api/holdings/600522", json={"enabled": False})
    assert r.status_code == 200

    r = c.get("/api/holdings")
    target = next(h for h in r.json() if h["symbol"] == "600522")
    assert target["enabled"] is False


def test_full_flow_with_token(monkeypatch, fake_scheduler):
    monkeypatch.setenv("A_TRADE_WEB_TOKEN", "test-token")
    from atrade.web.app import app
    c = TestClient(app)

    # No auth → 401
    r = c.put("/api/holdings/600522", json={"cost_price": 70})
    assert r.status_code == 401

    # With auth → 200
    r = c.put("/api/holdings/600522", json={"cost_price": 70},
              headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200

    r = c.post("/api/reload",
               headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
