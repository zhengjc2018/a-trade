"""多源股票快照（PE/PB + 价格 + 成交）。

三层 fallback：
1. push2（东财单股）：含 PE/PB，但 push2.eastmoney.com 在多数网络段被封
2. 腾讯 web.ifzq：价格 + 成交 + 市值 + 换手率（无 PE/PB）
3. datacenter（东财财报反推）：用 EPS_TTM + BVPS 算 PE/PB（无价格，需先有价格）

调用方拿到的字段：
- price / pre_close / open / pct_chg / total_mv / float_mv / turnover
- pe_ttm / pb（来自 push2 或 datacenter 推算）
- bvps / ttm_eps / total_share（来自 datacenter，便于人工核对）

流程：
1. push2 → 成功则返回（已有 PE/PB）
2. tx → 价格层（必定尝试，因为 datacenter 缺价格）
3. datacenter → 若 #2 拿到了价格，则用 BVPS/TTM_EPS 算 PE/PB

注：腾讯字段索引表（已知子集）：
- [3] 当前价， [4] 昨收， [5] 今开， [30] 时间戳
- [38] 换手率%
- [44] 总市值(亿)，[45] 流通市值(亿)
"""

from __future__ import annotations

import time
from typing import Optional

import requests
from loguru import logger

# ---------- 东财 push2 ----------
_URL_EASTMONEY = "https://push2.eastmoney.com/api/qt/stock/get"


def _to_secid_em(code: str) -> str:
    code = str(code).zfill(6)
    market = "1" if code.startswith(("5", "6", "7", "9")) else "0"
    return f"{market}.{code}"


def _fetch_eastmoney(code: str, retries: int = 1) -> Optional[dict]:
    """push2 单股接口：含 PE/PB。push2 在多数网络段被封, 快速失败。"""
    secid = _to_secid_em(code)
    params = {
        "secid": secid,
        "fields": "f43,f57,f58,f60,f84,f85,f116,f117,f167,f168,f169,f170,f171,f192",
        "invt": 2, "fltt": 1,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    for attempt in range(retries):
        try:
            r = requests.get(_URL_EASTMONEY, params=params, headers=headers,
                             timeout=5)
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
            logger.debug(f"[eastmoney] {code} 尝试 {attempt+1}/{retries}: {e}")
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
                "turnover": float(qt[38]) if qt[38] else None,
                "total_mv": float(qt[44]) * 1e8 if qt[44] else None,
                "float_mv": float(qt[45]) * 1e8 if qt[45] else None,
                "total_share": None,
                "float_share": None,
                "pe_ttm": None,
                "pb": None,
                "source": "tx",
            }
        except Exception as e:
            logger.warning(f"[tx] {code} 重试 {attempt+1}/{retries}: {e}")
            time.sleep(1 + attempt)
    return None


# ---------- 东财 datacenter ----------
_URL_DATACENTER = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


def _fetch_datacenter(code: str, retries: int = 2) -> Optional[dict]:
    """东财 datacenter 财报接口：反推 TTM EPS / BVPS / 总股本。

    拉 2 张表：
    1. RPT_F10_FINANCE_MAINFINADATA：EPSJB / TOTAL_SHARE / REPORT_TYPE
       （TOTAL_EQUITY_PK 字段虽然名字带"PK"，实际值是含少股权益的总权益）
    2. RPT_F10_FINANCE_GBALANCE：TOTAL_PARENT_EQUITY（真正归母权益）
       - 若 GBALANCE 失败（datacenter 限速），降级用 MAINFINADATA.TOTAL_EQUITY_PK

    计算：
    - BVPS = TOTAL_PARENT_EQUITY / SHARE_CAPITAL（GBALANCE 优先, fallback 含少股）
    - TTM EPS：
        * 最新一期是年报 → 直接用 EPSJB
        * 最新一期是季报且本年已发布年报 → 退化为直接用最新年报
        * 最新一期是季报且本年尚未发布年报 → TTM = 上一年年报 + 本年Q1 - 上一年Q1
    """
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://emweb.securities.eastmoney.com/",
    }

    def _get(report_name: str, columns: str, page_size: str) -> list:
        p = {
            "reportName": report_name,
            "columns": columns,
            "filter": f'(SECURITY_CODE="{code}")',
            "pageNumber": "1",
            "pageSize": page_size,
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
            "source": "HSF10",
        }
        time.sleep(0.5)  # datacenter 限速保护
        rr = requests.get(_URL_DATACENTER, params=p, headers=headers, timeout=10)
        rr.raise_for_status()
        return (rr.json().get("result") or {}).get("data") or []

    for attempt in range(retries):
        try:
            # 1. MAINFINADATA 拿 EPS / 总股本 / 报表类型
            rows = _get(
                "RPT_F10_FINANCE_MAINFINADATA",
                "SECUCODE,REPORT_DATE,REPORT_TYPE,EPSJB,TOTAL_SHARE,TOTAL_EQUITY_PK",
                "8",
            )
            if not rows:
                time.sleep(2 + attempt * 3)
                continue
            latest = rows[0]
            total_share = latest.get("TOTAL_SHARE")
            ttm_eps = _calc_ttm_eps(rows)

            # 2. GBALANCE 拿真归母权益（资产负债表）。失败则降级用
            #    MAINFINADATA.TOTAL_EQUITY_PK（含少股但至少有数据）
            bal_rows = _get(
                "RPT_F10_FINANCE_GBALANCE",
                "SECUCODE,REPORT_DATE,SHARE_CAPITAL,TOTAL_PARENT_EQUITY",
                "2",
            )
            parent_eq = None
            if bal_rows:
                parent_eq = bal_rows[0].get("TOTAL_PARENT_EQUITY")
            if parent_eq is None:
                parent_eq = latest.get("TOTAL_EQUITY_PK")  # 含少股权益 fallback
            share = total_share
            bvps = (parent_eq / share) if (parent_eq and share) else None
            return {
                "code": code,
                "name": None,
                "price": None,        # datacenter 不提供行情
                "pre_close": None,
                "open": None,
                "pct_chg": None,
                "amplitude": None,
                "vol_ratio": None,
                "turnover": None,
                "total_mv": None,
                "float_mv": None,
                "total_share": share,
                "float_share": None,
                "pe_ttm": None,        # 需要价格才能算
                "pb": None,
                "bvps": bvps,
                "ttm_eps": ttm_eps,
                "parent_equity": parent_eq,
                "source": "datacenter",
            }
        except Exception as e:
            logger.warning(f"[datacenter] {code} 重试 {attempt+1}/{retries}: {e}")
            time.sleep(2 + attempt * 3)
    return None


