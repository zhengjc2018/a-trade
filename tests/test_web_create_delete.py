"""POST /api/holdings + DELETE /api/holdings/{symbol} 测试。"""
import json


def test_create_holding(tmp_path, monkeypatch):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "600519", "name": "茅台",
                      "cost_price": 1500, "quantity": 100,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.post("/api/holdings", json={
        "symbol": "600522", "name": "中天科技",
        "cost_price": 62.0, "quantity": 200,
        "buy_date": "2026-05-01", "note": "新仓",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["symbol"] == "600522"
    assert body["name"] == "中天科技"
    assert body["cost_price"] == 62.0


def test_create_duplicate_rejected(tmp_path, monkeypatch):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "600519", "name": "茅台",
                      "cost_price": 1500, "quantity": 100,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.post("/api/holdings", json={
        "symbol": "600519", "name": "重复",
        "cost_price": 1500, "quantity": 100,
    })
    assert r.status_code == 400
    assert "已存在" in r.json()["detail"]


def test_create_missing_required_field(tmp_path, monkeypatch):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [], "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.post("/api/holdings", json={"symbol": "600522", "name": "x"})
    assert r.status_code == 400
    assert "cost_price" in r.json()["detail"] or "quantity" in r.json()["detail"]


def test_create_invalid_symbol(tmp_path, monkeypatch):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [], "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.post("/api/holdings", json={
        "symbol": "abc", "name": "x", "cost_price": 10, "quantity": 1,
    })
    assert r.status_code == 400


def test_delete_holding(tmp_path, monkeypatch):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [
            {"symbol": "600519", "name": "茅台",
             "cost_price": 1500, "quantity": 100, "buy_date": "", "note": ""},
            {"symbol": "000001", "name": "银行",
             "cost_price": 12, "quantity": 5000, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": ["000001"],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.delete("/api/holdings/000001")
    assert r.status_code == 200
    assert r.json() == {"deleted": "000001"}

    # 列表应只剩 1 只 + disabled_symbols 同步移除
    r = c.get("/api/holdings")
    holdings = r.json()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "600519"


def test_delete_not_found(tmp_path, monkeypatch):
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [], "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.delete("/api/holdings/600999")
    assert r.status_code == 404
