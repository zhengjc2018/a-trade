"""风险指标。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_risk(df: pd.DataFrame) -> dict:
    if df is None or len(df) < 60:
        raise ValueError("日线数据不足 60 行")
    out = df.sort_values("date").reset_index(drop=True)
    close = out["close"].astype(float)
    pct = close.pct_change().dropna()

    annual_vol = float(pct.std() * np.sqrt(252) * 100)

    tail = close.tail(252).reset_index(drop=True)
    dd = _drawdown_series(tail)
    max_dd_1y = float(dd.min() * 100)

    monthly_max_dd = _monthly_max_drawdown(tail)

    loss_streak = int(_max_run((pct < 0).astype(int)))

    return {
        "annual_vol_pct": round(annual_vol, 3),
        "max_drawdown_1y_pct": round(max_dd_1y, 3),
        "monthly_max_dd_pct": round(monthly_max_dd, 3),
        "loss_streak_max": loss_streak,
    }


def _drawdown_series(close: pd.Series) -> pd.Series:
    peak = close.cummax()
    return close / peak - 1


def _monthly_max_drawdown(close: pd.Series) -> float:
    if close is None or len(close) == 0:
        return 0.0
    worst = 0.0
    chunks = np.array_split(close.values, 12) if len(close) > 12 else [close.values]
    for chunk in chunks:
        if len(chunk) < 2:
            continue
        sub = pd.Series(chunk)
        dd = _drawdown_series(sub).min()
        if pd.notna(dd):
            worst = min(worst, float(dd))
    return worst * 100


def _max_run(series: pd.Series) -> int:
    max_run = run = 0
    for v in series:
        if v == 1:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run
