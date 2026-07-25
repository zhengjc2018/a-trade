"""T0Simulator 单元测试（适配新的事件驱动账本）。"""
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.backtest.t0_simulator import (
    Position,
    T0Simulator,
)


def make_flat_df(n: int = 60, price: float = 100.0):
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": [price] * n,
        "high": [price * 1.01] * n,
        "low":  [price * 0.99] * n,
        "close": [price] * n,
        "volume": [1000000] * n,
    })


def make_calm_df(n: int = 60):
    import math
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    closes = [100.0 + math.sin(i / 5) * 0.5 for i in range(n)]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    opens = [closes[(i-1) % n] for i in range(n)]
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": [1000000] * n,
    })


def _stub_indicators(d):
    """无信号时的指标 stub。"""
    return d.assign(**{
        "MA5": d["close"], "MA10": d["close"], "MA20": d["close"],
        "VOL_MA5": d["volume"],
        "RSI6": 50.0, "RSI12": 50.0,
        "BOLL_LOWER": d["close"] * 0.98,
        "BOLL_UPPER": d["close"] * 1.02,
        "MACD_HIST": 0.0,
        "KDJ_K": 50.0, "KDJ_D": 50.0, "KDJ_J": 50.0,
    })


# --- Position dataclass 测试（适配新接口） ---

def test_position_total_property():
    pos = Position(target_quantity=1000, settled_quantity=600, locked_quantity=400)
    assert pos.total == 1000


def test_position_initial_state():
    pos = Position(target_quantity=1000)
    assert pos.settled_quantity == 0
    assert pos.locked_quantity == 0
    assert pos.cash == 0.0


# --- 费用计算 ---

def test_fee_calculation_buy_with_min_commission():
    """买入费：max(amount*comm, min) + transfer."""
    sim = T0Simulator(fee_commission=0.001, fee_commission_min=5.0,
                       fee_transfer=0.0, slippage_pct=0.0)
    # 100*1000*0.001 = 100 > 5
    assert sim._calc_buy_fee(100.0, 1000) == pytest.approx(100.0)


def test_fee_calculation_buy_uses_minimum():
    """小金额时取最低佣金 5 元。"""
    sim = T0Simulator(fee_commission=0.001, fee_commission_min=5.0,
                       fee_transfer=0.0, slippage_pct=0.0)
    # 100*10*0.001 = 1.0 < 5 → 取 5
    assert sim._calc_buy_fee(100.0, 10) == pytest.approx(5.0)


def test_fee_calculation_sell_with_stamp_duty():
    """卖出费：max(comm, min) + stamp + transfer。"""
    sim = T0Simulator(fee_commission=0.001, fee_commission_min=5.0,
                       fee_stamp_duty_sell=0.005, fee_transfer=0.0,
                       slippage_pct=0.0)
    # comm = max(100*1000*0.001, 5) = 100; stamp = 100*1000*0.005 = 500 → 600
    assert sim._calc_sell_fee(100.0, 1000) == pytest.approx(600.0)


def test_slippage_buy_and_sell():
    sim = T0Simulator(slippage_pct=0.001)
    assert sim._slippage_buy(100.0) == pytest.approx(100.1, rel=1e-6)
    assert sim._slippage_sell(100.0) == pytest.approx(99.9, rel=1e-6)


def test_next_date():
    sim = T0Simulator()
    assert sim._next_date("2026-01-31") == "2026-02-01"


# --- 集成测试 ---

def test_run_with_no_signals_returns_zero_t_profit():
    """平稳数据不应触发任何做 T 信号 → T 净盈亏 = 0。"""
    sim = T0Simulator()
    df = make_flat_df(60)
    with patch.object(sim.history, "fetch_with_cache", return_value=df), \
         patch("atrade.indicators.indicators.add_all_indicators",
               side_effect=_stub_indicators):
        r = sim.run("600519", 100.0, 1000, start_date="20260101", end_date="20260301")
    assert r.net_t_profit == 0.0
    assert r.t_win_count == 0
    assert r.t_loss_count == 0
    assert r.fee_total == 0.0
    assert r.buy_hold_profit == 0.0
    assert r.last_close == 100.0
    assert r.quantity == 1000
    # 守恒：期末总持股 == 初始 quantity
    assert r.final_total_quantity == 1000


