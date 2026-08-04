"""今日荐股胜率复盘渲染测试。"""

from __future__ import annotations

from datetime import datetime

from atrade.data.quotes import Quote
from atrade.monitor.screen_ledger import Recommendation
from atrade.monitor.screen_review import build_screen_review


def _quote(symbol: str, price: float) -> Quote:
    q = Quote(symbol=symbol)
    q.price = price
    return q


def test_build_review_computes_win_rate_and_pnl():
    records = [
        Recommendation("600519", "贵州茅台", 1253.0, "2026-08-03T09:26:05"),
        Recommendation("000001", "平安银行", 10.8, "2026-08-03T09:26:05"),
        Recommendation("601318", "中国平安", 48.0, "2026-08-03T09:26:05"),
    ]
    quotes = {
        "600519": _quote("600519", 1260.0),   # 涨
        "000001": _quote("000001", 10.5),     # 跌
        "601318": _quote("601318", 48.0),     # 平
    }
    md = build_screen_review(records, quotes, now=datetime(2026, 8, 3, 15, 0))
    assert "今日推荐 **3** 只" in md
    assert "1胜 1负 1平" in md
    assert "胜率 **33.3%**" in md
    assert "600519" in md
    assert "+7.00" in md
    assert "-0.30" in md
    assert "+6.70" in md  # 合计：7.00 - 0.30 + 0.00


def test_build_review_handles_missing_quotes():
    records = [Recommendation("600519", "贵州茅台", 1253.0, "2026-08-03T09:26:05")]
    md = build_screen_review(records, {}, now=datetime(2026, 8, 3, 15, 0))
    assert "胜率 **N/A**" in md
    assert "N/A" in md


def test_build_review_empty_returns_empty_string():
    assert build_screen_review([], {}, now=datetime(2026, 8, 3, 15, 0)) == ""
