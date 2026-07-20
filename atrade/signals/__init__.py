"""做 T 信号引擎。

5 个核心信号：
1. 超卖反弹（低吸）
2. 突破回踩（低吸）
3. 放量拉升（高抛）
4. 分时顶背离（高抛）
5. 跌破止损（卖出）
"""
from .engine import Signal, SignalEngine, SignalStrength, SignalType

__all__ = ["SignalEngine", "Signal", "SignalType", "SignalStrength"]
