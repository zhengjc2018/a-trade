"""TMonitorRunner 送达后提交 + TTL 测试。"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.monitor.t_monitor import TMonitorRunner


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    state_path = tmp_path / "t_monitor_state.json"
    monkeypatch.setattr("atrade.monitor.t_monitor._STATE_FILE", state_path)
    return state_path


def _make_runner(ttl_hours=6):
    return TMonitorRunner(
        config={
            "enabled": True, "scan_interval_minutes": 2,
            "scale": "5m", "datalen": 60,
            "symbols": [{"symbol": "600519", "name": "茅台", "cost_price": 100, "quantity": 100}],
        },
        ttl_hours=ttl_hours,
    )


def test_state_init_when_missing(tmp_state):
    runner = _make_runner()
    assert runner._state == {"sent": {}}


def test_state_migrates_old_format(tmp_state):
    """旧格式 {"symbol": "key"} 应迁移为 {"sent": {"symbol": [{"key":..., "sent_at":...}]}}"""
    tmp_state.write_text(json.dumps({"600519": "600519:BUY:2026-01-01:100.00"}))
    runner = _make_runner()
    assert "600519" in runner._state["sent"]
    entry = runner._state["sent"]["600519"][0]
    assert entry["key"] == "600519:BUY:2026-01-01:100.00"
    assert "sent_at" in entry


def test_commit_sent_persists(tmp_state):
    runner = _make_runner()
    alerts = [{
        "__signal_key__": "600519:BUY:2026-01-01:100.00",
        "symbol": "600519", "name": "茅台",
        "signal_type": "BUY", "signal_name": "test",
        "reason": "r", "trigger_price": 100.0,
        "strength": "MEDIUM", "time": "2026-01-01",
    }]
    runner.commit_sent(alerts)
    state = json.loads(tmp_state.read_text())
    assert state["sent"]["600519"][0]["key"] == "600519:BUY:2026-01-01:100.00"


def test_run_once_does_not_persist_state(tmp_state):
    """run_once 产生候选告警但不写状态。"""
    runner = _make_runner()
    # 模拟扫描产出 1 条候选
    fake_alert = {
        "__signal_key__": "600519:BUY:2026-01-01:100.00",
        "symbol": "600519", "name": "茅台",
        "signal_type": "BUY", "signal_name": "test",
        "reason": "r", "trigger_price": 100.0,
        "strength": "MEDIUM", "time": "2026-01-01",
    }
    with patch.object(runner, "run_once", return_value=[fake_alert]):
        alerts = runner.run_once()
    # run_once 返回候选，但状态文件应为空
    assert not tmp_state.exists() or json.loads(tmp_state.read_text()) == {"sent": {}}
    # commit_sent 后才写入
    runner.commit_sent(alerts)
    state = json.loads(tmp_state.read_text())
    assert state["sent"]["600519"][0]["key"] == "600519:BUY:2026-01-01:100.00"


def test_dedup_within_ttl(tmp_state):
    """TTL 窗口内同一信号不重复。"""
    runner = _make_runner(ttl_hours=6)
    runner.commit_sent([{
        "__signal_key__": "K", "symbol": "600519", "name": "x",
        "signal_type": "BUY", "signal_name": "x",
        "reason": "x", "trigger_price": 100.0,
        "strength": "M", "time": "2026-01-01",
    }])
    assert runner._is_recently_sent("600519", "K") is True
    assert runner._is_recently_sent("600519", "OTHER") is False


def test_dedup_expires_after_ttl(tmp_state):
    """TTL 过期后重新允许。"""
    from datetime import datetime, timedelta
    runner = _make_runner(ttl_hours=1)
    expired = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
    runner._state = {"sent": {"600519": [{"key": "K", "sent_at": expired}]}}
    assert runner._is_recently_sent("600519", "K") is False
