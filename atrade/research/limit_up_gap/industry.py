"""行业标签与同行业涨停热度。"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
import requests


@lru_cache(maxsize=4096)
def industry_of(code: str) -> str:
    """腾讯行业接口；失败返回空字符串。"""
    code = str(code).zfill(6)
    market = "sh" + code if code.startswith(("5", "6", "7", "9")) else "sz" + code
    url = f"https://web.ifzq.gtimg.cn/appstock/app/MarketLayout?code={market}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        info = resp.json().get("data", {}).get(market, {})
        return str(info.get("industry") or info.get("hyName") or "").strip()
    except Exception:
        return ""


def daily_industry_heat(limit_rows: pd.DataFrame) -> pd.DataFrame:
    """统计每个交易日各行业的涨停家数，并标记前 3。"""
    if limit_rows.empty:
        return pd.DataFrame(columns=["date", "industry", "limit_count", "is_top3"])
    grouped = (
        limit_rows.groupby(["date", "industry"], dropna=False)
        .size()
        .rename("limit_count")
        .reset_index()
    )
    grouped["is_top3"] = (
        grouped.groupby("date")["limit_count"]
        .rank(method="first", ascending=False)
        <= 3
    )
    return grouped


def merge_industry_heat(
    samples: pd.DataFrame,
    heat: pd.DataFrame,
) -> pd.DataFrame:
    """把板块热度合并到首板样本，缺失行业按 0 处理。"""
    merged = samples.merge(heat, on=["date", "industry"], how="left")
    merged["industry_limit_count"] = merged["limit_count"].fillna(0).astype(int)
    merged["industry_is_top3"] = merged["is_top3"].eq(True).astype(bool)
    return merged.drop(columns=["limit_count", "is_top3"], errors="ignore")
