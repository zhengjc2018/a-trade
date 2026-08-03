"""首板次日高开标签推导测试。"""
from __future__ import annotations

import pandas as pd
import pytest

from atrade.research.limit_up_gap.labels import add_limit_labels


def _df():
    # 日期升序：T-1 普通、T 首板、T+1 高开、T+2 连板一字、T+3 普通
    return pd.DataFrame([
        {"date": "2026-07-29", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.1, "volume": 100_000},
        {"date": "2026-07-30", "open": 10.2, "high": 11.2, "low": 10.1, "close": 11.2, "volume": 300_000},
        {"date": "2026-07-31", "open": 11.5, "high": 11.8, "low": 11.2, "close": 11.5, "volume": 200_000},
        {"date": "2026-08-03", "open": 12.7, "high": 12.7, "low": 12.7, "close": 12.7, "volume": 50_000},
        {"date": "2026-08-04", "open": 12.8, "high": 13.0, "low": 12.6, "close": 12.9, "volume": 80_000},
    ])


def test_limit_labels():
    out = add_limit_labels(_df())
    assert list(out["is_limit_up"]) == [False, True, False, True, False]
    assert list(out["limit_streak"]) == [0, 1, 0, 1, 0]
    assert list(out["is_first_board"]) == [False, True, False, True, False]
    # 2026-08-03 是一字板；2026-07-30 不是
    assert list(out["is_yiziban"]) == [False, False, False, True, False]
    # T=2026-07-30 的 T+1 开盘 11.5，gap = 11.5/11.2 - 1 = 2.68%
    assert out.loc[1, "next_open_gap_pct"] == pytest.approx(2.6785, rel=1e-3)
    assert bool(out.loc[1, "next_open_win"])
    # 最后一根无 T+1
    assert not bool(out.loc[4, "next_open_exists"])


def test_min_gap_threshold():
    out = add_limit_labels(_df(), min_gap_pct=3.0)
    # gap 2.68% < 3%，不算胜
    assert not bool(out.loc[1, "next_open_win"])
