"""明日高开候选测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atrade.research.limit_up_gap.next_day_candidates import (
    build_next_day_candidates,
    render_next_day_candidates,
    score_candidates,
)


def _history():
    n = 70
    closes = np.linspace(10.0, 15.0, n)
    closes[-2:] = [10.0, 10.0]
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


def _snapshot():
    return pd.DataFrame([
        {"code": "600001", "name": "有效候选", "price": 12.0, "pct_chg": 2.0,
         "high": 12.3, "low": 11.8, "pe_ttm": 20.0, "pb": 2.0, "volume_lots": 1000},
        {"code": "600002", "name": "ST测试", "price": 5.0, "pct_chg": 2.0,
         "high": 5.1, "low": 4.9, "pe_ttm": 10.0, "pb": 1.0, "volume_lots": 1000},
        {"code": "600003", "name": "高价股", "price": 100.0, "pct_chg": 2.0,
         "high": 101.0, "low": 99.0, "pe_ttm": 20.0, "pb": 2.0, "volume_lots": 1000},
        {"code": "600004", "name": "差基本面", "price": 12.0, "pct_chg": 2.0,
         "high": 12.3, "low": 11.8, "pe_ttm": 200.0, "pb": 2.0, "volume_lots": 1000},
        {"code": "600005", "name": "接近涨停", "price": 12.0, "pct_chg": 9.9,
         "high": 12.3, "low": 11.8, "pe_ttm": 20.0, "pb": 2.0, "volume_lots": 1000},
        {"code": "300001", "name": "创业板", "price": 12.0, "pct_chg": 2.0,
         "high": 12.3, "low": 11.8, "pe_ttm": 20.0, "pb": 2.0, "volume_lots": 1000},
    ])


def _zt():
    return pd.DataFrame([
        {"代码": "600006", "名称": "涨停股", "涨跌幅": 10.0,
         "连板数": 1, "所属行业": "半导体"},
    ])


def _industry(code):
    return "证券" if code == "600007" else "半导体"


def test_build_next_day_candidates_filters():
    snapshot = pd.concat([
        _snapshot(),
        pd.DataFrame([
            {"code": "600007", "name": "证券板块", "price": 12.0, "pct_chg": 2.0,
             "high": 12.3, "low": 11.8, "pe_ttm": 20.0, "pb": 2.0, "volume_lots": 1000},
        ]),
    ], ignore_index=True)
    candidates = build_next_day_candidates(
        snapshot,
        _zt(),
        _FakeHistory(),
        _industry,
        "2026-08-04",
    )
    assert len(candidates) == 1
    assert candidates[0]["code"] == "600001"
    assert candidates[0]["industry_limit_count"] == 1


def test_score_and_render_top3():
    candidates = [
        {"code": "600001", "name": "A", "price": 12.0,
         "industry_limit_count": 3, "dist_high60": -0.1, "pos_ma20": 0.1,
         "pos_ma60": 0.1, "dist_low60": 0.2, "amount_yi": 10.0,
         "vol_ratio_5": 2.0, "amplitude_pct": 6.0},
        {"code": "600002", "name": "B", "price": 12.0,
         "industry_limit_count": 2, "dist_high60": 0.0, "pos_ma20": 0.0,
         "pos_ma60": 0.0, "dist_low60": 0.1, "amount_yi": 5.0,
         "vol_ratio_5": 1.0, "amplitude_pct": 3.0},
        {"code": "600003", "name": "C", "price": 12.0,
         "industry_limit_count": 1, "dist_high60": 0.1, "pos_ma20": -0.1,
         "pos_ma60": -0.1, "dist_low60": 0.0, "amount_yi": 1.0,
         "vol_ratio_5": 0.5, "amplitude_pct": 1.0},
    ]
    scored = score_candidates(candidates)
    assert scored[0]["code"] == "600001"
    md = render_next_day_candidates(scored, top_n=3, now=pd.Timestamp("2026-08-04 14:50"))
    assert "# 🚀 a-trade 明日高开候选" in md
    assert "600001" in md
    assert "Top 3" in md