def _calc_ttm_eps(rows: list) -> Optional[float]:
    """根据财报 rows 算 TTM EPS。

    rows 已按 REPORT_DATE 倒序。REPORT_TYPE ∈ {一季报, 中报, 三季报, 年报}。

    公式（EPSJB 为累计 EPS）：

    - 最新年报 → 直接用年报 EPSJB（视为全年 TTM）。
    - 最新中报 / 三季报 / 一季报（无更新年报）：
      TTM = 上一年年报 EPSJB + 本期累计 EPSJB - 上一年同期累计 EPSJB
    """
    if not rows:
        return None
    latest_annual = next((r for r in rows if r.get("REPORT_TYPE") == "年报"), None)
    latest_q = next(
        (r for r in rows if r.get("REPORT_TYPE") in ("一季报", "中报", "三季报")),
        None,
    )
    if not latest_annual and not latest_q:
        return None
    if latest_annual and not latest_q:
        return latest_annual.get("EPSJB")
    if latest_q and not latest_annual:
        # 缺上一年度年报，只能用本期累计作为退化值。
        return latest_q.get("EPSJB")

    annual_year = (latest_annual.get("REPORT_DATE") or "")[:4]
    q_year = (latest_q.get("REPORT_DATE") or "")[:4]
    q_type = latest_q.get("REPORT_TYPE")
    if annual_year == q_year:
        # 同年的年报 + 季报罕见（年报刚发布，新季报还没出）。
        # 直接用最新年报 EPSJB（即全年 = TTM）。
        return latest_annual.get("EPSJB")

    # 跨年：寻找上一年同类型报表的累计 EPS
    prev_same = next(
        (r for r in rows
         if r.get("REPORT_TYPE") == q_type
         and (r.get("REPORT_DATE") or "")[:4] == annual_year),
        None,
    )
    if prev_same is not None:
        curr_eps = latest_q.get("EPSJB") or 0.0
        prev_eps = prev_same.get("EPSJB") or 0.0
        return (latest_annual["EPSJB"] or 0.0) + curr_eps - prev_eps
    # 找不到上年同期 → 退化为用最新年报 EPSJB，并记录降级
    logger.debug(
        f"[ttm_eps] 缺少上一年 {q_type} 累计 EPS，回退到最新年报 EPSJB"
    )
    return latest_annual["EPSJB"]


def _merge_pe_pb(base: dict, fin: dict) -> dict:
    """用 datacenter 的 BVPS/TTM_EPS 给 base（腾讯层）补 PE/PB。

    base 必有 price，fin 必有 bvps/ttm_eps/total_share。
    """
    if not base or not fin or not base.get("price"):
        return base
    price = base["price"]
    bvps = fin.get("bvps")
    ttm_eps = fin.get("ttm_eps")
    if ttm_eps and ttm_eps > 0:
        base["pe_ttm"] = round(price / ttm_eps, 2)
    if bvps and bvps > 0:
        base["pb"] = round(price / bvps, 2)
    if fin.get("bvps") is not None:
        base["bvps"] = fin["bvps"]
    if fin.get("ttm_eps") is not None:
        base["ttm_eps"] = fin["ttm_eps"]
    if fin.get("total_share") is not None and not base.get("total_share"):
        base["total_share"] = fin["total_share"]
    if fin.get("parent_equity") is not None:
        base["parent_equity"] = fin["parent_equity"]
    base["source"] = (base.get("source") or "") + "+datacenter"
    return base


def _safe(v, scale):
    try:
        return float(v) / scale
    except (ValueError, TypeError, ZeroDivisionError):
        return None


# ---------- 主入口 ----------
def fetch_snap(code: str,
               retries_east: int = 1,
               retries_tx: int = 2,
               retries_datacenter: int = 2) -> Optional[dict]:
    """拉一次快照。

    1. push2（东财）→ 含 PE/PB；网络封了则快速失败
    2. 腾讯 → 价格 + 成交
    3. datacenter → 用 BVPS/TTM_EPS 给 #2 补 PE/PB
    """
    snap = _fetch_eastmoney(code, retries=retries_east)
    if snap:
        return snap

    snap = _fetch_tx(code, retries=retries_tx)
    if not snap:
        return None
    logger.info(f"[snap] {code} 走腾讯层（无 PE/PB）")

    # PE/PB 缺失时用 datacenter 反推
    if snap.get("pe_ttm") is None or snap.get("pb") is None:
        fin = _fetch_datacenter(code, retries=retries_datacenter)
        if fin:
            snap = _merge_pe_pb(snap, fin)
            logger.info(f"[snap] {code} 用 datacenter 补 PE/PB")
    return snap
