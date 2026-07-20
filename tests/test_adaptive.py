import numpy as np
import pandas as pd
import pytest

from atrade.per_symbol.adaptive import compute_adaptive


def make_5m(n=240):
    np.random.seed(2)
    close = 10 + np.cumsum(np.random.normal(0, 0.05, n))
    high = close * 1.005
    low = close * 0.995
    open_ = close + np.random.normal(0, 0.02, n)
    volume = np.random.randint(1000, 5000, n)
    idx = pd.date_range("2026-07-01 09:30", periods=n, freq="5min")
    return pd.DataFrame({
        "date": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_compute_adaptive_keys():
    out = compute_adaptive(make_5m(), signals_factory=lambda df: [])
    for k in ("intra_amp_p50", "intra_amp_p90", "hold_minutes_p90",
              "factor_score", "preferred_factors", "position_pct"):
        assert k in out, k


def test_compute_adaptive_position_in_range():
    out = compute_adaptive(make_5m(), signals_factory=lambda df: [])
    assert 0.1 <= out["position_pct"] <= 0.5


def test_compute_adaptive_preferred_factors_max_two():
    out = compute_adaptive(make_5m(), signals_factory=lambda df: [])
    assert len(out["preferred_factors"]) <= 2


def test_compute_adaptive_rejects_short_df():
    df = pd.DataFrame({"date": pd.date_range("2026-07-01", periods=10, freq="5min"),
                       "open": [10] * 10, "high": [10.05] * 10, "low": [9.95] * 10,
                       "close": [10] * 10, "volume": [1000] * 10})
    with pytest.raises(ValueError):
        compute_adaptive(df, signals_factory=lambda d: [])
