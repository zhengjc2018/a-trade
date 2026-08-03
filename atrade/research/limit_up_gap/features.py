"""首板量价特征。"""

from __future__ import annotations

import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """按日期升序输入日线，追加量价特征列。"""
    out = df.copy()
    out["vol_ratio_5"] = out["volume"] / out["volume"].rolling(5).mean().shift(1)
    prev_close = out["pre_close"] if "pre_close" in out.columns else out["close"].shift(1)
    out["amplitude_pct"] = (out["high"] - out["low"]) / prev_close * 100
    out["close_is_high"] = out["close"] >= out["high"]
    span = out["high"] - out["low"]
    out["body_ratio"] = ((out["close"] - out["open"]) / span).where(span > 0, 1.0)
    out["pos_ma20"] = out["close"] / out["close"].rolling(20).mean() - 1
    out["pos_ma60"] = out["close"] / out["close"].rolling(60).mean() - 1
    high60 = out["high"].rolling(60).max().shift(1)
    low60 = out["low"].rolling(60).min().shift(1)
    out["dist_high60"] = out["close"] / high60 - 1
    out["dist_low60"] = out["close"] / low60 - 1
    amount = out["amount"] if "amount" in out.columns else out["close"] * out["volume"]
    out["amount_yi"] = amount / 1e8
    return out
