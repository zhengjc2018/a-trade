"""端到端测试：手动触发一次报告推送。

不依赖定时器，立刻生成报告并推到 QQ 群。
"""

from __future__ import annotations

import asyncio
import sys

import botpy
from botpy import logging
from botpy.message import GroupMessage
from botpy.types.message import MarkdownPayload
from dotenv import load_dotenv
from loguru import logger

import os

_log = logging.get_logger()
load_dotenv()


class TestClient(botpy.Client):
    async def on_ready(self):
        logger.success(f"✅ Bot ready: {self.robot.name}")
        # 立刻生成报告并推送
        await self._do_push()

        # 等几秒看是否有 @ 消息（用户测试用）
        await asyncio.sleep(15)
        await self.close()

    async def on_group_at_message_create(self, message: GroupMessage):
        logger.info(f"收到 @ 消息: {message.content[:50]}")
        await message._api.post_group_message(
            group_openid=message.group_openid,
            msg_type=0,
            msg_id=message.id,
            content="✅ botpy 已连接。会自动推送日报和新闻，无需手动触发。",
        )

    async def _do_push(self):
        from atrade.report import ReportGenerator

        gen = ReportGenerator(
            holdings=[
                {"symbol": "600519", "name": "贵州茅台", "cost_price": 1650, "quantity": 100},
                {"symbol": "000001", "name": "平安银行", "cost_price": 12.5, "quantity": 5000},
            ],
            watch_keywords=["茅台", "银行", "美联储"],
        )

        report = gen.generate_closing_report()
        full_md = f"# 📊 a-trade 端到端测试推送\n\n{report}"
        if len(full_md) > 3800:
            full_md = full_md[:3800] + "\n\n...(截断)"

        try:
            result = await self.api.post_group_message(
                group_openid=os.getenv("QQ_TARGET_GROUP"),
                msg_type=2,
                markdown=MarkdownPayload(content=full_md),
            )
            logger.success(f"✅ 推送成功: {result}")
        except Exception as e:
            logger.error(f"❌ 推送失败: {e}")


def main() -> int:
    logger.info("=== 端到端推送测试 ===")
    intents = botpy.Intents(public_messages=True)
    client = TestClient(intents=intents)
    try:
        client.run(appid=os.getenv("QQ_BOT_APPID"), secret=os.getenv("QQ_BOT_APPSECRET"))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
