"""做 T 盘中监控。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from atrade.backtest.t0_simulator import T0Simulator
from atrade.data import HistoryProvider
from atrade.indicators import add_all_indicators


_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "cache" / "t_monitor_state.json"


@dataclass
class TMonitorItem:
    symbol: str
    name: str = ""
    cost_price: float = 0.0
    quantity: int = 0
    note: str = ""


@dataclass
class TMonitorConfig:
    enabled: bool = True
    scan_interval_minutes: int = 2
    scale: str = "5m"
    datalen: int = 120
    symbols: list[TMonitorItem] = field(default_factory=list)


class TMonitorRunner:
    """盘中做 T 监控与信号去重。"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.config = TMonitorConfig(
            enabled=bool(cfg.get("enabled", True)),
            scan_interval_minutes=int(cfg.get("scan_interval_minutes", 2)),
            scale=str(cfg.get("scale", "5m")),
            datalen=int(cfg.get("datalen", 120)),
            symbols=[
                TMonitorItem(
                    symbol=str(item.get("symbol", "")).zfill(6),
                    name=str(item.get("name", "")),
                    cost_price=float(item.get("cost_price", 0.0)),
                    quantity=int(item.get("quantity", 0)),
                    note=str(item.get("note", "")),
                )
                for item in (cfg.get("symbols") or [])
                if item.get("symbol")
            ],
        )
        self.history = HistoryProvider()
        self.engine = T0Simulator(scale=self.config.scale, datalen=self.config.datalen).engine
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if not _STATE_FILE.exists():
            return {}
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _signal_key(symbol: str, signal_type: str, trade_day: str, trigger_price: float) -> str:
        return f"{symbol}:{signal_type}:{trade_day}:{trigger_price:.2f}"

    def run_once(self) -> list[dict]:
        """返回需要推送的信号列表。"""
        if not self.config.enabled:
            return []

        alerts: list[dict] = []
        for item in self.config.symbols:
            try:
                df = self.history.fetch_with_cache(
                    item.symbol,
                    scale=self.config.scale,
                    datalen=self.config.datalen,
                    use_snapshot=False,
                )
                if df.empty or len(df) < 30:
                    continue
                df_ind = add_all_indicators(df).reset_index(drop=True)
                signals = self.engine.scan(item.symbol, df_ind)
                if not signals:
                    continue

                latest = df_ind.iloc[-1]
                trade_day = str(latest.get("date", ""))[:10]
                for sig in signals:
                    key = self._signal_key(item.symbol, sig.signal_type.value, trade_day, float(sig.trigger_price or 0.0))
                    if self._state.get(item.symbol) == key:
                        continue
                    self._state[item.symbol] = key
                    alerts.append({
                        "symbol": item.symbol,
                        "name": item.name or item.symbol,
                        "signal_type": sig.signal_type.value,
                        "signal_name": sig.name,
                        "reason": sig.reason,
                        "trigger_price": sig.trigger_price,
                        "strength": sig.strength.value,
                        "time": trade_day,
                        "note": item.note,
                    })
            except Exception as e:
                logger.warning(f"做T监控 {item.symbol} 失败: {e}")

        if alerts:
            self._save_state()
        return alerts

    @staticmethod
    def to_markdown(alerts: list[dict]) -> str:
        if not alerts:
            return ""
        lines = [
            "# 🔔 a-trade 做T信号",
            "",
            "| 代码 | 名称 | 信号 | 强度 | 触发价 | 说明 |",
            "|---|---|---|---|---:|---|",
        ]
        for a in alerts:
            lines.append(
                f"| {a['symbol']} | {a['name']} | {a['signal_name']} | {a['strength']} | "
                f"{float(a.get('trigger_price') or 0):.2f} | {a['reason'][:80]} |"
            )
        return "\n".join(lines)
