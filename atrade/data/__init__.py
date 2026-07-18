"""a-trade 数据访问层。

支持：
- 新浪实时行情（atrade.data.quotes）
- 新浪历史日线（atrade.data.history）
- 本地缓存层（atrade.data.cache）
- 东财当日快照（atrade.data.eastmoney）
"""
from .quotes import QuoteProvider, Quote
from .history import HistoryProvider, KLine
from .cache import LocalCache
from .eastmoney import fetch_snap

__all__ = [
    "QuoteProvider",
    "Quote",
    "HistoryProvider",
    "KLine",
    "LocalCache",
    "fetch_snap",
]
