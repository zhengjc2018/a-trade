"""次日高开研究（今日未涨停样本）测试。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from atrade.research.limit_up_gap.next_gap_study import (
    NextGapConfig,
    collect_next_gap_samples,
    render_next_gap_report,
    run_next_gap_study,
)


def _history():
    n = 70
    closes = np.linspace(10.0, 15.0, n)
    closes[-3:] = [10.0, 10.0, 11.0]  # 最后一天为首板，前一天为样本
    opens = closes.copy()
    opens[-1] = 11.5
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
        "open": opens,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": np.full(n, 100_000),
    })


class _FakeHistory:
    def fetch_with_cache(self, code, scale="1d", datalen=515, use_snapshot=False):
        return _history()


def _industry(code):
    return "半导体"


def test_collect_all_next_gap_samples():
    config = NextGapConfig(mode="all_next_gap", min_bars=65, lookback_bars=100)
    samples, excluded = collect_next_gap_samples(
        ["600001"],
        _FakeHistory(),
        _industry,
        config,
    )
    assert not samples.empty
    assert "next_open_gap_pct" in samples.columns
    assert excluded["industry"] == 0


def test_collect_first_board_predecessor_samples():
    config = NextGapConfig(mode="first_board_predecessor", min_bars=65, lookback_bars=100)
    samples, _ = collect_next_gap_samples(
        ["600001"],
        _FakeHistory(),
        _industry,
        config,
    )
    # 最后一天为首板，前一日是样本
    assert not samples.empty
    assert samples["date"].iloc[0] == _history().iloc[68]["date"]


def test_run_next_gap_study_and_render():
    config = NextGapConfig(
        mode="all_next_gap",
        min_samples=1,
        min_bars=65,
        lookback_bars=100,
    )
    result = run_next_gap_study(["600001"], _FakeHistory(), _industry, config)
    md = render_next_gap_report(result)
    assert "# 次日高开研究（今日未涨停）" in md
    assert "胜率" in md
