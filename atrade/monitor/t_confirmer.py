"""做 T 信号保守双阶段确认器。

设计目标：减少误报，宁可少做。

阶段一：候选（Candidate）
    TMonitorRunner.run_once() 仍由原引擎产生候选信号；
    此处把候选写入 _pending 队列，记录首次出现时间与触发价。

阶段二：确认（Confirmed）
    同一 symbol+signal_type 在 `confirm_bars` 个连续的扫描周期都命中，
    才升级为可推送信号。
    任一周期内信号消失 → 该候选丢弃，不放行。

STOP_LOSS：默认强制放行（趋势风险不可等待）。
candidate_ttl_minutes：候选超过该时间仍未确认则丢弃。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from loguru import logger

# 不需要走双阶段确认的信号类型（默认 STOP_LOSS）
BYPASS_TYPES = frozenset({"stop_loss"})


@dataclass
class Candidate:
    symbol: str
    signal_type: str
    strength: str
    signal_name: str
    reason: str
    trigger_price: float
    name: str = ""
    note: str = ""
    first_seen: datetime = field(default_factory=datetime.now)
    first_trigger_price: float | None = None
    hits: int = 1  # 连续命中次数
    last_seen: datetime = field(default_factory=datetime.now)

    def matches(self, other: Candidate) -> bool:
        """同一信号家族（同 symbol+signal_type）算同一候选。"""
        return self.symbol == other.symbol and self.signal_type == other.signal_type

    def update_from(self, other: Candidate) -> None:
        self.hits += 1
        self.last_seen = datetime.now()
        # 取较新或更"重"的字段；trigger_price 用新值（持续追踪），
        # first_trigger_price 在首次构造时设置，用于后续漂移检测
        self.strength = other.strength or self.strength
        self.signal_name = other.signal_name or self.signal_name
        self.reason = other.reason or self.reason
        self.trigger_price = other.trigger_price or self.trigger_price
        self.name = other.name or self.name
        self.note = other.note or self.note

    def to_alert_dict(self, signal_key: str) -> dict:
        return {
            "__signal_key__": signal_key,
            "symbol": self.symbol,
            "name": self.name,
            "signal_type": self.signal_type,
            "signal_name": self.signal_name,
            "reason": self.reason,
            "trigger_price": self.trigger_price,
            "strength": self.strength,
            "time": self.last_seen.strftime("%Y-%m-%d %H:%M"),
            "note": self.note,
            "hits": self.hits,
        }


@dataclass
class ConfirmerStats:
    pending: int = 0
    confirmed: int = 0
    expired: int = 0
    bypassed: int = 0


class TwoStageConfirmer:
    """双阶段确认器。

    Args:
        confirm_bars: 连续多少个扫描周期命中才放行（默认 2）
        candidate_ttl_minutes: 候选入队后超过该时间未确认则丢弃（默认 30）
    """

    def __init__(
        self,
        confirm_bars: int = 2,
        candidate_ttl_minutes: int = 30,
    ):
        self.confirm_bars = max(1, int(confirm_bars))
        self.candidate_ttl_minutes = max(1, int(candidate_ttl_minutes))
        self._pending: dict[tuple[str, str], Candidate] = {}
        self.stats = ConfirmerStats()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def reset(self) -> None:
        self._pending.clear()
        self.stats = ConfirmerStats()

    @staticmethod
    def _key(symbol: str, signal_type: str) -> tuple[str, str]:
        return (symbol, signal_type.lower())

    def _evict_expired(self, now: datetime) -> list[Candidate]:
        if not self._pending:
            return []
        expired: list[Candidate] = []
        ttl = timedelta(minutes=self.candidate_ttl_minutes)
        for key in list(self._pending.keys()):
            cand = self._pending[key]
            if now - cand.first_seen > ttl:
                expired.append(cand)
                del self._pending[key]
        if expired:
            self.stats.expired += len(expired)
            logger.debug(f"做T候选过期清理: {[c.symbol + ':' + c.signal_type for c in expired]}")
        return expired

    def filter(self, candidates: list[dict]) -> list[dict]:
        """接受当前候选，返回应当被放行的告警（已确认或 bypass）。

        Args:
            candidates: TMonitorRunner 扫描产出的候选告警列表。
                        每条至少包含 symbol/signal_type/strength/signal_name/
                        reason/trigger_price 等字段。

        Returns:
            可立即推送的告警列表（已带 __signal_key__）。
        """
        now = datetime.now()
        self._evict_expired(now)

        # 本次到来的 (symbol, signal_type) 集合
        seen_keys: set[tuple[str, str]] = set()
        confirmed: list[dict] = []
        bypassed: list[dict] = []

        for cand_dict in candidates:
            symbol = str(cand_dict.get("symbol", "")).zfill(6)
            sig_type = str(cand_dict.get("signal_type", "watch")).lower()
            key = self._key(symbol, sig_type)
            seen_keys.add(key)

            trigger_price = float(cand_dict.get("trigger_price") or 0.0)
            cand = Candidate(
                symbol=symbol,
                signal_type=sig_type,
                strength=str(cand_dict.get("strength", "")).lower(),
                signal_name=str(cand_dict.get("signal_name", "")),
                reason=str(cand_dict.get("reason", "")),
                trigger_price=trigger_price,
                first_trigger_price=trigger_price,
                name=str(cand_dict.get("name", "")),
                note=str(cand_dict.get("note", "")),
            )

            # bypass 类型（默认 STOP_LOSS）→ 立即放行
            if sig_type in BYPASS_TYPES:
                sig_key = f"{symbol}:{sig_type}:{cand.last_seen.strftime('%Y%m%d%H%M')}:{cand.trigger_price:.2f}"
                bypassed.append(cand.to_alert_dict(sig_key))
                # 同时从 pending 移除（避免后续被确认逻辑"误命中"）
                self._pending.pop(key, None)
                continue

            # 阶段一首次见到该候选 → 入队等待下次确认
            if key not in self._pending:
                self._pending[key] = cand
                continue

            existing = self._pending[key]
            # 触发价相对首次出现价漂移 > 1% 视为失效：用新候选替换旧的
            first_price = existing.first_trigger_price or existing.trigger_price
            if first_price and cand.trigger_price:
                drift = abs(cand.trigger_price - first_price) / first_price
                if drift > 0.01:
                    self._pending[key] = cand
                    self.stats.expired += 1
                    continue
            existing.update_from(cand)
            if existing.hits >= self.confirm_bars:
                sig_key = f"{symbol}:{sig_type}:{existing.last_seen.strftime('%Y%m%d%H%M')}:{existing.trigger_price:.2f}"
                confirmed.append(existing.to_alert_dict(sig_key))
                del self._pending[key]

        # 未在本轮再次出现的候选：视为信号消失，但保留 entry 等待下轮回归
        # 仅当 entry 已"老化"超过 1 个周期（默认 2 分钟扫描 → 4 分钟）才丢弃
        for key in list(self._pending.keys()):
            if key in seen_keys:
                continue
            cand = self._pending[key]
            age = now - cand.last_seen
            if age > timedelta(minutes=max(2, self.candidate_ttl_minutes // 2)):
                del self._pending[key]
                self.stats.expired += 1

        # 阶段二放行：把已确认的告警产出
        if confirmed:
            self.stats.confirmed += len(confirmed)
            logger.info(f"做T候选已确认: {[c['symbol'] + ':' + c['signal_type'] for c in confirmed]}")

        self.stats.pending = len(self._pending)
        return confirmed + bypassed

    def force_confirm(self, alerts: list[dict]) -> list[dict]:
        """手动把候选强制升级为已确认（运维 / 回放时使用）。"""
        for cand_dict in alerts:
            symbol = str(cand_dict.get("symbol", "")).zfill(6)
            sig_type = str(cand_dict.get("signal_type", "watch")).lower()
            key = self._key(symbol, sig_type)
            trigger_price = float(cand_dict.get("trigger_price") or 0.0)
            cand = Candidate(
                symbol=symbol,
                signal_type=sig_type,
                strength=str(cand_dict.get("strength", "")).lower(),
                signal_name=str(cand_dict.get("signal_name", "")),
                reason=str(cand_dict.get("reason", "")),
                trigger_price=trigger_price,
                first_trigger_price=trigger_price,
                name=str(cand_dict.get("name", "")),
                note=str(cand_dict.get("note", "")),
            )
            cand.hits = self.confirm_bars
            sig_key = f"{symbol}:{sig_type}:{cand.last_seen.strftime('%Y%m%d%H%M')}:{cand.trigger_price:.2f}"
            self._pending.pop(key, None)
            yield_confirmed = cand.to_alert_dict(sig_key)
            self.stats.confirmed += 1
            yield yield_confirmed
        self.stats.pending = len(self._pending)
