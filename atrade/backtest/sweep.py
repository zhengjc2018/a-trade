"""锁利/止损参数网格扫描。

规则（参考 docs/superpowers/specs/2026-07-25-backtest-system-design.md §6）：

1. 锁利候选默认 [0.01, 0.02, 0.03, 0.05, 0.07, 0.10]
2. 止损候选默认 [0.01, 0.02, 0.03, 0.05]
3. 排名门槛：胜率 ≥ 60%
4. 排名公式：T 净收益（元）+ max(0, win_rate - 0.5) × T_笔数 × log(笔数 + 1)
   — 奖励高胜率多次交易，惩罚高频刷单 + 低胜率单笔
5. Top 3 推荐入报告 Markdown
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .t0_simulator import T0BacktestResult, T0Simulator


@dataclass
class SweepGrid:
    take_profits: list[float] = field(default_factory=lambda: [0.01, 0.02, 0.03, 0.05, 0.07, 0.10])
    stop_losses: list[float] = field(default_factory=lambda: [0.01, 0.02, 0.03, 0.05])
    min_win_rate: float = 0.60
    max_combos: int = 50  # 防爆雪球

    def combos(self) -> list[tuple[float, float]]:
        pairs: list[tuple[float, float]] = []
        for tp in sorted({round(x, 4) for x in self.take_profits}):
            for sl in sorted({round(x, 4) for x in self.stop_losses}):
                pairs.append((tp, sl))
        if len(pairs) > self.max_combos:
            # 取网格对角带：tp 越大配 sl 也越大，避免组合到没有信号的角落
            pairs = [
                (tp, sl)
                for tp, sl in pairs
                if abs(tp - sl) <= 0.06 or (tp >= 0.05 and sl <= 0.04)
            ][: self.max_combos]
        return pairs

    @property
    def expected_count(self) -> int:
        return len(self.combos())


@dataclass
class SweepEntry:
    take_profit_pct: float
    stop_loss_pct: float
    result: T0BacktestResult
    score: float = 0.0

    @property
    def wins(self) -> int:
        return self.result.t_win_count

    @property
    def losses(self) -> int:
        return self.result.t_loss_count

    @property
    def win_rate(self) -> float:
        return self.result.t_win_rate

    @property
    def net_pnl(self) -> float:
        return self.result.net_t_profit

    @property
    def trades(self) -> int:
        return self.wins + self.losses


def _score(entry: SweepEntry) -> float:
    """综合评分：净收益 + 风险惩罚 + 高胜率奖励。

    目标：找"胜率高 × 单笔赚 × 笔数足够"的组合。
    """
    if entry.trades < 2:
        # 笔数太少不可信 → 加惩罚
        return entry.net_pnl - 50.0
    return (
        entry.net_pnl
        + max(0.0, entry.win_rate - 0.5) * entry.trades * math.log(entry.trades + 1) * 5
        - (1 - entry.win_rate) * entry.trades * 2  # 惩罚大幅亏损交易
    )


def _empty_result(symbol: str, why: str) -> T0BacktestResult:
    """构造一个「无成交」T0BacktestResult 占位，用于网格缺数据兜底。"""
    return T0BacktestResult(
        symbol=symbol,
        start_date="-",
        end_date="-",
        initial_cost=0.0,
        final_cost=0.0,
        cost_change=0.0,
        total_t_profit=0.0,
        net_t_profit=0.0,
        t_win_count=0,
        t_loss_count=0,
        t_win_rate=0.0,
        max_drawdown_pct=0.0,
        fee_total=0.0,
        buy_hold_profit=0.0,
        annualized_return=0.0,
        t_position_max=0,
        t1_locks_held=0,
        quantity=0,
        final_total_quantity=0,
        peak_cash_usage=0.0,
    )


def run_sweep(
    symbol: str,
    cost_price: float,
    quantity: int,
    grid: Optional[SweepGrid] = None,
    *,
    start_date: str = "2024-01-01",
    end_date: Optional[str] = None,
    scale: str = "1d",
    progress_cb=None,
) -> list[SweepEntry]:
    """对 (take_profit, stop_loss) 网格跑 T0Simulator，返回 SweepEntry 列表。

    Args:
        progress_cb: 可选回调 fn(done, total) 用于 UI 进度。
    """
    grid = grid or SweepGrid()
    end_dt = end_date or datetime.now().strftime("%Y-%m-%d")
    combos = grid.combos()
    if not combos:
        return []

    entries: list[SweepEntry] = []
    total = len(combos)
    for idx, (tp, sl) in enumerate(combos, start=1):
        sim = T0Simulator(
            scale=scale,
            datalen=600,
            take_profit_pct=tp,
            stop_loss_pct=sl,
        )
        try:
            result = sim.run(
                symbol,
                cost_price,
                quantity,
                start_date=start_date.replace("-", ""),
                end_date=end_dt.replace("-", ""),
            )
        except Exception:
            result = _empty_result(symbol, "数据不足")
        entry = SweepEntry(take_profit_pct=tp, stop_loss_pct=sl, result=result)
        entry.score = _score(entry)
        entries.append(entry)
        if progress_cb:
            try:
                progress_cb(idx, total)
            except Exception:
                pass
    return entries


def rank(entries: list[SweepEntry], min_win_rate: float = 0.60) -> list[SweepEntry]:
    """按门槛 + 综合得分排序。"""
    qualified = [e for e in entries if e.win_rate >= min_win_rate and e.trades >= 2]
    qualified.sort(key=lambda e: e.score, reverse=True)
    return qualified


def to_markdown(
    symbol: str,
    entries: list[SweepEntry],
    cost_price: float,
    quantity: int,
    top_k: int = 3,
) -> str:
    """渲染 Sweep 报告 Markdown：所有组合表 + Top K 推荐。"""
    md = [
        f"# 🧪 {symbol} 锁利/止损参数扫描",
        "",
        f"_生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}_",
        f"_基准：成本 {cost_price:.2f} / 数量 {quantity} 股_",
        "",
        "## 全部组合（按得分排序）",
        "",
        "| 锁利 | 止损 | 胜率 | T净额(元) | 笔数 | 得分 |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    sorted_entries = sorted(entries, key=lambda e: e.score, reverse=True)
    for e in sorted_entries:
        md.append(
            f"| +{e.take_profit_pct*100:.1f}% | -{e.stop_loss_pct*100:.1f}% | "
            f"{e.win_rate*100:.1f}% | {e.net_pnl:+.2f} | {e.trades} | {e.score:+.1f} |"
        )

    md.append("")
    md.append(f"## 推荐 Top {top_k}（胜率 ≥ 60%）")
    ranked = rank(entries)
    if not ranked:
        md.extend(["", "_⚠️ 当前网格没有胜率 ≥ 60% 的组合，建议扩大候选区间或调整因子。_"])
    for i, e in enumerate(ranked[:top_k], start=1):
        md.extend([
            "",
            f"### 第 {i} 名：锁利 +{e.take_profit_pct*100:.1f}% / 止损 -{e.stop_loss_pct*100:.1f}%",
            f"- 胜率 **{e.win_rate*100:.1f}%** ({e.wins}胜 / {e.losses}负)",
            f"- T 净额 **{e.net_pnl:+.2f} 元**（已扣费用）",
            f"- 笔数：{e.trades}｜综合得分：{e.score:+.1f}",
        ])

    if ranked:
        best = ranked[0]
        cur = (
            f"`PUT /api/t-settings/{symbol}` "
            f'{{"take_profit_pct": {best.take_profit_pct}, "stop_loss_pct": {best.stop_loss_pct}}}'
        )
        md.extend([
            "",
            "## 建议覆盖（仅参考，不自动写入）",
            "",
            "如果你认可第 1 名的参数，可调用 API 把当前的全局默认或该单股覆盖更新：",
            "",
            cur,
        ])
    md.append("")
    md.append("---")
    md.append("_⚠️ 仅历史回测数据，不构成投资建议；实盘参数需综合手续费、滑点、流动性等_")
    return "\n".join(md)
