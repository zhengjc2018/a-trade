"""技术指标库（参考 free-stockdb 设计，纯 Python 实现）。"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ============================================================
# 移动平均类
# ============================================================

def sma(series: pd.Series, n: int = 5) -> pd.Series:
    """简单移动平均。"""
    return series.rolling(n, min_periods=1).mean()


def ema(series: pd.Series, n: int = 12) -> pd.Series:
    """指数移动平均。"""
    return series.ewm(span=n, adjust=False).mean()


# ============================================================
# MACD（指数平滑异同移动平均）
# ============================================================

def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD 指标。

    Returns:
        (DIF, DEA, MACD_hist)
        - DIF = EMA(fast) - EMA(slow)
        - DEA = EMA(DIF, signal)
        - MACD_hist = (DIF - DEA) * 2
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


# ============================================================
# KDJ（随机指标）
# ============================================================

def kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """KDJ 指标。

    Returns:
        (K, D, J)
        - RSV = (close - lowest_low_n) / (highest_high_n - lowest_low_n) * 100
        - K = SMA(RSV, m1)
        - D = SMA(K, m2)
        - J = 3*K - 2*D
    """
    lowest_low = low.rolling(n, min_periods=1).min()
    highest_high = high.rolling(n, min_periods=1).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(alpha=1/m1, adjust=False).mean()
    d = k.ewm(alpha=1/m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


# ============================================================
# RSI（相对强弱指标）
# ============================================================

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI 指标。

    RSI = 100 - 100 / (1 + RS)
    RS = 平均涨幅 / 平均跌幅
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(n, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(n, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_val = 100 - 100 / (1 + rs)
    return rsi_val.fillna(50)


# ============================================================
# BOLL（布林带）
# ============================================================

def boll(
    close: pd.Series,
    n: int = 20,
    k: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """布林带。

    Returns:
        (MID, UPPER, LOWER)
        - MID = SMA(close, n)
        - UPPER = MID + k * STD(close, n)
        - LOWER = MID - k * STD(close, n)
    """
    mid = sma(close, n)
    std = close.rolling(n, min_periods=1).std()
    upper = mid + k * std
    lower = mid - k * std
    return mid, upper, lower


# ============================================================
# 成交量均线
# ============================================================

def vol_ma(volume: pd.Series, n: int = 5) -> pd.Series:
    """成交量均线。"""
    return volume.rolling(n, min_periods=1).mean()


# ============================================================
# 一键添加所有指标
# ============================================================

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """给日线 DataFrame 加所有指标。

    输入列：日期/开盘/收盘/最高/最低/成交量
    输出新增列：MA5/MA10/MA20/EMA12/EMA26/MACD_*/KDJ_*/RSI*/BOLL_*/VOL_MA5
    """
    df = df.copy()
    close = df["收盘"] if "收盘" in df.columns else df["close"]
    high = df["最高"] if "最高" in df.columns else df["high"]
    low = df["最低"] if "最低" in df.columns else df["low"]
    vol = df["成交量"] if "成交量" in df.columns else df["volume"]

    # 均线
    df["MA5"] = sma(close, 5)
    df["MA10"] = sma(close, 10)
    df["MA20"] = sma(close, 20)
    df["EMA12"] = ema(close, 12)
    df["EMA26"] = ema(close, 26)

    # MACD
    dif, dea, hist = macd(close)
    df["MACD_DIF"] = dif
    df["MACD_DEA"] = dea
    df["MACD_HIST"] = hist

    # KDJ
    k, d, j = kdj(high, low, close)
    df["KDJ_K"] = k
    df["KDJ_D"] = d
    df["KDJ_J"] = j

    # RSI
    df["RSI6"] = rsi(close, 6)
    df["RSI14"] = rsi(close, 14)

    # BOLL
    mid, upper, lower = boll(close)
    df["BOLL_MID"] = mid
    df["BOLL_UPPER"] = upper
    df["BOLL_LOWER"] = lower

    # 量能
    df["VOL_MA5"] = vol_ma(vol, 5)
    df["VOL_MA10"] = vol_ma(vol, 10)

    return df
