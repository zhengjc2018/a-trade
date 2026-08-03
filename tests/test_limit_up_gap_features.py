"""量价特征测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atrade.research.limit_up_gap.features import add_features


def _df():
    n = 70
    closes = np.linspace(10.0, 15.0, n)
    return pd.DataFrame({
        "open": closes * 0.99,
        "high": closes * 1.03,
        "low": closes * 0.98,
        "close": closes,
        "volume": np.full(n, 100_000),
    })


def test_add_features():
    out = add_features(_df())
    last = out.iloc[-1]
    assert last["vol_ratio_5"] == pytest.approx(1.0, rel=1e-6)
    assert last["amplitude_pct"] > 0
    assert not bool(last["close_is_high"])
    assert 0.0 < last["body_ratio"] < 1.0
    assert last["pos_ma20"] > 0
    assert last["pos_ma60"] > 0
    assert last["dist_high60"] < 0
    assert last["dist_low60"] >= 0
    assert last["amount_yi"] > 0
