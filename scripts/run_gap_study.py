"""首板次日高开研究 CLI。

用法:
    python3 scripts/run_gap_study.py
    python3 scripts/run_gap_study.py --days 365 --min-samples 30 --min-gap 1.0
    python3 scripts/run_gap_study.py --max-symbols 50 --out /tmp/gap_study.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import akshare as ak

from atrade.data import HistoryProvider
from atrade.monitor import TradingCalendar
from atrade.research.limit_up_gap import ztpool
from atrade.research.limit_up_gap.industry import industry_of
from atrade.research.limit_up_gap.next_gap_study import (
    NextGapConfig,
    render_next_gap_report,
    run_next_gap_study,
)
from atrade.research.limit_up_gap.qualifiers import (
    fundamentals_ok,
    industry_allowed,
    is_main_board,
    is_st_name,
    price_ok,
)
from atrade.research.limit_up_gap.report import render_report
from atrade.research.limit_up_gap.study import StudyConfig, run_study

MAIN_BOARD_PREFIXES = ("000", "001", "002", "600", "601", "603", "605")


def _codes() -> list[str]:
    df = ak.stock_info_a_code_name()
    out: list[str] = []
    for code, name in zip(df["code"], df["name"]):
        code = str(code).zfill(6)
        upper_name = str(name).upper()
        if (
            code.startswith(MAIN_BOARD_PREFIXES)
            and "ST" not in upper_name
            and "退" not in upper_name
        ):
            out.append(code)
    return out


def _allowed_codes():
    """用当前快照过滤出基本面/行业/价格合格的代码集（研究用静态代理）。"""
    from scripts.screen import fetch_market_snapshot, load_snapshot

    try:
        fetch_market_snapshot()
        df = load_snapshot()
    except Exception as e:
        print(f"⚠️ 全市场快照拉取失败，本次研究跳过基本面过滤: {e}")
        return None
    if df is None or df.empty:
        print("⚠️ 全市场快照为空，本次研究跳过基本面过滤")
        return None
    allowed: set[str] = set()
    for _, row in df.iterrows():
        code = str(row.get("code", "")).zfill(6)
        name = str(row.get("name", ""))
        if not is_main_board(code) or is_st_name(name):
            continue
        if not price_ok(row.get("price")):
            continue
        if not fundamentals_ok(row.get("pe_ttm"), row.get("pb")):
            continue
        if not industry_allowed(industry_of(code)):
            continue
        allowed.add(code)
    return allowed


def main() -> None:
    parser = argparse.ArgumentParser(description="首板次日高开研究")
    parser.add_argument("--days", type=int, default=365, help="研究天数，默认 365")
    parser.add_argument("--min-samples", type=int, default=30, help="分桶最小样本数")
    parser.add_argument("--min-gap", type=float, default=1.0, help="高开算胜的最小百分比")
    parser.add_argument("--top-pct", type=float, default=0.2, help="多因子 Top 比例")
    parser.add_argument("--max-symbols", type=int, default=0, help="只跑前 N 只（0=全部）")
    parser.add_argument(
        "--mode",
        type=str,
        default="all_next_gap",
        choices=["first_board_next_gap", "first_board_predecessor", "all_next_gap"],
        help="研究口径",
    )
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=0,
        help="拉取日线条数，默认 days+150",
    )
    parser.add_argument(
        "--with-zt-pool",
        action="store_true",
        help="启用东财涨停池历史增强",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / f"gap_study_{datetime.now().strftime('%Y%m%d')}.md",
    )
    args = parser.parse_args()

    codes = _codes()
    print(f"股票池: {len(codes)} 只")
    lookback_bars = args.lookback_bars or args.days + 150
    if args.mode == "first_board_next_gap":
        config = StudyConfig(
            min_gap_pct=args.min_gap,
            min_samples=args.min_samples,
            top_pct=args.top_pct,
            max_symbols=args.max_symbols,
            lookback_bars=lookback_bars,
            with_zt_pool=args.with_zt_pool,
        )
        zt_enrich = ztpool.enrich_samples if args.with_zt_pool else None
        result = run_study(
            codes,
            HistoryProvider(),
            industry_of,
            config,
            zt_enrich=zt_enrich,
            is_trade_day=TradingCalendar().is_trade_day,
        )
        markdown = render_report(result)
    else:
        config = NextGapConfig(
            mode=args.mode,
            min_gap_pct=args.min_gap,
            min_samples=args.min_samples,
            top_pct=args.top_pct,
            max_symbols=args.max_symbols,
            lookback_bars=lookback_bars,
            allowed_codes=_allowed_codes(),
        )
        result = run_next_gap_study(codes, HistoryProvider(), industry_of, config)
        markdown = render_next_gap_report(result)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")
    print(f"报告已写入: {args.out}")


if __name__ == "__main__":
    main()
