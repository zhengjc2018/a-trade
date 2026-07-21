"""钉钉 notifier 测试。"""

import base64
import hashlib
import hmac
import os
import sys
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.notify.dingtalk import (
    WEBHOOK_BASE,
    DingTalkNotifier,
    render_for_dingtalk,
)


def test_missing_access_token_raises(monkeypatch):
    monkeypatch.delenv("DINGTALK_ACCESS_TOKEN", raising=False)
    with pytest.raises(ValueError, match="DINGTALK_ACCESS_TOKEN"):
        DingTalkNotifier()


def test_placeholder_access_token_raises(monkeypatch):
    monkeypatch.setenv("DINGTALK_ACCESS_TOKEN", "your_token_here")
    with pytest.raises(ValueError, match="DINGTALK_ACCESS_TOKEN"):
        DingTalkNotifier()


def test_basic_webhook_url_no_secret():
    n = DingTalkNotifier(access_token="abc123", keyword="股票")
    assert n.webhook_url == f"{WEBHOOK_BASE}?access_token=abc123"


def test_webhook_url_with_hmac_signature():
    """加签 URL 应包含 timestamp + sign 参数。"""
    n = DingTalkNotifier(access_token="abc", keyword="", secret="topsecret")
    url = n.webhook_url
    assert "timestamp=" in url
    assert "&sign=" in url
    # 手动计算预期签名
    from urllib.parse import parse_qs
    qs = parse_qs(url.split("?", 1)[1])
    ts = qs["timestamp"][0]
    sign = qs["sign"][0]
    expected = hmac.new(
        b"topsecret", f"{ts}\ntopsecret".encode(), hashlib.sha256
    ).digest()
    expected_base64 = base64.b64encode(expected).decode("utf-8")
    assert sign == expected_base64
    assert f"&sign={urllib.parse.quote_plus(expected_base64)}" in url


def test_keyword_appended_when_missing():
    n = DingTalkNotifier(access_token="abc", keyword="股票")
    sent = {}

    def fake_post(payload):
        sent["payload"] = payload
        return {"errcode": 0, "errmsg": "ok"}

    with patch.object(n, "_post", side_effect=fake_post):
        n.send_text("hello world")
    assert "股票" in sent["payload"]["text"]["content"]
    assert sent["payload"]["msgtype"] == "text"


def test_keyword_not_appended_when_present():
    n = DingTalkNotifier(access_token="abc", keyword="股票")
    sent = {}

    def fake_post(payload):
        sent["payload"] = payload
        return {"errcode": 0, "errmsg": "ok"}

    with patch.object(n, "_post", side_effect=fake_post):
        n.send_text("推荐一只好股票")
    assert sent["payload"]["text"]["content"].count("股票") == 1


def test_send_markdown_payload():
    n = DingTalkNotifier(access_token="abc", keyword="股票")
    sent = {}

    def fake_post(payload):
        sent["payload"] = payload
        return {"errcode": 0, "errmsg": "ok"}

    with patch.object(n, "_post", side_effect=fake_post):
        n.send_markdown("# 标题\n内容", title="T 信号")
    p = sent["payload"]
    assert p["msgtype"] == "markdown"
    assert p["markdown"]["title"] == "T 信号"
    assert "标题" in p["markdown"]["text"]
    assert "股票" in p["markdown"]["text"]


def test_render_for_dingtalk_strips_table_pipes():
    md = """# 报告

| 代码 | 价格 |
|---|---|
| 600522 | 12.5 |

    正文内容。
"""
    out = render_for_dingtalk(md)
    assert "- **600522**：12.5" in out
    assert "|---|" not in out
    assert "正文内容。" in out


def test_real_post_to_dingtalk():
    """真实推送：使用 token + 关键词 '股票' 验证。"""
    token = os.getenv("DINGTALK_ACCESS_TOKEN")
    if not token or token == "your_token_here":
        pytest.skip("DINGTALK_ACCESS_TOKEN 未设置，跳过真实推送")
    n = DingTalkNotifier(access_token=token, keyword="股票")
    result = n.send_markdown(
        "## 钉钉连通性测试\n这是一条测试消息，包含股票关键词验证。",
        title="a-trade 测试",
    )
    assert result.get("errcode") == 0
