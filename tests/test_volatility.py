import numpy as np
import pandas as pd
import pytest

from atrade.per_symbol.volatility import compute_volatility


def make_df(n=300):
    np.random.seed(0)
    close = 10 + np.cumsum(np.random.normal(0, 0.1, n))
    high = close * 1.01
    low = close * 0.99
    open_ = close + np.random.normal(0, 0.05, n)
    volume = np.random.randint(100000, 200000, n)
    date = pd.date_range("2025-06-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": date, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_compute_volatility_returns_required_keys():
    out = compute_volatility(make_df())
    for k in ("daily_amp_p50", "daily_amp_p90", "daily_amp_max",
              "atr_14_pct", "gap_abs_mean", "gap_abs_gt2_pct",
              "vol_zscore_60", "streak_max_up", "streak_max_down"):
        assert k in out, k


def test_compute_volatility_atr_in_range():
    out = compute_volatility(make_df())
    assert 0 < out["atr_14_pct"] < 20


def test_compute_volatility_rejects_short_df():
    df = make_df(10)
    with pytest.raises(ValueError):
        compute_volatility(df)
