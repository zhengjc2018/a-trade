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
from atrade.market import MarketRegimeFilter, allows_signal
from atrade.notify import (
    infer_conclusion,
    prepend_headline,
)

from .t_confirmer import TwoStageConfirmer
from .t_state import TStateStore
from .t_trailing import TrailingConfig, check_trailing

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
    trailing: TrailingConfig = field(default_factory=TrailingConfig)


@dataclass
class TMonitorConfig:
    enabled: bool = True
    scan_interval_minutes: int = 2
    scale: str = "5m"
    datalen: int = 120
    confirm_bars: int = 2
    candidate_ttl_minutes: int = 30
    allow_non_main_board: bool = False  # 默认排除 ST/创业板/科创板/京板
    lots_per_trade: float = 1.0
    buy_momentum_threshold_pct: float = 5.0  # 个股 5 日动量 ≥ 此值则 BUY 双闸门短路
    trailing_defaults: dict = field(default_factory=dict)
    symbols: list[TMonitorItem] = field(default_factory=list)


class TMonitorRunner:
    """盘中做 T 监控与信号去重（送达后提交 + TTL + 双阶段确认）。"""

    def __init__(
        self,
        config: Optional[dict] = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
        confirmer: Optional[TwoStageConfirmer] = None,
        history=None,
        engine=None,
        regime_filter=None,
        t_state_store: Optional[TStateStore] = None,
    ):
        cfg = config or {}
        trailing_defaults = dict(cfg.get("trailing_defaults") or {})
        lots_per_trade = float(cfg.get("lots_per_trade", 1.0))
        buy_momentum_threshold = float(
            cfg.get("buy_momentum_threshold_pct", 5.0)
        )
        self.config = TMonitorConfig(
            enabled=bool(cfg.get("enabled", True)),
            scan_interval_minutes=int(cfg.get("scan_interval_minutes", 2)),
            scale=str(cfg.get("scale", "5m")),
            datalen=int(cfg.get("datalen", 120)),
            confirm_bars=int(cfg.get("confirm_bars", 2)),
            candidate_ttl_minutes=int(cfg.get("candidate_ttl_minutes", 30)),
            allow_non_main_board=bool(cfg.get("allow_non_main_board", False)),
            lots_per_trade=lots_per_trade,
            buy_momentum_threshold_pct=buy_momentum_threshold,
            trailing_defaults=trailing_defaults,
            symbols=[
                TMonitorItem(
                    symbol=str(item.get("symbol", "")).zfill(6),
                    name=str(item.get("name", "")),
                    cost_price=float(item.get("cost_price", 0.0)),
                    quantity=int(item.get("quantity", 0)),
                    note=str(item.get("note", "")),
                    trailing=TrailingConfig.from_dict(
                        trailing_defaults,
                        item.get("trailing") or {},
                        exit_lots=lots_per_trade,
                    ),
                )
                for item in (cfg.get("symbols") or [])
                if item.get("symbol")
            ],
        )
        self.ttl_hours = ttl_hours
        self.history = history or HistoryProvider()
        self.engine = engine or T0Simulator(
            scale=self.config.scale,
            datalen=self.config.datalen,
        ).engine
        self.regime_filter = (
            regime_filter
            or MarketRegimeFilter(
                buy_momentum_threshold_pct=buy_momentum_threshold,
            )
        )
        self.t_state_store = t_state_store or TStateStore()
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
        self.filtered_count = 0
        self.holdings_skipped_count = 0  # 持仓/已交易过滤掉的卖出候选

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

    def _filter_candidates_by_holdings(
        self, candidates: list[dict],
    ) -> tuple[list[dict], list[dict]]:
        """按"持仓量 + 今日已交易"过滤卖出/止损候选。

        设计目的：避免同一只股票当天重复推送卖出告警。
        逻辑：
          - SELL / STOP_LOSS 信号检查 holdings.quantity 是否 ≥ 1 手
            （lots_per_trade * 100 股）；不足 → 丢弃
          - 同一只股票同一天已执行过 sell/stop_loss → 丢弃（防"今天一直卖"）
          - BUY 不受影响（建仓方向）
          - 不在 holdings 中的标的 → 直接丢弃卖出信号

        返回 (保留的候选, 被过滤掉的候选含原因) 元组，方便日志与统计。
        """
        from .t_executor import _already_traded_today, _current_holding

        lots = max(0.01, float(self.config.lots_per_trade))
        shares_per_lot = max(1, int(round(lots * 100)))
        kept: list[dict] = []
        dropped: list[dict] = []
        for cand in candidates:
            symbol = str(cand.get("symbol", "")).zfill(6)
            sig = str(cand.get("signal_type", "watch")).lower()
            if sig not in {"sell", "stop_loss"}:
                kept.append(cand)
                continue
            holding = _current_holding(symbol)
            if holding is None:
                dropped.append({**cand, "_drop_reason": "未配置持仓"})
                continue
            qty = int(holding.get("quantity", 0))
            if qty < shares_per_lot:
                dropped.append({
                    **cand,
                    "_drop_reason": f"持仓 {qty} 股 < {shares_per_lot} 股",
                })
                continue
            if _already_traded_today(symbol, sig):
                dropped.append({
                    **cand,
                    "_drop_reason": f"今日已执行过 {sig.upper()}",
                })
                continue
            kept.append(cand)
        return kept, dropped

    def _scan_candidates(self) -> list[dict]:
        """扫描并应用个股日线、大盘双闸门和 T 仓风险退出。"""
        candidates: list[dict] = []
        market_gate = self.regime_filter.get_market_gate()
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
                latest = df_ind.iloc[-1]
                current_price = float(latest.get("close") or 0.0)
                trade_day = str(latest.get("date", ""))[:10]

                state = self.t_state_store.update_peak(item.symbol, current_price)
                risk_action = check_trailing(state, current_price, item.trailing)
                if risk_action is not None:
                    candidates.append(self._build_risk_candidate(item, risk_action, trade_day))
                    continue

                signals = self.engine.scan(item.symbol, df_ind)
                if not signals:
                    continue

                symbol_trend = None
                for sig in signals:
                    if sig.signal_type.value == "buy" and symbol_trend is None:
                        symbol_trend = self.regime_filter.get_symbol_trend(item.symbol)
                    allowed, filter_reason = allows_signal(
                        sig.signal_type.value,
                        symbol_trend or market_gate,
                        market_gate,
                        buy_momentum_threshold_pct=(
                            self.config.buy_momentum_threshold_pct
                        ),
                    )
                    if not allowed:
                        self.filtered_count += 1
                        logger.info(
                            f"做T信号过滤 {item.symbol} {sig.signal_type.value}: {filter_reason}"
                        )
                        continue
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
                        "factor_hits": list(sig.factor_hits),
                    })
            except Exception as e:
                self.error_count += 1
                logger.warning(f"做T监控 {item.symbol} 失败: {e}")
        return candidates

    @staticmethod
    def _build_risk_candidate(item, action, trade_day: str) -> dict:
        if action.action == "take_profit":
            signal_name = "T仓锁利"
        else:
            signal_name = "T仓止损"
        return {
            "symbol": item.symbol,
            "name": item.name or item.symbol,
            "signal_type": action.signal_type,
            "signal_name": signal_name,
            "reason": action.reason,
            "trigger_price": action.price,
            "strength": "strong",
            "time": trade_day,
            "note": item.note,
            "factor_hits": [action.action],
            "__risk_action__": action.action,
            "__execution_lots__": action.lots,
            "__bypass_confirm__": True,
        }

    def reset_t_state_day(self, date: Optional[str] = None) -> None:
        self.t_state_store.reset_day(date)

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

        candidates, dropped = self._filter_candidates_by_holdings(candidates)
        if dropped:
            self.holdings_skipped_count += len(dropped)
            for d in dropped:
                logger.info(
                    f"做T信号过滤 {d['symbol']} {d.get('signal_type')}: "
                    f"{d.get('_drop_reason')}"
                )

        risk_candidates = [item for item in candidates if item.get("__bypass_confirm__")]
        normal_candidates = [item for item in candidates if not item.get("__bypass_confirm__")]
        confirmed = self.confirmer.filter(normal_candidates)
        for item in risk_candidates:
            risk_action = item.get("__risk_action__", "risk")
            item["__signal_key__"] = (
                f"{item.get('symbol', '')}:{risk_action}:{item.get('time', '')}"
            )
            item["hits"] = 1
            confirmed.append(item)

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
            f"- 趋势过滤：{self.filtered_count}",
            f"- 持仓/已交易过滤：{self.holdings_skipped_count}",
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
