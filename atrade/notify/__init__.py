"""统一通知接口。

- Notifier 抽象：text / markdown / media 三种类型。
- 实现：BotpyNotifier（WebSocket 主动消息，4 条/月配额）和 OpenClawNotifier（REST 主动消息）。
- 调度器和 CLI 只调用 Notifier 接口；具体实现可由配置注入。
- 群 ID 优先取 `QQ_TARGET_GROUP` 环境变量；未设置时报错。

配额建议：
- 主动消息受 QQ 平台硬限制（群聊 / 单聊均 4 条/月）。
- 默认走被动回复（被 @ 时回复）；主动推送通过 OpenClawNotifier REST 接口。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from .botpy_notifier import BotpyNotifier
from .delivery import DeliveryAttempt, DeliveryError, DeliveryResult
from .dingtalk import DingTalkNotifier, render_for_dingtalk
from .headline import (
    chinese_signal_label,
    infer_conclusion,
    prepend_headline,
    render_headline,
    split_by_symbol_headlines,
)
from .ledger import DeliveryLedger
from .openclaw import OpenClawNotifier
from .router import DeliveryRouter


class Notifier(ABC):
    """统一通知抽象。"""

    @abstractmethod
    def send_text(self, content: str) -> dict:
        """发送纯文本到默认目标群。"""

    @abstractmethod
    def send_markdown(self, content: str) -> dict:
        """发送 Markdown 到默认目标群。"""


def load_notifier(
    preferred: str = "openclaw",
    target_group: Optional[str] = None,
) -> Notifier:
    """根据配置选择 Notifier 实现。

    Args:
        preferred: "openclaw" / "botpy" / "dingtalk"。
        target_group: QQ 群 ID（仅 QQ 通道需要）。

    Returns:
        Notifier 实例。

    Raises:
        ValueError: 配置缺失。
    """
    load_dotenv()
    preferred = (preferred or "openclaw").lower()

    if preferred == "dingtalk":
        try:
            return DingTalkNotifier()
        except Exception as e:
            logger.warning(f"DingTalkNotifier 初始化失败 ({e})")
            raise

    target = target_group or os.getenv("QQ_TARGET_GROUP")
    if not target or target.startswith("your_"):
        raise ValueError(
            "未配置 QQ_TARGET_GROUP（或仍为占位符），请在 .env 设置"
        )

    if preferred == "botpy":
        try:
            return BotpyNotifier()
        except Exception as e:
            logger.warning(f"BotpyNotifier 初始化失败 ({e})，降级为 OpenClawNotifier")
            return OpenClawNotifier(target_group=target)
    return OpenClawNotifier(target_group=target)


def split_markdown_by_bytes(content: str, max_bytes: int = 3800) -> list[str]:
    """按 UTF-8 字节安全截断 Markdown，优先在段落边界拆分。

    中文 UTF-8 一般占 3 字节；按字符截断会超平台 4096 字节上限。
    """
    if not content:
        return []
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return [content]

    parts: list[str] = []
    remaining = content
    while remaining:
        encoded = remaining.encode("utf-8")
        if len(encoded) <= max_bytes:
            parts.append(remaining)
            break
        # 优先在段落边界（\n\n）拆分；允许 2x max_bytes 以换取段落完整性
        # （QQ 平台硬限 4096 字节，宁可分两段也不要切碎语义）
        search_end = min(len(remaining), max_bytes * 2)
        boundary = remaining[:search_end].rfind("\n\n")
        if boundary > 0:
            cut = boundary
        else:
            # 无段落边界 → 二分查找最长可容纳前缀（按 UTF-8 字节）
            lo, hi = 0, min(len(remaining), search_end)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if len(remaining[:mid].encode("utf-8")) <= max_bytes:
                    lo = mid
                else:
                    hi = mid - 1
            cut = lo
        parts.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return parts


__all__ = [
    "Notifier",
    "BotpyNotifier",
    "OpenClawNotifier",
    "DingTalkNotifier",
    "render_for_dingtalk",
    "DeliveryAttempt",
    "DeliveryError",
    "DeliveryResult",
    "DeliveryLedger",
    "DeliveryRouter",
    "load_notifier",
    "split_markdown_by_bytes",
    "chinese_signal_label",
    "infer_conclusion",
    "prepend_headline",
    "render_headline",
    "split_by_symbol_headlines",
]
