"""OpenClaw / QQ 官方机器人推送模块。

通过 QQ 官方开放平台 REST API 发送消息到指定群。
- AppID + AppSecret -> 自动换取 access_token（约 2 小时有效，本地缓存）
- 群聊 / 私聊统一接口
- 支持 text / markdown 两种消息类型
- 自动 msg_seq 自增（0-65535）

协议参考: https://bot.q.qq.com/wiki
实现参考: https://github.com/qingfeng66640/qqbot_adapter
"""

from __future__ import annotations

import os
import threading
import time
from itertools import count
from typing import Optional

import requests
from dotenv import load_dotenv
from loguru import logger

# QQ 官方机器人 API 域名（OpenClaw 也走这套）
AUTH_URL = "https://bots.qq.com/app/getAppAccessToken"
API_BASE = "https://api.sgroup.qq.com"

# 消息类型常量
MSG_TYPE_TEXT = 0
MSG_TYPE_MARKDOWN = 2
MSG_TYPE_MEDIA = 7

MSG_SEQ_MAX = 65536


class OpenClawNotifier:
    """QQ 官方机器人（OpenClaw 兼容）推送器。

    注意：群 ID 必须是 group_openid（不是数字群号）。
    通过 scripts/discover_group_openid.py 可自动发现。
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        bot_qq: Optional[str] = None,
        target_group: Optional[str] = None,
        timeout: float = 10.0,
    ):
        load_dotenv()
        self.app_id = app_id or os.getenv("QQ_BOT_APPID")
        self.app_secret = app_secret or os.getenv("QQ_BOT_APPSECRET")
        self.bot_qq = bot_qq or os.getenv("QQ_BOT_QQ")
        self.target_group = target_group or os.getenv("QQ_TARGET_GROUP")
        self.timeout = timeout

        self._token: Optional[str] = None
        self._token_expire_at: float = 0.0
        self._token_lock = threading.Lock()

        # msg_seq 自增计数器
        self._seq_counter = count(1)

        self._validate_config()

    def _validate_config(self):
        missing = [
            name
            for name, val in [
                ("QQ_BOT_APPID", self.app_id),
                ("QQ_BOT_APPSECRET", self.app_secret),
                ("QQ_BOT_QQ", self.bot_qq),
                ("QQ_TARGET_GROUP", self.target_group),
            ]
            if not val or val.startswith("your_")
        ]
        if missing:
            raise ValueError(
                f"配置缺失或不正确: {missing}，请检查 .env 文件"
            )

    def _next_msg_seq(self) -> int:
        return next(self._seq_counter) % MSG_SEQ_MAX

    def _get_access_token(self) -> str:
        """获取 access_token，临近过期自动刷新。"""
        with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expire_at - 60:
                return self._token

            payload = {
                "appId": self.app_id,
                "clientSecret": self.app_secret,
            }
            resp = requests.post(
                AUTH_URL, json=payload, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()

            if "access_token" not in data:
                logger.error(f"获取 access_token 失败: {data}")
                raise RuntimeError(f"鉴权失败: {data}")

            self._token = data["access_token"]
            self._token_expire_at = now + int(data.get("expires_in", 7200))
            logger.info(
                f"OpenClaw access_token 获取成功，"
                f"有效期 {int(self._token_expire_at - now)} 秒"
            )
            return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"QQBot {self._get_access_token()}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: dict) -> dict:
        url = f"{API_BASE}/v2/groups/{self.target_group}/messages"
        resp = requests.post(
            url, json=payload, headers=self._headers(), timeout=self.timeout
        )
        if resp.status_code >= 400:
            logger.error(
                f"OpenClaw 推送失败 [{resp.status_code}]: {resp.text}"
            )
        resp.raise_for_status()
        return resp.json()

    def send_text(self, content: str) -> dict:
        """发送纯文本消息。"""
        payload = {
            "content": content,
            "msg_type": MSG_TYPE_TEXT,
            "msg_seq": self._next_msg_seq(),
        }
        logger.info(
            f"OpenClaw 发送文本 -> 群 {self.target_group}, "
            f"len={len(content)}"
        )
        return self._post(payload)

    def send_markdown(self, markdown: str) -> dict:
        """发送 Markdown 富文本（需机器人开启 Markdown 权限）。"""
        payload = {
            "msg_type": MSG_TYPE_MARKDOWN,
            "markdown": {"content": markdown},
            "msg_seq": self._next_msg_seq(),
        }
        try:
            logger.info(
                f"OpenClaw 发送 Markdown -> 群 {self.target_group}, "
                f"len={len(markdown)}"
            )
            return self._post(payload)
        except requests.HTTPError as e:
            logger.warning(f"Markdown 失败，降级为纯文本: {e}")
            return self.send_text(markdown)
