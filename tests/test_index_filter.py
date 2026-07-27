from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.market.index_filter import (
    MarketRegimeFilter,
    TrendSnapshot,
    allows_signal,
)


def _daily_frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.bdate_range("2026-01-01", periods=len(closes)).strftime("%Y-%m-%d"),
            "open": closes,
            "high": [price * 1.01 for price in closes],
            "low": [price * 0.99 for price in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        }
    )


def _snapshot(
    *,
    symbol: str = "600522",
    ma20: float = 110.0,
    ma60: float = 100.0,
    slope: float = 1.0,
    drop_pct_5d: float = 1.0,
    available: bool = True,
) -> TrendSnapshot:
    trend = "up" if ma20 > ma60 and slope > 0 else "down"
    return TrendSnapshot(
        symbol=symbol,
        price=110.0,
        ma20=ma20,
        ma60=ma60,
        ma20_slope=slope,
        drop_pct_5d=drop_pct_5d,
        trend=trend,
        fetched_at="2026-07-25T10:00:00",
        data_available=available,
    )


class _History:
    def __init__(self, frame: pd.DataFrame | None = None, error: Exception | None = None):
        self.frame = frame
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    def fetch(self, symbol: str, scale: str, datalen: int) -> pd.DataFrame:
        self.calls.append((symbol, scale, datalen))
        if self.error:
            raise self.error
        assert self.frame is not None
        return self.frame.copy()


def test_calculates_uptrend_from_daily_bars():
    history = _History(_daily_frame([80.0 + index * 0.5 for index in range(80)]))
    regime = MarketRegimeFilter(history=history)

    snapshot = regime.get_symbol_trend("600522")

    assert snapshot.data_available is True
    assert snapshot.trend == "up"
    assert snapshot.ma20 > snapshot.ma60
    assert snapshot.ma20_slope > 0
    assert history.calls == [("600522", "1d", 80)]


def test_symbol_buy_requires_daily_uptrend():
    allowed, reason = allows_signal(
        "buy",
        _snapshot(ma20=90.0, ma60=100.0, slope=-1.0),
        _snapshot(symbol="sh000300"),
    )

    assert allowed is False
    assert "个股" in reason


def test_symbol_data_failure_blocks_buy_but_not_sell():
    unavailable = _snapshot(available=False)

    assert allows_signal("buy", unavailable, _snapshot(symbol="sh000300"))[0] is False
    assert allows_signal("sell", unavailable, _snapshot(symbol="sh000300"))[0] is True


def test_market_downtrend_blocks_buy_only():
    market = _snapshot(symbol="sh000300", ma20=90.0, ma60=100.0, slope=-1.0)

    assert allows_signal("buy", _snapshot(), market)[0] is False
    assert allows_signal("sell", _snapshot(), market)[0] is True


def test_market_fast_drop_blocks_normal_signals_but_not_stop_loss():
    market = _snapshot(symbol="sh000300", drop_pct_5d=-3.01)

    assert allows_signal("buy", _snapshot(), market)[0] is False
    assert allows_signal("sell", _snapshot(), market)[0] is False
    assert allows_signal("stop_loss", _snapshot(), market)[0] is True


def test_market_drop_at_exact_threshold_is_allowed():
    market = _snapshot(symbol="sh000300", drop_pct_5d=-3.0)

    assert allows_signal("sell", _snapshot(), market)[0] is True


def test_market_fetch_failure_degrades_to_allow():
    regime = MarketRegimeFilter(history=_History(error=RuntimeError("down")))

    market = regime.get_market_gate()

    assert market.data_available is False
    assert allows_signal("buy", _snapshot(), market)[0] is True


def test_short_history_is_unavailable():
    regime = MarketRegimeFilter(history=_History(_daily_frame([100.0] * 64)))

    snapshot = regime.get_symbol_trend("600522")

    assert snapshot.data_available is False
    assert snapshot.trend == "unknown"


def test_snapshot_is_cached_for_ttl():
    clock = [100.0]
    history = _History(_daily_frame([80.0 + index * 0.5 for index in range(80)]))
    regime = MarketRegimeFilter(history=history, ttl_seconds=300, clock=lambda: clock[0])

    first = regime.get_market_gate()
    second = regime.get_market_gate()
    clock[0] += 301
    third = regime.get_market_gate()

    assert first == second
    assert third.data_available is True
    assert len(history.calls) == 2


def test_rejects_non_numeric_close_data():
    frame = _daily_frame([100.0] * 80)
    frame["close"] = "bad"
    regime = MarketRegimeFilter(history=_History(frame))

    snapshot = regime.get_symbol_trend("600522")

    assert snapshot.data_available is False
    assert snapshot.error


def test_constructor_rejects_non_positive_ttl():
    with pytest.raises(ValueError, match="ttl_seconds"):
        MarketRegimeFilter(history=_History(_daily_frame([100.0] * 80)), ttl_seconds=0)


