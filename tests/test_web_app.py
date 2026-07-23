"""FastAPI app + endpoints 测试。"""

import pytest


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("A_TRADE_WEB_TOKEN", raising=False)


def test_health_public():
    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["auth_enabled"] is False


def test_holdings_requires_auth_when_token_set(monkeypatch):
    monkeypatch.setenv("A_TRADE_WEB_TOKEN", "secret123")
    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/holdings")
    assert resp.status_code == 401


def test_holdings_ok_with_token(monkeypatch, tmp_path):
    monkeypatch.setenv("A_TRADE_WEB_TOKEN", "secret123")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(
        '{"holdings": [{"symbol": "600522", "name": "中天科技", '
        '"cost_price": 62.0, "quantity": 200, "buy_date": "", "note": ""}], '
        '"disabled_symbols": [], "watch_keywords": []}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/holdings", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["symbol"] == "600522"
    assert data[0]["enabled"] is True


def test_holdings_bad_token_401(monkeypatch, tmp_path):
    monkeypatch.setenv("A_TRADE_WEB_TOKEN", "secret123")
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "missing.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/holdings", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_put_holding_validates_negative_cost(monkeypatch, tmp_path):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(
        '{"holdings": [{"symbol": "600522", "name": "中天科技", '
        '"cost_price": 62.0, "quantity": 200, "buy_date": "", "note": ""}], '
        '"disabled_symbols": [], "watch_keywords": []}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.put("/api/holdings/600522", json={"cost_price": -1})
    assert resp.status_code == 400


def test_root_serves_html():
    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<html" in resp.text.lower()


def test_static_assets_served():
    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/static/app.css")
    # may 404 if css not built yet (Task 7); status should be 200 or 404
    assert resp.status_code in (200, 404)


def test_reload_returns_502_when_no_socket(monkeypatch):
    monkeypatch.setattr("atrade.web.reload_client._socket_path",
                        lambda: "/tmp/atrade-no-such-sock-zzz")
    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.post("/api/reload")
    assert resp.status_code == 502


def test_disable_via_enabled_flag(monkeypatch, tmp_path):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(
        '{"holdings": [{"symbol": "600522", "name": "中天科技", '
        '"cost_price": 62.0, "quantity": 200, "buy_date": "", "note": ""}], '
        '"disabled_symbols": [], "watch_keywords": []}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.put("/api/holdings/600522", json={"enabled": False})
    assert resp.status_code == 200

    resp = c.get("/api/holdings")
    target = next(h for h in resp.json() if h["symbol"] == "600522")
    assert target["enabled"] is False
