from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.monitor.t_state import TState
from atrade.monitor.t_trailing import TrailingConfig, check_trailing


def _holding(
    entry_price: float = 100.0,
    peak_price: float = 100.0,
    lots: float = 1.0,
) -> TState:
    return TState(
        symbol="600522",
        trade_date="2026-07-25",
        status="holding",
        entry_price=entry_price,
        entry_time="2026-07-25T10:00:00",
        peak_price=peak_price,
        lots=lots,
        entry_signal="趋势确认",
    )


def test_defaults_are_three_and_two_percent():
    config = TrailingConfig.from_dict()

    assert config.take_profit_pct == 0.03
    assert config.stop_loss_pct == 0.02
    assert config.exit_lots == 1.0


def test_symbol_override_wins_and_missing_value_uses_global_default():
    config = TrailingConfig.from_dict(
        defaults={"take_profit_pct": 0.04, "stop_loss_pct": 0.025},
        override={"stop_loss_pct": 0.015},
        exit_lots=0.5,
    )

    assert config.take_profit_pct == 0.04
    assert config.stop_loss_pct == 0.015
    assert config.exit_lots == 0.5


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("take_profit_pct", 0),
        ("take_profit_pct", 1),
        ("stop_loss_pct", -0.01),
        ("stop_loss_pct", "bad"),
    ],
)
def test_rejects_invalid_thresholds(field, value):
    with pytest.raises(ValueError, match=field):
        TrailingConfig.from_dict(override={field: value})


def test_rejects_non_positive_exit_lots():
    with pytest.raises(ValueError, match="exit_lots"):
        TrailingConfig.from_dict(exit_lots=0)


def test_take_profit_triggers_at_exact_threshold():
    action = check_trailing(_holding(), 103.0, TrailingConfig())

    assert action is not None
    assert action.action == "take_profit"
    assert action.signal_type == "sell"
    assert action.gain_pct == pytest.approx(0.03)
    assert "+3.00%" in action.reason


def test_stop_loss_triggers_at_exact_threshold():
    action = check_trailing(_holding(), 98.0, TrailingConfig())

    assert action is not None
    assert action.action == "stop_loss"
    assert action.signal_type == "stop_loss"
    assert action.gain_pct == pytest.approx(-0.02)
    assert "-2.00%" in action.reason


def test_exit_lots_are_clamped_to_open_lots():
    config = TrailingConfig(exit_lots=1.0)

    action = check_trailing(_holding(lots=0.5), 103.0, config)

    assert action is not None
    assert action.lots == 0.5


@pytest.mark.parametrize("price", [98.01, 100.0, 102.99])
def test_price_inside_band_has_no_action(price):
    assert check_trailing(_holding(), price, TrailingConfig()) is None


@pytest.mark.parametrize("status", ["empty", "locked"])
def test_non_holding_state_has_no_action(status):
    state = _holding()
    state.status = status

    assert check_trailing(state, 103.0, TrailingConfig()) is None


def test_invalid_prices_do_not_trigger():
    assert check_trailing(_holding(entry_price=0), 100.0, TrailingConfig()) is None
    assert check_trailing(_holding(), 0.0, TrailingConfig()) is None
