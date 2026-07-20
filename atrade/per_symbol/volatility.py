"""波动性指标。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_volatility(df: pd.DataFrame) -> dict:
    if df is None or len(df) < 60:
        raise ValueError("日线数据不足 60 行")
    out = df.sort_values("date").reset_index(drop=True)

    high = out["high"].astype(float)
    low = out["low"].astype(float)
    close = out["close"].astype(float)
    pre_close = close.shift(1)

    amp = (high - low) / pre_close * 100
    amp = amp.dropna()

    tr = pd.concat([
        (high - low),
        (high - pre_close).abs(),
        (low - pre_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=14).mean().iloc[-1]
    atr14_pct = float(atr14 / close.iloc[-1] * 100)

    gap = (out["open"].astype(float) / pre_close - 1).dropna() * 100
    gap_abs = gap.abs()
    gap_abs_mean = float(gap_abs.mean())
    gap_abs_gt2_pct = float((gap_abs > 2).mean() * 100)

    vol = out["volume"].astype(float)
    vol_ma = vol.rolling(60, min_periods=20).mean()
    vol_std = vol.rolling(60, min_periods=20).std()
    vol_z = ((vol - vol_ma) / vol_std).dropna()
    vol_zscore_60 = float(vol_z.iloc[-1]) if len(vol_z) else 0.0

    pct = close.pct_change().fillna(0)
    up = (pct > 0).astype(int)
    down = (pct < 0).astype(int)
    streak_max_up = int(_max_run(up))
    streak_max_down = int(_max_run(down))

    return {
        "daily_amp_p50": float(np.percentile(amp, 50)),
        "daily_amp_p90": float(np.percentile(amp, 90)),
        "daily_amp_max": float(amp.max()),
        "atr_14_pct": round(atr14_pct, 3),
        "gap_abs_mean": round(gap_abs_mean, 3),
        "gap_abs_gt2_pct": round(gap_abs_gt2_pct, 3),
        "vol_zscore_60": round(vol_zscore_60, 3),
        "streak_max_up": streak_max_up,
        "streak_max_down": streak_max_down,
    }


def _max_run(series: pd.Series) -> int:
    max_run = run = 0
    for v in series:
        if v == 1:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run
