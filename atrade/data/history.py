"""历史 K 线数据提供器。

数据源：新浪财经（hq.sinajs.cn 体系）
- 日线：600 个交易日（约 2.5 年）
- 5 分钟线：最近几天
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd
import requests
from loguru import logger


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
    """历史 K 线数据。"""

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
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "60m": 60,
        "1d": 240,   # 日线
        "1w": 1680,  # 周线
    }

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
        """获取历史 K 线。
        
        Args:
            symbol: 6 位代码
            scale: K 线周期
            datalen: 拉多少根（最大 600）
        
        Returns:
            DataFrame with columns: date, open, high, low, close, volume
        """
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

                # 新浪返回 JSONP：/*<script>...*/=([...])
                m = re.search(r'=\(\[([\s\S]+)\]\)', text)
                if not m:
                    logger.warning(f"解析失败: {text[:200]}")
                    return pd.DataFrame()

                raw = "[" + m.group(1) + "]"
                records = json.loads(raw)

                df = pd.DataFrame(records)
                df = df.rename(columns={
                    "day": "date",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                })
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
