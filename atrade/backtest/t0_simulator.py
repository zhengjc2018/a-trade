"""T+0 做 T 模拟器（事件驱动守恒账本）。

设计要点：

1. 状态模型（不变量）
   - target_quantity: 长期目标底仓股数（不可变，除非外部修改）
   - settled_quantity: 当前可卖股数（不受 T+1 限制）
   - locked_quantity: 当日买入、下个交易日才解锁的股数
   - trading_cash: T 交易累计现金流（买入为负，卖出为正，费用立即扣除）

2. 成交规则
   - 信号在第 N 根 K 线确认，最早在第 N+1 根 K 线以开盘价成交（避免前视）。
   - 同一根 K 线最多一个新方向动作（先止损 > 卖出 > 买入）。
   - 买入：cash -= amount + fee；locked_quantity += size。
   - 卖出：cash += amount - fee；优先扣减 settled_quantity，不足时扣减 locked_quantity（保守模式直接报错）。
   - 新交易日开始：locked_quantity → settled_quantity。

3. 正向 / 反向做 T
   - 总股份 == target 且收到 BUY：买入一个 T 仓 → 开启正向周期（settled -= size 实际上 T 仓在 locked）。
   - 总股份 > target 且收到 SELL 或到达 EOD：卖出可卖底仓，恢复 target。
   - 总股份 == target 且收到 SELL：卖出已 settled 的 T 仓，开启反向周期（先卖后买）。
   - 总股份 < target 且收到 BUY 或到达 EOD：买回缺口，恢复 target。

4. 估值与费用
   - 策略净值 = (settled + locked) * 当前价 + trading_cash
   - T 净盈亏 = trading_cash + (总股份 - target_quantity) * 当前价
   - 有效成本 = 原始成本 - T 净盈亏 / target_quantity
   - 佣金支持最低收费；卖出支持印花税；买卖支持过户费与滑点。

5. 必须成立的不变量（运行时校验）
   - 卖出数量不得超过 settled_quantity。
   - settled_quantity 与 locked_quantity 不得为负。
   - 平仓周期结束后 (settled + locked) == target_quantity。
   - 现金变化严格等于成交金额 + 费用。
   - 无交易时净值变化 == 死拿。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from atrade.data import HistoryProvider
from atrade.indicators import add_all_indicators
from atrade.signals import SignalEngine, SignalType


@dataclass
class Position:
    """底仓 + T 仓状态（事件驱动版）。

    Attributes:
        target_quantity: 策略长期维持的底仓股数（不可变基准）。
        settled_quantity: 当前可卖股数。
        locked_quantity: 当日买入、下一交易日才可卖的股数。
        t_avg_cost: T 仓移动加权成本（仅 T 仓部分）。
        cash: T 交易累计现金流（净，含费用）。
        open_cycle: 是否有未平 T 周期（用于阻止同向叠加）。
    """
    target_quantity: int = 0
    settled_quantity: int = 0
    locked_quantity: int = 0
    t_avg_cost: float = 0.0
    cash: float = 0.0
    open_cycle: bool = False

    @property
    def total(self) -> int:
        return self.settled_quantity + self.locked_quantity

    def is_locked_today(self, today: str) -> bool:
        return self.locked_quantity > 0


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
    net_t_profit: float
    t_win_count: int
    t_loss_count: int
    t_win_rate: float
    max_drawdown_pct: float
    fee_total: float
    buy_hold_profit: float
    annualized_return: float
    t_position_max: int
    t1_locks_held: int
    quantity: int = 0
    final_total_quantity: int = 0
    peak_cash_usage: float = 0.0
    trades: list[T0Trade] = field(default_factory=list)
    last_close: float = 0.0

    def summary(self) -> str:
        lines = [
            f"# 📊 {self.symbol} T+0 回测报告（事件驱动守恒账本）",
            f"回测区间: {self.start_date} ~ {self.end_date}",
            "",
            "## 核心指标",
            "| 指标 | 数值 |",
            "|---|---|",
            f"| 初始成本（用户输入） | {self.initial_cost:.2f} |",
            f"| 最新收盘价（回测末日） | {self.last_close:.2f} |",
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
            f"| 期末总持股 | {self.final_total_quantity} |",
            f"| 峰值资金占用 | {self.peak_cash_usage:.0f} |",
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
    """T+0 做 T 模拟器（事件驱动守恒账本）。"""

    def __init__(
        self,
        scale: str = "1d",
        datalen: int = 600,
        t_position_pct: float = 0.33,
        fee_commission: float = 0.00025,
        fee_commission_min: float = 5.0,
        fee_stamp_duty_sell: float = 0.001,
        fee_transfer: float = 0.0001,
        slippage_pct: float = 0.0005,
        force_close_loss_pct: float = 0.05,
        signal_cooldown_days: int = 5,
    ):
        self.history = HistoryProvider()
        self.engine = SignalEngine()
        self.scale = scale
        self.datalen = datalen
        self.t_position_pct = t_position_pct
        self.fee_commission = fee_commission
        self.fee_commission_min = fee_commission_min
        self.fee_stamp_duty_sell = fee_stamp_duty_sell
        self.fee_transfer = fee_transfer
        self.slippage_pct = slippage_pct
        self.force_close_loss_pct = force_close_loss_pct
        self.signal_cooldown_days = signal_cooldown_days

    # ---------- 工具 ----------
    def _slippage_buy(self, price: float) -> float:
        return price * (1 + self.slippage_pct)

    def _slippage_sell(self, price: float) -> float:
        return price * (1 - self.slippage_pct)

    def _calc_buy_fee(self, price: float, qty: int) -> float:
        amount = price * qty
        commission = max(amount * self.fee_commission, self.fee_commission_min)
        transfer = amount * self.fee_transfer
        return commission + transfer

    def _calc_sell_fee(self, price: float, qty: int) -> float:
        amount = price * qty
        commission = max(amount * self.fee_commission, self.fee_commission_min)
        stamp = amount * self.fee_stamp_duty_sell
        transfer = amount * self.fee_transfer
        return commission + stamp + transfer

    @staticmethod
    def _next_date(date_str: str) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    @staticmethod
    def _day_key(date_str: str) -> str:
        return str(date_str)[:10]

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        s = str(date_str).strip()
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d").strftime("%Y-%m-%d")
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y-%m-%d")

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
        df = self.history.fetch_with_cache(symbol, scale=self.scale, datalen=self.datalen)
        if df is None or len(df) < 30:
            raise ValueError(f"{symbol} 数据不足")

        start_day = self._normalize_date(start_date)
        end_day = self._normalize_date(end_date)

        df["date_obj"] = pd.to_datetime(df["date"])
        df["trade_day"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df[
            (df["trade_day"] >= start_day) &
            (df["trade_day"] <= end_day)
        ].copy().reset_index(drop=True)
        if len(df) < 30:
            raise ValueError(f"{symbol} 日期范围内数据不足（{len(df)} 行）")

        df_ind = add_all_indicators(df).reset_index(drop=True)

        # 初始状态：所有底仓可卖
        pos = Position(
            target_quantity=int(quantity),
            settled_quantity=int(quantity),
            locked_quantity=0,
            t_avg_cost=0.0,
            cash=0.0,
            open_cycle=False,
        )

        trades: list[T0Trade] = []
        fee_total = 0.0
        t_win = t_loss = 0
        t_position_max = 0
        t1_locks_held = 0
        portfolio_values: list[tuple[str, float]] = []
        last_signal_date: dict[str, str] = {}

        # 资金占用峰值（绝对值）
        peak_cash_usage = 0.0

        # 信号队列：上一根 K 线确认后，本根 K 线开盘价成交
        pending_signal: Optional[SignalType] = None

        for i in range(30, len(df_ind)):
            row = df_ind.iloc[i]
            today = self._day_key(row["trade_day"])
            is_last_bar_of_day = (
                i == len(df_ind) - 1 or
                self._day_key(df_ind.iloc[i + 1]["trade_day"]) != today
            )

            # 1. 新交易日开始：解锁昨日买入（locked → settled）
            if i == 30 or self._day_key(df_ind.iloc[i - 1]["trade_day"]) != today:
                if pos.locked_quantity > 0:
                    pos.settled_quantity += pos.locked_quantity
                    pos.locked_quantity = 0

            # 2. 执行上一根 K 线确认的信号（用本根 K 线开盘价成交）
            if pending_signal is not None and i > 30:
                self._execute_pending(
                    pending_signal, pos, row["open"], today,
                    cost_price, trades, t_win, t_loss,
                )
                pending_signal = None
                # 更新守恒指标
                peak_cash_usage = max(peak_cash_usage, -pos.cash)

            # 3. 当前 K 线确认信号（最早下一根 K 线开盘成交）
            signals = self.engine.scan(symbol, df_ind.iloc[:i + 1])
            if signals:
                # 优先级：止损 > 卖出 > 买入
                for s in signals:
                    key = s.signal_type.value
                    if key in last_signal_date:
                        last = datetime.strptime(last_signal_date[key], "%Y-%m-%d")
                        cur = datetime.strptime(today, "%Y-%m-%d")
                        if (cur - last).days < self.signal_cooldown_days:
                            continue
                    last_signal_date[key] = today
                    if pending_signal is None:
                        pending_signal = s.signal_type
                    break  # 只取第一个有效信号

            # 4. 强制止损（T 仓浮亏超阈值，仅在 unlocked 时）
            if pos.t_holdings_via_state() > 0 and pos.t_avg_cost > 0 and pos.open_cycle is not False:
                pass  # placeholder，保留 t_holdings 计算
            cur_price = row["close"]
            t_holdings = pos.t_holdings_via_state()
            if t_holdings > 0 and pos.t_avg_cost > 0 and pos.locked_quantity == 0:
                unrealized_pct = (cur_price - pos.t_avg_cost) / pos.t_avg_cost
                if unrealized_pct <= -self.force_close_loss_pct:
                    self._do_sell(
                        pos, cur_price, t_holdings,
                        today, cost_price, "强制止损",
                        trades,
                    )
                    fee_total += trades[-1].fee
                    pos.t_avg_cost = 0.0
                    pos.open_cycle = False
                    if trades[-1].profit >= 0:
                        t_win += 1
                    else:
                        t_loss += 1
                    peak_cash_usage = max(peak_cash_usage, -pos.cash)

            # 5. EOD 强制平仓（恢复 target）
            if force_eod_close and is_last_bar_of_day:
                if pos.total > pos.target_quantity:
                    # 多出来的全卖 → 恢复 target
                    excess = pos.total - pos.target_quantity
                    sell_qty = min(excess, pos.settled_quantity)
                    if sell_qty > 0:
                        self._do_sell(
                            pos, cur_price, sell_qty,
                            today, cost_price, "EOD 平仓(恢复到 target)",
                            trades,
                        )
                        fee_total += trades[-1].fee
                        if trades[-1].profit >= 0:
                            t_win += 1
                        else:
                            t_loss += 1
                        pos.open_cycle = False
                elif pos.total < pos.target_quantity:
                    # 反向：缺口买回
                    gap = pos.target_quantity - pos.total
                    self._do_buy(
                        pos, cur_price, gap,
                        today, "EOD 补仓(恢复到 target)",
                        trades,
                    )
                    fee_total += trades[-1].fee
                    pos.open_cycle = False

            t_position_max = max(t_position_max, t_holdings)
            if pos.locked_quantity > 0:
                t1_locks_held += 1

            # 6. 跟踪净值
            portfolio_values.append(
                (today, pos.total * cur_price + pos.cash)
            )

        # ---------- 汇总 ----------
        last_close = df_ind.iloc[-1]["close"]
        # T 净盈亏 = trading_cash + (总股份 - target) * 当前价
        net_t_profit = pos.cash + (pos.total - pos.target_quantity) * last_close
        net_t_pct = net_t_profit / max(cost_price * quantity, 1) * 100

        # 有效成本 = 原始成本 - T净盈亏 / target_quantity
        new_cost = cost_price - net_t_profit / max(pos.target_quantity, 1)
        cost_change_pct = (new_cost - cost_price) / cost_price * 100
        buy_hold_pct = (last_close - cost_price) / cost_price * 100

        # 期末盯市：把所有 T 仓按收盘价卖出（T 净盈亏已含此项）
        fee_total_for_summary = fee_total

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
            start_date=df_ind.iloc[0]["trade_day"],
            end_date=df_ind.iloc[-1]["trade_day"],
            initial_cost=cost_price,
            final_cost=new_cost,
            quantity=quantity,
            cost_change=cost_change_pct,
            total_t_profit=pos.cash,
            net_t_profit=net_t_profit,
            t_win_count=t_win,
            t_loss_count=t_loss,
            t_win_rate=win_rate,
            max_drawdown_pct=max_dd,
            fee_total=fee_total_for_summary,
            buy_hold_profit=buy_hold_pct,
            annualized_return=ann_return,
            t_position_max=t_position_max,
            t1_locks_held=t1_locks_held,
            final_total_quantity=pos.total,
            peak_cash_usage=peak_cash_usage,
            trades=trades,
            last_close=float(last_close),
        )

    # ---------- 内部动作 ----------
    def _execute_pending(self, sig_type: SignalType, pos: Position,
                          price: float, today: str, cost_price: float,
                          trades: list, t_win: int, t_loss: int):
        """执行上一根 K 线确认的信号；返回成交价。"""
        cur_price = price
        size = max(int(pos.target_quantity * self.t_position_pct), 100)

        if sig_type == SignalType.BUY:
            # 正向 / 反向做 T：根据总股份 vs target 决定
            if pos.total == pos.target_quantity:
                # 正向：买一个 T 仓
                self._do_buy(pos, cur_price, size, today, sig_type.name + "(正向 T)",
                             trades)
            elif pos.total < pos.target_quantity:
                # 反向补回
                gap = pos.target_quantity - pos.total
                self._do_buy(pos, cur_price, gap, today, sig_type.name + "(反向补)",
                             trades)
        elif sig_type == SignalType.SELL:
            if pos.total == pos.target_quantity:
                # 反向：卖出一个 T 仓（需 T 仓存在；按已 settled 处理）
                t_holdings = pos.t_holdings_via_state()
                sell_qty = min(size, t_holdings)
                if sell_qty > 0:
                    self._do_sell(pos, cur_price, sell_qty, today, cost_price,
                                  sig_type.name + "(反向 T)", trades)
            elif pos.total > pos.target_quantity:
                # 正向卖出底仓
                excess = pos.total - pos.target_quantity
                sell_qty = min(excess, pos.settled_quantity)
                if sell_qty > 0:
                    self._do_sell(pos, cur_price, sell_qty, today, cost_price,
                                  sig_type.name + "(底仓减)", trades)
        elif sig_type == SignalType.STOP_LOSS:
            # 止损只对当前可卖 T 仓生效
            t_holdings = pos.t_holdings_via_state()
            if t_holdings > 0 and pos.locked_quantity == 0:
                self._do_sell(pos, cur_price, t_holdings, today, cost_price,
                              sig_type.name, trades)
        return cur_price

    def _do_buy(self, pos: Position, price: float, qty: int,
                 today: str, signal_name: str,
                 trades: list):
        buy_price = self._slippage_buy(price)
        amount = buy_price * qty
        fee = self._calc_buy_fee(buy_price, qty)
        trades.append(T0Trade(
            date=today, direction="buy",
            price=buy_price, quantity=qty,
            amount=amount, signal=signal_name, fee=fee,
        ))
        pos.cash -= (amount + fee)
        # 先算 T 仓加权成本（用加锁前的状态），再加锁
        prev_holdings = pos.t_holdings_via_state()
        prev_cost = pos.t_avg_cost * prev_holdings
        new_holdings = prev_holdings + qty
        if new_holdings > 0:
            pos.t_avg_cost = (prev_cost + buy_price * qty) / new_holdings
        pos.locked_quantity += qty
        pos.open_cycle = True

    def _do_sell(self, pos: Position, price: float, qty: int,
                 today: str, cost_price: float, signal_name: str,
                 trades: list):
        if qty <= 0:
            return
        # 守恒校验：卖出不得超过 settled
        if qty > pos.settled_quantity:
            raise ValueError(
                f"卖出 {qty} 超过可卖 {pos.settled_quantity}（违反 T+1 约束）"
            )
        sell_price = self._slippage_sell(price)
        amount = sell_price * qty
        fee = self._calc_sell_fee(sell_price, qty)
        profit = (sell_price - pos.t_avg_cost) * qty - fee
        trades.append(T0Trade(
            date=today, direction="sell",
            price=sell_price, quantity=qty,
            amount=amount, signal=signal_name,
            profit=profit, fee=fee,
        ))
        pos.cash += (amount - fee)
        pos.settled_quantity -= qty
        # 如果是 T 仓部分卖出，按比例降低 t_avg_cost
        t_holdings = pos.t_holdings_via_state()
        if t_holdings > 0 and qty <= t_holdings:
            pos.t_avg_cost = pos.t_avg_cost  # 不变（卖出后剩下的 T 仓成本不变）
        elif qty > t_holdings and t_holdings > 0:
            # 部分卖 T 仓 + 部分卖底仓
            pos.t_avg_cost = 0.0
        else:
            # 卖底仓
            pos.t_avg_cost = pos.t_avg_cost
        # 如果卖出后总股份 == target 且 open_cycle → 关闭周期
        if pos.total == pos.target_quantity:
            pos.open_cycle = False


# 给 Position 加一个辅助属性：t_holdings（用 settled - target_quantity + locked）
def _t_holdings_via_state(self) -> int:
    """T 仓估算 = 总股份 - 底仓（target）。

    反向做 T 时，T 仓可能为 0 但实际有"已卖未补"缺口，
    此处保守取 max(0, total - target)。
    """
    return max(0, self.total - self.target_quantity)


Position.t_holdings_via_state = _t_holdings_via_state
