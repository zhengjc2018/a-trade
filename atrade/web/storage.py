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


def create_holding(holding: dict) -> dict:
    """新增一只持仓。holding 必须含 symbol/cost_price/quantity。

    返回：归一化后的 holding dict（含 updated_at）。
    抛 ValueError：symbol 已存在 / 字段非法。
    """
    validated = validate_holding(holding)
    sym = validated["symbol"]
    with _lock:
        meta = read_holdings()
        existing = {str(h.get("symbol", "")).zfill(6) for h in meta["holdings"]}
        if sym in existing:
            raise ValueError(f"symbol 已存在: {sym}")
        validated["updated_at"] = datetime.now().isoformat(timespec="seconds")
        meta["holdings"].append(validated)
        _write_unlocked(meta)
        return validated


def delete_holding(symbol: str) -> str:
    """删除指定持仓（同时从 disabled_symbols 中移除）。"""
    sym = str(symbol).zfill(6)
    with _lock:
        meta = read_holdings()
        before = len(meta["holdings"])
        meta["holdings"] = [
            h for h in meta["holdings"]
            if str(h.get("symbol", "")).zfill(6) != sym
        ]
        if len(meta["holdings"]) == before:
            raise KeyError(f"symbol not in holdings: {symbol}")
        disabled = {str(s).zfill(6) for s in meta.get("disabled_symbols") or []}
        disabled.discard(sym)
        meta["disabled_symbols"] = sorted(disabled)
        _write_unlocked(meta)
        return sym


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


_HOLDING_REQUIRED_FIELDS = {"symbol", "name", "cost_price", "quantity"}


def validate_holding(holding: dict) -> dict:
    """校验新增持仓的字段，返回归一化 dict。"""
    if not isinstance(holding, dict):
        raise ValueError("holding 必须是 dict")
    missing = _HOLDING_REQUIRED_FIELDS - set(holding.keys())
    if missing:
        raise ValueError(f"holding 缺少必需字段: {sorted(missing)}")
    sym = str(holding["symbol"]).zfill(6)
    import re as _re
    if not _re.match(r"^\d{6}$", sym):
        raise ValueError(f"symbol 必须是 6 位数字: {holding['symbol']!r}")
    cost = holding["cost_price"]
    if not isinstance(cost, (int, float)) or cost <= 0:
        raise ValueError(f"cost_price 必须 > 0: {cost!r}")
    qty = holding["quantity"]
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise ValueError(f"quantity 必须为正整数: {qty!r}")
    note = str(holding.get("note", ""))
    if len(note) > 200:
        raise ValueError("note 不能超过 200 字符")
    buy_date = str(holding.get("buy_date", ""))
    if buy_date and len(buy_date) > 10:
        raise ValueError(f"buy_date 格式错误: {buy_date!r}")
    return {
        "symbol": sym,
        "name": str(holding["name"]),
        "cost_price": float(cost),
        "quantity": qty,
        "buy_date": buy_date,
        "note": note,
    }


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
