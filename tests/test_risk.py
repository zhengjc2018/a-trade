import numpy as np
import pandas as pd
import pytest

from atrade.per_symbol.risk import compute_risk


def make_df(n=300):
    np.random.seed(1)
    close = 10 + np.cumsum(np.random.normal(0, 0.1, n))
    return pd.DataFrame({
        "date": pd.date_range("2025-06-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.random.randint(100000, 200000, n),
    })


def test_compute_risk_keys():
    out = compute_risk(make_df())
    for k in ("annual_vol_pct", "max_drawdown_1y_pct",
              "monthly_max_dd_pct", "loss_streak_max"):
        assert k in out


def test_compute_risk_rejects_short_df():
    with pytest.raises(ValueError):
        compute_risk(make_df(10))


def test_compute_risk_values_reasonable():
    out = compute_risk(make_df())
    assert 0 < out["annual_vol_pct"] < 200
    assert out["max_drawdown_1y_pct"] <= 0
    assert out["monthly_max_dd_pct"] <= 0
    assert out["loss_streak_max"] >= 0
