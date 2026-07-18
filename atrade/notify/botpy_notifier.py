"""基于 qq-botpy 的 QQ 机器人推送模块。

封装 botpy 的 API 调用，提供：
- send_group_text(group_openid, content): 主动推文本到群
- send_group_markdown(group_openid, md): 主动推 Markdown 到群
- BotpyClient: 完整的 Client（含事件监听）
"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

import botpy
from botpy import logging
from botpy.message import GroupMessage, Message
from dotenv import load_dotenv
from loguru import logger

_log = logging.get_logger()


def _load_config() -> dict:
    """从 .env 加载 AppID / AppSecret。"""
    load_dotenv()
    return {
        "appid": os.getenv("QQ_BOT_APPID"),
        "secret": os.getenv("QQ_BOT_APPSECRET"),
    }


class AtBotClient(botpy.Client):
    """a-trade 机器人 Client。

    监听群 @ 消息并自动回复（被动回复模式，无月度限制）。
    主动推送通过外部调用 send_group_text / send_group_markdown。
    """

    async def on_ready(self):
        _log.info(f"✅ 机器人「{self.robot.name}」已就绪")

    async def on_group_at_message_create(self, message: GroupMessage):
        """群内 @ 消息事件。"""
        logger.info(
            f"收到群消息: group={message.group_openid}, "
            f"author={message.author.member_openid}, "
            f"content={message.content[:50]}"
        )
        # 默认 echo 回复 — 实际命令路由由 BotRouter 处理
        # 这里只做最小演示
        try:
            await message._api.post_group_message(
                group_openid=message.group_openid,
                msg_type=0,
                msg_id=message.id,
                content=f"✅ a-trade 已收到 @\n\n（命令路由待实现）",
            )
        except Exception as e:
            logger.error(f"被动回复失败: {e}")


class BotpyNotifier:
    """botpy 推送器：用于主动发消息。

    用法：
        async with BotpyNotifier() as notifier:
            await notifier.send_group_text(group_openid, "hello")
    """

    def __init__(
        self,
        appid: Optional[str] = None,
        secret: Optional[str] = None,
    ):
        cfg = _load_config()
        self.appid = appid or cfg["appid"]
        self.secret = secret or cfg["secret"]

        if not self.appid or not self.secret:
            raise ValueError("请在 .env 配置 QQ_BOT_APPID 和 QQ_BOT_APPSECRET")

        self._client: Optional[AtBotClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    async def __aenter__(self):
        """异步上下文：启动 Client（保持 WebSocket 在线）。"""
        self._client = AtBotClient(
            intents=botpy.Intents(public_messages=True)
        )
        # 后台线程跑 client.run()
        self._loop = asyncio.get_event_loop()

        def _run():
            asyncio.run(self._client.run(appid=self.appid, secret=self.secret))

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        # 等 READY
        for _ in range(30):
            if self._client.robot:
                break
            await asyncio.sleep(1)

        logger.info(f"✅ botpy Client 已启动: {self._client.robot.name}")
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.close()

    async def send_group_text(
        self,
        group_openid: str,
        content: str,
    ) -> dict:
        """主动发送文本到群（需要主动消息权限）。"""
        if not self._client:
            raise RuntimeError("请用 async with BotpyNotifier() 初始化")

        result = await self._client.api.post_group_message(
            group_openid=group_openid,
            msg_type=0,
            content=content,
        )
        logger.success(f"群消息已发送: id={result.get('id')}")
        return result

    async def send_group_markdown(
        self,
        group_openid: str,
        markdown_content: str,
    ) -> dict:
        """主动发送 Markdown 到群。"""
        from botpy.types.message import MarkdownPayload
        if not self._client:
            raise RuntimeError("请用 async with BotpyNotifier() 初始化")

        result = await self._client.api.post_group_message(
            group_openid=group_openid,
            msg_type=2,
            markdown=MarkdownPayload(content=markdown_content),
        )
        logger.success(f"Markdown 已发送: id={result.get('id')}")
        return result
