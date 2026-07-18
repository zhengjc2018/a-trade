"""OpenClaw 推送测试脚本。

用法：
    1. cp .env.example .env  并填入真实凭据
    2. python3 scripts/test_openclaw.py
"""

from __future__ import annotations

import sys

from atrade.notify.openclaw import OpenClawNotifier
from loguru import logger


TEST_TEXT = """🎉 a-trade 推送测试

如果你看到这条消息，说明 OpenClaw 接入成功！
✅ access_token 获取正常
✅ HTTP API 调用正常
✅ 消息已到达目标群

后续 a-trade 的做 T 信号、监控提醒、收盘报告
都会通过这个通道推送到这里。

— a-trade v0.0.1"""

TEST_MARKDOWN = """# a-trade 推送测试 (Markdown)

## ✅ 接入成功

| 项目 | 状态 |
| --- | --- |
| AppID 鉴权 | OK |
| access_token 自动获取 | OK |
| Markdown 渲染 | OK |
| 群消息送达 | OK |

> 后续信号推送 / 收盘报告都会用这个格式。
"""


def main() -> int:
    logger.info("=== OpenClaw 推送测试 ===")
    try:
        notifier = OpenClawNotifier()
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        logger.error("请检查 .env 文件，确认 4 个值都已填入真实数据")
        return 1

    logger.info(f"AppID: {notifier.app_id}")
    logger.info(f"BotQQ: {notifier.bot_qq}")
    logger.info(f"目标群: {notifier.target_group}")

    try:
        logger.info("--- 测试 1: 发送纯文本 ---")
        result = notifier.send_text(TEST_TEXT)
        logger.success(f"文本消息发送成功: {result}")

        logger.info("--- 测试 2: 发送 Markdown ---")
        result = notifier.send_markdown(TEST_MARKDOWN)
        logger.success(f"Markdown 消息发送成功: {result}")

    except Exception as e:
        logger.error(f"推送失败: {e}")
        logger.error("可能原因:")
        logger.error("  1. AppID / AppSecret 错误")
        logger.error("  2. 机器人未在目标群中")
        logger.error("  3. 网络问题")
        logger.error("  4. 机器人没有 send_group_msg 权限")
        return 1

    logger.success("=== 测试完成，请到目标群查看消息 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
