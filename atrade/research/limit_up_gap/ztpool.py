"""东财涨停池历史增强（可选）。

默认不启用；`--with-zt-pool` 打开后，按日期拉取涨停池，补充换手率、
流通市值、炸板次数、封单资金。接口不可用/失败时原样返回。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import pandas as pd

ZT_COLUMN_MAP = {
    "代码": "code",
    "换手率": "zt_turnover",
    "流通市值": "zt_float_mv_yi",
    "炸板次数": "zt_break_count",
    "封单资金": "zt_seal_amount_yi",
}
ZT_FACTOR_COLUMNS = [
    "zt_turnover",
    "zt_float_mv_yi",
    "zt_break_count",
    "zt_seal_amount_yi",
]


def fetch_zt_day(date: str) -> Optional[pd.DataFrame]:
    """拉取某交易日涨停池；失败返回 None。"""
    try:
        import akshare as ak

        compact = datetime.strptime(date, "%Y-%m-%d").strftime("%Y%m%d")
        df = ak.stock_zt_pool_em(date=compact)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def enrich_samples(
    samples: pd.DataFrame,
    fetch_day: Optional[Callable[[str], Optional[pd.DataFrame]]] = None,
) -> pd.DataFrame:
    """按 date+code 合并涨停池字段；缺失值保留 NA。"""
    if samples.empty:
        return samples
    fetch_day = fetch_day or fetch_zt_day
    pieces: list[pd.DataFrame] = []
    for date in sorted(samples["date"].unique()):
        day = samples[samples["date"] == date].copy()
        zt = fetch_day(date)
        if zt is None or zt.empty:
            for col in ZT_FACTOR_COLUMNS:
                day[col] = pd.NA
            pieces.append(day)
            continue
        zt = zt.rename(columns=ZT_COLUMN_MAP).copy()
        zt["code"] = zt["code"].astype(str).str.zfill(6)
        zt = zt.drop_duplicates("code")
        merge_cols = [col for col in ZT_FACTOR_COLUMNS if col in zt.columns]
        day = day.merge(zt[["code"] + merge_cols], on="code", how="left")
        if "zt_float_mv_yi" in day.columns:
            day["zt_float_mv_yi"] = day["zt_float_mv_yi"] / 1e8
        if "zt_seal_amount_yi" in day.columns:
            day["zt_seal_amount_yi"] = day["zt_seal_amount_yi"] / 1e8
        for col in ZT_FACTOR_COLUMNS:
            if col not in day.columns:
                day[col] = pd.NA
        pieces.append(day)
    return pd.concat(pieces, ignore_index=True)
