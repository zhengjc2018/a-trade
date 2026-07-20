"""回归测试：现金与 t_avg_cost 不应被双重计算。"""
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.backtest.t0_simulator import T0Simulator


def make_linear_df(closes):
    n = len(closes)
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": dates, "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes, "volume": [1_000_000] * n,
    })


def _stub(d):
    return d.assign(MA5=d["close"], MA10=d["close"], MA20=d["close"],
                    VOL_MA5=d["volume"], RSI6=50.0, RSI12=50.0,
                    BOLL_LOWER=d["close"] * 0.98, BOLL_UPPER=d["close"] * 1.02,
                    MACD_HIST=0.0, KDJ_K=50.0, KDJ_D=50.0, KDJ_J=50.0)


def test_same_price_buy_sell_no_profit():
    """同价买卖时 T 净额应仅损失手续费，不产生虚增利润。"""
    closes = [10.0 + i * 0.1 for i in range(60)]
    df = make_linear_df(closes)
    sim = T0Simulator(scale="1d", slippage_pct=0.0, t_position_pct=0.5)
    from atrade.signals import Signal, SignalStrength, SignalType
    fake = Signal(symbol="T", signal_type=SignalType.BUY, strength=SignalStrength.MEDIUM,
                  name="t", reason="t", trigger_price=closes[-1])
    with patch.object(sim.history, "fetch_with_cache", return_value=df), \
         patch("atrade.indicators.indicators.add_all_indicators", side_effect=_stub), \
         patch.object(sim.engine, "scan", return_value=[fake]):
        r = sim.run("T", 10.0, 100, start_date="20250101", end_date="20250301")
    # 同价买卖 → 每笔盈亏 ≈ -fee，net_t 应只是负的费用总和
    assert r.net_t_profit < 0
    # 不应有正向虚增
    assert r.net_t_profit > -r.fee_total * 2  # 不超过 2 倍费用（合理余量）
    # 期末持股 = 初始
    assert r.final_total_quantity == 100


def test_per_trade_profit_within_one_fee_of_zero_on_same_price():
    """同价买卖时每笔 trade.profit 应等于 -fee（无虚假 T 利润）。"""
    closes = [10.0 + i * 0.1 for i in range(60)]
    df = make_linear_df(closes)
    sim = T0Simulator(scale="1d", slippage_pct=0.0, t_position_pct=0.5)
    from atrade.signals import Signal, SignalStrength, SignalType
    fake = Signal(symbol="T", signal_type=SignalType.BUY, strength=SignalStrength.MEDIUM,
                  name="t", reason="t", trigger_price=closes[-1])
    with patch.object(sim.history, "fetch_with_cache", return_value=df), \
         patch("atrade.indicators.indicators.add_all_indicators", side_effect=_stub), \
         patch.object(sim.engine, "scan", return_value=[fake]):
        r = sim.run("T", 10.0, 100, start_date="20250101", end_date="20250301")
    # 每笔 sell 的盈亏 ≈ -fee（同价买卖），不应有大的正/负偏离
    for t in r.trades:
        if t.direction == "sell":
            assert abs(t.profit + t.fee) < 1e-3, (
                f"same-price sell profit {t.profit} != -fee {t.fee}（t_avg_cost 污染？）"
            )


def test_cash_not_double_counted():
    """现金只应由 _do_buy/_do_sell 更新，不在主循环重复加。"""
    closes = [10.0 + i * 0.1 for i in range(60)]
    df = make_linear_df(closes)
    sim = T0Simulator(scale="1d", slippage_pct=0.0, t_position_pct=0.5)
    from atrade.signals import Signal, SignalStrength, SignalType
    fake = Signal(symbol="T", signal_type=SignalType.BUY, strength=SignalStrength.MEDIUM,
                  name="t", reason="t", trigger_price=closes[-1])
    with patch.object(sim.history, "fetch_with_cache", return_value=df), \
         patch("atrade.indicators.indicators.add_all_indicators", side_effect=_stub), \
         patch.object(sim.engine, "scan", return_value=[fake]):
        r = sim.run("T", 10.0, 100, start_date="20250101", end_date="20250301")
    # 总 t 现金流 = -sum(buy amount + buy fee) + sum(sell amount - sell fee)
    expected_cash = 0.0
    for t in r.trades:
        if t.direction == "buy":
            expected_cash -= (t.amount + t.fee)
        else:
            expected_cash += (t.amount - t.fee)
    assert abs(r.total_t_profit - expected_cash) < 1e-3, (
        f"cash {r.total_t_profit} != expected {expected_cash} (double counted?)"
    )
