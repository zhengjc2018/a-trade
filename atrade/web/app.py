"""a-trade 持仓配置 Web 接口。

监听 0.0.0.0:8765，提供：
- GET /api/health
- GET /api/holdings
- PUT /api/holdings/{symbol}
- POST /api/reload
- GET /            单页 HTML UI
- GET /static/*    静态资源

可选 Bearer Token：环境变量 A_TRADE_WEB_TOKEN 非空时启用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import storage
from .reload_client import request_reload

logger = logging.getLogger("atrade.web")

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

app = FastAPI(title="a-trade web admin", version="0.1.0")


def _get_token() -> str | None:
    tok = os.getenv("A_TRADE_WEB_TOKEN", "").strip()
    return tok or None


def require_bearer(request: Request) -> None:
    """如果启用了 token，校验 Authorization。"""
    expected = _get_token()
    if expected is None:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth[len("Bearer "):].strip()
    if token != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bearer token")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "auth_enabled": _get_token() is not None}


@app.get("/api/holdings", dependencies=[Depends(require_bearer)])
def get_holdings() -> list[dict]:
    meta = storage.read_holdings()
    disabled = set(meta.get("disabled_symbols") or [])
    out = []
    for h in meta.get("holdings", []):
        h2 = dict(h)
        h2["enabled"] = h2.get("symbol") not in disabled
        out.append(h2)
    return out


@app.post("/api/holdings", dependencies=[Depends(require_bearer)], status_code=status.HTTP_201_CREATED)
def post_holding(holding: dict) -> dict:
    """新增一只持仓。Body: {symbol, name, cost_price, quantity, buy_date?, note?}

    若 name 缺失或等于 symbol，自动从实时行情查名。
    """
    sym = str(holding.get("symbol", "")).zfill(6)
    provided_name = str(holding.get("name", "")).strip()
    if not provided_name or provided_name == sym:
        from .quote_lookup import lookup_quote
        q = lookup_quote(sym)
        if q and q.get("name"):
            holding["name"] = q["name"]
    try:
        validated = storage.create_holding(holding)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return validated


@app.delete("/api/holdings/{symbol}", dependencies=[Depends(require_bearer)])
def delete_holding(symbol: str) -> dict:
    """删除指定持仓。"""
    try:
        removed = storage.delete_holding(symbol)
    except KeyError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"symbol not found: {symbol}"
        ) from None
    return {"deleted": removed}


@app.put("/api/holdings/{symbol}", dependencies=[Depends(require_bearer)])
def put_holding(symbol: str, patch: dict) -> dict:
    try:
        validated = storage.validate_patch(patch)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    sym = str(symbol).zfill(6)

    # enabled 单独走 disabled_symbols 列表
    enabled_flag = validated.pop("enabled", None)
    if enabled_flag is not None:
        meta = storage.read_holdings()
        disabled = set(meta.get("disabled_symbols") or [])
        if enabled_flag:
            disabled.discard(sym)
        else:
            disabled.add(sym)
        meta["disabled_symbols"] = sorted(disabled)
        storage.write_holdings(meta)

    if validated:
        try:
            updated = storage.update_holding(sym, validated)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"symbol not found: {sym}") from None
    else:
        # 仅切 enabled
        meta = storage.read_holdings()
        target = next(
            (h for h in meta.get("holdings", [])
             if str(h.get("symbol", "")).zfill(6) == sym),
            None,
        )
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"symbol not found: {sym}") from None
        updated = target

    return updated


@app.get("/api/quote/{symbol}", dependencies=[Depends(require_bearer)])
def get_quote(symbol: str) -> dict:
    """实时查询某只股票的行情（用于 UI 自动回填名称）。"""
    from .quote_lookup import lookup_quote
    quote = lookup_quote(symbol)
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"无法获取 {symbol} 行情")
    return quote


@app.post("/api/holdings/backfill-names", dependencies=[Depends(require_bearer)])
def post_backfill_names() -> dict:
    """扫描所有 holdings，缺失的 name 自动从行情查询回填。"""
    from .quote_lookup import backfill_names
    meta = storage.read_holdings()
    updated = backfill_names(meta)
    return {
        "updated": len(updated.get("holdings", [])),
        "holdings": updated.get("holdings", []),
    }


@app.get("/api/t-trades", dependencies=[Depends(require_bearer)])
def get_t_trades(limit: int = 20) -> list[dict]:
    """最近的 T-trade 记录（默认 20 条）。"""
    from atrade.monitor.t_executor import load_trades
    trades = load_trades()
    return trades[-limit:][::-1]  # 最新的在前


@app.post("/api/reload", dependencies=[Depends(require_bearer)])
def post_reload() -> dict:
    try:
        result = request_reload()
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"scheduler socket unavailable: {e}",
        ) from e
    except RuntimeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return result


@app.get("/")
def root() -> FileResponse:
    if not _INDEX_HTML.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "index.html not built")
    return FileResponse(_INDEX_HTML, media_type="text/html")


if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
