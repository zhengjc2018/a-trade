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
