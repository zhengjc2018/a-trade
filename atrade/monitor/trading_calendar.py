"""A 股交易日与交易时段判断。"""

from __future__ import annotations

from datetime import datetime, date, time
from functools import lru_cache
from typing import Optional

import akshare as ak
from loguru import logger


MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)


class TradingCalendar:
    """A 股交易日历与交易时段判断。"""

    def __init__(self):
        self._trade_dates = None

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_trade_dates() -> set[str]:
        try:
            df = ak.tool_trade_date_hist_sina()
            col = "trade_date" if "trade_date" in df.columns else df.columns[0]
            dates = {str(v)[:10] for v in df[col].tolist()}
            logger.info(f"已加载交易日历: {len(dates)} 天")
            return dates
        except Exception as e:
            logger.warning(f"加载交易日历失败，回退到工作日判断: {e}")
            return set()

    @staticmethod
    def _normalize_day(value: Optional[object] = None) -> str:
        if value is None:
            return datetime.now().strftime("%Y-%m-%d")
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        s = str(value).strip()
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        return s[:10]

    def is_trade_day(self, value: Optional[object] = None) -> bool:
        day = self._normalize_day(value)
        trade_dates = self._load_trade_dates()
        if trade_dates:
            return day in trade_dates
        # fallback: 工作日
        dt = datetime.strptime(day, "%Y-%m-%d")
        return dt.weekday() < 5

    def is_trading_session(self, value: Optional[object] = None) -> bool:
        dt = self._normalize_datetime(value)
        if not self.is_trade_day(dt):
            return False
        t = dt.time()
        return (
            MORNING_START <= t <= MORNING_END or
            AFTERNOON_START <= t <= AFTERNOON_END
        )

    def is_open_for_intraday_scan(self, value: Optional[object] = None) -> bool:
        dt = self._normalize_datetime(value)
        if not self.is_trade_day(dt):
            return False
        t = dt.time()
        return (
            MORNING_START <= t < MORNING_END or
            AFTERNOON_START <= t < AFTERNOON_END
        )

    @staticmethod
    def _normalize_datetime(value: Optional[object] = None) -> datetime:
        if value is None:
            return datetime.now()
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, time(0, 0))
        s = str(value).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return datetime.now()
