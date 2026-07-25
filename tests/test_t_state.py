from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.monitor.t_state import TStateStore


def _now(value: str):
    parsed = datetime.fromisoformat(value)
    return lambda: parsed


def test_missing_state_returns_empty(tmp_path):
    store = TStateStore(tmp_path / "t_state.json", now=_now("2026-07-25T09:30:00"))

    state = store.get("600522")

    assert state.symbol == "600522"
    assert state.status == "empty"
    assert state.entry_price == 0.0


def test_state_round_trip_persists(tmp_path):
    path = tmp_path / "t_state.json"
    clock = _now("2026-07-25T10:00:00")
    store = TStateStore(path, now=clock)

    store.mark_buy(
        "600522",
        entry_price=62.0,
        lots=1.0,
        entry_signal="趋势确认",
        timestamp="2026-07-25T10:00:00",
    )
    state = TStateStore(path, now=clock).get("600522")

    assert state.status == "holding"
    assert state.trade_date == "2026-07-25"
    assert state.entry_price == 62.0
    assert state.peak_price == 62.0
    assert state.lots == 1.0
    assert state.entry_signal == "趋势确认"


def test_corrupt_state_recovers(tmp_path):
    path = tmp_path / "t_state.json"
    path.write_text("{", encoding="utf-8")
    store = TStateStore(path, now=_now("2026-07-25T10:00:00"))

    assert store.get("600522").status == "empty"

    store.mark_buy("600522", 62.0, 1.0, "趋势确认")
    assert json.loads(path.read_text(encoding="utf-8"))["states"]["600522"]["status"] == "holding"


def test_stale_day_is_not_returned(tmp_path):
    path = tmp_path / "t_state.json"
    old_store = TStateStore(path, now=_now("2026-07-24T10:00:00"))
    old_store.mark_buy("600522", 62.0, 1.0, "趋势确认")

    today_store = TStateStore(path, now=_now("2026-07-25T09:29:00"))

    assert today_store.get("600522").status == "empty"


def test_reset_day_clears_all_states(tmp_path):
    path = tmp_path / "t_state.json"
    store = TStateStore(path, now=_now("2026-07-25T09:30:00"))
    store.mark_buy("600522", 62.0, 1.0, "趋势确认")
    store.mark_buy("002436", 41.0, 1.0, "超卖反弹")

    store.reset_day("2026-07-25")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"trade_date": "2026-07-25", "states": {}}


def test_peak_price_only_moves_up(tmp_path):
    store = TStateStore(tmp_path / "t_state.json", now=_now("2026-07-25T10:00:00"))
    store.mark_buy("600522", 62.0, 1.0, "趋势确认")

    store.update_peak("600522", 63.0)
    store.update_peak("600522", 61.0)

    assert store.get("600522").peak_price == 63.0


def test_mark_exit_preserves_entry_and_changes_status(tmp_path):
    store = TStateStore(tmp_path / "t_state.json", now=_now("2026-07-25T10:00:00"))
    store.mark_buy("600522", 62.0, 1.0, "趋势确认")

    state = store.mark_exit("600522", status="locked")

    assert state.status == "locked"
    assert state.entry_price == 62.0
    assert state.lots == 0.0


@pytest.mark.parametrize(
    ("price", "lots", "message"),
    [(0.0, 1.0, "entry_price"), (62.0, 0.0, "lots")],
)
def test_mark_buy_rejects_invalid_values(tmp_path, price, lots, message):
    store = TStateStore(tmp_path / "t_state.json")

    with pytest.raises(ValueError, match=message):
        store.mark_buy("600522", price, lots, "趋势确认")


def test_rejects_invalid_exit_status(tmp_path):
    store = TStateStore(tmp_path / "t_state.json")

    with pytest.raises(ValueError, match="status"):
        store.mark_exit("600522", status="holding")
