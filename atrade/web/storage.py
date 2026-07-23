"""holdings.local.json 读/写（原子操作 + 进程内锁）。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_HOLDINGS_PATH: Optional[Path] = None  # 由 init_app() 注入
_lock = threading.Lock()


def init_app(path: Path) -> None:
    """在 FastAPI startup 时注入 holdings.local.json 路径。"""
    global _HOLDINGS_PATH
    _HOLDINGS_PATH = path


def _resolve_path() -> Path:
    if _HOLDINGS_PATH is None:
        from atrade.config import LOCAL_HOLDINGS
        return LOCAL_HOLDINGS
    return _HOLDINGS_PATH


def read_holdings() -> dict:
    """读 holdings 文件，返回完整 meta dict（含 disabled_symbols / watch_keywords）。"""
    from atrade.config import load_holdings_with_meta
    try:
        return load_holdings_with_meta()
    except FileNotFoundError:
        return {"holdings": [], "disabled_symbols": [], "watch_keywords": []}


def write_holdings(meta: dict) -> None:
    """原子写入：写 tmp → os.replace。"""
    with _lock:
        _write_unlocked(meta)


def _write_unlocked(meta: dict) -> None:
    path = _resolve_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(meta, ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


def update_holding(symbol: str, patch: dict) -> dict:
    """读 → 改 → 写。返回更新后的 holding。"""
    with _lock:
        meta = read_holdings()
        target_idx = None
        sym = str(symbol).zfill(6)
        for idx, h in enumerate(meta["holdings"]):
            if str(h.get("symbol", "")).zfill(6) == sym:
                target_idx = idx
                break
        if target_idx is None:
            raise KeyError(f"symbol not in holdings: {symbol}")
        meta["holdings"][target_idx].update(patch)
        meta["holdings"][target_idx]["updated_at"] = (
            datetime.now().isoformat(timespec="seconds")
        )
        _write_unlocked(meta)
        return meta["holdings"][target_idx]


_ALLOWED_FIELDS = {"cost_price", "quantity", "buy_date", "note", "enabled"}


def validate_patch(patch: dict) -> dict:
    """校验 patch 字段。返回规范化后的 dict；失败抛 ValueError。"""
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是 dict")
    if not patch:
        raise ValueError("patch 不能为空")
    out: dict = {}
    unknown = set(patch.keys()) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"patch 包含未知字段: {sorted(unknown)}")
    if "cost_price" in patch:
        cp = patch["cost_price"]
        if not isinstance(cp, (int, float)) or cp <= 0:
            raise ValueError(f"cost_price 必须 > 0，实际: {cp}")
        out["cost_price"] = float(cp)
    if "quantity" in patch:
        q = patch["quantity"]
        if isinstance(q, bool) or not isinstance(q, int) or q <= 0:
            raise ValueError(f"quantity 必须为正整数，实际: {q}")
        out["quantity"] = q
    if "buy_date" in patch:
        bd = str(patch["buy_date"])
        if bd and len(bd) > 10:
            raise ValueError(f"buy_date 格式错误: {bd}")
        out["buy_date"] = bd
    if "note" in patch:
        n = str(patch["note"])
        if len(n) > 200:
            raise ValueError(f"note 不能超过 200 字符（{len(n)}）")
        out["note"] = n
    if "enabled" in patch:
        if not isinstance(patch["enabled"], bool):
            raise ValueError("enabled 必须是 bool")
        out["enabled"] = bool(patch["enabled"])
    if not out:
        raise ValueError("patch 不能为空")
    return out
