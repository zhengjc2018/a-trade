"""通过 WebSocket 发现 group_openid。

QQ 官方机器人的群 ID 是 group_openid（不是数字群号）。
要从入站消息事件里才能读到，所以本脚本连 WebSocket 网关，
等你 @ 一次机器人后捕获 group_openid 并自动写入 .env。

用法：
    ./start.sh scripts/discover_group_openid.py
    （然后在群里 @ 一次机器人）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import requests
import websockets
from dotenv import load_dotenv, set_key
from loguru import logger

AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL = "https://api.sgroup.qq.com/gateway"
WSS_URL = "wss://api.sgroup.qq.com/websocket/"

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def get_token(app_id: str, app_secret: str) -> str:
    resp = requests.post(
        AUTH_URL,
        json={"appId": app_id, "clientSecret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError(f"鉴权失败: {data}")
    return data["access_token"]


async def discover(app_id: str, app_secret: str, timeout: int = 60):
    token = get_token(app_id, app_secret)
    logger.info(f"✅ access_token 获取成功")

    # 优先调 /gateway，失败用 fallback
    try:
        gw_resp = requests.get(
            GATEWAY_URL,
            headers={"Authorization": f"QQBot {token}"},
            timeout=5,
        )
        gw_resp.raise_for_status()
        wss_endpoint = gw_resp.json().get("url", WSS_URL)
    except Exception as e:
        logger.warning(f"/gateway 接口失败，用 fallback: {e}")
        wss_endpoint = WSS_URL

    logger.info(f"连接 WebSocket: {wss_endpoint[:60]}...")

    async with websockets.connect(wss_endpoint) as ws:
        # 1. 等 Hello
        hello = json.loads(await ws.recv())
        if hello.get("op") != 10:
            raise RuntimeError(f"期望 Hello (op=10)，收到: {hello}")
        heartbeat_interval = hello["d"]["heartbeat_interval"] / 1000
        logger.info(f"✅ Hello 收到，心跳 {heartbeat_interval}s")

        # 2. Identify
        identify = {
            "op": 2,
            "d": {
                "token": f"QQBot {token}",
                "intents": 1 << 25,  # GROUP_AT_MESSAGE_CREATE
                "shard": [0, 1],
            },
        }
        await ws.send(json.dumps(identify))
        logger.info("Identify 已发送，等待 Ready ...")

        # 3. 等 Ready
        try:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        except asyncio.TimeoutError:
            raise RuntimeError("等 Ready 超时")

        if ready.get("op") != 0 or ready.get("t") != "READY":
            raise RuntimeError(f"未收到 READY: {ready}")

        bot_user = ready["d"].get("user", {})
        logger.success(
            f"✅ READY! Bot: {bot_user.get('username')} "
            f"(id={bot_user.get('id')})"
        )

        # 4. 等群 @ 消息
        logger.info("=" * 50)
        logger.info("👉 现在请在 QQ 群里 @ 机器人 发送任意消息")
        logger.info(f"   （脚本会运行 {timeout} 秒）")
        logger.info("=" * 50)

        async def heartbeat():
            while True:
                await asyncio.sleep(heartbeat_interval)
                try:
                    await ws.send(json.dumps({"op": 1, "d": None}))
                except Exception:
                    break

        hb_task = asyncio.create_task(heartbeat())

        try:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                ws_timeout = min(remaining, heartbeat_interval * 2)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=ws_timeout)
                    msg = json.loads(raw)
                    if msg.get("t") == "GROUP_AT_MESSAGE_CREATE":
                        d = msg["d"]
                        group_openid = d.get("group_openid")
                        content = d.get("content", "")[:50]
                        author = d.get("author", {}).get("member_openid", "?")
                        if group_openid:
                            logger.success(
                                f"✅ 捕获群消息！\n"
                                f"   group_openid = {group_openid}\n"
                                f"   content = {content}\n"
                                f"   author_openid = {author}"
                            )
                            return group_openid
                except asyncio.TimeoutError:
                    continue
        finally:
            hb_task.cancel()

        raise RuntimeError(f"{timeout} 秒内未捕获到群 @ 消息")


def main() -> int:
    load_dotenv()
    app_id = os.getenv("QQ_BOT_APPID")
    app_secret = os.getenv("QQ_BOT_APPSECRET")

    if not app_id or not app_secret:
        logger.error("请先在 .env 配置 QQ_BOT_APPID 和 QQ_BOT_APPSECRET")
        return 1

    logger.info("=== OpenClaw group_openid 发现器 ===")
    logger.info(f"AppID: {app_id}")

    try:
        group_openid = asyncio.run(discover(app_id, app_secret, timeout=60))
    except Exception as e:
        logger.error(f"失败: {e}")
        return 1

    # 自动写入 .env
    set_key(str(ENV_FILE), "QQ_TARGET_GROUP", group_openid)
    logger.success(f"✅ 已将 group_openid 写入 {ENV_FILE}")
    logger.success("现在可以跑: ./start.sh scripts/test_openclaw.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
