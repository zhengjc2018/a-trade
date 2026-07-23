"""T 信号自动执行器。

T 信号触发后默认自动执行：
- SELL / STOP_LOSS：扣减持仓 1 手（lots_per_trade * 100 股），记录 trade
- BUY：仅记录 trade，不动持仓（不模拟加仓现金）

防重复：
- 同一只股票同一天同一方向最多 1 次（SELL/STOP_LOSS 共用 sell 槽位）
- 持仓 < 1 手 → SELL/STOP_LOSS 跳过
- 持仓 == 0 → T 扫描过滤（见 TMonitorRunner）
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

_TRADES_FILE = Path(__file__).resolve().parents[2] / "data" / "cache" / "t_trades.json"
_lock = threading.Lock()


@dataclass
class TTrade:
    timestamp: str
    symbol: str
    name: str
    direction: str  # "BUY" / "SELL" / "STOP_LOSS"
    shares: int
    lots: float
    price: float
    signal_name: str
    reason: str
    holding_qty_after: int
    skipped_reason: str = ""  # 若非空说明跳过原因


def load_trades() -> list[dict]:
    if not _TRADES_FILE.exists():
        return []
    try:
        return json.loads(_TRADES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_trade(trade: dict) -> None:
    with _lock:
        trades = load_trades()
        trades.append(trade)
        _TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _TRADES_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(trades, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_TRADES_FILE)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _already_traded_today(symbol: str, direction: str, today: Optional[str] = None) -> bool:
    today = today or _today()
    sym = str(symbol).zfill(6)
    for t in load_trades():
        if (
            str(t.get("symbol", "")).zfill(6) == sym
            and t.get("timestamp", "").startswith(today)
        ):
            # SELL 和 STOP_LOSS 共用 sell 槽
            d = t.get("direction", "")
            if direction in ("sell", "stop_loss") and d in ("SELL", "STOP_LOSS"):
                return True
            if direction == "buy" and d == "BUY":
                return True
    return False


def _current_holding(symbol: str) -> Optional[dict]:
    from atrade.config import load_holdings_with_meta
    sym = str(symbol).zfill(6)
    meta = load_holdings_with_meta()
    for h in meta.get("holdings", []):
        if str(h.get("symbol", "")).zfill(6) == sym:
            return h
    return None


def _update_holding_quantity(symbol: str, delta_shares: int) -> int:
    """在 holdings.local.json 里增减 quantity。返回最新 quantity。"""
    import os

    from atrade.config import LOCAL_HOLDINGS, load_holdings_with_meta

    sym = str(symbol).zfill(6)
    meta = load_holdings_with_meta()
    found = False
    for h in meta["holdings"]:
        if str(h.get("symbol", "")).zfill(6) == sym:
            h["quantity"] = max(0, int(h.get("quantity", 0)) + delta_shares)
            h["updated_at"] = datetime.now().isoformat(timespec="seconds")
            new_qty = h["quantity"]
            found = True
            break
    if not found:
        raise KeyError(f"symbol not in holdings: {sym}")
    # 原子写回 LOCAL_HOLDINGS（默认）
    path = LOCAL_HOLDINGS
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return new_qty


@dataclass
class ExecutorConfig:
    auto_execute: bool = True
    lots_per_trade: float = 1.0


class TTradeExecutor:
    """T 信号执行器（线程安全）。"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.config = ExecutorConfig(
            auto_execute=bool(cfg.get("auto_execute", True)),
            lots_per_trade=float(cfg.get("lots_per_trade", 1.0)),
        )

    def execute(self, alert: dict) -> Optional[dict]:
        """执行或跳过，返回 trade dict 或 None。

        alert 字段：symbol, name, signal_type, signal_name, reason, trigger_price, ...
        """
        if not self.config.auto_execute:
            return None

        symbol = str(alert.get("symbol", "")).zfill(6)
        if not symbol:
            return None
        sig = str(alert.get("signal_type", "watch")).lower()
        lots = max(0.01, float(self.config.lots_per_trade))
        shares = int(round(lots * 100))
        price = float(alert.get("trigger_price") or 0)
        now = datetime.now().isoformat(timespec="seconds")

        # 反重复：今天已执行过同方向 → 跳过
        if _already_traded_today(symbol, sig):
            trade = TTrade(
                timestamp=now, symbol=symbol,
                name=alert.get("name", ""), direction=sig.upper(),
                shares=0, lots=0, price=price,
                signal_name=alert.get("signal_name", ""),
                reason=alert.get("reason", ""),
                holding_qty_after=_current_qty(symbol),
                skipped_reason=f"今日已执行过 {sig.upper()}",
            )
            save_trade(asdict(trade))
            return asdict(trade)

        # SELL / STOP_LOSS：扣减持仓
        if sig in ("sell", "stop_loss"):
            holding = _current_holding(symbol)
            if holding is None:
                return None
            current_qty = int(holding.get("quantity", 0))
            if current_qty < shares:
                trade = TTrade(
                    timestamp=now, symbol=symbol,
                    name=holding.get("name", ""), direction=sig.upper(),
                    shares=0, lots=0, price=price,
                    signal_name=alert.get("signal_name", ""),
                    reason=alert.get("reason", ""),
                    holding_qty_after=current_qty,
                    skipped_reason=f"持仓不足（{current_qty} 股 < {shares} 股）",
                )
                save_trade(asdict(trade))
                return asdict(trade)
            try:
                new_qty = _update_holding_quantity(symbol, -shares)
            except KeyError:
                return None
            trade = TTrade(
                timestamp=now, symbol=symbol,
                name=holding.get("name", ""), direction=sig.upper(),
                shares=shares, lots=lots, price=price,
                signal_name=alert.get("signal_name", ""),
                reason=alert.get("reason", ""),
                holding_qty_after=new_qty,
            )
            save_trade(asdict(trade))
            logger.success(f"✅ T-trade 执行: {sig.upper()} {symbol} {shares}股 @ {price} (剩余 {new_qty} 股)")
            return asdict(trade)

        # BUY：仅记录，不动持仓
        holding = _current_holding(symbol)
        trade = TTrade(
            timestamp=now, symbol=symbol,
            name=(holding or {}).get("name", alert.get("name", "")),
            direction="BUY", shares=shares, lots=lots,
            price=price, signal_name=alert.get("signal_name", ""),
            reason=alert.get("reason", ""),
            holding_qty_after=(holding or {}).get("quantity", 0),
            skipped_reason="BUY 仅记账，不模拟加仓",
        )
        save_trade(asdict(trade))
        logger.info(f"📝 T-trade 记账: BUY {symbol} {shares}股 @ {price}")
        return asdict(trade)


def _current_qty(symbol: str) -> int:
    h = _current_holding(symbol)
    return int(h.get("quantity", 0)) if h else 0
