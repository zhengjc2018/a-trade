"""测试被动回复（在 5 分钟窗口内 @ 机器人后回复）。

无需"主动消息"权限，但需要：
1. 你在群里 @ 机器人 发送任意消息
2. 5 分钟内运行本脚本
3. 脚本会捕获 msg_id 并尝试带 msg_id 回复

用法：
    1. 在群里 @ 机器人 发一句话
    2. 立刻跑: ./start.sh scripts/test_passive_reply.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from itertools import count

import requests
import websockets
from dotenv import load_dotenv
from loguru import logger

AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"
GATEWAY_URL = "https://api.sgroup.qq.com/gateway"
WSS_URL = "wss://api.sgroup.qq.com/websocket/"
API_BASE = "https://api.sgroup.qq.com"


def get_token(app_id: str, app_secret: str) -> tuple[str, int]:
    resp = requests.post(
        AUTH_URL,
        json={"appId": app_id, "clientSecret": app_secret},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["access_token"], int(data.get("expires_in", 7200))


def send_text_with_msg_id(
    token: str,
    app_id: str,
    group_openid: str,
    msg_id: str,
    content: str,
    msg_seq: int,
) -> dict:
    """带 msg_id 的被动回复（无需主动权限）。"""
    url = f"{API_BASE}/v2/groups/{group_openid}/messages"
    headers = {
        "Authorization": f"QQBot {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "content": content,
        "msg_type": 0,
        "msg_id": msg_id,
        "msg_seq": msg_seq,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    if resp.status_code >= 400:
        logger.error(f"被动回复失败 [{resp.status_code}]: {resp.text}")
    resp.raise_for_status()
    return resp.json()


async def wait_for_group_message(
    app_id: str, app_secret: str, timeout: int = 30
) -> tuple[str, str]:
    """连 WebSocket 等群 @ 消息，返回 (group_openid, msg_id)。"""
    token, _ = get_token(app_id, app_secret)
    logger.info(f"✅ access_token OK")

    try:
        gw_resp = requests.get(
            GATEWAY_URL,
            headers={"Authorization": f"QQBot {token}"},
            timeout=5,
        )
        gw_resp.raise_for_status()
        wss_endpoint = gw_resp.json().get("url", WSS_URL)
    except Exception:
        wss_endpoint = WSS_URL

    async with websockets.connect(wss_endpoint) as ws:
        hello = json.loads(await ws.recv())
        if hello.get("op") != 10:
            raise RuntimeError(f"非 Hello: {hello}")
        heartbeat = hello["d"]["heartbeat_interval"] / 1000

        await ws.send(json.dumps({
            "op": 2,
            "d": {
                "token": f"QQBot {token}",
                "intents": 1 << 25,
                "shard": [0, 1],
            },
        }))

        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if ready.get("t") != "READY":
            raise RuntimeError(f"未收到 READY: {ready}")
        logger.success(f"✅ READY")

        logger.info(f"👉 请在群里 @ 机器人 发任意消息（{timeout}秒内）")

        async def heartbeat_loop():
            while True:
                await asyncio.sleep(heartbeat)
                try:
                    await ws.send(json.dumps({"op": 1, "d": None}))
                except Exception:
                    break

        hb = asyncio.create_task(heartbeat_loop())
        try:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5))
                    msg = json.loads(raw)
                    if msg.get("t") == "GROUP_AT_MESSAGE_CREATE":
                        d = msg["d"]
                        return d.get("group_openid"), d.get("id")
                except asyncio.TimeoutError:
                    continue
        finally:
            hb.cancel()
        raise RuntimeError("超时未捕获到群消息")


def main() -> int:
    load_dotenv()
    app_id = os.getenv("QQ_BOT_APPID")
    app_secret = os.getenv("QQ_BOT_APPSECRET")
    group = os.getenv("QQ_TARGET_GROUP")

    logger.info("=== OpenClaw 被动回复测试 ===")
    logger.info("(无需主动消息权限，5 分钟窗口内有效)")

    try:
        group_openid, msg_id = asyncio.run(wait_for_group_message(app_id, app_secret, 60))
    except Exception as e:
        logger.error(f"捕获消息失败: {e}")
        return 1

    logger.success(f"捕获到消息: group={group_openid}, msg_id={msg_id}")

    token, _ = get_token(app_id, app_secret)
    seq = next(count(1))
    try:
        result = send_text_with_msg_id(
            token, app_id, group_openid, msg_id,
            "✅ 被动回复测试成功！\n\n这条消息使用了 msg_id 模式，无需主动消息权限。",
            seq,
        )
        logger.success(f"✅ 被动回复成功: {result}")
        return 0
    except Exception as e:
        logger.error(f"被动回复失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
