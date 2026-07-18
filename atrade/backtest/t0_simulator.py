"""T+0 做 T 模拟器（T+1 严格约束版）。

规则:
- 底仓（已有持仓）：任何 SELL 信号当天即可卖，不受 T+1 限制
- T 仓：当天买 → 次开盘前 lock，次日开盘可卖
- 反向做 T（先卖后买）：仅针对底仓——卖出底仓一部分，标记次日买回
- 强制平仓：浮动亏损 >= force_close_loss_pct → 当日收盘价平
- EOD 强制平仓：收盘前若有 T 仓，按收盘价平

费用（默认）:
- 佣金：买卖各 0.025%
- 印花税：卖出 0.1%
- 滑点：买卖各 0.05%
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from atrade.data import HistoryProvider
from atrade.indicators import add_all_indicators
from atrade.signals import SignalEngine, SignalType


@dataclass
class Position:
    """持仓快照。

    base: 底仓股数（不受 T+1 限制）
    t_holdings: T 仓股数
    t_avg_cost: T 仓移动加权成本
    lock_until_date: T 仓最早可卖日期（YYYY-MM-DD）。空字符串=未锁定。
    """
    base: int = 0
    t_holdings: int = 0
    t_avg_cost: float = 0.0
    lock_until_date: str = ""

    def is_locked(self, today: str) -> bool:
        if not self.lock_until_date:
            return False
        return today < self.lock_until_date


@dataclass
class T0Trade:
    """单笔 T 交易。"""
    date: str
    direction: str  # "buy" / "sell"
    price: float
    quantity: int
    amount: float
    signal: str
    profit: float = 0.0
    fee: float = 0.0


@dataclass
class T0BacktestResult:
    symbol: str
    start_date: str
    end_date: str
    initial_cost: float
    final_cost: float
    cost_change: float
    total_t_profit: float
    net_t_profit: float           # 总盈亏减去总费用
    t_win_count: int
    t_loss_count: int
    t_win_rate: float
    max_drawdown_pct: float
    fee_total: float
    buy_hold_profit: float
    annualized_return: float      # 年化收益率 %
    t_position_max: int           # T 仓峰值
    t1_locks_held: int            # 累计 T+1 锁仓次数
    quantity: int = 0              # 初始持仓股数
    trades: list[T0Trade] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"# 📊 {self.symbol} T+0 回测报告（T+1 严格约束）",
            f"回测区间: {self.start_date} ~ {self.end_date}",
            "",
            f"## 核心指标",
            f"| 指标 | 数值 |",
            f"|---|---|",
            f"| 初始成本 | {self.initial_cost:.2f} |",
            f"| 最终成本 | {self.final_cost:.2f} |",
            f"| **成本变化** | **{self.cost_change:+.2f}%** |",
            f"| T 净盈亏 | {self.net_t_profit:+.2f}（已扣费用） |",
            f"| T 总费用 | {self.fee_total:.2f} |",
            f"| T 胜率 | {self.t_win_rate*100:.1f}% |",
            f"| T 笔数 | {self.t_win_count + self.t_loss_count}（{self.t_win_count} 胜 / {self.t_loss_count} 负）|",
            f"| T 仓峰值 | {self.t_position_max} 股 |",
            f"| T+1 锁仓天数 | {self.t1_locks_held} |",
            f"| 最大回撤 | {self.max_drawdown_pct*100:.2f}% |",
            f"| 年化收益率 | {self.annualized_return:+.2f}% |",
            f"| 同期死拿盈亏 | {self.buy_hold_profit:+.2f}% |",
            "",
        ]
        if self.trades:
            lines.append("## 交易明细（最近 10 笔）")
            lines.append("| 日期 | 方向 | 价格 | 数量 | 信号 | 盈亏 | 费用 |")
            lines.append("|---|---|---|---|---|---|---|")
            for t in self.trades[-10:]:
                lines.append(
                    f"| {t.date} | {t.direction} | {t.price:.2f} | "
                    f"{t.quantity} | {t.signal} | {t.profit:+.2f} | {t.fee:.2f} |"
                )
        return "\n".join(lines)


class T0Simulator:
    """T+0 做 T 模拟器（T+1 严格约束）。"""

    def __init__(
        self,
        t_position_pct: float = 0.33,
        fee_commission: float = 0.00025,
        fee_stamp_duty_sell: float = 0.001,
        slippage_pct: float = 0.0005,
        force_close_loss_pct: float = 0.05,
        signal_cooldown_days: int = 5,
    ):
        self.history = HistoryProvider()
        self.engine = SignalEngine()
        self.t_position_pct = t_position_pct
        self.fee_commission = fee_commission
        self.fee_stamp_duty_sell = fee_stamp_duty_sell
        self.slippage_pct = slippage_pct
        self.force_close_loss_pct = force_close_loss_pct
        # 同方向信号 cooldown（避免短时间重复触发）
        self.signal_cooldown_days = signal_cooldown_days

    # ---------- 工具 ----------
    def _slippage_buy(self, price: float) -> float:
        return price * (1 + self.slippage_pct)

    def _slippage_sell(self, price: float) -> float:
        return price * (1 - self.slippage_pct)

    def _calc_buy_fee(self, price: float, qty: int) -> float:
        return price * qty * self.fee_commission

    def _calc_sell_fee(self, price: float, qty: int) -> float:
        return price * qty * (self.fee_commission + self.fee_stamp_duty_sell)

    @staticmethod
    def _next_date(date_str: str) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    # ---------- 主流程 ----------
    def run(
        self,
        symbol: str,
        cost_price: float,
        quantity: int,
        start_date: str = "20240101",
        end_date: str = "20260717",
        force_eod_close: bool = True,
    ) -> T0BacktestResult:
        """跑回测。"""
        df = self.history.fetch_with_cache(symbol)
        if df is None or len(df) < 60:
            raise ValueError(f"{symbol} 数据不足")

        df["date_obj"] = pd.to_datetime(df["date"])
        df = df[(df["date_obj"] >= start_date) & (df["date_obj"] <= end_date)].copy()
        if len(df) < 30:
            raise ValueError(f"{symbol} 日期范围内数据不足（{len(df)} 行）")

        df_ind = add_all_indicators(df).reset_index(drop=True)

        pos = Position(base=quantity, t_holdings=0, t_avg_cost=0.0,
                       lock_until_date="")
        trades: list[T0Trade] = []
        total_profit_gross = 0.0
        fee_total = 0.0
        t_win = t_loss = 0
        t_position_max = 0
        t1_locks_held = 0
        portfolio_values: list[tuple[str, float]] = []
        # 信号冷却：每种信号类型在 N 天内不重触
        last_signal_date: dict[str, str] = {}
        i_last_signal: dict[str, int] = {}

        for i in range(30, len(df_ind)):
            row = df_ind.iloc[i]
            today = row["date"]

            # 1. 先解锁昨日买入的 T 仓
            if pos.lock_until_date and today >= pos.lock_until_date:
                pos.lock_until_date = ""

            # 2. 强制止损（T 仓浮亏超阈值）
            if pos.t_holdings > 0 and pos.t_avg_cost > 0:
                cur_price = row["close"]
                unrealized_pct = (cur_price - pos.t_avg_cost) / pos.t_avg_cost
                if unrealized_pct <= -self.force_close_loss_pct:
                    sell_price = self._slippage_sell(cur_price)
                    fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                    profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                    trades.append(T0Trade(
                        date=today, direction="sell",
                        price=sell_price, quantity=pos.t_holdings,
                        amount=sell_price * pos.t_holdings,
                        signal="强制止损", profit=profit, fee=fee,
                    ))
                    total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                    fee_total += fee
                    if profit >= 0:
                        t_win += 1
                    else:
                        t_loss += 1
                    pos.t_holdings = 0
                    pos.t_avg_cost = 0.0
                    pos.lock_until_date = ""

            # 3. 信号处理
            signals = self.engine.scan(symbol, df_ind.iloc[:i+1])
            cur_close = row["close"]
            t_size = int(pos.base * self.t_position_pct)

            for sig in signals:
                # 冷却检查：同类信号 N 天内不重触
                key = sig.signal_type.value
                if key in last_signal_date:
                    from datetime import datetime as _dt
                    last = _dt.strptime(last_signal_date[key], "%Y-%m-%d")
                    cur = _dt.strptime(today, "%Y-%m-%d")
                    if (cur - last).days < self.signal_cooldown_days:
                        continue
                last_signal_date[key] = today
                i_last_signal[key] = i

                if sig.signal_type == SignalType.STOP_LOSS:
                    if pos.t_holdings > 0 and not pos.is_locked(today):
                        sell_price = self._slippage_sell(cur_close)
                        fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                        profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                        trades.append(T0Trade(
                            date=today, direction="sell",
                            price=sell_price, quantity=pos.t_holdings,
                            amount=sell_price * pos.t_holdings, signal=sig.name,
                            profit=profit, fee=fee,
                        ))
                        total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                        fee_total += fee
                        if profit >= 0:
                            t_win += 1
                        else:
                            t_loss += 1
                        pos.t_holdings = 0
                        pos.t_avg_cost = 0.0

                elif sig.signal_type == SignalType.SELL:
                    if pos.t_holdings > 0 and not pos.is_locked(today):
                        sell_price = self._slippage_sell(cur_close)
                        fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                        profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                        trades.append(T0Trade(
                            date=today, direction="sell",
                            price=sell_price, quantity=pos.t_holdings,
                            amount=sell_price * pos.t_holdings, signal=sig.name,
                            profit=profit, fee=fee,
                        ))
                        total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                        fee_total += fee
                        if profit >= 0:
                            t_win += 1
                        else:
                            t_loss += 1
                        pos.t_holdings = 0
                        pos.t_avg_cost = 0.0
                        pos.lock_until_date = ""
                    elif pos.t_holdings == 0 and pos.base >= t_size:
                        # 反向做 T：底仓卖出 t_size，次日买回
                        sell_price = self._slippage_sell(cur_close)
                        fee = self._calc_sell_fee(sell_price, t_size)
                        base_diff = (sell_price - cost_price) * t_size - fee
                        trades.append(T0Trade(
                            date=today, direction="sell",
                            price=sell_price, quantity=t_size,
                            amount=sell_price * t_size,
                            signal=sig.name + "(底仓减)", profit=base_diff, fee=fee,
                        ))
                        total_profit_gross += (sell_price - cost_price) * t_size
                        fee_total += fee
                        pos.base -= t_size
                        pos.lock_until_date = self._next_date(today)
                        t1_locks_held += 1

                elif sig.signal_type == SignalType.BUY:
                    # T 仓买入
                    if t_size > 0:
                        buy_price = self._slippage_buy(cur_close)
                        fee = self._calc_buy_fee(buy_price, t_size)
                        new_qty = pos.t_holdings + t_size
                        new_avg = (
                            (pos.t_avg_cost * pos.t_holdings + buy_price * t_size) / new_qty
                            if pos.t_holdings > 0 else buy_price
                        )
                        trades.append(T0Trade(
                            date=today, direction="buy",
                            price=buy_price, quantity=t_size,
                            amount=buy_price * t_size, signal=sig.name, fee=fee,
                        ))
                        fee_total += fee
                        pos.t_holdings = new_qty
                        pos.t_avg_cost = new_avg
                        pos.lock_until_date = self._next_date(today)
                        t_position_max = max(t_position_max, pos.t_holdings)
                        t1_locks_held += 1
                        # 如果是反向做的"次日买回"，把底仓还回
                        if pos.base < quantity:
                            pos.base += t_size

            # 4. 收盘强制平仓（T 仓）—— 仅在未被 T+1 锁仓时才平
            if force_eod_close and pos.t_holdings > 0 and not pos.is_locked(today):
                sell_price = self._slippage_sell(cur_close)
                fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                trades.append(T0Trade(
                    date=today, direction="sell",
                    price=sell_price, quantity=pos.t_holdings,
                    amount=sell_price * pos.t_holdings, signal="EOD 强制平",
                    profit=profit, fee=fee,
                ))
                total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                fee_total += fee
                if profit >= 0:
                    t_win += 1
                else:
                    t_loss += 1
                pos.t_holdings = 0
                pos.t_avg_cost = 0.0
                pos.lock_until_date = ""

            # 5. 跟踪净值
            portfolio_values.append(
                (today, (pos.base + pos.t_holdings) * cur_close)
            )

        # ---------- 汇总 ----------
        last_close = df_ind.iloc[-1]["close"]
        new_cost = (
            (cost_price * quantity + total_profit_gross) / quantity
            if quantity > 0 else cost_price
        )
        cost_change_pct = (new_cost - cost_price) / cost_price * 100
        buy_hold_pct = (last_close - cost_price) / cost_price * 100
        net_t_profit = total_profit_gross - fee_total
        net_t_pct = net_t_profit / (cost_price * quantity) * 100

        max_dd = 0.0
        if portfolio_values:
            peak = -1e18
            for _, v in portfolio_values:
                peak = max(peak, v)
                if peak > 0:
                    dd = (peak - v) / peak
                    max_dd = max(max_dd, dd)

        days = (df_ind["date_obj"].iloc[-1] - df_ind["date_obj"].iloc[0]).days
        years = max(days / 365.0, 1e-9)
        ann_return = ((1 + net_t_pct / 100) ** (1 / years) - 1) * 100

        total_trades = t_win + t_loss
        win_rate = t_win / total_trades if total_trades > 0 else 0.0

        return T0BacktestResult(
            symbol=symbol,
            start_date=df_ind.iloc[0]["date"],
            end_date=df_ind.iloc[-1]["date"],
            initial_cost=cost_price,
            final_cost=new_cost,
            quantity=quantity,
            cost_change=cost_change_pct,
            total_t_profit=total_profit_gross,
            net_t_profit=net_t_profit,
            t_win_count=t_win,
            t_loss_count=t_loss,
            t_win_rate=win_rate,
            max_drawdown_pct=max_dd,
            fee_total=fee_total,
            buy_hold_profit=buy_hold_pct,
            annualized_return=ann_return,
            t_position_max=t_position_max,
            t1_locks_held=t1_locks_held,
            trades=trades,
        )
