"""每日首板高开候选测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atrade.data.quotes import Quote
from atrade.research.limit_up_gap.daily_candidates import (
    build_daily_candidates,
    render_daily_candidates,
    score_candidates,
)


def _quote(code, price=11.0, open_price=10.5, high=11.0, low=10.4, volume=100_000):
    return Quote(
        symbol=code,
        open=open_price,
        high=high,
        low=low,
        price=price,
        volume=volume,
    )


def _history():
    n = 70
    closes = np.linspace(10.0, 15.0, n)
    closes[-2:] = [10.0, 10.0]  # 昨日收盘，今日 11.0 为涨停
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "open": closes * 0.99,
        "high": closes * 1.01,
        "low": closes * 0.98,
        "close": closes,
        "volume": np.full(n, 100_000),
    })


class _FakeHistory:
    def fetch_with_cache(self, code, scale="1d", datalen=150, use_snapshot=False):
        return _history()


def _zt_df():
    return pd.DataFrame([
        {"代码": "600001", "名称": "测试首板", "涨跌幅": 10.0, "连板数": 1, "所属行业": "半导体"},
        {"代码": "600005", "名称": "测试首板2", "涨跌幅": 10.0, "连板数": 1, "所属行业": "半导体"},
        {"代码": "600002", "名称": "测试连板", "涨跌幅": 10.0, "连板数": 2, "所属行业": "半导体"},
        {"代码": "600003", "名称": "测试一字板", "涨跌幅": 10.0, "连板数": 1, "所属行业": "白酒"},
        {"代码": "300001", "名称": "创业板", "涨跌幅": 20.0, "连板数": 1, "所属行业": "新能源"},
        {"代码": "600004", "名称": "ST测试", "涨跌幅": 5.0, "连板数": 1, "所属行业": "银行"},
    ])


def test_build_daily_candidates_filters_and_scores():
    zt = _zt_df()
    quotes = {
        "600001": _quote("600001"),
        "600005": _quote("600005"),
        "600003": _quote("600003", open_price=12.0, high=12.0, low=12.0, price=12.0),
    }
    candidates = build_daily_candidates(zt, _FakeHistory(), quotes, "2026-08-04")
    codes = {c["code"] for c in candidates}
    assert codes == {"600001", "600005"}
    assert all(c["industry_limit_count"] == 3 for c in candidates)
    assert all("vol_ratio_5" in c and "score" not in c for c in candidates)


def test_build_daily_candidates_overwrites_existing_today_row():
    hist = _history()
    hist.loc[hist.index[-1], "date"] = "2026-08-04"
    hist.loc[hist.index[-1], ["open", "high", "low"]] = [10.0, 10.1, 9.9]

    class _HistoryWithToday:
        def fetch_with_cache(self, code, scale="1d", datalen=150, use_snapshot=False):
            return hist

    zt = pd.DataFrame([
        {"代码": "600001", "名称": "测试首板", "涨跌幅": 10.0,
         "连板数": 1, "所属行业": "半导体"},
    ])
    quotes = {"600001": _quote("600001")}
    candidates = build_daily_candidates(zt, _HistoryWithToday(), quotes, "2026-08-04")
    assert len(candidates) == 1
    assert candidates[0]["code"] == "600001"


def test_score_candidates_sorts_by_score_desc():
    candidates = [
        {"code": "600001", "industry_limit_count": 2,
         "dist_high60": 0.1, "pos_ma20": 0.1, "vol_ratio_5": 0.5, "amplitude_pct": 1.0},
        {"code": "600005", "industry_limit_count": 1,
         "dist_high60": -0.1, "pos_ma20": -0.1, "vol_ratio_5": 5.0, "amplitude_pct": 9.0},
    ]
    scored = score_candidates(candidates)
    assert scored[0]["code"] == "600001"
    assert scored[0]["score"] >= scored[1]["score"]


def test_render_daily_candidates_contains_header():
    md = render_daily_candidates([
        {"code": "600001", "name": "测试首板", "price": 11.0,
         "industry_limit_count": 2, "vol_ratio_5": 0.5,
         "amplitude_pct": 1.0, "score": 5},
    ], now=pd.Timestamp("2026-08-04 14:50"))
    assert "# 🚀 a-trade 首板高开候选" in md
    assert "600001" in md


def test_render_daily_candidates_empty():
    assert render_daily_candidates([]) == ""
