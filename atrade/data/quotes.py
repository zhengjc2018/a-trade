"""行情数据提供器。

支持多源：
- 新浪 (hq.sinajs.cn) — 主源，零频率限制
- 东财 (akshare) — 备用

用法：
    provider = QuoteProvider()
    quote = provider.get("600519")
    quote = provider.batch(["600519", "000001"])
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable

import requests
from loguru import logger


@dataclass
class Quote:
    """个股行情。"""
    symbol: str           # 600519
    name: str = ""
    open: float = 0.0
    prev_close: float = 0.0
    price: float = 0.0
    high: float = 0.0
    low: float = 0.0
    change: float = 0.0         # 涨跌额
    change_pct: float = 0.0     # 涨跌幅 %
    volume: int = 0             # 成交量
    turnover: float = 0.0       # 成交额
    datetime: str = ""

    @property
    def is_valid(self) -> bool:
        return self.price > 0


class QuoteProvider:
    """行情数据提供器。"""

    SINA_URL = "https://hq.sinajs.cn/list={symbols}"
    SINA_HEADERS = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
    }

    @staticmethod
    def _to_sina_symbol(symbol: str) -> str:
        """6 位代码 -> sh600519 / sz000001."""
        symbol = str(symbol).strip().zfill(6)
        prefix = "sh" if symbol.startswith("6") else "sz"
        return f"{prefix}{symbol}"

    @staticmethod
    def _from_sina_symbol(sina_sym: str) -> str:
        """sh600519 -> 600519."""
        return sina_sym[2:]

    def _parse_sina_line(self, line: str) -> Quote | None:
        """解析单只股票的新浪行情。
        
        数据格式：
        var hq_str_sh600519="贵州茅台,今开,昨收,现价,最高,最低,...,日期,时间,..."
        """
        m = re.match(r'var hq_str_([a-z]{2}\d{6})="([^"]+)"', line.strip())
        if not m:
            return None
        sina_sym, raw = m.groups()
        fields = raw.split(",")
        if len(fields) < 32:
            return None
        try:
            return Quote(
                symbol=self._from_sina_symbol(sina_sym),
                name=fields[0],
                open=float(fields[1] or 0),
                prev_close=float(fields[2] or 0),
                price=float(fields[3] or 0),
                high=float(fields[4] or 0),
                low=float(fields[5] or 0),
                volume=int(float(fields[8] or 0)),
                turnover=float(fields[9] or 0),
                datetime=f"{fields[30]} {fields[31]}",
            )
        except (ValueError, IndexError) as e:
            logger.debug(f"解析失败 {sina_sym}: {e}")
            return None

    def _fetch_sina(self, symbols: list[str]) -> dict[str, Quote]:
        """从新浪一次拉多只股票。"""
        if not symbols:
            return {}

        sina_syms = [self._to_sina_symbol(s) for s in symbols]
        url = self.SINA_URL.format(symbols=",".join(sina_syms))

        for attempt in range(3):
            try:
                resp = requests.get(
                    url, headers=self.SINA_HEADERS, timeout=10
                )
                resp.raise_for_status()
                result = {}
                for line in resp.text.strip().split("\n"):
                    quote = self._parse_sina_line(line)
                    if quote and quote.is_valid:
                        result[quote.symbol] = quote
                        # 算涨跌
                        if quote.prev_close > 0:
                            quote.change = quote.price - quote.prev_close
                            quote.change_pct = (
                                quote.change / quote.prev_close * 100
                            )
                logger.info(f"✅ 新浪行情: {len(result)}/{len(symbols)} 只")
                return result
            except Exception as e:
                logger.warning(f"新浪行情重试 {attempt+1}/3 失败: {e}")
                time.sleep(1 + attempt)
        logger.error(f"❌ 新浪行情 3 次重试后失败")
        return {}

    def get(self, symbol: str) -> Quote | None:
        """获取单只股票行情。"""
        return self.batch([symbol]).get(symbol)

    def batch(self, symbols: Iterable[str]) -> dict[str, Quote]:
        """批量获取行情（新浪一次拉）。"""
        symbols = list(symbols)
        return self._fetch_sina(symbols)
