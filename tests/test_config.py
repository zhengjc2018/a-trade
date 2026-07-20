import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.config import (
    ConfigError,
    load_holdings,
    load_monitor_config,
    load_watch_keywords,
)


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """将默认配置路径指向临时目录，避免污染仓库真实配置。"""
    from atrade import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "DEFAULT_HOLDINGS", tmp_path / "holdings.json")
    monkeypatch.setattr(cfg_mod, "LOCAL_HOLDINGS", tmp_path / "holdings.local.json")
    monkeypatch.setattr(cfg_mod, "DEFAULT_MONITOR", tmp_path / "monitor.json")
    monkeypatch.setattr(cfg_mod, "LOCAL_MONITOR", tmp_path / "monitor.local.json")
    monkeypatch.delenv("A_TRADE_HOLDINGS_PATH", raising=False)
    monkeypatch.delenv("A_TRADE_MONITOR_PATH", raising=False)
    return tmp_path


def test_load_holdings_prefers_local_over_default(isolated_config):
    """真实数据放在 *.local.json 应优先于默认 *.json。"""
    (isolated_config / "holdings.local.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "600000", "name": "本地", "cost_price": 5.0, "quantity": 1000}
        ]
    }))
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "600001", "name": "默认", "cost_price": 5.0, "quantity": 1000}
        ]
    }))
    holdings = load_holdings()
    assert len(holdings) == 1
    assert holdings[0]["symbol"] == "600000"


def test_load_holdings_falls_back_to_default(isolated_config):
    """仅有 holdings.json（无 .local）时也能加载。"""
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "600001", "name": "默认", "cost_price": 5.0, "quantity": 1000}
        ]
    }))
    holdings = load_holdings()
    assert holdings[0]["symbol"] == "600001"


def test_load_holdings_rejects_invalid_symbol(isolated_config):
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "abc", "cost_price": 5.0, "quantity": 1000}
        ]
    }))
    with pytest.raises(ConfigError, match="6 位数字"):
        load_holdings()


def test_load_holdings_rejects_zero_cost(isolated_config):
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "600001", "cost_price": 0, "quantity": 1000}
        ]
    }))
    with pytest.raises(ConfigError, match="cost_price"):
        load_holdings()


def test_load_holdings_rejects_zero_qty(isolated_config):
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "600001", "cost_price": 5.0, "quantity": 0}
        ]
    }))
    with pytest.raises(ConfigError, match="quantity"):
        load_holdings()


def test_load_holdings_normalizes_symbol_to_6_digits(isolated_config):
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [
            {"symbol": "519", "cost_price": 5.0, "quantity": 1000}
        ]
    }))
    holdings = load_holdings()
    assert holdings[0]["symbol"] == "000519"


def test_load_monitor_returns_validated_config(isolated_config):
    (isolated_config / "monitor.json").write_text(json.dumps({
        "news": {"enabled": True},
        "screen": {
            "enabled": True, "interval_minutes": 30,
            "pct_chg_min": -5, "pct_chg_max": 5,
            "amount_min": 1e8, "code_in": []
        },
        "t_monitor": {
            "enabled": True, "scan_interval_minutes": 2,
            "scale": "5m", "datalen": 120,
            "symbols": [{"symbol": "600001", "cost_price": 5.0, "quantity": 1000}]
        },
    }))
    cfg = load_monitor_config()
    assert cfg["news"]["enabled"] is True
    assert cfg["t_monitor"]["symbols"][0]["symbol"] == "600001"
    assert cfg["t_monitor"]["scale"] == "5m"


def test_load_monitor_rejects_invalid_scale(isolated_config):
    (isolated_config / "monitor.json").write_text(json.dumps({
        "t_monitor": {"scale": "99x", "scan_interval_minutes": 1, "datalen": 60, "symbols": []},
    }))
    with pytest.raises(ConfigError, match="scale"):
        load_monitor_config()


def test_load_monitor_rejects_negative_interval(isolated_config):
    (isolated_config / "monitor.json").write_text(json.dumps({
        "t_monitor": {"scale": "5m", "scan_interval_minutes": -1, "datalen": 60, "symbols": []},
    }))
    with pytest.raises(ConfigError, match="scan_interval_minutes"):
        load_monitor_config()


def test_load_monitor_returns_empty_when_missing(isolated_config):
    """未找到任何配置时返回空配置而非抛错。"""
    cfg = load_monitor_config()
    assert cfg["news"]["enabled"] is False
    assert cfg["t_monitor"]["symbols"] == []


def test_load_holdings_raises_when_all_missing(isolated_config):
    with pytest.raises(ConfigError, match="未找到"):
        load_holdings()


def test_load_watch_keywords_returns_list(isolated_config):
    (isolated_config / "holdings.json").write_text(json.dumps({
        "holdings": [],
        "watch_keywords": ["白酒", "半导体"],
    }))
    kw = load_watch_keywords()
    assert kw == ["白酒", "半导体"]
