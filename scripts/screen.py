"""盘中股票筛选器（基于东财 clist 全市场快照）。

用法:
    # 全市场快照 → 落盘为 data/cache/market_snapshot.csv
    python3 scripts/screen.py --snapshot
    # 按代码筛选（需先有快照）
    python3 scripts/screen.py --symbols 600519,000001,300750
    python3 scripts/screen.py --portfolio
    # 按价量阈值筛（需要先有快照）
    python3 scripts/screen.py --pct-chg-min -5 --pct-chg-max -1   # 当日跌 1-5%
    python3 scripts/screen.py --amount-min 5e8                       # 成交额 ≥ 5 亿

注：
- 东财接口有限频。snapshot 模式会拉 ~10 次拿全市场。
- clist 接口本身不带 PE/PB。screen 只展示价量/市值。
- 需要 PE/PB 时用 `atrade.data.eastmoney.fetch_snap(code)`：
  push2 → 腾讯价格 → datacenter 财报反推 (BVPS/TTM_EPS)。三层 fallback。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "data" / "cache"
SNAPSHOT_FILE = SNAPSHOT_DIR / "market_snapshot.csv"

CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# FS 过滤器：沪深京主板（不含科创板/北交所）
FS_BOARD = "m:1+t:2+t:23+t:1+t:0+f:!2+m:0+t:6+f:!2"

# 字段 f1=最新价 ×100 / f2=涨跌幅% / f5=成交额 / f12=code / f14=name / f20=总市值
FIELDS = "f1,f2,f3,f4,f5,f6,f9,f12,f14,f15,f20,f23"


def fetch_market_snapshot(page_size: int = 200, max_pages: int = 50) -> pd.DataFrame:
    """拉全市场沪深京主板快照，分页拉直到集齐。"""
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
            "fid": "f3",  # 按涨跌幅排序
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
                    "price": it.get("f2"),       # f2: 最新价 ×100
                    "pct_chg": it.get("f3"),     # f3: 涨跌幅%
                    "change": it.get("f4"),       # f4: 涨跌额 ×100
                    "volume": it.get("f5"),      # f5: 成交量(手)
                    "amount": it.get("f6"),      # f6: 成交额(元)
                    "amplitude": it.get("f9"),   # f9: 振幅%
                    "high": it.get("f15"),       # f15: 最高 ×100
                    "low": it.get("f16"),        # f16: 最低 ×100
                    "total_mv": it.get("f20"),   # f20: 总市值(元)
                    "pe_ttm": it.get("f23"),     # f23: 市盈率(动)
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


def load_snapshot() -> pd.DataFrame:
    if not SNAPSHOT_FILE.exists():
        logger.warning(f"snapshot 不存在: {SNAPSHOT_FILE}，请先跑 --snapshot")
        return pd.DataFrame()
    return pd.read_csv(SNAPSHOT_FILE, dtype={"code": str})


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
        price = (r.get("price") or 0) / 100  # ×100 后存
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
    parser = argparse.ArgumentParser(description="a-trade 盘中选股器")
    parser.add_argument("--snapshot", action="store_true",
                        help="拉全市场快照到本地 cache")
    parser.add_argument("--code-in", type=str,
                        help="逗号分隔股票代码列表")
    parser.add_argument("--portfolio", action="store_true",
                        help="用 config/holdings.json 里的代码")
    parser.add_argument("--pct-chg-min", type=float, default=None,
                        help="最小涨跌幅 %（如 -5 表示跌 ≤5%）")
    parser.add_argument("--pct-chg-max", type=float, default=None,
                        help="最大涨跌幅 %（如 -1 表示跌 ≥1%）")
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
        cfg = Path(__file__).resolve().parents[1] / "config" / "holdings.json"
        holdings = json.loads(cfg.read_text())["holdings"]
        symbols = [h["symbol"] for h in holdings]
        print(f"持仓代码: {symbols}")

    if symbols:
        # 即使 --code-in 也可能想用阈值（用 code-in 当作强约束，threshold 当作 weak）
        df = load_snapshot()
        if df.empty:
            return
        # 用阈值过滤 + code-in
        if args.pct_chg_min is not None or args.pct_chg_max is not None or args.amount_min is not None:
            df = filter_by_thresholds(df, args)
        else:
            df = df[df["code"].isin(symbols)]
    elif any([args.pct_chg_min, args.pct_chg_max, args.amount_min]):
        df = load_snapshot()
        if df.empty:
            return
        df = filter_by_thresholds(df, args)
    else:
        parser.print_help()
        return

    print_table(df)


if __name__ == "__main__":
    main()
