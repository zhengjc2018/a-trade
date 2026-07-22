"""做 T 盘中监控。

状态模型（P1-4 修复）：

- sent: 字典 {symbol: [{"key": str, "sent_at": ISO timestamp}, ...]}
- 每次 scan 只产生候选告警，不写状态。
- 通知层确认成功后，把对应的 key 写入状态（带 TTL）。
- 失败时保留为未发送，允许下一次任务重试。

双阶段确认（P1-6 修复）：

- run_once() 扫描得到候选信号。
- TwoStageConfirmer.filter() 把候选写入 _pending；连续 confirm_bars 个周期
  命中同一 symbol+signal_type 才升级为可推送告警。
- STOP_LOSS 默认走 BYPASS_TYPES，立即推送。
- 候选超过 candidate_ttl_minutes 自动丢弃。

key 格式："{symbol}:{signal_type}:{YYYYMMDDHHMM}:{trigger_price:.2f}"
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
from atrade.notify import (
    infer_conclusion,
    prepend_headline,
)

from .t_confirmer import TwoStageConfirmer

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
    confirm_bars: int = 2
    candidate_ttl_minutes: int = 30
    symbols: list[TMonitorItem] = field(default_factory=list)


class TMonitorRunner:
    """盘中做 T 监控与信号去重（送达后提交 + TTL + 双阶段确认）。"""

    def __init__(
        self,
        config: Optional[dict] = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        confirmer: Optional[TwoStageConfirmer] = None,
    ):
        cfg = config or {}
        self.config = TMonitorConfig(
            enabled=bool(cfg.get("enabled", True)),
            scan_interval_minutes=int(cfg.get("scan_interval_minutes", 2)),
            scale=str(cfg.get("scale", "5m")),
            datalen=int(cfg.get("datalen", 120)),
            confirm_bars=int(cfg.get("confirm_bars", 2)),
            candidate_ttl_minutes=int(cfg.get("candidate_ttl_minutes", 30)),
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
        self.confirmer = confirmer or TwoStageConfirmer(
            confirm_bars=self.config.confirm_bars,
            candidate_ttl_minutes=self.config.candidate_ttl_minutes,
        )
        self.scan_count = 0
        self.signal_count = 0  # 真正推送出去的告警
        self.candidate_count = 0  # 引擎产出候选数
        self.skipped_count = 0  # TTL 命中跳过
        self.error_count = 0

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
    def _signal_key(symbol: str, signal_type: str, when: datetime, trigger_price: float) -> str:
        return f"{symbol}:{signal_type}:{when.strftime('%Y%m%d%H%M')}:{trigger_price:.2f}"

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

    def _scan_candidates(self) -> list[dict]:
        """执行一次扫描，返回未经过滤的候选告警。"""
        candidates: list[dict] = []
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
                    candidates.append({
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
                self.error_count += 1
                logger.warning(f"做T监控 {item.symbol} 失败: {e}")
        return candidates

    def run_once(self) -> list[dict]:
        """扫描 → 双阶段确认 → TTL 去重，返回可推送的告警。

        顺序：
        1. 引擎扫描得到候选
        2. 走 confirmer.filter()：候选入队 / 升级 / 过期
        3. STOP_LOSS 走 bypass 直接放行
        4. TTL 命中跳过
        """
        if not self.config.enabled:
            return []

        self.scan_count += 1
        candidates = self._scan_candidates()
        self.candidate_count += len(candidates)

        confirmed = self.confirmer.filter(candidates)

        # TTL 命中再过滤一次（confirmer 不感知 TTL）
        alerts: list[dict] = []
        for a in confirmed:
            key = a.get("__signal_key__")
            if key and self._is_recently_sent(a.get("symbol", ""), key):
                self.skipped_count += 1
                continue
            # 补一个标准 key（confirmer 已经填了 __signal_key__）
            alerts.append(a)

        self.signal_count += len(alerts)
        return alerts

    def status_markdown(self) -> str:
        if self.error_count:
            base = f"⚠️ 今日做T扫描有 {self.error_count} 次异常，请检查数据源"
        elif self.signal_count:
            base = f"✅ 今日已推送 {self.signal_count} 条做T信号"
        else:
            base = "⏸️ 观望：今日暂无满足连续确认门槛的做T信号"
        # 顶部结论（同样头部置顶逻辑）
        conclusion = "buy" if self.signal_count else "no_signal"
        headline = (
            f"{'🟢' if conclusion == 'buy' else '⏸️'} 操作结论: "
            f"{'买入' if conclusion == 'buy' else '观望'} "
            f"({self.signal_count} 条已推送)"
        )
        return "\n".join([
            "# 🔎 做T状态汇总",
            "",
            headline,
            "",
            base,
            f"- 扫描次数：{self.scan_count}",
            f"- 引擎候选：{self.candidate_count}",
            f"- 已推送：{self.signal_count}",
            f"- TTL 跳过：{self.skipped_count}",
            f"- 待确认：{self.confirmer.pending_count}",
            f"- 确认门槛：{self.confirmer.confirm_bars} 根 + {self.confirmer.candidate_ttl_minutes} 分钟内",
            "- 说明：候选需连续命中才升级；STOP_LOSS 例外立即推送",
        ])

    @staticmethod
    def to_markdown(alerts: list[dict]) -> str:
        if not alerts:
            return ""
        conclusion, strength = infer_conclusion(alerts)
        symbols = sorted({a.get("symbol", "") for a in alerts if a.get("symbol")})
        body_lines = [
            "# 🔔 a-trade 做T信号",
            "",
            f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "| 代码 | 名称 | 信号 | 强度 | 触发价 | 说明 |",
            "|---|---|---|---|---:|---|",
        ]
        for a in alerts:
            body_lines.append(
                f"| {a['symbol']} | {a.get('name', '')} | {a['signal_name']} | {a['strength']} | "
                f"{float(a.get('trigger_price') or 0):.2f} | {str(a['reason'])[:80]} |"
            )
        body_lines.extend([
            "",
            "---",
            "_⚠️ 仅供参考，投资有风险_",
        ])
        return prepend_headline(
            "\n".join(body_lines),
            conclusion=conclusion,
            strength=strength,
            symbols=symbols,
        )
