"""做 T 当日成交配对与胜率统计。"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class RoundTrip:
    symbol: str
    name: str
    entry_price: float
    exit_price: float
    shares: int
    pnl: float
    pnl_pct: float
    entry_time: str
    exit_time: str
    entry_factor: str
    exit_factor: str
    holding_minutes: int


@dataclass
class _OpenBuy:
    timestamp: datetime
    symbol: str
    name: str
    price: float
    remaining_shares: int
    factor: str


def compute_round_trips(
    trades: list[dict],
    date: Optional[str] = None,
) -> list[RoundTrip]:
    """按股票把当天有效 BUY 与后续 SELL/STOP_LOSS 做 FIFO 配对。"""
    trade_date = date or datetime.now().strftime("%Y-%m-%d")
    normalized = []
    for trade in trades:
        timestamp = _parse_timestamp(trade.get("timestamp"))
        if timestamp is None or timestamp.strftime("%Y-%m-%d") != trade_date:
            continue
        if trade.get("skipped_reason") or _positive_int(trade.get("shares")) <= 0:
            continue
        direction = str(trade.get("direction", "")).upper()
        if direction not in {"BUY", "SELL", "STOP_LOSS"}:
            continue
        price = _positive_float(trade.get("price"))
        if price <= 0:
            continue
        normalized.append((timestamp, trade, direction, price))
    normalized.sort(key=lambda item: item[0])

    open_buys: dict[str, deque[_OpenBuy]] = defaultdict(deque)
    round_trips: list[RoundTrip] = []
    for timestamp, trade, direction, price in normalized:
        symbol = str(trade.get("symbol", "")).zfill(6)
        shares = _positive_int(trade.get("shares"))
        if direction == "BUY":
            open_buys[symbol].append(
                _OpenBuy(
                    timestamp=timestamp,
                    symbol=symbol,
                    name=str(trade.get("name", "")),
                    price=price,
                    remaining_shares=shares,
                    factor=_trade_factor(trade),
                )
            )
            continue

        remaining_exit_shares = shares
        queue = open_buys[symbol]
        while remaining_exit_shares > 0 and queue:
            entry = queue[0]
            if timestamp < entry.timestamp:
                break
            matched_shares = min(entry.remaining_shares, remaining_exit_shares)
            pnl = (price - entry.price) * matched_shares
            round_trips.append(
                RoundTrip(
                    symbol=symbol,
                    name=str(trade.get("name") or entry.name),
                    entry_price=entry.price,
                    exit_price=price,
                    shares=matched_shares,
                    pnl=pnl,
                    pnl_pct=price / entry.price - 1.0,
                    entry_time=entry.timestamp.isoformat(timespec="seconds"),
                    exit_time=timestamp.isoformat(timespec="seconds"),
                    entry_factor=entry.factor,
                    exit_factor=_trade_factor(trade),
                    holding_minutes=int((timestamp - entry.timestamp).total_seconds() // 60),
                )
            )
            entry.remaining_shares -= matched_shares
            remaining_exit_shares -= matched_shares
            if entry.remaining_shares == 0:
                queue.popleft()
    return round_trips


def compute_execution_stats(
    trades: list[dict],
    date: Optional[str] = None,
) -> dict:
    """按个股聚合"当日信号执行"统计（不要求闭环）。

    用途：当 compute_round_trips 因缺 BUY 返回空时，仍可向用户展示：
      - 该股今天 T 信号触发了多少次
      - 实际执行了多少（shares > 0）
      - 跳过了多少次（持仓不足 / 今日已交易）
      - 当前持仓（最后一次 holding_qty_after）

    返回:
        {
            "by_symbol": {
                "<symbol>": {
                    "name": "中天科技",
                    "trades_count": 16,
                    "executed_count": 1,
                    "skipped_count": 15,
                    "last_holding_qty_after": 100,
                    "directions": {"SELL": 16, "BUY": 0},
                    "signals": ["放量拉升", "T仓锁利"],
                },
                ...
            },
            "total_trades": int,
            "total_executed": int,
            "total_skipped": int,
        }
    """
    trade_date = date or datetime.now().strftime("%Y-%m-%d")
    by_symbol: dict[str, dict] = {}
    total_trades = 0
    total_executed = 0
    total_skipped = 0

    for trade in trades:
        timestamp = _parse_timestamp(trade.get("timestamp"))
        if timestamp is None or timestamp.strftime("%Y-%m-%d") != trade_date:
            continue
        symbol = str(trade.get("symbol", "")).zfill(6)
        if not symbol or len(symbol) != 6:
            continue
        direction = str(trade.get("direction", "")).upper()
        if direction not in {"BUY", "SELL", "STOP_LOSS"}:
            continue
        shares = _positive_int(trade.get("shares"))
        skipped_reason = str(trade.get("skipped_reason", "")).strip()
        signal_name = str(trade.get("signal_name", "")).strip()
        name = str(trade.get("name", "")).strip()
        holding_after = trade.get("holding_qty_after")

        bucket = by_symbol.setdefault(symbol, {
            "name": name,
            "trades_count": 0,
            "executed_count": 0,
            "skipped_count": 0,
            "last_holding_qty_after": holding_after if holding_after is not None else 0,
            "directions": {},
            "signals": [],
            "last_timestamp": "",
        })
        bucket["trades_count"] += 1
        total_trades += 1
        bucket["directions"][direction] = bucket["directions"].get(direction, 0) + 1
        if signal_name and signal_name not in bucket["signals"]:
            bucket["signals"].append(signal_name)
        if shares > 0:
            bucket["executed_count"] += 1
            total_executed += 1
            bucket["last_holding_qty_after"] = int(holding_after) if holding_after is not None else bucket["last_holding_qty_after"]
        elif skipped_reason:
            bucket["skipped_count"] += 1
            total_skipped += 1
        ts_str = timestamp.isoformat(timespec="seconds")
        if ts_str > bucket["last_timestamp"]:
            bucket["last_timestamp"] = ts_str

    return {
        "by_symbol": dict(sorted(by_symbol.items())),
        "total_trades": total_trades,
        "total_executed": total_executed,
        "total_skipped": total_skipped,
    }


def compute_stats(trips: list[RoundTrip]) -> dict:
    """计算总胜率、盈亏比及按股票/入场因子分组统计。"""
    overall = _summarize(trips)
    by_symbol: dict[str, list[RoundTrip]] = defaultdict(list)
    by_factor: dict[str, list[RoundTrip]] = defaultdict(list)
    for trip in trips:
        by_symbol[trip.symbol].append(trip)
        by_factor[trip.entry_factor or "未知因子"].append(trip)
    overall["by_symbol"] = {
        key: _summarize(group)
        for key, group in sorted(by_symbol.items())
    }
    overall["by_factor"] = {
        key: _summarize(group)
        for key, group in sorted(by_factor.items())
    }
    return overall


def _summarize(trips: list[RoundTrip]) -> dict:
    count = len(trips)
    wins = sum(1 for trip in trips if trip.pnl > 0)
    losses = sum(1 for trip in trips if trip.pnl < 0)
    breakevens = count - wins - losses
    total_pnl = sum(trip.pnl for trip in trips)
    gross_profit = sum(trip.pnl for trip in trips if trip.pnl > 0)
    gross_loss = abs(sum(trip.pnl for trip in trips if trip.pnl < 0))
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "breakevens": breakevens,
        "win_rate": wins / count if count else 0.0,
        "total_pnl": total_pnl,
        "avg_pnl": total_pnl / count if count else 0.0,
        "avg_pnl_pct": (
            sum(trip.pnl_pct for trip in trips) / count if count else 0.0
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
    }


def _parse_timestamp(value: object) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _positive_int(value: object) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def _positive_float(value: object) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return normalized if normalized > 0 else 0.0


def _trade_factor(trade: dict) -> str:
    risk_action = str(trade.get("risk_action", "")).strip()
    if risk_action:
        return risk_action
    factor_hits = [str(item).strip() for item in trade.get("factor_hits", []) if str(item).strip()]
    if factor_hits:
        return "+".join(factor_hits)
    return str(trade.get("signal_name", "")).strip() or "未知因子"
