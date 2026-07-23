"""GET /api/t-trades 测试。"""
import json


def test_trades_api_returns_recent(tmp_path, monkeypatch):
    trades_path = tmp_path / "t_trades.json"
    monkeypatch.setattr(
        "atrade.monitor.t_executor._TRADES_FILE", trades_path
    )
    trades_path.write_text(json.dumps([
        {"timestamp": "2026-07-23T10:00:00", "symbol": "002436",
         "direction": "SELL", "shares": 100, "price": 50.0,
         "holding_qty_after": 200, "skipped_reason": ""},
    ]))

    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.get("/api/t-trades")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["symbol"] == "002436"


def test_trades_api_empty(tmp_path, monkeypatch):
    trades_path = tmp_path / "t_trades.json"
    monkeypatch.setattr(
        "atrade.monitor.t_executor._TRADES_FILE", trades_path
    )
    # file doesn't exist
    from fastapi.testclient import TestClient

    from atrade.web.app import app
    c = TestClient(app)
    r = c.get("/api/t-trades")
    assert r.status_code == 200
    assert r.json() == []
