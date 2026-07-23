"""holdings 配置新增 disabled_symbols 字段测试。"""
import json

import pytest


def test_disabled_symbols_passthrough(tmp_path, monkeypatch):
    cfg_path = tmp_path / "holdings.json"
    cfg_path.write_text(json.dumps({
        "holdings": [{"symbol": "600519", "name": "茅台",
                      "cost_price": 1500, "quantity": 100,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": ["600519"],
        "watch_keywords": ["白酒"],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", cfg_path)
    # LOCAL_HOLDINGS 不存在 → 走 DEFAULT_HOLDINGS
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "missing.json")
    # 清空环境变量避免影响测试
    monkeypatch.delenv("A_TRADE_HOLDINGS_PATH", raising=False)

    from atrade.config import load_holdings_with_meta
    result = load_holdings_with_meta()
    assert result["holdings"][0]["symbol"] == "600519"
    assert result["disabled_symbols"] == ["600519"]
    assert result["watch_keywords"] == ["白酒"]


def test_invalid_disabled_symbol_format(tmp_path, monkeypatch):
    cfg_path = tmp_path / "holdings.json"
    cfg_path.write_text(json.dumps({
        "holdings": [],
        "disabled_symbols": ["abc"],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", cfg_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "missing.json")
    monkeypatch.delenv("A_TRADE_HOLDINGS_PATH", raising=False)

    from atrade.config import load_holdings_with_meta
    with pytest.raises(Exception) as exc:
        load_holdings_with_meta()
    assert "6 位" in str(exc.value) or "symbol" in str(exc.value).lower()


def test_default_when_missing(tmp_path, monkeypatch):
    cfg_path = tmp_path / "holdings.json"
    # 旧格式：没有 disabled_symbols / watch_keywords
    cfg_path.write_text(json.dumps({
        "holdings": [{"symbol": "600519", "name": "茅台",
                      "cost_price": 1500, "quantity": 100,
                      "buy_date": "", "note": ""}],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", cfg_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "missing.json")
    monkeypatch.delenv("A_TRADE_HOLDINGS_PATH", raising=False)

    from atrade.config import load_holdings_with_meta
    result = load_holdings_with_meta()
    assert result["disabled_symbols"] == []
    assert result["watch_keywords"] == []
