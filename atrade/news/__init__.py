"""a-trade 新闻数据模块。

支持多源新闻聚合：
- 财经早餐（每日宏观）
- 个股新闻（持仓股相关）
- 全球财经快讯（盘中实时）
- 板块热点（行业动态）
"""
from .collector import NewsCollector, NewsItem

__all__ = ["NewsCollector", "NewsItem"]
