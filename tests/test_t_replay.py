from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.monitor.t_replay import RoundTrip, compute_round_trips, compute_stats


def _trade(
    direction: str,
    price: float,
    time: str,
    *,
    date: str = "2026-07-25",
    symbol: str = "600522",
    name: str = "中天科技",
    shares: int = 100,
    skipped_reason: str = "",
    factor_hits=None,
    signal_name: str = "趋势确认",
    risk_action: str = "",
) -> dict:
    return {
        "timestamp": f"{date}T{time}:00",
        "symbol": symbol,
        "name": name,
        "direction": direction,
        "shares": shares,
        "lots": shares / 100,
        "price": price,
        "signal_name": signal_name,
        "reason": "test",
        "holding_qty_after": 200,
        "skipped_reason": skipped_reason,
        "factor_hits": factor_hits or [],
        "risk_action": risk_action,
    }


def _trip(pnl: float, symbol: str = "600522", factor: str = "趋势确认") -> RoundTrip:
    entry_price = 100.0
    shares = 100
    exit_price = entry_price + pnl / shares
    return RoundTrip(
        symbol=symbol,
        name="中天科技",
        entry_price=entry_price,
        exit_price=exit_price,
        shares=shares,
        pnl=pnl,
        pnl_pct=(exit_price / entry_price) - 1,
        entry_time="2026-07-25T10:00:00",
        exit_time="2026-07-25T14:00:00",
        entry_factor=factor,
        exit_factor="T仓锁利",
        holding_minutes=240,
    )


def test_pairs_buy_then_sell_same_symbol_same_day():
    trips = compute_round_trips(
        [_trade("BUY", 100, "10:00"), _trade("SELL", 103, "14:00")],
        "2026-07-25",
    )

    assert len(trips) == 1
    assert trips[0].pnl == 300.0
    assert trips[0].pnl_pct == pytest.approx(0.03)
    assert trips[0].holding_minutes == 240


def test_ignores_cross_day_and_skipped_trades():
    trades = [
        _trade("BUY", 100, "10:00", date="2026-07-24"),
        _trade("SELL", 103, "14:00"),
        _trade("BUY", 100, "10:30", skipped_reason="今日已执行"),
    ]

    assert compute_round_trips(trades, "2026-07-25") == []


def test_ignores_zero_share_and_sell_before_buy():
    trades = [
        _trade("SELL", 103, "09:45"),
        _trade("BUY", 100, "10:00", shares=0),
    ]

    assert compute_round_trips(trades, "2026-07-25") == []


def test_partial_sell_creates_partial_round_trip():
    trips = compute_round_trips(
        [
            _trade("BUY", 100, "10:00", shares=100),
            _trade("SELL", 103, "14:00", shares=50),
        ],
        "2026-07-25",
    )

    assert len(trips) == 1
    assert trips[0].shares == 50
    assert trips[0].pnl == 150.0


def test_fifo_pairing_across_multiple_buys():
    trips = compute_round_trips(
        [
            _trade("BUY", 100, "10:00", shares=100),
            _trade("BUY", 101, "10:30", shares=100),
            _trade("SELL", 103, "14:00", shares=150),
        ],
        "2026-07-25",
    )

    assert [trip.shares for trip in trips] == [100, 50]
    assert [trip.entry_price for trip in trips] == [100.0, 101.0]


def test_factor_uses_hits_then_falls_back_to_signal_name():
    trips = compute_round_trips(
        [
            _trade("BUY", 100, "10:00", factor_hits=["趋势确认", "超卖反弹"]),
            _trade(
                "STOP_LOSS",
                98,
                "14:00",
                signal_name="T仓止损",
                risk_action="stop_loss",
            ),
        ],
        "2026-07-25",
    )

    assert trips[0].entry_factor == "趋势确认+超卖反弹"
    assert trips[0].exit_factor == "stop_loss"


def test_invalid_timestamp_is_ignored():
    invalid = _trade("BUY", 100, "10:00")
    invalid["timestamp"] = "bad"

    assert compute_round_trips([invalid], "2026-07-25") == []


