"""Runner / Router 集成 banner + at_all 行为。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest


@pytest.fixture
def runner():
    """Mock 出 DailyScheduler，跑 _deliver 验证 banner / at_all / task_key。"""
    from atrade.scheduler.runner import DailyScheduler
    sched = DailyScheduler.__new__(DailyScheduler)
    sched.delivery_router = MagicMock()
    return sched


def test_deliver_at_all_default_for_morning_brief(runner):
    for task in ["morning_brief", "noon_report", "closing_report", "holdings_news",
                 "auction_analysis", "t_status_morning", "t_status_closing",
                 "screen_review", "next_day_gap_candidates"]:
        runner._deliver(task, "title", "body", "")
        call_kwargs = runner.delivery_router.send.call_args.kwargs
        assert call_kwargs["at_all"] is True, f"{task} should default at_all=True"


def test_deliver_at_all_false_for_t_monitor(runner):
    runner._deliver("t_monitor", "title", "body", ":1030")
    call_kwargs = runner.delivery_router.send.call_args.kwargs
    assert call_kwargs["at_all"] is False


def test_deliver_at_all_explicit_override(runner):
    runner._deliver("morning_brief", "title", "body", "", at_all=False)
    call_kwargs = runner.delivery_router.send.call_args.kwargs
    assert call_kwargs["at_all"] is False


def test_deliver_prepends_banner(runner):
    runner._deliver("morning_brief", "海外收盘", "正文 ABC", "")
    sent_md = runner.delivery_router.send.call_args[0][2]
    assert "🟢 **a-trade 早盘快讯**" in sent_md
    assert "正文 ABC" in sent_md
    assert sent_md.index("🟢") < sent_md.index("正文 ABC")


def test_deliver_task_key_includes_minute(runner):
    runner._deliver("morning_brief", "title", "body", "")
    task_key = runner.delivery_router.send.call_args[0][0]
    today = datetime.now().strftime("%Y-%m-%d")
    assert task_key.startswith("morning_brief:" + today)
    parts = task_key.split(":")
    # 至少包含 4 位 HHMM
    assert len(parts[-1]) >= 4


def test_deliver_banner_for_unknown_task(runner):
    runner._deliver("some_new_task", "title", "body", "")
    sent_md = runner.delivery_router.send.call_args[0][2]
    assert "📣 **a-trade some_new_task**" in sent_md


def test_render_banner_unknown_uses_default_title():
    from atrade.notify.dingtalk import render_banner
    md = render_banner("xyz")
    assert "📣 **a-trade xyz**" in md
