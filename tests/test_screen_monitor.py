"""盘中/早盘选股推送渲染测试。"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from atrade.monitor.screen_ledger import RecommendationLedger
from atrade.monitor.screen_monitor import ScreenMonitorRunner


def _fake_candidates() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "code": "600519",
            "name": "贵州茅台",
            "price": 1253.0,
            "pct_chg": 2.5,
            "amplitude": 3.0,
            "amount": 1.25e9,
            "total_mv": 1.5e12,
            "pe_ttm": 25.0,
        },
        {
            "code": "000001",
            "name": "平安银行",
            "price": 10.8,
            "pct_chg": 1.2,
            "amplitude": 2.0,
            "amount": 1.08e10,
            "total_mv": 2.0e11,
            "pe_ttm": 5.5,
        },
    ])


def test_run_once_renders_real_price(monkeypatch, tmp_path):
    """快照 price 已是实际元，推送里不应再除以 100。"""
    df = _fake_candidates()
    ledger = RecommendationLedger(tmp_path / "recommendations.json")
    monkeypatch.setattr(
        "atrade.monitor.screen_monitor.fetch_market_snapshot",
        lambda: None,
    )
    monkeypatch.setattr(
        "atrade.monitor.screen_monitor.load_snapshot",
        lambda: df,
    )
    monkeypatch.setattr(
        "atrade.monitor.screen_monitor.filter_screen_candidates",
        lambda data, args: data,
    )

    md = ScreenMonitorRunner(ledger=ledger).run_once(source="pre_market")
    assert "1253.00" in md
    assert "10.80" in md
    assert "12.53" not in md
    assert "0.11" not in md
    picks = ledger.get(datetime.now().strftime("%Y-%m-%d"))
    assert len(picks) == 2
    assert picks[0].symbol == "600519"
    assert picks[0].price == 1253.0
    assert picks[0].source == "pre_market"


def test_run_once_disabled_returns_empty():
    assert ScreenMonitorRunner({"enabled": False}).run_once() == ""
