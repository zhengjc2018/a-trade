"""技术指标计算模块。

参考 free-stockdb 设计，提供：
- 移动平均类：MA / EMA / SMA
- 趋势类：BOLL / MACD
- 摆动类：KDJ / RSI
- 成交量类：VOL_MA
"""
from .indicators import (
    add_all_indicators,
    boll,
    ema,
    kdj,
    macd,
    rsi,
    sma,
    vol_ma,
)

__all__ = [
    "sma", "ema", "macd", "kdj", "rsi", "boll", "vol_ma",
    "add_all_indicators",
]
