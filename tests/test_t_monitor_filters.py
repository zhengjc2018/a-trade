from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.market.index_filter import TrendSnapshot
from atrade.monitor.t_monitor import TMonitorRunner
from atrade.monitor.t_state import TStateStore
from atrade.signals import Signal, SignalStrength, SignalType


def _intraday_frame(price: float = 100.0) -> pd.DataFrame:
    closes = [price] * 60
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-07-25 09:35", periods=60, freq="5min").strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "open": closes,
            "high": [value * 1.01 for value in closes],
            "low": [value * 0.99 for value in closes],
            "close": closes,
            "volume": [1_000_000] * 60,
        }
    )


def _trend(
    symbol: str,
    *,
    ma20: float = 110.0,
    ma60: float = 100.0,
    drop_pct_5d: float = 1.0,
) -> TrendSnapshot:
    return TrendSnapshot(
        symbol=symbol,
        price=110.0,
        ma20=ma20,
        ma60=ma60,
        ma20_slope=1.0 if ma20 > ma60 else -1.0,
        drop_pct_5d=drop_pct_5d,
        trend="up" if ma20 > ma60 else "down",
        fetched_at="2026-07-25T10:00:00",
    )


class _History:
    def __init__(self, price: float = 100.0):
        self.price = price

    def fetch_with_cache(self, *args, **kwargs):
        return _intraday_frame(self.price)


class _Engine:
    def __init__(self, signals):
        self.signals = signals
        self.calls = 0

    def scan(self, symbol, frame):
        self.calls += 1
        return self.signals


class _Regime:
    def __init__(self, symbol_trend=None, market=None):
        self.symbol_trend = symbol_trend or _trend("600522")
        self.market = market or _trend("sh000300")
        self.market_calls = 0

    def get_market_gate(self):
        self.market_calls += 1
        return self.market

    def get_symbol_trend(self, symbol):
        return self.symbol_trend


def _signal(signal_type: SignalType) -> Signal:
    return Signal(
        symbol="600522",
        signal_type=signal_type,
        strength=SignalStrength.STRONG,
        name=f"{signal_type.value} test",
        reason="test reason",
        trigger_price=100.0,
        factor_hits=["趋势确认"],
    )


def _runner(tmp_path, engine, regime, price=100.0, confirm_bars=2):
    store = TStateStore(
        tmp_path / "t_state.json",
        now=lambda: datetime(2026, 7, 25, 10, 0),
    )
    runner = TMonitorRunner(
        config={
            "enabled": True,
            "scale": "5m",
            "datalen": 60,
            "confirm_bars": confirm_bars,
            "trailing_defaults": {"take_profit_pct": 0.03, "stop_loss_pct": 0.02},
            "symbols": [
                {
                    "symbol": "600522",
                    "name": "中天科技",
                    "cost_price": 62.0,
                    "quantity": 200,
                }
            ],
        },
        history=_History(price),
        engine=engine,
        regime_filter=regime,
        t_state_store=store,
    )
    return runner, store


