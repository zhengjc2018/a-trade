"""做 T 当日持仓状态持久化。"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal, Optional

from loguru import logger

DEFAULT_T_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "cache" / "t_state.json"
_FILE_LOCK = threading.RLock()

TStateStatus = Literal["empty", "holding", "locked"]


@dataclass
class TState:
    symbol: str
    trade_date: str = ""
    status: TStateStatus = "empty"
    entry_price: float = 0.0
    entry_time: str = ""
    peak_price: float = 0.0
    lots: float = 0.0
    entry_signal: str = ""


class TStateStore:
    """按股票保存当日 T 仓状态。"""

    def __init__(
        self,
        path: Optional[Path] = None,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.path = Path(path) if path is not None else DEFAULT_T_STATE_FILE
        self.now = now

    def get(self, symbol: str) -> TState:
        normalized_symbol = _normalize_symbol(symbol)
        today = self.now().strftime("%Y-%m-%d")
        with _FILE_LOCK:
            payload = self._read_unlocked()
        if payload.get("trade_date") != today:
            return _empty_state(normalized_symbol, today)

        raw_state = payload.get("states", {}).get(normalized_symbol)
        return _state_from_dict(normalized_symbol, today, raw_state)

    def set(self, symbol: str, state: TState) -> None:
        normalized_symbol = _normalize_symbol(symbol)
        if state.status not in {"empty", "holding", "locked"}:
            raise ValueError(f"无效 status: {state.status}")
        normalized_state = replace(state, symbol=normalized_symbol)
        with _FILE_LOCK:
            payload = self._read_unlocked()
            if payload.get("trade_date") != normalized_state.trade_date:
                payload = {"trade_date": normalized_state.trade_date, "states": {}}
            raw_state = asdict(normalized_state)
            raw_state.pop("symbol")
            payload["states"][normalized_symbol] = raw_state
            self._write_unlocked(payload)

    def mark_buy(
        self,
        symbol: str,
        entry_price: float,
        lots: float,
        entry_signal: str,
        timestamp: Optional[str] = None,
    ) -> TState:
        if entry_price <= 0:
            raise ValueError("entry_price 必须 > 0")
        if lots <= 0:
            raise ValueError("lots 必须 > 0")
        entry_time = timestamp or self.now().isoformat(timespec="seconds")
        try:
            trade_date = datetime.fromisoformat(entry_time).strftime("%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"timestamp 格式无效: {entry_time}") from error
        state = TState(
            symbol=_normalize_symbol(symbol),
            trade_date=trade_date,
            status="holding",
            entry_price=float(entry_price),
            entry_time=entry_time,
            peak_price=float(entry_price),
            lots=float(lots),
            entry_signal=str(entry_signal),
        )
        self.set(symbol, state)
        return state

    def update_peak(self, symbol: str, current_price: float) -> TState:
        state = self.get(symbol)
        if state.status != "holding" or current_price <= state.peak_price:
            return state
        state.peak_price = float(current_price)
        self.set(symbol, state)
        return state

    def mark_exit(self, symbol: str, status: TStateStatus = "empty") -> TState:
        if status not in {"empty", "locked"}:
            raise ValueError(f"退出 status 只能为 empty 或 locked，实际: {status}")
        state = self.get(symbol)
        state.status = status
        state.lots = 0.0
        self.set(symbol, state)
        return state

    def reset_day(self, date: Optional[str] = None) -> None:
        trade_date = date or self.now().strftime("%Y-%m-%d")
        try:
            datetime.strptime(trade_date, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError(f"date 格式必须为 YYYY-MM-DD，实际: {trade_date}") from error
        with _FILE_LOCK:
            self._write_unlocked({"trade_date": trade_date, "states": {}})

    def _read_unlocked(self) -> dict:
        if not self.path.exists():
            return {"trade_date": "", "states": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("states"), dict):
                raise ValueError("状态文件根结构无效")
            return payload
        except Exception as error:
            logger.warning(f"T 状态文件损坏，按空状态恢复: {self.path}: {error}")
            return {"trade_date": "", "states": {}}

    def _write_unlocked(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.path)


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().zfill(6)
    if not normalized.isdigit() or len(normalized) != 6:
        raise ValueError(f"symbol 必须为 6 位数字，实际: {symbol}")
    return normalized


def _empty_state(symbol: str, trade_date: str) -> TState:
    return TState(symbol=symbol, trade_date=trade_date)


def _state_from_dict(symbol: str, trade_date: str, raw_state: object) -> TState:
    if not isinstance(raw_state, dict):
        return _empty_state(symbol, trade_date)
    try:
        status = str(raw_state.get("status", "empty"))
        if status not in {"empty", "holding", "locked"}:
            raise ValueError(f"无效 status: {status}")
        return TState(
            symbol=symbol,
            trade_date=trade_date,
            status=status,
            entry_price=float(raw_state.get("entry_price", 0.0)),
            entry_time=str(raw_state.get("entry_time", "")),
            peak_price=float(raw_state.get("peak_price", 0.0)),
            lots=float(raw_state.get("lots", 0.0)),
            entry_signal=str(raw_state.get("entry_signal", "")),
        )
    except (TypeError, ValueError) as error:
        logger.warning(f"T 状态记录无效 {symbol}，按空状态恢复: {error}")
        return _empty_state(symbol, trade_date)
