"""双阶段做T确认器测试。"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.monitor.t_confirmer import (
    BYPASS_TYPES,
    TwoStageConfirmer,
)


def _alert(symbol="600522", signal_type="BUY", strength="strong",
           trigger_price=62.0, name="中天科技", reason="r"):
    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "strength": strength,
        "signal_name": f"{signal_type} test",
        "reason": reason,
        "trigger_price": trigger_price,
        "name": name,
        "note": "",
        "time": "2026-07-22",
    }


def test_first_scan_does_not_confirm():
    c = TwoStageConfirmer(confirm_bars=2)
    out = c.filter([_alert()])
    assert out == []
    assert c.pending_count == 1
    assert c.stats.confirmed == 0


def test_second_scan_confirms():
    c = TwoStageConfirmer(confirm_bars=2)
    c.filter([_alert()])
    out = c.filter([_alert()])
    assert len(out) == 1
    assert out[0]["symbol"] == "600522"
    assert out[0]["signal_type"] == "buy"
    assert out[0]["hits"] == 2
    assert c.pending_count == 0
    assert c.stats.confirmed == 1


def test_stop_loss_bypass_immediate():
    c = TwoStageConfirmer(confirm_bars=2)
    out = c.filter([_alert(signal_type="STOP_LOSS")])
    assert len(out) == 1
    assert out[0]["signal_type"] == "stop_loss"
    assert c.pending_count == 0


def test_signal_disappear_drops_pending():
    c = TwoStageConfirmer(confirm_bars=2, candidate_ttl_minutes=30)
    c.filter([_alert()])
    assert c.pending_count == 1
    # 第二轮什么都不来 → 在 TTL 衰减前保留
    out = c.filter([])
    assert out == []
    assert c.pending_count == 1  # 还没过期


def test_signal_reappear_resumes_count():
    c = TwoStageConfirmer(confirm_bars=3)
    c.filter([_alert()])  # hits=1
    c.filter([_alert()])  # hits=2
    out = c.filter([_alert()])  # hits=3 → confirm
    assert len(out) == 1
    assert c.pending_count == 0


def test_expired_candidate_dropped(monkeypatch):
    c = TwoStageConfirmer(confirm_bars=2, candidate_ttl_minutes=1)
    c.filter([_alert()])
    assert c.pending_count == 1
    # 把 first_seen 拨到 5 分钟前
    cand = list(c._pending.values())[0]
    cand.first_seen = datetime.now() - timedelta(minutes=5)
    out = c.filter([_alert()])
    assert out == []
    assert c.pending_count == 1  # 重新入队
    assert c.stats.expired >= 1


def test_drift_price_drops_pending():
    c = TwoStageConfirmer(confirm_bars=2)
    c.filter([_alert(trigger_price=62.0)])
    out = c.filter([_alert(trigger_price=70.0)])
    assert out == []
    # 原候选被丢弃（drift），新候选入队
    assert c.pending_count == 1


def test_force_confirm_shortcut():
    c = TwoStageConfirmer(confirm_bars=3)
    out = list(c.force_confirm([_alert()]))
    assert len(out) == 1
    assert out[0]["hits"] == 3


def test_multi_symbol_independent():
    c = TwoStageConfirmer(confirm_bars=2)
    c.filter([_alert(symbol="600522"), _alert(symbol="601318")])
    assert c.pending_count == 2
    out = c.filter([_alert(symbol="600522")])  # 只确认 600522
    assert len(out) == 1
    assert out[0]["symbol"] == "600522"
    assert c.pending_count == 1


def test_unknown_signal_type_treated_as_watch():
    c = TwoStageConfirmer(confirm_bars=1)
    out = c.filter([_alert(signal_type="unknown")])
    assert len(out) == 0
    # 仍然入队（因为 confirm_bars=1 时下轮应升级）
    assert c.pending_count == 1


def test_bypass_types_contains_stop_loss():
    assert "stop_loss" in BYPASS_TYPES


def test_reset_clears_state():
    c = TwoStageConfirmer(confirm_bars=2)
    c.filter([_alert()])
    assert c.pending_count == 1
    c.reset()
    assert c.pending_count == 0
    assert c.stats.confirmed == 0


def test_disappear_old_drops_pending():
    c = TwoStageConfirmer(confirm_bars=2, candidate_ttl_minutes=30)
    c.filter([_alert()])
    # 手动把 last_seen 拨到 30 分钟前
    cand = list(c._pending.values())[0]
    cand.last_seen = datetime.now() - timedelta(minutes=30)
    out = c.filter([])
    assert out == []
    assert c.pending_count == 0
