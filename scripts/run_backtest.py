"""回测 CLI 入口。

用法:
    python3 scripts/run_backtest.py --symbol 600519 --cost 1650 --qty 100
    python3 scripts/run_backtest.py --portfolio
    python3 scripts/run_backtest.py --symbol 600519 --cost 1650 --qty 100 --push
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.backtest import T0Simulator
from atrade.backtest.t0_simulator import T0BacktestResult


REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def run_one(symbol: str, cost: float, qty: int, args) -> T0BacktestResult:
    sim = T0Simulator(
        scale=args.scale,
        datalen=args.datalen,
        t_position_pct=args.t_position_pct,
        fee_commission=args.fee_commission,
        fee_stamp_duty_sell=args.fee_stamp_duty_sell,
        slippage_pct=args.slippage,
    )
    return sim.run(symbol, cost, qty,
                   start_date=args.start.replace("-", ""),
                   end_date=args.end.replace("-", ""))


def print_console(results):
    print("\n" + "=" * 80)
    print(f"{'代码':<8} {'区间':<24} {'成本变化':>10} {'T 净额':>12} "
          f"{'胜率':>8} {'最大回撤':>10} {'年化':>10} {'vs 死拿':>10}")
    print("-" * 80)
    for r in results:
        # vs 死拿 = T 净额相对持仓成本 + 死拿涨跌
        # denom = cost_price * quantity（持仓建仓成本）
        position_cost = max(r.initial_cost * max(r.quantity, 1), 1)
        vs = r.net_t_profit / position_cost * 100 + r.buy_hold_profit
        print(
            f"{r.symbol:<8} {r.start_date}~{r.end_date:<10} "
            f"{r.cost_change:>+9.2f}% {r.net_t_profit:>+11.2f} "
            f"{r.t_win_rate*100:>7.1f}% {r.max_drawdown_pct*100:>9.2f}% "
            f"{r.annualized_return:>+9.2f}% {vs:>+9.2f}%"
        )
    print("=" * 80 + "\n")


def save_report(results):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = []
    for r in results:
        path = REPORTS_DIR / f"backtest_{r.symbol}_{stamp}.md"
        path.write_text(r.summary(), encoding="utf-8")
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description="a-trade T+0 回测 CLI")
    parser.add_argument("--symbol", action="append", help="股票代码（可多次）")
    parser.add_argument("--cost", action="append", type=float, help="成本价")
    parser.add_argument("--qty", action="append", type=int, help="持仓股数")
    parser.add_argument("--portfolio", action="store_true",
                        help="用 config/holdings.json 全跑")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end",
                        default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--scale", default="1d",
                        choices=["1d", "5m", "15m", "30m", "60m"],
                        help="回测周期")
    parser.add_argument("--datalen", type=int, default=600,
                        help="拉取 K 线根数")
    parser.add_argument("--t-position-pct", type=float, default=0.5)
    parser.add_argument("--fee-commission", type=float, default=0.00025)
    parser.add_argument("--fee-stamp-duty-sell", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--push", action="store_true", help="推送到 QQ 群")

    args = parser.parse_args()

    targets = []
    if args.portfolio:
        from atrade.config import load_holdings
        holdings = load_holdings()
        for h in holdings:
            targets.append((h["symbol"], h["cost_price"], h["quantity"]))
    elif args.symbol:
        symbols = args.symbol
        costs = args.cost or [0.0] * len(symbols)
        qtys = args.qty or [0] * len(symbols)
        for s, c, q in zip(symbols, costs, qtys):
            targets.append((s, c, q))
    else:
        parser.print_help()
        return

    results = [run_one(s, c, q, args) for s, c, q in targets]
    print_console(results)
    paths = save_report(results)
    for p in paths:
        print(f"📄 报告: {p}")

    if args.push:
        try:
            from atrade.notify import load_notifier, split_markdown_by_bytes
            notifier = load_notifier(preferred="openclaw")
            for r in results:
                for chunk in split_markdown_by_bytes(r.summary(), max_bytes=3500):
                    notifier.send_markdown(chunk)
        except Exception as e:
            print(f"⚠️ 推送失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
