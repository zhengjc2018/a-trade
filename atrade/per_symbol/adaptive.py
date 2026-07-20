"""做 T 适配度与因子命中统计。"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Callable, Optional

import numpy as np
import pandas as pd

FACTORS = ("波段反弹", "趋势确认", "放量突破", "超卖反弹")


def _classify(signal) -> Optional[str]:
    if signal is None:
        return None
    hits = getattr(signal, "factor_hits", None) or []
    if hits:
        return hits[0]
    name = getattr(signal, "name", "")
    for f in FACTORS:
        if f in name:
            return f
    return None


def compute_adaptive(
    intraday_df: pd.DataFrame,
    signals_factory: Optional[Callable[[pd.DataFrame], Iterable]] = None,
    interval_minutes: int = 5,
) -> dict:
    if intraday_df is None or len(intraday_df) < 60:
        raise ValueError("分钟线数据不足 60 行")
    df = intraday_df.sort_values("date").reset_index(drop=True)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    pre_close = df["close"].shift(1)
    amp = ((high - low) / pre_close * 100).dropna()

    close = df["close"].astype(float)
    hold_min = _hold_minutes_p90(close, interval_minutes=interval_minutes)

    counter: Counter = Counter()
    if signals_factory is not None:
        try:
            signals_iter = signals_factory(df)
        except Exception:
            signals_iter = []
        for sig in signals_iter:
            tag = _classify(sig)
            if tag:
                counter[tag] += 1
    else:
        try:
            from atrade.signals import SignalEngine
            engine = SignalEngine()
            for i in range(60, len(df) + 1):
                sub = df.iloc[:i]
                try:
                    signals = engine.scan("000000", sub)
                except Exception:
                    continue
                for sig in signals:
                    tag = _classify(sig)
                    if tag:
                        counter[tag] += 1
        except Exception:
            counter = Counter()

    factor_score = {f: int(counter.get(f, 0)) for f in FACTORS}
    preferred = [f for f, _ in sorted(counter.items(), key=lambda kv: -kv[1])[:2]]

    p50 = float(np.percentile(amp, 50))
    if p50 < 0.5:
        position_pct = 0.1
    elif p50 > 2.0:
        position_pct = 0.5
    else:
        position_pct = round(0.1 + (p50 - 0.5) / 1.5 * 0.4, 3)
    position_pct = max(0.1, min(0.5, position_pct))

    return {
        "intra_amp_p50": round(float(np.percentile(amp, 50)), 3),
        "intra_amp_p90": round(float(np.percentile(amp, 90)), 3),
        "hold_minutes_p90": hold_min,
        "factor_score": factor_score,
        "preferred_factors": preferred,
        "position_pct": position_pct,
    }


def _hold_minutes_p90(close: pd.Series, interval_minutes: int) -> int:
    if len(close) < 2:
        return 0
    mn = close.cummin()
    mx = close.cummax()
    spread = mx - mn
    peak_idx = int(spread.idxmax())
    peak_value = spread.iloc[peak_idx]
    if peak_value <= 0:
        return 0
    target = peak_value * (1 - 0.9)
    for i in range(peak_idx, len(close)):
        if spread.iloc[i] <= target:
            return int((i - peak_idx) * interval_minutes)
    return int((len(close) - 1 - peak_idx) * interval_minutes)
