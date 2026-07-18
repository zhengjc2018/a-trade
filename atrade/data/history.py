"""历史 K 线 + 派生字段 + 本地缓存 + 东财当日快照。

数据流:
- fetch(sina) → 原 OHLCV，不入库
- fetch_with_cache → 优先读 cache，不足时拉 sina 入库；末尾补东财快照
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

import pandas as pd
import requests
from loguru import logger

from .cache import LocalCache
from .eastmoney import fetch_snap


@dataclass
class KLine:
    """单根 K 线。"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoryProvider:
    """历史 K 线（含本地缓存）。"""

    KLINE_URL = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/"
        "CN_MarketDataService.getKLineData"
        "?symbol={symbol}&scale={scale}&ma=no&datalen={datalen}"
    )

    HEADERS = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36",
    }

    SCALE_MAP = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60,
        "1d": 240, "1w": 1680,
    }

    def __init__(self, cache_path: Optional[str] = None):
        self.cache = LocalCache(db_path=cache_path)

    @staticmethod
    def _to_sina_symbol(symbol: str) -> str:
        symbol = str(symbol).strip().zfill(6)
        prefix = "sh" if symbol.startswith("6") else "sz"
        return f"{prefix}{symbol}"

    def fetch(
        self,
        symbol: str,
        scale: Literal["1d", "5m", "15m", "30m", "60m"] = "1d",
        datalen: int = 600,
    ) -> pd.DataFrame:
        """从新浪拉历史 K 线（不入库）。保留向后兼容。"""
        sina_sym = self._to_sina_symbol(symbol)
        sina_scale = self.SCALE_MAP.get(scale, 240)
        url = self.KLINE_URL.format(
            symbol=sina_sym, scale=sina_scale, datalen=datalen
        )

        for attempt in range(3):
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                resp.raise_for_status()
                text = resp.text.strip()
                m = re.search(r'=\(\[([\s\S]+)\]\)', text)
                if not m:
                    logger.warning(f"解析失败: {text[:200]}")
                    return pd.DataFrame()
                raw = "[" + m.group(1) + "]"
                records = json.loads(raw)
                df = pd.DataFrame(records)
                df = df.rename(columns={"day": "date"})
                for col in ["open", "high", "low", "close"]:
                    df[col] = df[col].astype(float)
                df["volume"] = df["volume"].astype(int)
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df[["date", "open", "high", "low", "close", "volume"]]
                logger.info(f"✅ 历史 K 线 {symbol} {scale}: {len(df)} 根")
                return df
            except Exception as e:
                logger.warning(f"历史 K 线重试 {attempt+1}/3: {e}")
                time.sleep(1 + attempt)
        return pd.DataFrame()

    def fetch_with_cache(
        self,
        symbol: str,
        scale: Literal["1d", "5m", "15m", "30m", "60m"] = "1d",
        datalen: int = 600,
        use_snapshot: bool = True,
    ) -> pd.DataFrame:
        """拉取 + 入库 + 派生字段 + 当日快照。

        Returns:
            DataFrame 含派生字段（pre_close, pct_chg, amplitude, amount,
            turnover, vol_ratio, is_st, ah_factor），末尾可能含当日基本面
            （pe_ttm, pb, float_mv, total_mv, float_share, total_share）。
        """
        symbol = str(symbol).zfill(6)

        # 5 分钟 / 15 分钟等日内数据无法直接落到日线 cache 的主键模型里，
        # 这里走“直接拉取 + 派生字段”路径，不写入 SQLite。
        if scale != "1d":
            raw = self.fetch(symbol, scale=scale, datalen=datalen)
            if raw.empty:
                return raw
            raw = raw.copy()
            raw["code"] = symbol
            raw["ah_factor"] = 1.0
            df = _add_derived_fields(raw)
            return df.tail(datalen).reset_index(drop=True)

        cached_count = self.cache.count(symbol)

        # 1. cache 命中足够，直接走 cache
        if cached_count >= max(60, datalen // 2):
            df = self.cache.range(symbol)
        else:
            # 2. 拉 sina 入库
            raw = self.fetch(symbol, scale=scale, datalen=datalen)
            if raw.empty:
                logger.warning(f"{symbol} 新浪拉取失败，回退到 cache")
                return self.cache.range(symbol)
            init = raw.copy()
            init["code"] = symbol
            init["ah_factor"] = 1.0
            self.cache.upsert_daily(init)
            df = self.cache.range(symbol)

        if df.empty:
            return df

        # 3. 派生字段（按 plan 配置 ah_factor=1.0）
        df = _add_derived_fields(df)
        df = df.tail(datalen).reset_index(drop=True)

        # 4. 当日快照（失败降级）
        if use_snapshot and len(df) > 0:
            snap = fetch_snap(symbol)
            if snap and snap.get("price"):
                # 当日 snapshot 写入最新一行
                idx = df.index[-1]
                for col in ["pe_ttm", "pb", "float_mv", "total_mv",
                            "float_share", "total_share"]:
                    if snap.get(col) is not None:
                        df.at[idx, col] = snap[col]
                if snap.get("name"):
                    df.at[idx, "name"] = snap["name"]
                # 写回 cache
                self.cache.upsert_daily(df.tail(1))

        return df


def _add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """派生字段。pre_close 由前一根 close 推出。"""
    out = df.copy()
    out["pre_close"] = out["close"].shift(1)
    out["pct_chg"] = (out["close"] - out["pre_close"]) / out["pre_close"] * 100
    out["amplitude"] = (out["high"] - out["low"]) / out["pre_close"] * 100
    out["amount"] = out["close"] * out["volume"] * 100  # 1手=100股
    if "VOL_MA5" in out.columns:
        out["vol_ratio"] = out["volume"] / out["VOL_MA5"]
    else:
        ma5 = out["volume"].rolling(5, min_periods=1).mean()
        out["vol_ratio"] = out["volume"] / ma5

    # turnover = volume / float_share * 100，若没有 float_share 则空
    if "float_share" not in out.columns:
        out["float_share"] = None
    out["turnover"] = out["volume"] / out["float_share"] * 100

    out["is_st"] = 0
    out["ah_factor"] = 1.0
    return out
