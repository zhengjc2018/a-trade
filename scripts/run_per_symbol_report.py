"""按需生成个股做 T 策略报告。

用法:
    python3 scripts/run_per_symbol_report.py --portfolio
    python3 scripts/run_per_symbol_report.py --symbol 600522 --cost 12.5 --qty 2000
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data import HistoryProvider
from atrade.per_symbol.adaptive import compute_adaptive
from atrade.per_symbol.report import build_report, render_markdown
from atrade.per_symbol.risk import compute_risk
from atrade.per_symbol.styler import classify_style, summarize
from atrade.per_symbol.volatility import compute_volatility

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
HOLDINGS_FILE = Path(__file__).resolve().parents[1] / "config" / "holdings.json"


def load_holdings() -> list[dict]:
    if not HOLDINGS_FILE.exists():
        return []
    return json.loads(HOLDINGS_FILE.read_text()).get("holdings", [])


def report_one(symbol: str, name: str, cost_price: float, quantity: int,
               intraday_days: int = 30) -> str:
    hp = HistoryProvider()
    daily = hp.fetch_with_cache(symbol, scale="1d", datalen=252)
    if daily is None or len(daily) < 60:
        raise ValueError(f"{symbol} 日线数据不足")
    latest_price = float(daily.iloc[-1]["close"])
    if not math.isfinite(latest_price) or latest_price <= 0:
        latest_price = None
    display_name = name or symbol
    if display_name == symbol and "name" in daily.columns:
        names = daily["name"].dropna().astype(str)
        valid_names = names[~names.isin(("", "None", "nan"))]
        if not valid_names.empty:
            display_name = valid_names.iloc[-1]
    intraday = hp.fetch_with_cache(symbol, scale="5m", datalen=240)

    volatility = compute_volatility(daily)
    risk = compute_risk(daily)
    if intraday is not None and len(intraday) >= 60:
        adaptive = compute_adaptive(intraday)
    else:
        adaptive = {
            "intra_amp_p50": 0.0,
            "intra_amp_p90": 0.0,
            "hold_minutes_p90": 0,
            "factor_score": {},
            "preferred_factors": [],
            "position_pct": 0.1,
        }
    style = classify_style(volatility, risk, adaptive)
    summary = summarize(display_name, style, volatility, risk, adaptive)
    rep = build_report(
        symbol=symbol, name=display_name,
        cost_price=cost_price, quantity=quantity,
        volatility=volatility, risk=risk, adaptive=adaptive,
        style=style, summary=summary, intraday_days=intraday_days,
        latest_price=latest_price,
    )
    return render_markdown(rep)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="个股做 T 策略报告")
    parser.add_argument("--symbol", help="股票代码")
    parser.add_argument("--cost", type=float, default=0.0)
    parser.add_argument("--qty", type=int, default=0)
    parser.add_argument("--portfolio", action="store_true",
                        help="使用 config/holdings.json 中的所有持仓")
    parser.add_argument("--intraday-days", type=int, default=30)
    args = parser.parse_args(argv)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    targets = []
    if args.portfolio:
        targets = [(h["symbol"], h.get("name", h["symbol"]),
                    h.get("cost_price", 0.0), h.get("quantity", 0)) for h in load_holdings()]
    elif args.symbol:
        targets = [(args.symbol, args.symbol, args.cost, args.qty)]
    else:
        parser.print_help()
        return 1

    rc = 0
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for symbol, name, cost, qty in targets:
        try:
            md = report_one(symbol, name, cost, qty, intraday_days=args.intraday_days)
            path = REPORTS_DIR / f"per_symbol_{symbol}_{stamp}.md"
            path.write_text(md, encoding="utf-8")
            print(f"✅ {symbol} -> {path}")
        except Exception as e:
            rc = 2
            print(f"⚠️ {symbol} 失败: {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