def test_downtrend_buy_is_filtered(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    engine = _Engine([_signal(SignalType.BUY)])
    regime = _Regime(symbol_trend=_trend("600522", ma20=90, ma60=100))
    runner, _ = _runner(tmp_path, engine, regime)

    assert runner._scan_candidates() == []
    assert runner.filtered_count == 1


def test_market_fast_drop_filters_sell_but_preserves_stop_loss(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    engine = _Engine([_signal(SignalType.SELL), _signal(SignalType.STOP_LOSS)])
    regime = _Regime(market=_trend("sh000300", drop_pct_5d=-3.1))
    runner, _ = _runner(tmp_path, engine, regime)

    candidates = runner._scan_candidates()

    assert [item["signal_type"] for item in candidates] == ["stop_loss"]


def test_trailing_stop_has_priority_over_engine_signals(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    engine = _Engine([_signal(SignalType.BUY)])
    runner, store = _runner(tmp_path, engine, _Regime(), price=98.0)
    store.mark_buy("600522", 100.0, 1.0, "趋势确认", "2026-07-25T10:00:00")

    candidates = runner._scan_candidates()

    assert len(candidates) == 1
    assert candidates[0]["signal_type"] == "stop_loss"
    assert candidates[0]["__risk_action__"] == "stop_loss"
    assert candidates[0]["__execution_lots__"] == 1.0
    assert engine.calls == 0


def test_take_profit_bypasses_two_stage_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    engine = _Engine([])
    runner, store = _runner(tmp_path, engine, _Regime(), price=103.0, confirm_bars=2)
    store.mark_buy("600522", 100.0, 1.0, "趋势确认", "2026-07-25T10:00:00")

    alerts = runner.run_once()

    assert len(alerts) == 1
    assert alerts[0]["signal_type"] == "sell"
    assert alerts[0]["__risk_action__"] == "take_profit"
    assert alerts[0]["__signal_key__"].startswith("600522:take_profit:2026-07-25")


def test_peak_updates_without_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    runner, store = _runner(tmp_path, _Engine([]), _Regime(), price=102.0)
    store.mark_buy("600522", 100.0, 1.0, "趋势确认", "2026-07-25T10:00:00")

    assert runner._scan_candidates() == []
    assert store.get("600522").peak_price == 102.0


def test_factor_hits_survive_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    runner, _ = _runner(
        tmp_path,
        _Engine([_signal(SignalType.BUY)]),
        _Regime(),
        confirm_bars=2,
    )

    assert runner.run_once() == []
    alerts = runner.run_once()

    assert alerts[0]["factor_hits"] == ["趋势确认"]


def test_market_gate_fetched_once_for_multiple_symbols(tmp_path, monkeypatch):
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    regime = _Regime()
    runner, _ = _runner(tmp_path, _Engine([]), regime)
    runner.config.symbols.append(runner.config.symbols[0])

    runner._scan_candidates()

    assert regime.market_calls == 1


def test_sell_filtered_when_holdings_below_one_lot(tmp_path, monkeypatch):
    """持仓 < 1 手时 SELL / STOP_LOSS 候选应在推送前被过滤。"""
    import json

    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")

    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [
            {"symbol": "600522", "name": "中天科技", "cost_price": 62.0,
             "quantity": 50, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    engine = _Engine([_signal(SignalType.SELL)])
    runner, _ = _runner(tmp_path, engine, _Regime())

    candidates = [
        {
            "symbol": "600522", "name": "中天科技",
            "signal_type": "sell", "signal_name": "放量拉升",
            "reason": "x", "trigger_price": 100.0, "strength": "strong",
        }
    ]
    kept, dropped = runner._filter_candidates_by_holdings(candidates)
    assert kept == []
    assert dropped[0]["_drop_reason"].startswith("持仓 50 股 < 100 股")


def test_sell_filtered_when_already_traded_today(tmp_path, monkeypatch):
    """同一只股票当日已执行过 SELL 时，新候选应在推送前被过滤。"""
    import json

    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")

    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [
            {"symbol": "600522", "name": "中天科技", "cost_price": 62.0,
             "quantity": 200, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    # 锁定 _today 为 2026-07-25（与 _runner 使用的 store.now 一致）
    monkeypatch.setattr(t_executor, "_today", lambda: "2026-07-25")
    t_executor.save_trade({
        "timestamp": "2026-07-25T10:00:00", "symbol": "600522",
        "name": "中天科技", "direction": "SELL", "shares": 100,
        "lots": 1.0, "price": 63.5, "signal_name": "放量拉升",
        "reason": "test", "holding_qty_after": 100,
        "risk_action": "", "factor_hits": [],
    })

    engine = _Engine([_signal(SignalType.SELL)])
    runner, _ = _runner(tmp_path, engine, _Regime())

    candidates = [
        {
            "symbol": "600522", "name": "中天科技",
            "signal_type": "sell", "signal_name": "放量拉升",
            "reason": "x", "trigger_price": 100.0, "strength": "strong",
        }
    ]
    kept, dropped = runner._filter_candidates_by_holdings(candidates)
    assert kept == []
    assert "今日已执行过" in dropped[0]["_drop_reason"]


def test_buy_passes_holdings_filter(tmp_path, monkeypatch):
    """BUY 信号不受持仓过滤影响。"""
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    runner, _ = _runner(tmp_path, _Engine([]), _Regime())
    candidates = [
        {"symbol": "600522", "signal_type": "buy", "signal_name": "x",
         "reason": "x", "trigger_price": 100.0, "strength": "strong"},
    ]
    kept, dropped = runner._filter_candidates_by_holdings(candidates)
    assert len(kept) == 1
    assert dropped == []


def test_run_once_drops_repeated_sells_after_first_executed(tmp_path, monkeypatch):
    """run_once 第一次卖出 + 执行后，第二次扫描应被 holdings 过滤掉。"""
    import json

    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", tmp_path / "sent.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [
            {"symbol": "600522", "name": "中天科技", "cost_price": 62.0,
             "quantity": 200, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    from atrade.monitor import t_executor
    trades_file = tmp_path / "t_trades.json"
    monkeypatch.setattr(t_executor, "_TRADES_FILE", trades_file)

    # 用 take_profit 风险候选（bypass_confirm=True），单次扫描即可推送
    runner, store = _runner(tmp_path, _Engine([]), _Regime(), price=103.0, confirm_bars=1)
    store.mark_buy("600522", 100.0, 1.0, "趋势确认", "2026-07-25T10:00:00")

    # 第一次扫描 + 推送：take_profit 风险候选
    alerts_1 = runner.run_once()
    assert len(alerts_1) == 1
    assert alerts_1[0]["signal_type"] == "sell"
    runner.commit_sent(alerts_1)
    for a in alerts_1:
        ex = t_executor.TTradeExecutor({"auto_execute": True, "lots_per_trade": 1.0})
        trade = ex.execute(a)
        assert trade and not trade.get("skipped_reason")
    # 第一次执行后持仓从 200 → 100
    assert json.loads(holdings_path.read_text())["holdings"][0]["quantity"] == 100

    # 第二次扫描：trigger_price 不变 → take_profit 风险候选仍会触发
    # 但因为今天已经写过 SELL trade → _already_traded_today 命中 → 被过滤
    alerts_2 = runner.run_once()
    assert alerts_2 == []
    assert runner.holdings_skipped_count >= 1
