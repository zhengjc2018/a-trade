"""多源股票快照（PE/PB + 价格 + 成交）。

源 1: 东方财富 push2 /api/qt/stock/get （含 PE/PB，但反爬严重）
源 2: 腾讯 web.ifzq /appstock /fqkline/get （含价量、市值，部分字段）

策略：
1. 先试源 1（东财）。失败 → 试源 2（腾讯）
2. 两个都失败 → 返回 None
3. 字段缺失为 None 时调用方需做兼容性判断

注：腾讯字段索引表（已知子集）：
- [3] 当前价， [4] 昨收， [5] 今开， [30] 时间戳
- [38] 换手率%
- [44] 总市值(亿)，[45] 流通市值(亿)
- [46]/[47] 部分指数
"""

from __future__ import annotations

import time
from typing import Optional

import requests
from loguru import logger


# ---------- 东财 ----------
_URL_EASTMONEY = "https://push2.eastmoney.com/api/qt/stock/get"


def _to_secid_em(code: str) -> str:
    code = str(code).zfill(6)
    market = "1" if code.startswith(("5", "6", "7", "9")) else "0"
    return f"{market}.{code}"


def _fetch_eastmoney(code: str, retries: int = 3) -> Optional[dict]:
    secid = _to_secid_em(code)
    params = {
        "secid": secid,
        "fields": "f43,f57,f58,f60,f84,f85,f116,f117,f167,f168,f169,f170,f171,f192",
        "invt": 2, "fltt": 1,
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    for attempt in range(retries):
        try:
            r = requests.get(_URL_EASTMONEY, params=params, headers=headers,
                             timeout=10)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            if not data or not data.get("f57"):
                return None
            return {
                "code": str(data["f57"]).zfill(6),
                "name": data.get("f58"),
                "price": _safe(data["f43"], 100) if data.get("f43") else None,
                "pre_close": _safe(data["f60"], 100) if data.get("f60") else None,
                "open": _safe(data["f169"], 100) if data.get("f169") is not None else None,
                "pct_chg": data.get("f170"),
                "amplitude": data.get("f171"),
                "vol_ratio": data.get("f192"),
                "pe_ttm": data.get("f167"),
                "pb": data.get("f168"),
                "total_mv": data.get("f116"),       # 万元
                "float_mv": data.get("f117"),       # 万元
                "total_share": data.get("f84"),
                "float_share": data.get("f85"),
                "source": "eastmoney",
            }
        except Exception as e:
            logger.warning(f"[eastmoney] {code} 重试 {attempt+1}/{retries}: {e}")
            time.sleep(1 + attempt * 2)
    return None


# ---------- 腾讯 ----------
_URL_TX = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _to_tx_market(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("5", "6", "7", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_tx(code: str, retries: int = 2) -> Optional[dict]:
    """腾讯 ifzq 接口：返回 88 个字段。"""
    mk = _to_tx_market(code)
    url = f"{_URL_TX}?param={mk},day,,,1,qfq"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.qq.com/",
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            d = r.json()
            qt = d.get("data", {}).get(mk, {}).get("qt", {}).get(mk)
            if not qt or len(qt) < 45:
                return None
            return {
                "code": code,
                "name": qt[1],
                "price": float(qt[3]) if qt[3] else None,
                "pre_close": float(qt[4]) if qt[4] else None,
                "open": float(qt[5]) if qt[5] else None,
                "pct_chg": None,
                "amplitude": None,
                "vol_ratio": None,
                # 换手率%
                "turnover": float(qt[38]) if qt[38] else None,
                # 总市值/流通市值（亿）
                "total_mv": float(qt[44]) * 1e8 if qt[44] else None,  # 亿 → 元
                "float_mv": float(qt[45]) * 1e8 if qt[45] else None,
                "total_share": None,
                "float_share": None,
                # PE/PB 字段不可靠（[46]/[47] 不一定），标 None
                "pe_ttm": None,
                "pb": None,
                "source": "tx",
            }
        except Exception as e:
            logger.warning(f"[tx] {code} 重试 {attempt+1}/{retries}: {e}")
            time.sleep(1 + attempt)
    return None


def _safe(v, scale):
    try:
        return float(v) / scale
    except (ValueError, TypeError, ZeroDivisionError):
        return None


# ---------- 主入口 ----------
def fetch_snap(code: str, retries_east: int = 3, retries_tx: int = 2) -> Optional[dict]:
    """拉一次快照，源 1（东财，含 PE/PB） → 源 2（腾讯，价格/换手率）→ None。"""
    snap = _fetch_eastmoney(code, retries=retries_east)
    if snap:
        return snap
    snap = _fetch_tx(code, retries=retries_tx)
    if snap:
        logger.info(f"[snap] {code} fallback 到腾讯")
        return snap
    return None
