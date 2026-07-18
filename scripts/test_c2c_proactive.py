"""测试私聊主动消息（C2C 互动召回）。

不依赖群主动权限，直接推送到你的 QQ 私聊。

前置：你必须在 30 天内和机器人私聊过（或在群里 @ 过）。
首次需要你先在 QQ 给机器人发一条私聊消息（如 "hi"）激活互动召回。
"""

from __future__ import annotations

import os
import sys
from itertools import count

import requests
from dotenv import load_dotenv
from loguru import logger

AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE = "https://api.sgroup.qq.com"

TEST_MSG = """🎉 a-trade 私聊推送测试

如果你看到这条消息，说明 C2C 主动推送通道打通！

后续 a-trade 的做 T 信号、监控提醒、收盘报告
都会通过这个通道推送到你的 QQ 私聊。

— a-trade v0.0.1"""


def main() -> int:
    load_dotenv()
    app_id = os.getenv("QQ_BOT_APPID")
    app_secret = os.getenv("QQ_BOT_APPSECRET")

    logger.info("=== C2C 私聊主动推送测试 ===")

    # 1. 拿 token
    resp = requests.post(
        AUTH_URL,
        json={"appId": app_id, "clientSecret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data["access_token"]
    logger.info(f"✅ token OK ({data['expires_in']}s)")

    # 2. 让用户输入 user_openid（或者先用 QQ 号）
    user_qq = input("\n请输入你的 QQ 号（纯数字，例如 12345678）: ").strip()
    if not user_qq:
        logger.error("QQ 号不能为空")
        return 1

    # 注意：C2C 接口的 user_openid 也不是真实 QQ 号！
    # 但有些场景（特别是个人开发者未认证）可以用 QQ 号代替
    # 先尝试用 QQ 号直接发送
    url = f"{API_BASE}/v2/users/{user_qq}/messages"
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "content": TEST_MSG,
        "msg_type": 0,
        "msg_seq": next(count(1)),
    }

    logger.info(f"POST {url}")
    resp = requests.post(url, json=payload, headers=headers, timeout=10)

    if resp.status_code == 200:
        result = resp.json()
        logger.success(f"✅ 发送成功！消息 ID: {result.get('id')}")
        logger.success(f"请打开 QQ 私聊（机器人 {os.getenv('QQ_BOT_QQ')}）查看")
        return 0

    # 失败的话，可能是 user_openid 而不是 QQ 号
    logger.warning(f"直接用 QQ 号失败 [{resp.status_code}]: {resp.text[:300]}")
    logger.info("")
    logger.info("=" * 60)
    logger.info("需要 user_openid（不是 QQ 号）")
    logger.info("请运行 ./start.sh scripts/discover_user_openid.py 获取")
    logger.info("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