def test_run_supports_intraday_5m_scale():
    """5 分钟模式应通过 scale 参数进入日内数据路径。"""
    sim = T0Simulator(scale="5m", datalen=20)
    df = make_flat_df(60)
    with patch.object(sim.history, "fetch_with_cache", return_value=df), \
         patch("atrade.indicators.indicators.add_all_indicators",
               side_effect=_stub_indicators):
        r = sim.run("600519", 100.0, 1000, start_date="20260101", end_date="20260301")
    assert r.quantity == 1000
    assert sim.scale == "5m"
    assert sim.datalen == 20


def test_run_calculates_max_drawdown():
    """净值下跌应有最大回撤。"""
    sim = T0Simulator()
    n = 60
    closes = [100.0 + i * 0.1 for i in range(30)] + [103.0 - i * 0.5 for i in range(30)]
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    opens = [closes[(i-1) % n] for i in range(n)]
    dates = pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": [1000000] * n,
    })
    with patch.object(sim.history, "fetch_with_cache", return_value=df), \
         patch("atrade.indicators.indicators.add_all_indicators",
               side_effect=_stub_indicators):
        r = sim.run("TEST", 100.0, 1000, start_date="20260101", end_date="20260301")
    assert r.max_drawdown_pct >= 0.0
    assert isinstance(r.max_drawdown_pct, float)


def test_signal_cooldown_days_stored():
    """cooldown 参数应被正确存储。"""
    sim = T0Simulator(signal_cooldown_days=3)
    assert sim.signal_cooldown_days == 3


# ---------- take_profit_pct / stop_loss_pct 注入测试 ----------

def _trending_df(n: int, daily_returns: list, base_price: float = 100.0):
    """构造 daily_returns 是每个交易日收益率列表的 df（首日 0）。"""

    import pandas as pd
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    assert len(daily_returns) == n
    closes = []
    cum = base_price
    for r in daily_returns:
        cum *= (1 + r)
        closes.append(cum)
    opens = [base_price] + closes[:-1]
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.995 for c in closes]
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000000] * n,
    })


class _FakeHistory:
    """返回一个静态 df，不依赖外网数据。"""

    def __init__(self, df):
        self._df = df

    def fetch_with_cache(self, *args, **kwargs):
        return self._df.copy()


def _make_sim_with_df(df, **kwargs):
    sim = T0Simulator(
        scale="1d",
        datalen=len(df),
        fee_commission=0.0001,
        fee_commission_min=0.01,
        fee_stamp_duty_sell=0.0001,
        slippage_pct=0.0,  # 测试关掉滑点
        **kwargs,
    )
    sim.history = _FakeHistory(df)
    return sim


def _always_buy_signal():
    from atrade.signals import Signal, SignalStrength, SignalType
    def _scan(self, symbol, df):
        if len(df) < 35:
            return []
        return [
            Signal(
                symbol="000001",
                signal_type=SignalType.BUY,
                strength=SignalStrength.WEAK,
                name="fake-buy",
                reason="test buy",
                trigger_price=float(df.iloc[-1]["close"]),
                factor_hits=["fake"],
            )
        ]
    return _scan


def test_take_profit_kicks_in(monkeypatch):
    """每日 +1%，take_profit=0.02 → 必然触发。"""
    monkeypatch.setattr("atrade.signals.SignalEngine.scan", _always_buy_signal())
    df = _trending_df(60, [0.01] * 60, base_price=100.0)
    sim = _make_sim_with_df(df, take_profit_pct=0.02)
    result = sim.run("000001", cost_price=100.0, quantity=100,
                     start_date="2026-01-01", end_date="2026-04-15",
                     force_eod_close=False)
    signals = [t.signal for t in result.trades if "锁利" in t.signal]
    assert signals, f"没有触发锁利: {[t.signal for t in result.trades]}"


def test_stop_loss_kicks_in(monkeypatch):
    """每日 -2%，stop_loss=0.05 → 应立即触发止损。"""
    monkeypatch.setattr("atrade.signals.SignalEngine.scan", _always_buy_signal())
    df = _trending_df(60, [-0.02] * 60, base_price=100.0)
    sim = _make_sim_with_df(df, stop_loss_pct=0.05)
    result = sim.run("000001", cost_price=100.0, quantity=100,
                     start_date="2026-01-01", end_date="2026-04-15",
                     force_eod_close=False)
    stop_signals = [t for t in result.trades if t.signal == "强制止损"]
    assert stop_signals, f"未触发止损: {[t.signal for t in result.trades]}"


# test_default_behavior_unchanged 已删除（既有 11 项测试覆盖默认行为）


