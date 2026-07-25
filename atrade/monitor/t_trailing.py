"""做 T 锁利与止损判断。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Optional

from .t_state import TState

DEFAULT_TAKE_PROFIT_PCT = 0.03
DEFAULT_STOP_LOSS_PCT = 0.02
DEFAULT_EXIT_LOTS = 1.0


@dataclass(frozen=True)
class TrailingConfig:
    take_profit_pct: float = DEFAULT_TAKE_PROFIT_PCT
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT
    exit_lots: float = DEFAULT_EXIT_LOTS

    @classmethod
    def from_dict(
        cls,
        defaults: Optional[Mapping[str, object]] = None,
        override: Optional[Mapping[str, object]] = None,
        exit_lots: float = DEFAULT_EXIT_LOTS,
    ) -> TrailingConfig:
        default_values = defaults or {}
        override_values = override or {}
        take_profit_pct = _resolve_percentage(
            "take_profit_pct",
            default_values,
            override_values,
            DEFAULT_TAKE_PROFIT_PCT,
        )
        stop_loss_pct = _resolve_percentage(
            "stop_loss_pct",
            default_values,
            override_values,
            DEFAULT_STOP_LOSS_PCT,
        )
        normalized_exit_lots = _positive_number(exit_lots, "exit_lots")
        return cls(
            take_profit_pct=take_profit_pct,
            stop_loss_pct=stop_loss_pct,
            exit_lots=normalized_exit_lots,
        )


@dataclass(frozen=True)
class TrailingAction:
    action: str
    signal_type: str
    price: float
    lots: float
    reason: str
    gain_pct: float


def check_trailing(
    state: TState,
    current_price: float,
    config: TrailingConfig,
) -> Optional[TrailingAction]:
    """根据 T 仓入场价判断是否到达锁利或止损线。"""
    if state.status != "holding" or state.entry_price <= 0 or state.lots <= 0:
        return None
    if current_price <= 0 or not math.isfinite(current_price):
        return None

    gain_pct = current_price / state.entry_price - 1.0
    lots = min(float(state.lots), float(config.exit_lots))
    if gain_pct >= config.take_profit_pct:
        return TrailingAction(
            action="take_profit",
            signal_type="sell",
            price=float(current_price),
            lots=lots,
            reason=(
                f"T 仓收益 {gain_pct:+.2%}，达到 +{config.take_profit_pct:.2%} 锁利线"
            ),
            gain_pct=gain_pct,
        )
    if gain_pct <= -config.stop_loss_pct:
        return TrailingAction(
            action="stop_loss",
            signal_type="stop_loss",
            price=float(current_price),
            lots=lots,
            reason=(
                f"T 仓收益 {gain_pct:+.2%}，达到 -{config.stop_loss_pct:.2%} 止损线"
            ),
            gain_pct=gain_pct,
        )
    return None


def _resolve_percentage(
    field: str,
    defaults: Mapping[str, object],
    override: Mapping[str, object],
    fallback: float,
) -> float:
    value = override.get(field)
    if value in {None, ""}:
        value = defaults.get(field)
    if value in {None, ""}:
        value = fallback
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须为 0 和 1 之间的数字")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 < normalized < 1:
        raise ValueError(f"{field} 必须在 0 和 1 之间")
    return normalized


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须为正数")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(f"{field} 必须为正数")
    return normalized