def test_stats_include_win_rate_profit_factor_symbol_and_factor_groups():
    stats = compute_stats([
        _trip(300.0),
        _trip(-100.0),
        _trip(0.0, symbol="002436", factor="超卖反弹"),
    ])

    assert stats["count"] == 3
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert stats["breakevens"] == 1
    assert stats["win_rate"] == pytest.approx(1 / 3)
    assert stats["total_pnl"] == 200.0
    assert stats["profit_factor"] == 3.0
    assert stats["by_symbol"]["600522"]["count"] == 2
    assert stats["by_factor"]["趋势确认"]["win_rate"] == 0.5


def test_stats_without_losses_has_unbounded_profit_factor():
    stats = compute_stats([_trip(300.0)])

    assert stats["profit_factor"] is None


def test_empty_stats_are_zeroed():
    stats = compute_stats([])

    assert stats["count"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["total_pnl"] == 0.0
    assert stats["by_symbol"] == {}


def test_compute_execution_stats_aggregates_per_symbol():
    """按个股聚合触发/执行/跳过/当前持仓。"""
    from atrade.monitor.t_replay import compute_execution_stats

    trades = [
        # 600522: 1 执行 + 2 跳过 + 1 STOP_LOSS 执行
        _trade("SELL", 63.5, "10:00", date="2026-07-27", symbol="600522",
               name="中天科技", shares=100),
        _trade("SELL", 63.6, "10:30", date="2026-07-27", symbol="600522",
               shares=0, skipped_reason="今日已执行过 SELL"),
        _trade("SELL", 63.7, "11:00", date="2026-07-27", symbol="600522",
               shares=0, skipped_reason="今日已执行过 SELL"),
        _trade("STOP_LOSS", 60.0, "14:00", date="2026-07-27", symbol="600522",
               shares=100),
        # 002436: 1 BUY（仅记账）+ 1 SELL
        _trade("BUY", 41.0, "11:30", date="2026-07-27", symbol="002436",
               name="兴森科技", shares=100),
        _trade("SELL", 41.5, "13:00", date="2026-07-27", symbol="002436",
               shares=100),
    ]

    stats = compute_execution_stats(trades, "2026-07-27")

    assert stats["total_trades"] == 6
    assert stats["total_executed"] == 4
    assert stats["total_skipped"] == 2

    # 600522
    sym_a = stats["by_symbol"]["600522"]
    assert sym_a["name"] == "中天科技"
    assert sym_a["trades_count"] == 4
    assert sym_a["executed_count"] == 2
    assert sym_a["skipped_count"] == 2
    assert sym_a["directions"]["SELL"] == 3
    assert sym_a["directions"]["STOP_LOSS"] == 1

    # 002436
    sym_b = stats["by_symbol"]["002436"]
    assert sym_b["name"] == "兴森科技"
    assert sym_b["trades_count"] == 2
    assert sym_b["executed_count"] == 2
    assert sym_b["skipped_count"] == 0
    assert sym_b["directions"]["BUY"] == 1
    assert sym_b["directions"]["SELL"] == 1


def test_compute_execution_stats_filters_other_dates():
    """非当日 trade 应被过滤。"""
    from atrade.monitor.t_replay import compute_execution_stats

    trades = [
        _trade("SELL", 63.0, "10:00", date="2026-07-25"),
        _trade("SELL", 63.5, "10:00", date="2026-07-27"),
    ]
    stats = compute_execution_stats(trades, "2026-07-27")
    assert stats["total_trades"] == 1
    assert "600522" in stats["by_symbol"]


def test_compute_execution_stats_empty_for_no_trades():
    """无 trade 时返回空聚合。"""
    from atrade.monitor.t_replay import compute_execution_stats

    stats = compute_execution_stats([], "2026-07-27")
    assert stats["total_trades"] == 0
    assert stats["total_executed"] == 0
    assert stats["total_skipped"] == 0
    assert stats["by_symbol"] == {}
