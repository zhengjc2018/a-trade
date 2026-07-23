"""实时行情/名称查询（用于回填 holdings 的 name 字段）。"""

from __future__ import annotations

from typing import Optional


def lookup_quote(symbol: str) -> Optional[dict]:
    """查单只股票的实时行情（含名称）。失败返回 None。

    返回: {"symbol", "name", "price", "change_pct", "is_valid"}
    """
    try:
        from atrade.data.quotes import QuoteProvider
        provider = QuoteProvider()
        sym = str(symbol).zfill(6)
        quotes = provider.batch([sym])
        q = quotes.get(sym)
        if q is None or not q.is_valid:
            return None
        return {
            "symbol": q.symbol,
            "name": q.name,
            "price": q.price,
            "change_pct": q.change_pct,
            "is_valid": True,
        }
    except Exception:
        return None


def backfill_names(meta: dict) -> dict:
    """遍历 holdings，若 name == symbol 或为空则查一次回填。

    返回更新后的 meta（写回磁盘）。
    """
    holdings = meta.get("holdings", [])
    changed = False
    for h in holdings:
        sym = str(h.get("symbol", "")).zfill(6)
        cur_name = str(h.get("name", "")).strip()
        if cur_name and cur_name != sym:
            continue
        quote = lookup_quote(sym)
        if quote and quote.get("name"):
            h["name"] = quote["name"]
            changed = True
    if changed:
        # 写回 LOCAL_HOLDINGS
        import json
        import os

        from atrade.config import LOCAL_HOLDINGS

        LOCAL_HOLDINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = LOCAL_HOLDINGS.with_suffix(LOCAL_HOLDINGS.suffix + ".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, LOCAL_HOLDINGS)
    return meta
