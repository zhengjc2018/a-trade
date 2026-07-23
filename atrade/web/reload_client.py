"""通过 Unix socket 通知 a-trade scheduler 重读配置。

web 进程作为客户端；scheduler 是 socket 服务端（见 atrade.scheduler.runner）。
"""

from __future__ import annotations

import ast
import os
import socket

_RELOAD_SOCK_ENV = "A_TRADE_RELOAD_SOCK"


def _socket_path() -> str:
    return os.getenv(_RELOAD_SOCK_ENV, "/var/run/a-trade-reload.sock")


def request_reload(timeout: float = 5.0) -> dict:
    """连接 scheduler 的 reload socket，发送 reload 命令，解析响应。

    成功响应：`OK {<dict>}` → 返回解析后的 dict
    失败响应：`ERR ...` → 抛 RuntimeError
    socket 不可用：抛 ConnectionRefusedError / FileNotFoundError
    """
    path = _socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall(b"reload\n")
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        resp = b"".join(chunks).decode("utf-8", errors="ignore").strip()
    if resp.startswith("OK "):
        payload = resp[3:].strip()
        if payload.startswith(("{", "[")):
            try:
                return ast.literal_eval(payload)
            except (ValueError, SyntaxError):
                return {"raw": payload}
        return {"raw": payload}
    if resp.startswith("ERR"):
        raise RuntimeError(f"scheduler reload failed: {resp}")
    raise RuntimeError(f"unexpected response: {resp!r}")
