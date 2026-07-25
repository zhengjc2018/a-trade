"""钉钉自定义机器人推送（webhook + markdown）。

支持：
- 关键词验证（payload 必须包含配置的关键词）
- 加签（HMAC-SHA256，timestamp + sign 拼到 URL）
- Markdown 消息（标题 + 正文）

限制：
- 钉钉 markdown 不支持表格渲染（|...|），需要调用方将表格转成
  项目符号 / 对齐文本，或使用 `render_for_dingtalk` 工具。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import time
import urllib.parse
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv
from loguru import logger

WEBHOOK_BASE = "https://oapi.dingtalk.com/robot/send"


class DingTalkNotifier:
    """钉钉群自定义机器人推送器。

    用法：
        notifier = DingTalkNotifier(access_token="xxx", keyword="股票")
        notifier.send_markdown("标题", "正文")

    或从环境变量加载：
        load_dotenv()
        notifier = DingTalkNotifier(
            access_token=os.getenv("DINGTALK_ACCESS_TOKEN"),
            keyword=os.getenv("DINGTALK_KEYWORD", ""),
            secret=os.getenv("DINGTALK_SECRET") or None,
        )
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        keyword: str = "",
        secret: Optional[str] = None,
        at_all: bool = False,
        timeout: float = 10.0,
    ):
        load_dotenv()
        self.access_token = (
            access_token
            or os.getenv("DINGTALK_ACCESS_TOKEN")
            or os.getenv("DINGTALK_TOKEN")
        )
        self.keyword = keyword or os.getenv("DINGTALK_KEYWORD", "")
        self.secret = secret or os.getenv("DINGTALK_SECRET") or None
        self.at_all = at_all or (os.getenv("DINGTALK_AT_ALL", "").lower() in ("1", "true", "yes"))
        self.timeout = timeout

        if not self.access_token or self.access_token.startswith("your_"):
            raise ValueError(
                "DINGTALK_ACCESS_TOKEN 未配置。请在 .env 设置 "
                "DINGTALK_ACCESS_TOKEN=<从钉钉群机器人 webhook 复制的 access_token>"
            )

    @property
    def webhook_url(self) -> str:
        """构造带签名后的 webhook URL。"""
        url = f"{WEBHOOK_BASE}?access_token={self.access_token}"
        if self.secret:
            ts = str(round(time.time() * 1000))
            string_to_sign = f"{ts}\n{self.secret}"
            digest = hmac.new(
                self.secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))
            url = f"{url}&timestamp={ts}&sign={sign}"
        return url

    def _ensure_keyword(self, text: str) -> str:
        """若消息未包含关键词，自动追加一行，避免被关键词校验拒绝。"""
        if not self.keyword:
            return text
        if self.keyword in text:
            return text
        return f"{text}\n\n> {self.keyword}"

    def send_text(self, content: str) -> dict:
        """发送纯文本。"""
        payload = {
            "msgtype": "text",
            "text": {"content": self._ensure_keyword(content)},
            "at": {"isAtAll": self.at_all},
        }
        return self._post(payload)

    def send_markdown(
        self,
        content: str,
        title: str = "a-trade 通知",
        at_all: Optional[bool] = None,
    ) -> dict:
        """发送 Markdown。

        Args:
            content: Markdown 正文（已被 render_for_dingtalk 转换）。
            title: 推送标题，会被钉钉作为消息卡片预览。
            at_all: 覆盖默认 at_all（本条消息是否 @ 全体）。None 表示用实例默认。
        """
        effective_at_all = self.at_all if at_all is None else bool(at_all)
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": self._ensure_keyword(content),
            },
            "at": {"isAtAll": effective_at_all},
        }
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if resp.status_code >= 400 or data.get("errcode", 0) != 0:
                logger.error(
                    f"DingTalk 推送失败 [{resp.status_code}]: "
                    f"{data.get('errmsg', resp.text[:200])}"
                )
                from .delivery import DeliveryError

                raise DeliveryError(
                    "dingtalk",
                    data.get("errmsg") or f"HTTP {resp.status_code}",
                    response=data,
                )
            else:
                logger.success(f"✅ DingTalk 已发送: {payload.get('msgtype')}")
            return data
        except Exception as e:
            logger.error(f"DingTalk 推送异常: {e}")
            raise


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _table_cells(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _render_table_row(headers: list[str], values: list[str]) -> str:
    pairs = list(zip(headers, values))
    if len(pairs) == 2:
        return f"- **{pairs[0][1]}**：{pairs[1][1]}"
    return "- " + "；".join(
        f"**{header}**：{value}" for header, value in pairs
    )


# 任务 → 视觉横幅（emoji + 加粗 + 颜色 emoji 用于钉钉本地渲染）
_BANNERS: dict[str, tuple[str, str]] = {
    # task_name: (level_emoji, title)
    "morning_brief":    ("🟢", "a-trade 早盘快讯"),
    "auction_analysis": ("🟡", "a-trade 集合竞价"),
    "noon_report":      ("🟠", "a-trade 午盘报告"),
    "closing_report":   ("🔴", "a-trade 收盘日报"),
    "holdings_news":    ("⚪", "a-trade 持仓新闻"),
    "delivery_heartbeat": ("⚙️", "a-trade 通知心跳"),
    "t_monitor":        ("📊", "a-trade 做T信号"),
    "t_status_morning": ("📈", "a-trade 上午做T汇总"),
    "t_status_closing": ("📉", "a-trade 收盘做T汇总"),
    "screen_monitor":   ("🔍", "a-trade 盘中选股"),
    "backtest":         ("🧪", "a-trade 回测报告"),
}


def render_banner(
    task_name: str,
    subtitle: str = "",
    *,
    time_stamp: Optional[str] = None,
) -> str:
    """生成钉钉顶端醒目横幅，避免被折叠 / 与 t_monitor 噪声混淆。

    Returns:
        一段 Markdown 字符串，应放在推送内容最前。
    """
    level_emoji, title = _BANNERS.get(
        task_name, ("📣", f"a-trade {task_name}")
    )
    ts = time_stamp or datetime.now().strftime("%Y-%m-%d %H:%M")
    if subtitle:
        second_line = f"**🕒 {ts}** ｜ {subtitle}"
    else:
        second_line = f"**🕒 {ts}**"
    parts = [
        f"# {level_emoji} {title}",
        second_line,
        "---",
    ]
    return "\n\n".join(parts)


def render_for_dingtalk(md: str) -> str:
    """把标准 Markdown 表格转换为钉钉可读的项目列表。"""
    lines = md.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if (
            index + 1 < len(lines)
            and line.strip().startswith("|")
            and line.strip().endswith("|")
            and _is_table_separator(lines[index + 1])
        ):
            headers = _table_cells(line)
            index += 2
            while index < len(lines):
                row = lines[index].strip()
                if not (row.startswith("|") and row.endswith("|")):
                    break
                values = _table_cells(row)
                output.append(_render_table_row(headers, values))
                index += 1
            continue
        output.append(line)
        index += 1
    return "\n".join(output)
