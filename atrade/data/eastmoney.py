"""东财 push2 当日快照。

调用：fetch_snap("600519") → dict 或 None（失败降级）
"""

from __future__ import annotations

import time
from typing import Optional

import requests
from loguru import logger


_URL = "https://push2.eastmoney.com/api/qt/stock/get"


def _to_secid(code: str) -> str:
    code = str(code).zfill(6)
    market = "1" if code.startswith(("5", "6", "7", "9")) else "0"
    return f"{market}.{code}"


def fetch_snap(code: str, retries: int = 3) -> Optional[dict]:
    """拉一次当日快照，字段映射见代码块。失败/无响应返回 None。"""
    secid = _to_secid(code)
    params = {
        "secid": secid,
        # f43=今收/100  f44=高  f57=code  f58=name  f60=昨收/100  f84=总股本
        # f85=流通股本  f116=总市值(万)  f117=流通市值(万)  f167=PE_TTM
        # f168=PB  f169=今开/100  f170=涨幅%  f171=振幅%  f192=量比
        "fields": "f43,f57,f58,f60,f84,f85,f116,f117,f167,f168,f169,f170,f171,f192",
        "invt": 2,
        "fltt": 1,
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    for attempt in range(retries):
        try:
            r = requests.get(_URL, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            if not data or not data.get("f57"):
                logger.warning(f"[eastmoney] {code} 空响应")
                return None
            return {
                "code": str(data["f57"]).zfill(6),
                "name": data.get("f58"),
                "price": data["f43"] / 100 if data.get("f43") else None,
                "pre_close": data["f60"] / 100 if data.get("f60") else None,
                "open": data.get("f169", 0) / 100 if data.get("f169") is not None else None,
                "pct_chg": data.get("f170"),
                "amplitude": data.get("f171"),
                "vol_ratio": data.get("f192"),
                "pe_ttm": data.get("f167"),
                "pb": data.get("f168"),
                "total_mv": data.get("f116"),
                "float_mv": data.get("f117"),
                "total_share": data.get("f84"),
                "float_share": data.get("f85"),
            }
        except Exception as e:
            logger.warning(f"[eastmoney] {code} 重试 {attempt+1}/{retries}: {e}")
            time.sleep(1 + attempt * 2)
    return None
