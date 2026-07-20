"""历史 K 线 + 派生字段 + 本地缓存 + 东财当日快照。

数据契约：
- 新浪 K 线成交量单位为"股"（实测 600519 与实时报价一致），不再乘 100。
- 日线成交额 = close * volume（元），与实时报价成交额量级一致。
- 日线日期保存为 YYYY-MM-DD。
- 分钟线时间保存为 YYYY-MM-DD HH:MM:SS（保留时分秒）。
- 实时基本面只附加到当前返回的 DataFrame，不写回历史日线。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

import pandas as pd
import requests
from loguru import logger

from .cache import LocalCache
from .eastmoney import fetch_snap

# 缓存新鲜度：与最新交易日比较，落后超过这个工作日数就重新拉取。
CACHE_STALE_WORKDAYS = 1


@dataclass
class KLine:
    """单根 K 线。"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _last_n_trade_days(today: datetime, n: int) -> list[str]:
    """回溯 n 个工作日（粗略：跳过周末，不考虑节假日）。"""
    out = []
    d = today
    while len(out) < n:
        if d.weekday() < 5:  # 周一 ~ 周五
            out.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return out


class HistoryProvider:
    """历史 K 线（含本地缓存 + 新鲜度判断）。"""

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

    INTRADAY_SCALES = {"1m", "5m", "15m", "30m", "60m"}

    def __init__(self, cache_path: Optional[str] = None):
        self.cache = LocalCache(db_path=cache_path)

    @staticmethod
    def _to_sina_symbol(symbol: str) -> str:
        symbol = str(symbol).strip().zfill(6)
        prefix = "sh" if symbol.startswith("6") else "sz"
        return f"{prefix}{symbol}"

    @staticmethod
    def _format_date(date_str: str, scale: str) -> str:
        """统一时间字段格式：日线 YYYY-MM-DD；分钟线 YYYY-MM-DD HH:MM:SS。"""
        if scale == "1d":
            return str(date_str)[:10]
        # 分钟线原始值形如 "2026-07-15 10:30" / "2026-07-15"
        s = str(date_str)
        if len(s) == 10:
            return f"{s} 15:00:00"  # 历史分钟线缺时间时按收盘占位
        return s

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
                # 新浪 K 线成交量单位为"股"
                df["volume"] = df["volume"].astype(int)
                df["date"] = df["date"].apply(lambda s: self._format_date(s, scale))
                df = df[["date", "open", "high", "low", "close", "volume"]]
                logger.info(f"✅ 历史 K 线 {symbol} {scale}: {len(df)} 根")
                return df
            except Exception as e:
                logger.warning(f"历史 K 线重试 {attempt+1}/3: {e}")
                time.sleep(1 + attempt)
        return pd.DataFrame()

    def is_cache_stale(self, symbol: str) -> bool:
        """缓存是否需要刷新：返回 True 时应重新拉取。

        判定规则：
        - 缓存为空 → True
        - 缓存最后日期落后今天 >= CACHE_STALE_WORKDAYS 个工作日 → True
        """
        last = self.cache.last_date(symbol)
        if not last:
            return True
        try:
            datetime.strptime(last, "%Y-%m-%d")
        except ValueError:
            return True
        recent = _last_n_trade_days(datetime.now(), CACHE_STALE_WORKDAYS)
        # 如果 last 早于最近 N 个工作日的最早一天，就视为陈旧
        return last < recent[-1]

    def fetch_with_cache(
        self,
        symbol: str,
        scale: Literal["1d", "5m", "15m", "30m", "60m"] = "1d",
        datalen: int = 600,
        use_snapshot: bool = True,
    ) -> pd.DataFrame:
        """拉取 + 入库 + 派生字段 + 可选当日快照。

        Returns:
            DataFrame 含派生字段（pre_close, pct_chg, amplitude, amount,
            turnover, vol_ratio, is_st, ah_factor），末尾可能含当日基本面
            （pe_ttm, pb, float_mv, total_mv, float_share, total_share）。
        """
        symbol = str(symbol).zfill(6)

        if scale in self.INTRADAY_SCALES:
            raw = self.fetch(symbol, scale=scale, datalen=datalen)
            if raw.empty:
                return raw
            raw = raw.copy()
            raw["code"] = symbol
            raw["ah_factor"] = 1.0
            df = _add_derived_fields(raw)
            return df.tail(datalen).reset_index(drop=True)

        cached_count = self.cache.count(symbol)
        cache_stale = self.is_cache_stale(symbol)

        # 1. cache 命中足够且不陈旧，直接走 cache
        if cached_count >= max(60, datalen // 2) and not cache_stale:
            df = self.cache.range(symbol)
        else:
            # 2. 拉 sina 入库
            raw = self.fetch(symbol, scale=scale, datalen=datalen)
            if raw.empty:
                if cached_count > 0:
                    logger.warning(f"{symbol} 新浪拉取失败，回退到 cache")
                    return self.cache.range(symbol)
                return raw
            init = raw.copy()
            init["code"] = symbol
            init["ah_factor"] = 1.0
            self.cache.upsert_daily(init)
            df = self.cache.range(symbol)

        if df.empty:
            return df

        df = _add_derived_fields(df)
        df = df.tail(datalen).reset_index(drop=True)

        # 4. 当日快照：实时字段仅附加到内存中的最后一行，不写回历史日线。
        if use_snapshot and len(df) > 0:
            snap = fetch_snap(symbol)
            if snap and snap.get("price"):
                idx = df.index[-1]
                for col in ["pe_ttm", "pb", "float_mv", "total_mv",
                            "float_share", "total_share"]:
                    if snap.get(col) is not None:
                        df.at[idx, col] = snap[col]
                if snap.get("name"):
                    df.at[idx, "name"] = snap["name"]

        return df


def _add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """派生字段。pre_close 由前一根 close 推出。

    amount = close * volume （元）；volume 已经是股。
    """
    out = df.copy()
    out["pre_close"] = out["close"].shift(1)
    out["pct_chg"] = (out["close"] - out["pre_close"]) / out["pre_close"] * 100
    out["amplitude"] = (out["high"] - out["low"]) / out["pre_close"] * 100
    out["amount"] = out["close"] * out["volume"]
    if "VOL_MA5" in out.columns:
        out["vol_ratio"] = out["volume"] / out["VOL_MA5"]
    else:
        ma5 = out["volume"].rolling(5, min_periods=1).mean()
        out["vol_ratio"] = out["volume"] / ma5

    if "float_share" not in out.columns:
        out["float_share"] = None
    out["turnover"] = out["volume"] / out["float_share"] * 100

    out["is_st"] = 0
    out["ah_factor"] = 1.0
    return out
