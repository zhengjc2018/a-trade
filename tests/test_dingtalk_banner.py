"""钉钉通知醒目度优化：banner / at_all / task_key 去重。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from atrade.notify.dingtalk import render_banner, render_for_dingtalk


def test_banner_contains_emoji_and_title():
    md = render_banner("morning_brief", "海外收盘")
    assert "# 🟢" in md
    assert "a-trade 早盘快讯" in md
    assert "海外收盘" in md
    assert md.count(chr(10)) >= 2


def test_banner_without_subtitle():
    md = render_banner("closing_report")
    assert "a-trade 收盘日报" in md
    assert "# 🔴" in md
    assert "🕒" in md


def test_banner_unknown_task_uses_default():
    md = render_banner("nonexistent")
    assert "a-trade nonexistent" in md
    assert "# 📣" in md


def test_banner_task_name_to_emoji_mapping():
    for task in [
        "morning_brief", "auction_analysis", "noon_report",
        "closing_report", "holdings_news", "delivery_heartbeat",
        "t_monitor", "t_status_morning", "t_status_closing",
        "screen_monitor", "backtest",
    ]:
        b = render_banner(task)
        assert b.startswith("#"), f"banner {task} missing # heading"


def test_render_for_dingtalk_handles_two_col_table():
    md = "| col1 | col2 |" + chr(10) + "|---|---|" + chr(10) + "| a | b |"
    rendered = render_for_dingtalk(md)
    assert "**a**" in rendered
    assert "b" in rendered


def test_render_for_dingtalk_handles_three_col_table():
    md = (
        "| H1 | H2 | H3 |" + chr(10) +
        "|---|---|---|" + chr(10) +
        "| x | y | z |" + chr(10) +
        "| p | q | r |"
    )
    rendered = render_for_dingtalk(md)
    assert "**H1**" in rendered
    assert "**H2**" in rendered
    assert "**H3**" in rendered


def test_render_for_dingtalk_passthrough_no_table():
    md = "## heading" + chr(10) + chr(10) + "body text"
    assert render_for_dingtalk(md) == md
