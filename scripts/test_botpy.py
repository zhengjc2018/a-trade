"""使用 qq-botpy 测试推送。

分别测试：
1. 主动发文本到群（需要主动消息权限，预期失败 40034105）
2. 被动回复（无需权限）

用法：
    ./start.sh scripts/test_botpy.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import botpy
from botpy import logging
from botpy.message import GroupMessage, Message
from dotenv import load_dotenv
from loguru import logger

_log = logging.get_logger()
load_dotenv()

APPID = os.getenv("QQ_BOT_APPID")
SECRET = os.getenv("QQ_BOT_APPSECRET")
GROUP = os.getenv("QQ_TARGET_GROUP")

TEST_TEXT = """🎉 a-trade botpy 推送测试

如果你看到这条消息，说明 qq-botpy 接入成功！

— a-trade v0.0.1"""

TEST_MD = """# a-trade botpy 测试 (Markdown)

## ✅ 接入成功
- AppID + AppSecret 鉴权：OK
- WebSocket 网关连接：OK
- Markdown 渲染：OK
"""


class TestClient(botpy.Client):
    async def on_ready(self):
        logger.success(f"✅ Bot ready: {self.robot.name}")
        # 主动发一条消息测试
        try:
            result = await self.api.post_group_message(
                group_openid=GROUP,
                msg_type=0,
                content=TEST_TEXT,
            )
            logger.success(f"主动文本发送成功: {result}")
        except Exception as e:
            logger.warning(f"主动文本发送失败（预期: 无权限）: {e}")

        # 测 Markdown
        try:
            from botpy.types.message import MarkdownPayload
            result = await self.api.post_group_message(
                group_openid=GROUP,
                msg_type=2,
                markdown=MarkdownPayload(content=TEST_MD),
            )
            logger.success(f"主动 Markdown 发送成功: {result}")
        except Exception as e:
            logger.warning(f"主动 Markdown 发送失败: {e}")

        # 5 秒后退出
        await asyncio.sleep(5)
        await self.close()

    async def on_group_at_message_create(self, message: GroupMessage):
        logger.info(f"收到群 @ 消息: {message.content[:50]}")
        await message._api.post_group_message(
            group_openid=message.group_openid,
            msg_type=0,
            msg_id=message.id,
            content="✅ botpy 被动回复测试成功！",
        )


def main() -> int:
    logger.info("=== qq-botpy 推送测试 ===")
    logger.info(f"AppID: {APPID}")
    logger.info(f"目标群: {GROUP}")

    if not all([APPID, SECRET, GROUP]):
        logger.error("请先在 .env 配置 QQ_BOT_APPID / SECRET / TARGET_GROUP")
        return 1

    intents = botpy.Intents(public_messages=True)
    client = TestClient(intents=intents)
    try:
        client.run(appid=APPID, secret=SECRET)
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"运行异常: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
