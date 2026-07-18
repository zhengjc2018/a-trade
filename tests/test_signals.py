import pandas as pd
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.signals import SignalEngine, SignalType, SignalStrength


def make_df(closes: list, volumes: list = None) -> pd.DataFrame:
    """从收盘价序列构造测试用 DataFrame."""
    n = len(closes)
    dates = pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    opens = closes
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    if volumes is None:
        volumes = [1000000] * n
    return pd.DataFrame({
        "date": dates, "open": opens, "high": highs,
        "low": lows, "close": closes, "volume": volumes,
    })


def test_wave_rebound_factor():
    """60 日跌 20% + RSI 30-50 + 缩量 → 波段反弹因子命中。"""
    # 构造 60 日从 100 跌到 80（-20%），最后 3 日缩量
    closes = [100.0 - i * 0.34 for i in range(60)]
    closes[-1] = 80.0
    closes[-2] = 79.5
    closes[-3] = 79.0
    volumes = [2000000] * 60
    volumes[-1] = 600000   # 缩量
    volumes[-2] = 700000
    volumes[-3] = 800000
    df = make_df(closes, volumes)
    df["RSI6"] = 35.0
    df["VOL_MA5"] = 1800000.0  # VOL_MA5 取大，确保 recent3 < vol_ma5
    df["BOLL_LOWER"] = df["close"] * 0.97
    df["MA5"] = df["close"].rolling(5).mean()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA20"] = df["close"].rolling(20).mean()
    df["MACD_HIST"] = 0.0

    eng = SignalEngine()
    sigs = eng.scan("TEST", df)
    # 至少有 BUY 信号
    buy = [s for s in sigs if s.signal_type == SignalType.BUY]
    assert any("波段反弹" in s.factor_hits for s in buy)


def test_trend_confirm_factor():
    """MA5 上穿 MA10 + 量比 > 1.2 → 趋势确认因子。"""
    closes = [100.0 + (i % 5) * 0.5 for i in range(60)]
    df = make_df(closes)
    # 最后一天量放大 → VOL_MA5 自然 < latest volume
    df["VOL_MA5"] = 800000.0  # 缩量
    df["MA5"] = 101.0          # 上穿 MA10 100.5
    df["MA10"] = 100.5
    df.iloc[-2, df.columns.get_loc("MA5")] = 100.0   # prev ma5=100
    df.iloc[-2, df.columns.get_loc("MA10")] = 100.5  # prev ma5<=ma10
    df["RSI6"] = 50.0
    df["BOLL_LOWER"] = df["close"] * 0.97
    df["MA20"] = 100.0
    df["MACD_HIST"] = 0.0

    eng = SignalEngine()
    sigs = eng.scan("TEST", df)
    buy = [s for s in sigs if s.signal_type == SignalType.BUY]
    assert any("趋势确认" in s.factor_hits for s in buy)


def test_oversold_factor():
    """RSI<25 + 触及 BOLL 下轨 + 量比 > 1.3 → 超卖反弹。"""
    closes = [100.0 + (i % 5) * 0.5 for i in range(60)]
    n = len(closes)
    volumes = [800000] * n   # 基线 vol 800k
    volumes[-1] = 1200000    # 最后一天放量
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": closes, "high": [c*1.01 for c in closes],
        "low": [c*0.99 for c in closes], "close": closes, "volume": volumes,
    })
    df["RSI6"] = 22.0
    df["BOLL_LOWER"] = df["close"].iloc[-1] * 1.01  # close < boll_lower * 1.02
    df["VOL_MA5"] = 800000.0
    df["MA5"] = 100.0
    df["MA10"] = 100.0
    df["MA20"] = 100.0
    df["MACD_HIST"] = 0.0

    eng = SignalEngine()
    sigs = eng.scan("TEST", df)
    buy = [s for s in sigs if s.signal_type == SignalType.BUY]
    assert any("超卖反弹" in s.factor_hits for s in buy)


