"""日线趋势快照与做 T 大盘双闸门。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import pandas as pd
from loguru import logger

from atrade.data import HistoryProvider

DEFAULT_MARKET_SYMBOL = "sh000300"
DEFAULT_TTL_SECONDS = 300
DAILY_BAR_COUNT = 80
MINIMUM_TREND_BARS = 65


@dataclass(frozen=True)
class TrendSnapshot:
    """一只股票或指数的日线趋势摘要。"""

    symbol: str
    price: float
    ma20: float
    ma60: float
    ma20_slope: float
    drop_pct_5d: float
    trend: str
    fetched_at: str
    data_available: bool = True
    error: str = ""


class MarketRegimeFilter:
    """拉取并短期缓存个股/指数日线趋势。"""

    def __init__(
        self,
        history: Optional[HistoryProvider] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须 > 0")
        self.history = history or HistoryProvider()
        self.ttl_seconds = int(ttl_seconds)
        self.clock = clock
        self._cache: dict[str, tuple[float, TrendSnapshot]] = {}
        self._lock = threading.RLock()

    def get_symbol_trend(self, symbol: str) -> TrendSnapshot:
        return self._get_daily_trend(str(symbol).zfill(6))

    def get_market_gate(self) -> TrendSnapshot:
        return self._get_daily_trend(DEFAULT_MARKET_SYMBOL)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _get_daily_trend(self, symbol: str) -> TrendSnapshot:
        now = self.clock()
        with self._lock:
            cached = self._cache.get(symbol)
            if cached and now - cached[0] < self.ttl_seconds:
                return cached[1]

        snapshot = self._fetch_daily_trend(symbol)
        with self._lock:
            self._cache[symbol] = (now, snapshot)
        return snapshot

    def _fetch_daily_trend(self, symbol: str) -> TrendSnapshot:
        try:
            frame = self.history.fetch(symbol, scale="1d", datalen=DAILY_BAR_COUNT)
            snapshot = _calculate_snapshot(symbol, frame)
            if not snapshot.data_available:
                logger.warning(f"日线趋势不可用 {symbol}: {snapshot.error}")
            return snapshot
        except Exception as error:
            logger.warning(f"日线趋势拉取失败 {symbol}: {error}")
            return _unavailable_snapshot(symbol, str(error))


def _calculate_snapshot(symbol: str, frame: pd.DataFrame) -> TrendSnapshot:
    if frame is None or "close" not in frame.columns:
        return _unavailable_snapshot(symbol, "缺少 close 字段")

    close = pd.to_numeric(frame["close"], errors="coerce").dropna().reset_index(drop=True)
    if len(close) < MINIMUM_TREND_BARS:
        return _unavailable_snapshot(symbol, f"日 K 不足 {MINIMUM_TREND_BARS} 根")

    previous_price = float(close.iloc[-6])
    if previous_price <= 0:
        return _unavailable_snapshot(symbol, "5 日前收盘价无效")

    price = float(close.iloc[-1])
    ma20 = float(close.iloc[-20:].mean())
    ma60 = float(close.iloc[-60:].mean())
    ma20_five_days_ago = float(close.iloc[-25:-5].mean())
    ma20_slope = ma20 - ma20_five_days_ago
    drop_pct_5d = (price / previous_price - 1.0) * 100.0

    if ma20 > ma60 and ma20_slope > 0:
        trend = "up"
    elif ma20 < ma60:
        trend = "down"
    else:
        trend = "sideways"

    return TrendSnapshot(
        symbol=symbol,
        price=price,
        ma20=ma20,
        ma60=ma60,
        ma20_slope=ma20_slope,
        drop_pct_5d=drop_pct_5d,
        trend=trend,
        fetched_at=datetime.now().isoformat(timespec="seconds"),
    )


def _unavailable_snapshot(symbol: str, error: str) -> TrendSnapshot:
    return TrendSnapshot(
        symbol=symbol,
        price=0.0,
        ma20=0.0,
        ma60=0.0,
        ma20_slope=0.0,
        drop_pct_5d=0.0,
        trend="unknown",
        fetched_at=datetime.now().isoformat(timespec="seconds"),
        data_available=False,
        error=error,
    )


def allows_signal(
    signal_type: str,
    symbol_trend: TrendSnapshot,
    market_gate: TrendSnapshot,
) -> tuple[bool, str]:
    """判断普通信号是否通过个股日线与大盘双闸门。"""
    normalized_type = str(signal_type).lower()
    if normalized_type in {"stop_loss", "take_profit"}:
        return True, "风险退出始终放行"

    if market_gate.data_available and market_gate.drop_pct_5d < -3.0:
        return False, f"大盘 5 日跌幅 {market_gate.drop_pct_5d:.2f}% 超过 3%"

    if normalized_type != "buy":
        return True, "非买入信号无需个股上升趋势"

    if not symbol_trend.data_available:
        return False, f"个股日线趋势不可用: {symbol_trend.error or '未知原因'}"
    if symbol_trend.trend != "up":
        return False, "个股日线未满足 MA20>MA60 且 MA20 向上"
    if market_gate.data_available and market_gate.ma20 < market_gate.ma60:
        return False, "大盘 MA20 低于 MA60"
    return True, "通过个股日线与大盘趋势过滤"
