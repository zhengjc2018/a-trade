"""T+0 做 T 模拟器。

模拟规则：
- 起始：N 股持仓，成本 P0
- 每个交易日，按当日信号做 T：
  * 低吸信号：用资金买入 position_pct 仓位
  * 高抛信号：卖出 position_pct 仓位
  * 止损信号：清仓
  * 收盘前若有未平仓位：强制平仓
- 计算：累计 T 盈亏、持仓成本变化、胜率、最大回撤
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from loguru import logger

from atrade.data import HistoryProvider
from atrade.indicators import add_all_indicators
from atrade.signals import SignalEngine, SignalType


@dataclass
class T0Trade:
    """单笔 T 交易。"""
    date: str
    direction: str  # "buy" / "sell"
    price: float
    quantity: int
    amount: float       # 总金额
    signal: str         # 触发的信号名
    profit: float = 0.0 # 平仓时的盈亏


@dataclass
class T0BacktestResult:
    """回测结果汇总。"""
    symbol: str
    start_date: str
    end_date: str
    initial_cost: float
    final_cost: float
    cost_change: float          # 成本变化（负数=降低成本）
    total_t_profit: float       # T 累计盈亏
    t_win_count: int             # 盈利 T 笔数
    t_loss_count: int            # 亏损 T 笔数
    t_win_rate: float            # T 胜率
    max_drawdown: float          # 最大回撤
    buy_hold_profit: float       # 同期不动的盈亏
    vs_buy_hold: float           # 做 T 相对死拿的差异
    trades: list[T0Trade] = field(default_factory=list)

    def summary(self) -> str:
        """生成报告。"""
        lines = [
            f"# 📊 {self.symbol} T+0 回测报告",
            f"回测区间: {self.start_date} ~ {self.end_date}",
            "",
            f"## 核心指标",
            f"| 指标 | 数值 |",
            f"|---|---|",
            f"| 初始成本 | {self.initial_cost:.2f} |",
            f"| 最终成本 | {self.final_cost:.2f} |",
            f"| **成本变化** | **{self.cost_change:+.2f}%** |",
            f"| T 累计盈亏 | {self.total_t_profit:+.2f} |",
            f"| T 胜率 | {self.t_win_rate*100:.1f}% |",
            f"| T 笔数 | {self.t_win_count + self.t_loss_count}（{self.t_win_count} 胜 / {self.t_loss_count} 负）|",
            f"| 最大回撤 | {self.max_drawdown*100:.2f}% |",
            f"| 同期死拿盈亏 | {self.buy_hold_profit:+.2f}% |",
            f"| **做 T vs 死拿** | **{self.vs_buy_hold:+.2f}%** |",
            "",
        ]
        if self.trades:
            lines.append("## 交易明细（最近 10 笔）")
            lines.append("| 日期 | 方向 | 价格 | 数量 | 信号 | 盈亏 |")
            lines.append("|---|---|---|---|---|---|")
            for t in self.trades[-10:]:
                lines.append(
                    f"| {t.date} | {t.direction} | {t.price:.2f} | "
                    f"{t.quantity} | {t.signal} | {t.profit:+.2f} |"
                )
        return "\n".join(lines)


class T0Simulator:
    """T+0 做 T 模拟器。"""

    def __init__(self):
        self.history = HistoryProvider()
        self.engine = SignalEngine()

    def run(
        self,
        symbol: str,
        cost_price: float,
        quantity: int,
        start_date: str = "20240101",
        end_date: str = "20260717",
        t_position_pct: float = 0.33,
    ) -> T0BacktestResult:
        """跑回测。
        
        Args:
            symbol: 股票代码
            cost_price: 你的成本价
            quantity: 持仓股数
            start_date: 回测起始日
            end_date: 回测结束日
            t_position_pct: T 仓位比例
        """
        df = self.history.fetch(symbol, scale="1d", datalen=600)
        if df is None or len(df) < 60:
            raise ValueError(f"{symbol} 数据不足")

        # 过滤日期范围
        df["date_obj"] = pd.to_datetime(df["date"])
        df = df[(df["date_obj"] >= start_date) & (df["date_obj"] <= end_date)]
        if len(df) < 30:
            raise ValueError(f"{symbol} 日期范围内数据不足（{len(df)} 行）")

        # 计算指标
        df_ind = add_all_indicators(df)
        df_ind = df_ind.reset_index(drop=True)

        # 模拟做 T
        trades = []
        base_holdings = quantity         # 底仓
        t_holdings = 0                  # T 仓
        t_avg_cost = 0.0                # T 仓平均成本
        t_total_profit = 0.0
        t_win = t_loss = 0
        t_entry_price = 0.0
        peak_value = cost_price * quantity

        for i in range(len(df_ind)):
            row = df_ind.iloc[i]
            if i < 30:
                continue  # 跳过前 30 天（指标未稳定）

            signals = self.engine.scan(symbol, df_ind.iloc[:i+1])
            if not signals:
                continue

            # 优先级：止损 > 高抛 > 低吸
            sig = signals[0]
            close = row["close"]
            t_size = int(base_holdings * t_position_pct)

            if sig.signal_type == SignalType.STOP_LOSS:
                # 全部清仓
                if t_holdings > 0:
                    profit = (close - t_avg_cost) * t_holdings
                    trades.append(T0Trade(
                        date=row["date"], direction="sell",
                        price=close, quantity=t_holdings,
                        amount=close * t_holdings,
                        signal=sig.name, profit=profit,
                    ))
                    t_total_profit += profit
                    t_holdings = 0
                    t_avg_cost = 0

            elif sig.signal_type == SignalType.SELL:
                # 高抛：卖出 T 仓
                if t_holdings > 0:
                    profit = (close - t_avg_cost) * t_holdings
                    trades.append(T0Trade(
                        date=row["date"], direction="sell",
                        price=close, quantity=t_holdings,
                        amount=close * t_holdings,
                        signal=sig.name, profit=profit,
                    ))
                    t_total_profit += profit
                    if profit > 0:
                        t_win += 1
                    else:
                        t_loss += 1
                    t_holdings = 0
                    t_avg_cost = 0

            elif sig.signal_type == SignalType.BUY:
                # 低吸：买入 T 仓（允许累积）
                if t_size > 0:
                    new_qty = t_holdings + t_size
                    new_avg = (
                        (t_avg_cost * t_holdings + close * t_size) / new_qty
                        if t_holdings > 0 else close
                    )
                    trades.append(T0Trade(
                        date=row["date"], direction="buy",
                        price=close, quantity=t_size,
                        amount=close * t_size, signal=sig.name,
                    ))
                    t_holdings = new_qty
                    t_avg_cost = new_avg

            # 跟踪最大回撤
            current_value = (base_holdings + t_holdings) * close
            peak_value = max(peak_value, current_value)
            drawdown = (peak_value - current_value) / peak_value

        # 计算最终指标
        last_price = df_ind.iloc[-1]["close"]
        # 新成本 = (原成本 * 原数量 + T 净盈亏) / 总数量
        new_cost = (
            (cost_price * quantity + t_total_profit) / quantity
        ) if quantity > 0 else cost_price
        cost_change_pct = (new_cost - cost_price) / cost_price * 100

        buy_hold_pct = (last_price - cost_price) / cost_price * 100
        total_t_profit_pct = t_total_profit / (cost_price * quantity) * 100

        total_trades = t_win + t_loss
        win_rate = t_win / total_trades if total_trades > 0 else 0

        return T0BacktestResult(
            symbol=symbol,
            start_date=df_ind.iloc[0]["date"],
            end_date=df_ind.iloc[-1]["date"],
            initial_cost=cost_price,
            final_cost=new_cost,
            cost_change=cost_change_pct,
            total_t_profit=t_total_profit,
            t_win_count=t_win,
            t_loss_count=t_loss,
            t_win_rate=win_rate,
            max_drawdown=0.0,  # TODO: 跟踪
            buy_hold_profit=buy_hold_pct,
            vs_buy_hold=total_t_profit_pct,
            trades=trades,
        )
