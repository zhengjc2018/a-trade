"""盘中股票筛选器（基于东财 clist 全市场快照）。

东财全市场快照字段契约（fltt=2，invt=2 实测核对）：
- f2  最新价（实际价格，未乘 100）
- f3  涨跌幅（百分比，例如 -2.5）
- f4  涨跌额（实际金额）
- f5  成交量（手，1 手 = 100 股）
- f6  成交额（元）
- f7  振幅（百分比）
- f8  换手率（百分比）
- f9  动态市盈率
- f10 量比
- f12 股票代码
- f14 股票名称
- f15 最高价（实际价格）
- f16 最低价（实际价格）
- f20 总市值（元）
- f23 市净率

用法:
    python3 scripts/screen.py --snapshot
    python3 scripts/screen.py --symbols 600519,000001,300750
    python3 scripts/screen.py --portfolio
    python3 scripts/screen.py --pct-chg-min -5 --pct-chg-max -1
    python3 scripts/screen.py --amount-min 5e8
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data import HistoryProvider, fetch_snap
from atrade.indicators import add_all_indicators


SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
SNAPSHOT_FILE = SNAPSHOT_DIR / "market_snapshot.csv"

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

FS_BOARD = "m:1+t:2+t:23+t:1+t:0+f:!2+m:0+t:6+f:!2"
MAIN_BOARD_PREFIXES = ("000", "001", "002", "600", "601", "603", "605")
EXCLUDED_INDUSTRIES = {"房地产", "白酒", "教育", "医疗", "医药", "证券", "银行"}
MAX_PRICE = 80.0
MAX_PE_TTM = 35.0
MAX_PB = 5.0

# 字段契约：f2=最新价 / f3=涨跌幅% / f6=成交额 / f7=振幅% / f9=市盈率(动) /
#         f10=量比 / f12=code / f14=name / f15=最高 / f16=最低 /
#         f20=总市值 / f23=市净率
FIELDS = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f20,f23"


def fetch_market_snapshot(page_size: int = 200, max_pages: int = 50) -> pd.DataFrame:
    """拉全市场沪深京主板快照，分页拉直到集齐。

    所有价格 / 成交额 / 市值字段均为实际数值（人民币元），不需要再乘除 100。
    """
    headers = {
        "User-Agent": "Mozilla/5.0 Chrome/120.0",
        "Accept": "*/*",
        "Referer": "https://quote.eastmoney.com/",
    }
    all_rows = []
    for page in range(1, max_pages + 1):
        params = {
            "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fid": "f3",
            "fs": FS_BOARD,
            "fields": FIELDS,
            "_": "1",
        }
        try:
            r = requests.get(CLIST_URL, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            d = r.json()
            diff = d.get("data", {}).get("diff") or []
            if not diff:
                logger.info(f"第 {page} 页空，停止")
                break
            for it in diff:
                row = {
                    "code": str(it.get("f12", "")).zfill(6),
                    "name": it.get("f14"),
                    "price": _to_float(it.get("f2")),
                    "pct_chg": _to_float(it.get("f3")),
                    "change": _to_float(it.get("f4")),
                    "volume_lots": _to_float(it.get("f5")),
                    "amount": _to_float(it.get("f6")),
                    "amplitude": _to_float(it.get("f7")),
                    "turnover": _to_float(it.get("f8")),
                    "pe_ttm": _to_float(it.get("f9")),
                    "vol_ratio": _to_float(it.get("f10")),
                    "high": _to_float(it.get("f15")),
                    "low": _to_float(it.get("f16")),
                    "total_mv": _to_float(it.get("f20")),
                    "pb": _to_float(it.get("f23")),
                }
                if row["code"]:
                    all_rows.append(row)
            logger.info(f"第 {page} 页: {len(diff)} 行")
            if len(diff) < page_size:
                break
        except Exception as e:
            logger.warning(f"第 {page} 页失败: {e}")
            time.sleep(2)
            continue
        time.sleep(0.3)
    df = pd.DataFrame(all_rows)
    if not df.empty:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(SNAPSHOT_FILE, index=False)
        logger.info(f"snapshot 落盘: {SNAPSHOT_FILE} ({len(df)} 行)")
    return df


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None
    except Exception:
        pass
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def load_snapshot() -> pd.DataFrame:
    if not SNAPSHOT_FILE.exists():
        logger.warning(f"snapshot 不存在: {SNAPSHOT_FILE}，请先跑 --snapshot")
        return pd.DataFrame()
    return pd.read_csv(SNAPSHOT_FILE, dtype={"code": str})


def is_main_board_code(code: str) -> bool:
    code = str(code).zfill(6)
    return code.startswith(MAIN_BOARD_PREFIXES)


def is_st_name(name: str) -> bool:
    if not name:
        return False
    upper = str(name).upper()
    return upper.startswith("ST") or upper.startswith("*ST") or "退" in upper


def _industry_blocked_keywords() -> set[str]:
    return EXCLUDED_INDUSTRIES


@lru_cache(maxsize=2048)
def _industry_cache_get(code: str) -> Optional[str]:
    """通过腾讯行业接口查行业分类；失败返回 None。"""
    try:
        mk = "sh" + code if code.startswith(("5", "6", "7", "9")) else "sz" + code
        url = f"https://web.ifzq.gtimg.cn/appstock/app/MarketLayout?code={mk}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        d = r.json()
        info = d.get("data", {}).get(mk, {})
        return info.get("industry") or info.get("hyName") or None
    except Exception:
        return None


def is_excluded_industry(code: str) -> bool:
    """是否属于排除行业（粗筛）。"""
    industry = _industry_cache_get(code)
    if not industry:
        return False
    return any(k in industry for k in _industry_blocked_keywords())


def fetch_fundamental_snapshot(code: str) -> dict:
    """通过东财 push2 拿单股的 PE / PB / 流通市值等基本面字段。"""
    try:
        return fetch_snap(code) or {}
    except Exception:
        return {}


def has_good_fundamentals(code: str, snap_row: pd.Series) -> bool:
    """粗筛：PE / PB / 排除行业。"""
    pe = _to_float(snap_row.get("pe_ttm"))
    pb = _to_float(snap_row.get("pb"))
    if pe is not None and pe > MAX_PE_TTM:
        return False
    if pb is not None and pb > MAX_PB:
        return False
    if is_excluded_industry(code):
        return False
    return True


def close_above_ma5(code: str, current_price: float, history: Optional[HistoryProvider] = None) -> bool:
    """当前价站上 5 日均线（粗筛）。"""
    try:
        hp = history or HistoryProvider()
        df = hp.fetch_with_cache(code, scale="1d", datalen=30, use_snapshot=False)
        if df.empty or len(df) < 5 or "MA5" not in df.columns:
            return False
        hist = add_all_indicators(df)
        if hist.empty:
            return False
        ma5 = hist["MA5"].iloc[-1]
        if pd.isna(ma5):
            return False
        return float(current_price) > float(ma5)
    except Exception as e:
        logger.debug(f"{code} MA5 判断失败: {e}")
        return False


def apply_quality_filters(
    df: pd.DataFrame,
    history: Optional[HistoryProvider] = None,
) -> pd.DataFrame:
    """按个股质量条件筛选。"""
    if df.empty:
        return df

    hp = history or HistoryProvider()
    rows = []
    for _, row in df.iterrows():
        code = str(row.get("code", "")).zfill(6)
        if not is_main_board_code(code):
            continue
        if is_st_name(str(row.get("name", ""))):
            continue
        price = _to_float(row.get("price"))
        if price is None:
            continue
        if price > MAX_PRICE:
            continue
        if is_excluded_industry(code):
            continue
        if not has_good_fundamentals(code, row):
            continue
        if not close_above_ma5(code, price, hp):
            continue
        rows.append(row)

    if not rows:
        return df.iloc[0:0].copy()
    return pd.DataFrame(rows).reset_index(drop=True)


def filter_by_thresholds(df: pd.DataFrame, args) -> pd.DataFrame:
    out = df.copy()
    if args.pct_chg_min is not None:
        out = out[out["pct_chg"] >= args.pct_chg_min]
    if args.pct_chg_max is not None:
        out = out[out["pct_chg"] <= args.pct_chg_max]
    if args.amount_min is not None:
        out = out[out["amount"] >= args.amount_min]
    if args.code_in:
        codes = [c.strip() for c in args.code_in.split(",")]
        out = out[out["code"].isin(codes)]
    return out


def filter_screen_candidates(df: pd.DataFrame, args, history: Optional[HistoryProvider] = None) -> pd.DataFrame:
    """先做阈值筛，再做质量筛。"""
    out = filter_by_thresholds(df, args)
    out = apply_quality_filters(out, history=history)
    return out


def print_table(df: pd.DataFrame, max_rows: int = 50):
    if df.empty:
        print("(无数据)")
        return
    print("\n" + "=" * 110)
    print(f"{'代码':<8}{'名称':<14}{'现价':>10}{'涨幅%':>8}{'振幅%':>8}"
          f"{'成交额(亿)':>14}{'总市值(亿)':>14}{'PE_TTM':>12}")
    print("-" * 110)
    for _, r in df.head(max_rows).iterrows():
        amount_yi = (r.get("amount") or 0) / 1e8
        mv_yi = (r.get("total_mv") or 0) / 1e8
        price = r.get("price") or 0.0
        print(f"{r['code']:<8}{r['name'][:12]:<14}{price:>10.2f}"
              f"{(r.get('pct_chg') or 0):>8.2f}"
              f"{(r.get('amplitude') or 0):>8.2f}"
              f"{amount_yi:>14.2f}"
              f"{mv_yi:>14.2f}"
              f"{(r.get('pe_ttm') or 0):>12.2f}")
    print("=" * 110)
    if len(df) > max_rows:
        print(f"（共 {len(df)} 行，只显示前 {max_rows}）\n")


def main():
    parser = argparse.ArgumentParser(
        description="a-trade 盘中选股器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python3 scripts/screen.py --snapshot\n"
            "  python3 scripts/screen.py --portfolio\n"
            "  python3 scripts/screen.py --pct-chg-min -5 --pct-chg-max -1\n"
            "  python3 scripts/screen.py --amount-min 500000000\n"
        ),
    )
    parser.add_argument("--snapshot", action="store_true",
                        help="拉全市场快照到本地 cache")
    parser.add_argument("--code-in", type=str,
                        help="逗号分隔股票代码列表")
    parser.add_argument("--portfolio", action="store_true",
                        help="用 config/holdings.local.json 里的代码")
    parser.add_argument("--pct-chg-min", type=float, default=None,
                        help="最小涨跌幅（百分比，如 -5 表示跌 5%%）")
    parser.add_argument("--pct-chg-max", type=float, default=None,
                        help="最大涨跌幅（百分比，如 -1 表示跌 1%%）")
    parser.add_argument("--amount-min", type=float, default=None,
                        help="最小成交额（元）")
    args = parser.parse_args()

    if args.snapshot:
        fetch_market_snapshot()
        return

    symbols = []
    if args.code_in:
        symbols = [s.strip() for s in args.code_in.split(",")]
    elif args.portfolio:
        from atrade.config import load_holdings
        holdings = load_holdings()
        symbols = [h.get("symbol") for h in holdings if h.get("symbol")]
        print(f"持仓代码: {symbols}")

    if symbols:
        df = load_snapshot()
        if df.empty:
            return
        if args.pct_chg_min is not None or args.pct_chg_max is not None or args.amount_min is not None:
            df = filter_screen_candidates(df, args)
        else:
            df = df[df["code"].isin(symbols)]
            df = apply_quality_filters(df)
    elif any([args.pct_chg_min, args.pct_chg_max, args.amount_min]):
        df = load_snapshot()
        if df.empty:
            return
        df = filter_screen_candidates(df, args)
    else:
        parser.print_help()
        return

    print_table(df)


if __name__ == "__main__":
    main()
