"""涨停/首板/连板/一字板推导与 T+1 高开标签。"""

from __future__ import annotations

import pandas as pd

LIMIT_UP_PCT = 0.099


def add_limit_labels(
    df: pd.DataFrame,
    min_gap_pct: float = 1.0,
) -> pd.DataFrame:
    """按日期升序输入日线，追加涨停与次日高开相关列。"""
    out = df.copy()
    out["prev_close"] = out["close"].shift(1)
    out["is_limit_up"] = (
        (out["close"] >= out["prev_close"] * (1 + LIMIT_UP_PCT))
        & (out["prev_close"] > 0)
    )
    streak: list[int] = []
    current = 0
    for flag in out["is_limit_up"].tolist():
        current = current + 1 if flag else 0
        streak.append(current)
    out["limit_streak"] = streak
    out["is_first_board"] = out["limit_streak"] == 1
    out["is_yiziban"] = (
        out["is_limit_up"]
        & (out["open"] == out["high"])
        & (out["high"] == out["low"])
        & (out["low"] == out["close"])
    )
    out["next_open"] = out["open"].shift(-1)
    out["next_open_exists"] = out["next_open"].notna() & (out["next_open"] > 0)
    out["next_open_gap_pct"] = (out["next_open"] / out["close"] - 1) * 100
    out["next_open_win"] = (
        out["next_open_gap_pct"].ge(min_gap_pct).fillna(False)
    )
    return out
