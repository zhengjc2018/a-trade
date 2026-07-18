"""a-trade 数据访问层。

支持：
- 新浪实时行情（atrade.data.quotes）
- 新浪历史日线（atrade.data.history）
- 本地缓存层（atrade.data.cache）
"""
from .quotes import QuoteProvider, Quote
from .history import HistoryProvider, KLine
from .cache import LocalCache

__all__ = ["QuoteProvider", "Quote", "HistoryProvider", "KLine", "LocalCache"]