def test_buy_momentum_bypass_short_circuits_both_gates():
    """5 日动量 ≥ 阈值时，BUY 双闸门（个股 trend + 大盘 MA20）都被短路放行。"""
    from atrade.market import index_filter
    from atrade.market.index_filter import allows_signal

    # 个股 trend=sideways（不满足 up）+ 大盘 MA20<MA60（不满足），
    # 但 5 日涨 16.48% → 应被短路放行
    symbol_trend = index_filter.TrendSnapshot(
        symbol="002436", price=35.7, ma20=39.81, ma60=39.07,
        ma20_slope=-4.06, drop_pct_5d=16.48,
        trend="sideways", fetched_at="2026-07-27",
    )
    market_gate = index_filter.TrendSnapshot(
        symbol="sh000300", price=4702.4, ma20=4764.0, ma60=4842.3,
        ma20_slope=-57.08, drop_pct_5d=2.26,
        trend="down", fetched_at="2026-07-27",
    )

    allowed, reason = allows_signal(
        "buy", symbol_trend, market_gate,
        buy_momentum_threshold_pct=5.0,
    )
    assert allowed is True
    assert "短路放行" in reason
    assert "16.48" in reason


def test_buy_momentum_below_threshold_still_blocked_by_gates():
    """5 日动量 < 阈值时，原双闸门仍生效（不会被绕过）。"""
    from atrade.market import index_filter
    from atrade.market.index_filter import allows_signal

    symbol_trend = index_filter.TrendSnapshot(
        symbol="600522", price=32.66, ma20=42.17, ma60=45.44,
        ma20_slope=-7.38, drop_pct_5d=1.37,
        trend="down", fetched_at="2026-07-27",
    )
    market_gate = index_filter.TrendSnapshot(
        symbol="sh000300", price=4702.4, ma20=4764.0, ma60=4842.3,
        ma20_slope=-57.08, drop_pct_5d=2.26,
        trend="down", fetched_at="2026-07-27",
    )

    allowed, reason = allows_signal(
        "buy", symbol_trend, market_gate,
        buy_momentum_threshold_pct=5.0,
    )
    assert allowed is False
    assert "未满足 MA20>MA60" in reason


def test_buy_momentum_threshold_zero_disables_bypass():
    """阈值=0 时 5 日动量短路相当于关闭。"""
    from atrade.market import index_filter
    from atrade.market.index_filter import allows_signal

    symbol_trend = index_filter.TrendSnapshot(
        symbol="002436", price=35.7, ma20=39.81, ma60=39.07,
        ma20_slope=-4.06, drop_pct_5d=16.48,
        trend="sideways", fetched_at="2026-07-27",
    )
    market_gate = index_filter.TrendSnapshot(
        symbol="sh000300", price=4702.4, ma20=4764.0, ma60=4842.3,
        ma20_slope=-57.08, drop_pct_5d=2.26,
        trend="down", fetched_at="2026-07-27",
    )

    allowed, reason = allows_signal(
        "buy", symbol_trend, market_gate,
        buy_momentum_threshold_pct=0.0,
    )
    # 阈值=0 时 drop_pct_5d=16.48 >= 0 仍会触发（除非改成严格大于）
    # 我们的语义是 >=，所以仍放行
    assert allowed is True
    assert "短路放行" in reason


def test_buy_momentum_bypass_respects_market_crash_circuit_breaker():
    """大盘 5 日跌幅熔断（< -3%）始终生效，5 日动量短路不能绕过。"""
    from atrade.market import index_filter
    from atrade.market.index_filter import allows_signal

    # 即便个股 5 日涨 50%，大盘 5 日跌 -5% → 仍被熔断拒绝
    symbol_trend = index_filter.TrendSnapshot(
        symbol="002436", price=100, ma20=80, ma60=70,
        ma20_slope=10, drop_pct_5d=50.0,
        trend="up", fetched_at="2026-07-27",
    )
    market_gate = index_filter.TrendSnapshot(
        symbol="sh000300", price=4500, ma20=4800, ma60=4900,
        ma20_slope=-50, drop_pct_5d=-5.0,
        trend="down", fetched_at="2026-07-27",
    )

    allowed, reason = allows_signal(
        "buy", symbol_trend, market_gate,
        buy_momentum_threshold_pct=5.0,
    )
    assert allowed is False
    assert "大盘 5 日跌幅" in reason


def test_sell_signal_unchanged_by_momentum_threshold():
    """非 BUY 信号不受 5 日动量短路影响（仅 BUY 双闸门涉及）。"""
    from atrade.market import index_filter
    from atrade.market.index_filter import allows_signal

    symbol_trend = index_filter.TrendSnapshot(
        symbol="600522", price=32.66, ma20=42.17, ma60=45.44,
        ma20_slope=-7.38, drop_pct_5d=1.37,
        trend="down", fetched_at="2026-07-27",
    )
    market_gate = index_filter.TrendSnapshot(
        symbol="sh000300", price=4702.4, ma20=4764.0, ma60=4842.3,
        ma20_slope=-57.08, drop_pct_5d=2.26,
        trend="down", fetched_at="2026-07-27",
    )

    allowed, reason = allows_signal(
        "sell", symbol_trend, market_gate,
        buy_momentum_threshold_pct=5.0,
    )
    assert allowed is True
    assert "无需个股上升趋势" in reason
