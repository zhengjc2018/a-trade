"""做 T 盘中监控。

状态模型（P1-4 修复）：

- sent: 字典 {symbol: [{"key": str, "sent_at": ISO timestamp}, ...]}
- 每次 scan 只产生候选告警，不写状态。
- 通知层确认成功后，把对应的 key 写入状态（带 TTL）。
- 失败时保留为未发送，允许下一次任务重试。

key 格式："{symbol}:{signal_type}:{trade_day}:{trigger_price:.2f}"
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

from atrade.backtest.t0_simulator import T0Simulator
from atrade.data import HistoryProvider
from atrade.indicators import add_all_indicators

_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "cache" / "t_monitor_state.json"

# 默认 TTL：同一信号在 TTL 窗口内不重复推送。
DEFAULT_TTL_HOURS = 6


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
    """盘中做 T 监控与信号去重（送达后提交 + TTL）。"""

    def __init__(self, config: Optional[dict] = None, ttl_hours: int = DEFAULT_TTL_HOURS):
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
        self.ttl_hours = ttl_hours
        self.history = HistoryProvider()
        self.engine = T0Simulator(scale=self.config.scale, datalen=self.config.datalen).engine
        self._state = self._load_state()

    def _load_state(self) -> dict:
        if not _STATE_FILE.exists():
            return {"sent": {}}
        try:
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if "sent" not in data:
                # 旧格式兼容：{"<symbol>": "<key>"} → {"sent": {"<symbol>": [...]}}
                converted = {"sent": {}}
                for k, v in data.items():
                    if isinstance(v, str):
                        converted["sent"].setdefault(k, []).append({
                            "key": v, "sent_at": datetime.now().isoformat(timespec="seconds"),
                        })
                return converted
            return data
        except Exception:
            return {"sent": {}}

    def _save_state(self) -> None:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _signal_key(symbol: str, signal_type: str, trade_day: str, trigger_price: float) -> str:
        return f"{symbol}:{signal_type}:{trade_day}:{trigger_price:.2f}"

    def _is_recently_sent(self, symbol: str, key: str) -> bool:
        """key 是否在 TTL 窗口内已发送。"""
        sent_list = self._state.get("sent", {}).get(symbol, [])
        now = datetime.now()
        for entry in sent_list:
            if entry.get("key") != key:
                continue
            try:
                sent_at = datetime.fromisoformat(entry["sent_at"])
            except (KeyError, ValueError):
                return False
            if now - sent_at <= timedelta(hours=self.ttl_hours):
                return True
        return False

    def commit_sent(self, alerts: list[dict]) -> None:
        """通知层确认成功后调用：把 alerts 标记为已发送。"""
        now_iso = datetime.now().isoformat(timespec="seconds")
        for a in alerts:
            symbol = a.get("symbol", "")
            key = a.get("__signal_key__")
            if not symbol or not key:
                continue
            bucket = self._state.setdefault("sent", {}).setdefault(symbol, [])
            bucket.append({"key": key, "sent_at": now_iso})
        self._save_state()

    def run_once(self) -> list[dict]:
        """返回需要推送的候选告警列表（不写状态）。"""
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
                    key = self._signal_key(
                        item.symbol,
                        sig.signal_type.value,
                        trade_day,
                        float(sig.trigger_price or 0.0),
                    )
                    if self._is_recently_sent(item.symbol, key):
                        continue
                    alerts.append({
                        "__signal_key__": key,
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