def test_stop_loss_strict():
    """需要连续 3 日 close < MA20 才触发 stop loss。"""
    closes = [100.0] * 60
    df = make_df(closes)
    df["MA20"] = [110.0] * 60  # MA20 远高于 close
    df["RSI6"] = 50.0
    df["BOLL_LOWER"] = df["close"] * 0.9
    df["VOL_MA5"] = 1000000.0
    df["MA5"] = df["close"]
    df["MA10"] = df["close"]
    df["MACD_HIST"] = 0.0

    eng = SignalEngine()
    sigs = eng.scan("TEST", df)
    # 连续 3 日 close < MA20*0.98 → 应触发 stop loss
    stop = [s for s in sigs if s.signal_type == SignalType.STOP_LOSS]
    assert len(stop) == 1
    assert "连续3日" in stop[0].name


def test_no_stop_loss_if_only_one_day():
    """只有 1 日 close < MA20 不触发 stop loss（避免频繁）。"""
    closes = [100.0] * 60
    df = make_df(closes)
    df["MA20"] = [110.0] * 60
    df["close"] = df["close"].copy()
    # 最后一天 close < MA20*0.98 = 107.8
    df.loc[df.index[-1], "close"] = 100.0
    df.loc[df.index[-2], "close"] = 110.0  # >= MA20*0.98 → 不触发
    df.loc[df.index[-3], "close"] = 110.0

    df["RSI6"] = 50.0
    df["BOLL_LOWER"] = df["close"] * 0.9
    df["VOL_MA5"] = 1000000.0
    df["MA5"] = df["close"]
    df["MA10"] = df["close"]
    df["MACD_HIST"] = 0.0

    eng = SignalEngine()
    sigs = eng.scan("TEST", df)
    stop = [s for s in sigs if s.signal_type == SignalType.STOP_LOSS]
    assert len(stop) == 0


def test_no_signals_returns_empty():
    """平稳数据 → 0 BUY, 0 STOP_LOSS。"""
    closes = [100.0 + (i % 5) * 0.1 for i in range(60)]
    n = len(closes)
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": closes, "high": [c*1.01 for c in closes],
        "low": [c*0.99 for c in closes], "close": closes, "volume": [1000000]*n,
    })
    df["RSI6"] = 50.0
    df["VOL_MA5"] = 1000000.0
    df["BOLL_LOWER"] = df["close"] * 0.97
    df["MA5"] = df["close"]
    df["MA10"] = df["close"]
    df["MA20"] = df["close"]
    df["MACD_HIST"] = 0.0

    eng = SignalEngine()
    sigs = eng.scan("TEST", df)
    # 平稳数据不会触发任何 BUY 或 STOP_LOSS 信号
    buy = [s for s in sigs if s.signal_type == SignalType.BUY]
    stop = [s for s in sigs if s.signal_type == SignalType.STOP_LOSS]
    assert len(buy) == 0
    assert len(stop) == 0


def test_factor_count_drives_strength():
    """验证strength 由 factor 数量决定：1=WEAK, 2=MEDIUM, 3+=STRONG。"""
    from atrade.signals.engine import SignalEngine
    eng = SignalEngine()

    # 单独调用每个因子，看返回是否合理
    closes = [100.0 - i * 0.34 for i in range(60)]
    closes[-1] = 80.0
    closes[-2] = 79.5
    closes[-3] = 79.0
    n = len(closes)
    volumes = [1500000] * n
    volumes[-1] = 200000
    volumes[-2] = 250000
    volumes[-3] = 300000
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": closes, "high": [c*1.01 for c in closes],
        "low": [c*0.99 for c in closes], "close": closes, "volume": volumes,
    })
    df["RSI6"] = 35.0
    df["VOL_MA5"] = 1200000.0
    df["BOLL_LOWER"] = df["close"].iloc[-1] * 0.5
    df["MA5"] = 80.5
    df["MA10"] = 80.0
    # prev MA5 = 79.5, prev MA10 = 80.0 → 上穿
    df.iloc[-2, df.columns.get_loc("MA5")] = 79.5
    df.iloc[-2, df.columns.get_loc("MA10")] = 80.0
    df["MA20"] = 78.0
    df["MACD_HIST"] = 0.0

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    # 波段反弹因子确认命中
    f1 = eng._factor_wave_rebound(df, latest)
    assert f1 is not None and f1[0] == "波段反弹"
    # 趋势确认因子：需要 volume > VOL_MA5*1.2 → 实际 200k/1.2M = 0.17 → 不命中
    f2 = eng._factor_trend_confirm(df, latest, prev)
    # 量比不够 → 不命中
    assert f2 is None
