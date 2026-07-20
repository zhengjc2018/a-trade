"""回测模块。

T+0 做 T 模拟器：模拟"日内买卖"对持仓成本的影响。
"""
from .t0_simulator import T0BacktestResult, T0Simulator, T0Trade

__all__ = ["T0Simulator", "T0BacktestResult", "T0Trade"]
