"""做 T 信号检测引擎。

本版本针对"满仓被套做 T"场景设计。

信号类型:
- SignalType.BUY：低吸（建 T 仓）
- SignalType.SELL：高抛（清 T 仓）
- SignalType.STOP_LOSS：趋势性止损
- SignalType.WATCH：仅观察，不动手

评分体系:
- 每个信号带 strength: WEAK / MEDIUM / STRONG
- strength 由"因子共振数"决定：1 个因子命中 WEAK，2 个 MEDIUM，3+ 个 STRONG

因子集合（新增的设计思路）:
1. **波段反弹**：60 日跌幅 > 15% + 近 3 日缩量 + RSI 在 30-50 区间
2. **趋势确认**：MA5 上穿 MA10 + 量比 > 1.2
3. **放量突破**：突破 60 日新高 + 量比 > 1.5
4. **超卖反弹**：RSI < 25 + 触及 BOLL 下轨 + 量比放大
5. **放量拉升**（SELL）：量比 > 3 + 涨幅 > 5%
6. **MACD 顶背离**（SELL）：价格新高 + MACD HIST 不新高
7. **跌破 MA20**（STOP_LOSS）：连续 3 日 close < MA20
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import pandas as pd
from loguru import logger


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    STOP_LOSS = "stop_loss"
    WATCH = "watch"


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
    name: str
    reason: str
    trigger_price: float
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    position_pct: float = 0.33
    # 用于回测 / 显示
    factor_hits: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))


class SignalEngine:
    """信号检测引擎。"""

    def scan(self, symbol: str, df: pd.DataFrame) -> list[Signal]:
        """扫描所有信号，按 direction 分组返回 BUY / SELL / STOP_LOSS。"""
        if df is None or len(df) < 30:
            return []

        signals: list[Signal] = []
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        price = latest["close"]

        # ---- BUY 信号：收集各因子，合并为打分 ----
        buy_factors: list[tuple[str, str]] = []  # (factor_name, reason)

        # 因子 1: 波段反弹（60 日跌幅 > 15% + 缩量 + RSI 在 30-50）
        h = self._factor_wave_rebound(df, latest)
        if h: buy_factors.append(h)

        # 因子 2: 趋势确认（MA5 上穿 MA10 + 量比放大）
        h = self._factor_trend_confirm(df, latest, prev)
        if h: buy_factors.append(h)

        # 因子 3: 放量突破（60 日新高 + 量比 > 1.5）
        h = self._factor_breakout(df, latest)
        if h: buy_factors.append(h)

        # 因子 4: 超卖反弹（RSI < 25 + 触及 BOLL 下轨）
        h = self._factor_oversold(df, latest)
        if h: buy_factors.append(h)

        if buy_factors:
            n = len(buy_factors)
            strength = SignalStrength.STRONG if n >= 3 else (
                SignalStrength.MEDIUM if n == 2 else SignalStrength.WEAK
            )
            reasons = "；".join(r for _, r in buy_factors)
            factor_names = [f for f, _ in buy_factors]
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.BUY,
                strength=strength,
                name=f"BUY({n}因子共振)",
                reason=f"共振因子: {', '.join(factor_names)}。{reasons}",
                trigger_price=price,
                target_price=price * 1.03,
                stop_loss=price * 0.97,
                position_pct=0.33,
                factor_hits=factor_names,
            ))

        # ---- SELL 信号 ----
        for s in self._signals_sell(df, latest, prev, price, symbol):
            signals.append(s)

        # ---- STOP_LOSS：连续 3 日 close < MA20 才触发（更保守）----
        if self._check_stop_loss_strict(df, latest):
            signals.append(Signal(
                symbol=symbol,
                signal_type=SignalType.STOP_LOSS,
                strength=SignalStrength.STRONG,
                name="跌破MA20(连续3日)",
                reason="连续 3 日收盘低于 MA20，趋势走弱",
                trigger_price=price,
                stop_loss=price * 0.95,
                position_pct=0.5,
            ))

        return signals

    # ============================================================
    # BUY 因子
    # ============================================================
    def _factor_wave_rebound(self, df: pd.DataFrame, latest: pd.Series
                              ) -> Optional[tuple[str, str]]:
        """波段反弹：60 日跌幅 > 15% + 近 3 日缩量 + RSI 30-50。"""
        if len(df) < 60:
            return None
        close_60d_ago = df["close"].iloc[-61] if len(df) >= 61 else df["close"].iloc[0]
        drop_pct = (latest["close"] - close_60d_ago) / close_60d_ago * 100
        if drop_pct > -15:
            return None
        # 近 3 日均量 vs VOL_MA5
        recent3_vol = df["volume"].iloc[-3:].mean()
        vol_ma5 = latest.get("VOL_MA5", recent3_vol)
        if recent3_vol >= vol_ma5:
            return None
        rsi = latest.get("RSI6", 50)
        if not (30 <= rsi <= 50):
            return None
        return ("波段反弹",
                f"60日跌幅 {drop_pct:.1f}%，3日均量 {recent3_vol:.0f} < VOL_MA5 {vol_ma5:.0f}，RSI6={rsi:.1f}")

    def _factor_trend_confirm(self, df: pd.DataFrame,
                               latest: pd.Series, prev: pd.Series
                               ) -> Optional[tuple[str, str]]:
        """趋势确认：MA5 上穿 MA10 + 量比 > 1.2。"""
        ma5 = latest.get("MA5")
        ma10 = latest.get("MA10")
        prev_ma5 = prev.get("MA5")
        prev_ma10 = prev.get("MA10")
        if any(pd.isna([ma5, ma10, prev_ma5, prev_ma10])):
            return None
        # 上穿：前一日 ma5 <= ma10，今日 ma5 > ma10
        if not (prev_ma5 <= prev_ma10 and ma5 > ma10):
            return None
        vol_ma5 = latest.get("VOL_MA5", 0)
        if vol_ma5 <= 0:
            return None
        vol_ratio = latest["volume"] / vol_ma5
        if vol_ratio < 1.2:
            return None
        return ("趋势确认",
                f"MA5({ma5:.2f}) 上穿 MA10({ma10:.2f})，量比 {vol_ratio:.2f}")

    def _factor_breakout(self, df: pd.DataFrame, latest: pd.Series
                          ) -> Optional[tuple[str, str]]:
        """放量突破：突破 60 日新高 + 量比 > 1.5。"""
        high_60 = df["high"].iloc[-60:].max()
        if latest["close"] < high_60 * 0.995:
            return None
        vol_ma5 = latest.get("VOL_MA5", 0)
        if vol_ma5 <= 0:
            return None
        vol_ratio = latest["volume"] / vol_ma5
        if vol_ratio < 1.5:
            return None
        return ("放量突破", f"突破 60 日新高 {high_60:.2f}，量比 {vol_ratio:.2f}")

    def _factor_oversold(self, df: pd.DataFrame, latest: pd.Series
                          ) -> Optional[tuple[str, str]]:
        """超卖反弹：RSI < 25 + 触及 BOLL 下轨 + 量比放大。"""
        rsi = latest.get("RSI6", 50)
        close = latest["close"]
        boll_lower = latest.get("BOLL_LOWER", close)
        if rsi >= 25 or close > boll_lower * 1.02:
            return None
        vol_ma5 = latest.get("VOL_MA5", 0)
        if vol_ma5 <= 0:
            return None
        vol_ratio = latest["volume"] / vol_ma5
        if vol_ratio < 1.3:
            return None
        return ("超卖反弹",
                f"RSI6={rsi:.1f}, 触及 BOLL 下轨 {boll_lower:.2f}, 量比 {vol_ratio:.2f}")

    # ============================================================
    # SELL 信号（保留放量拉升 + MACD 顶背离）
    # ============================================================
    def _signals_sell(self, df: pd.DataFrame, latest: pd.Series,
                       prev: pd.Series, price: float, symbol: str
                       ) -> list[Signal]:
        out = []
        # 放量拉升
        vol_ma5 = latest.get("VOL_MA5", 0)
        if vol_ma5 > 0:
            vol_ratio = latest["volume"] / vol_ma5
            pct_chg = (latest["close"] - prev["close"]) / prev["close"] * 100
            if vol_ratio > 3 and pct_chg > 5:
                out.append(Signal(
                    symbol=symbol, signal_type=SignalType.SELL,
                    strength=SignalStrength.STRONG,
                    name="放量拉升",
                    reason=f"量比 {vol_ratio:.2f}, 涨幅 {pct_chg:.1f}%",
                    trigger_price=price,
                    target_price=price * 0.97, stop_loss=price * 1.03,
                    position_pct=0.33,
                ))
        # MACD 顶背离
        if len(df) >= 30:
            recent = df.tail(20)
            price_recent_high = recent["high"].max()
            macd_recent_high = recent["MACD_HIST"].max()
            if latest["close"] >= price_recent_high * 0.98:
                latest_hist = latest["MACD_HIST"]
                if (latest_hist < macd_recent_high * 0.5
                        and latest_hist < 0):
                    out.append(Signal(
                        symbol=symbol, signal_type=SignalType.SELL,
                        strength=SignalStrength.STRONG,
                        name="MACD 顶背离",
                        reason=f"价格近 20 日新高 {price_recent_high:.2f}，MACD HIST 背离 ({latest_hist:.2f} vs {macd_recent_high:.2f})",
                        trigger_price=price,
                        target_price=price * 0.95, stop_loss=price * 1.03,
                        position_pct=0.5,
                    ))
        return out

    # ============================================================
    # STOP_LOSS（严格版：连续 3 日）
    # ============================================================
    def _check_stop_loss_strict(self, df: pd.DataFrame,
                                 latest: pd.Series) -> bool:
        if len(df) < 3:
            return False
        ma20 = latest.get("MA20")
        if pd.isna(ma20):
            return False
        if latest["close"] >= ma20 * 0.98:
            return False
        # 前 2 日也得 close < ma20 * 0.98
        for i in (-3, -2):
            r = df.iloc[i]
            r_ma20 = r.get("MA20")
            if pd.isna(r_ma20) or r["close"] >= r_ma20 * 0.98:
                return False
        return True
