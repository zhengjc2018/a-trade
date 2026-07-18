"""做 T 信号检测引擎。

输出：
- SignalType: BUY（低吸）/ SELL（高抛）/ STOP_LOSS（止损）
- SignalStrength: WEAK / MEDIUM / STRONG
- 每个信号带触发原因、建议价格、目标价、止损价
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd
from loguru import logger


class SignalType(str, Enum):
    BUY = "buy"             # 低吸
    SELL = "sell"           # 高抛
    STOP_LOSS = "stop_loss"  # 止损
    WATCH = "watch"         # 仅观察


class SignalStrength(str, Enum):
    WEAK = "weak"
    MEDIUM = "medium"
    STRONG = "strong"


@dataclass
class Signal:
    """单个交易信号。"""
    symbol: str
    signal_type: SignalType
    strength: SignalStrength
    name: str                    # 信号名（如 "超卖反弹"）
    reason: str                  # 触发原因（人话）
    trigger_price: float         # 触发时价格
    target_price: Optional[float] = None   # 目标价
    stop_loss: Optional[float] = None       # 建议止损
    position_pct: float = 0.33   # 建议仓位比例（默认 1/3）
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))


class SignalEngine:
    """信号检测引擎。
    
    用法：
        engine = SignalEngine()
        signals = engine.scan("600519")
    """

    def scan(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """扫描单只股票的所有信号。"""
        if df is None or len(df) < 30:
            logger.warning(f"{symbol}: 数据不足（{len(df) if df is not None else 0} 行）")
            return []

        signals = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = latest["close"]

        # 信号 1: 超卖反弹（低吸）
        s = self._signal_oversold_rebound(symbol, df, latest, price)
        if s: signals.append(s)

        # 信号 2: 突破回踩（低吸）
        s = self._signal_breakout_pullback(symbol, df, latest, prev, price)
        if s: signals.append(s)

        # 信号 3: 放量拉升（高抛）
        s = self._signal_volume_surge(symbol, df, latest, prev, price)
        if s: signals.append(s)

        # 信号 4: MACD 顶背离（高抛）
        s = self._signal_macd_divergence(symbol, df, latest, price)
        if s: signals.append(s)

        # 信号 5: 跌破止损
        s = self._signal_stop_loss(symbol, df, latest, price)
        if s: signals.append(s)

        return signals

    # ============================================================
    # 信号 1: 超卖反弹
    # ============================================================
    def _signal_oversold_rebound(
        self, symbol: str, df: pd.DataFrame, latest: pd.Series, price: float
    ) -> Optional[Signal]:
        """RSI < 30 + 触及布林下轨 + 量比放大 → 超卖反弹"""
        rsi = latest.get("RSI6", 50)
        close = latest["close"]
        boll_lower = latest.get("BOLL_LOWER", close)

        if rsi < 30 and close <= boll_lower * 1.02:
            # 强度：RSI 越低越强
            strength = SignalStrength.STRONG if rsi < 20 else SignalStrength.MEDIUM
            target = close * 1.03  # 反弹 3%
            return Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                name="超卖反弹",
                reason=f"RSI6={rsi:.1f} 超卖，触及布林下轨 {boll_lower:.2f}",
                trigger_price=price,
                target_price=target,
                stop_loss=close * 0.97,
                position_pct=0.33,
            )
        return None

    # ============================================================
    # 信号 2: 突破回踩
    # ============================================================
    def _signal_breakout_pullback(
        self, symbol: str, df: pd.DataFrame, latest: pd.Series, prev: pd.Series, price: float
    ) -> Optional[Signal]:
        """最近 20 日新高 + 缩量回踩 → 低吸机会"""
        close = latest["close"]
        high_20 = df["high"].tail(20).max()

        # 突破条件：前一日 close > 前 19 日最高 且 当日 close 在突破价 2% 之内
        if prev["close"] >= high_20 * 0.99 and abs(close - high_20) / high_20 < 0.02:
            # 量能缩量（最新成交量 < 5 日均量）
            if latest["volume"] < latest["VOL_MA5"] * 0.85:
                return Signal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    strength=SignalStrength.MEDIUM,
                    name="突破回踩",
                    reason=f"突破 20 日新高 {high_20:.2f} 后缩量回踩",
                    trigger_price=price,
                    target_price=high_20 * 1.05,
                    stop_loss=high_20 * 0.97,
                    position_pct=0.33,
                )
        return None

    # ============================================================
    # 信号 3: 放量拉升
    # ============================================================
    def _signal_volume_surge(
        self, symbol: str, df: pd.DataFrame, latest: pd.Series, prev: pd.Series, price: float
    ) -> Optional[Signal]:
        """量比 > 2 + 涨幅 > 3% → 高抛"""
        vol_ratio = latest["volume"] / latest["VOL_MA5"] if latest["VOL_MA5"] > 0 else 1
        pct_chg = (latest['close'] - prev['close']) / prev['close'] * 100

        if vol_ratio > 2 and pct_chg > 3:
            return Signal(
                symbol=symbol,
                signal_type=SignalType.SELL,
                strength=SignalStrength.STRONG if vol_ratio > 3 else SignalStrength.MEDIUM,
                name="放量拉升",
                reason=f"量比 {vol_ratio:.1f} 放大，涨幅 {pct_chg:+.1f}%，建议减仓",
                trigger_price=price,
                target_price=price * 0.97,  # 短期回踩目标
                stop_loss=price * 1.03,
                position_pct=0.33,
            )
        return None

    # ============================================================
    # 信号 4: MACD 顶背离
    # ============================================================
    def _signal_macd_divergence(
        self, symbol: str, df: pd.DataFrame, latest: pd.Series, price: float
    ) -> Optional[Signal]:
        """价格新高 + MACD 不新高 → 顶背离，高抛"""
        if len(df) < 30:
            return None

        recent = df.tail(20)
        price_recent_high = recent["high"].max()
        macd_recent_high = recent["MACD_HIST"].max()

        # 当前价格接近 20 日新高，但 MACD HIST 比 20 日最高低
        if price >= price_recent_high * 0.98:
            latest_hist = latest["MACD_HIST"]
            if latest_hist < macd_recent_high * 0.5 and latest_hist < 0:
                return Signal(
                    symbol=symbol,
                    signal_type=SignalType.SELL,
                    strength=SignalStrength.STRONG,
                    name="MACD 顶背离",
                    reason=f"价格接近 20 日新高 {price_recent_high:.2f}，但 MACD HIST 背离（{latest_hist:.2f} vs 峰值 {macd_recent_high:.2f}）",
                    trigger_price=price,
                    target_price=price * 0.95,
                    stop_loss=price * 1.03,
                    position_pct=0.5,
                )
        return None

    # ============================================================
    # 信号 5: 跌破止损
    # ============================================================
    def _signal_stop_loss(
        self, symbol: str, df: pd.DataFrame, latest: pd.Series, price: float
    ) -> Optional[Signal]:
        """收盘跌破 MA20 → 趋势走弱"""
        close = latest["close"]
        ma20 = latest["MA20"]

        if close < ma20 * 0.98:
            return Signal(
                symbol=symbol,
                signal_type=SignalType.STOP_LOSS,
                strength=SignalStrength.STRONG,
                name="跌破 MA20",
                reason=f"收盘 {close:.2f} 跌破 MA20 ({ma20:.2f})，趋势转弱",
                trigger_price=price,
                stop_loss=close * 0.95,
                position_pct=0.5,
            )
        return None
