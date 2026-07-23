"""新闻收集器：聚合多源新闻，支持关键词过滤和去重。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import akshare as ak
from loguru import logger


@dataclass
class NewsItem:
    """单条新闻。"""
    title: str
    summary: str
    source: str
    publish_time: datetime
    url: str = ""
    category: str = ""  # macro / stock / global / sector
    related_symbols: list[str] = field(default_factory=list)


class NewsCollector:
    """多源新闻收集器。"""

    def __init__(
        self,
        watch_symbols: Iterable[str] | None = None,
        watch_keywords: Iterable[str] | None = None,
    ):
        self.watch_symbols = list(watch_symbols or [])
        self.watch_keywords = list(watch_keywords or [])

    # ---------- 1. 财经早餐（每日宏观要闻） ----------
    def fetch_morning_brief(self, limit: int = 10) -> list[NewsItem]:
        """东方财富财经早餐 — 每日宏观。"""
        try:
            df = ak.stock_info_cjzc_em()
            items = []
            for _, row in df.head(limit).iterrows():
                items.append(NewsItem(
                    title=str(row.get("标题", "")),
                    summary=str(row.get("摘要", "")),
                    source="东方财富财经早餐",
                    publish_time=self._parse_time(row.get("发布时间", "")),
                    url=str(row.get("链接", "")),
                    category="macro",
                ))
            logger.info(f"✅ 财经早餐: 原始 {len(items)} 条，今天 {len(self.filter_today_only(items))} 条")
            return self.filter_today_only(items)
        except Exception as e:
            logger.error(f"❌ 财经早餐失败: {e}")
            return []

    # ---------- 2. 个股新闻 ----------
    def fetch_stock_news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        """指定个股的新闻。"""
        try:
            df = ak.stock_news_em(symbol=symbol)
            items = []
            for _, row in df.head(limit).iterrows():
                items.append(NewsItem(
                    title=str(row.get("新闻标题", "")),
                    summary=str(row.get("新闻内容", ""))[:200],
                    source=str(row.get("文章来源", "东方财富")),
                    publish_time=self._parse_time(row.get("发布时间", "")),
                    url=str(row.get("新闻链接", "")),
                    category="stock",
                    related_symbols=[symbol],
                ))
            logger.info(f"✅ 个股新闻 {symbol}: 原始 {len(items)} 条，今天 {len(self.filter_today_only(items))} 条")
            return self.filter_today_only(items)
        except Exception as e:
            logger.error(f"❌ 个股新闻 {symbol} 失败: {e}")
            return []

    def fetch_all_watchlist_news(self, per_symbol: int = 3) -> list[NewsItem]:
        """所有持仓股新闻聚合。"""
        all_items = []
        for symbol in self.watch_symbols:
            all_items.extend(self.fetch_stock_news(symbol, limit=per_symbol))
        # 按时间倒序
        all_items.sort(key=lambda x: x.publish_time, reverse=True)
        return all_items

    # ---------- 3. 全球财经快讯（盘中实时） ----------
    def fetch_global_news(self, limit: int = 20) -> list[NewsItem]:
        """全球财经快讯。"""
        try:
            df = ak.stock_info_global_em()
            items = []
            for _, row in df.head(limit).iterrows():
                items.append(NewsItem(
                    title=str(row.get("标题", "")),
                    summary=str(row.get("摘要", "")),
                    source="东方财富全球快讯",
                    publish_time=self._parse_time(row.get("发布时间", "")),
                    url=str(row.get("链接", "")),
                    category="global",
                ))
            logger.info(f"✅ 全球快讯: 原始 {len(items)} 条，今天 {len(self.filter_today_only(items))} 条")
            return self.filter_today_only(items)
        except Exception as e:
            logger.error(f"❌ 全球快讯失败: {e}")
            return []

    # ---------- 4. 关键词过滤 ----------
    def filter_by_keywords(
        self, items: list[NewsItem], hours: int = 24
    ) -> list[NewsItem]:
        """按持仓/关键词过滤最近 N 小时的新闻。"""
        cutoff = datetime.now() - timedelta(hours=hours)
        filtered = []
        for item in items:
            if item.publish_time < cutoff:
                continue
            text = item.title + " " + item.summary
            # 匹配持仓代码
            if any(sym in text for sym in self.watch_symbols):
                filtered.append(item)
                continue
            # 匹配关键词
            if any(kw in text for kw in self.watch_keywords):
                filtered.append(item)
                continue
        # 去重（按标题）
        seen = set()
        unique = []
        for item in filtered:
            if item.title in seen:
                continue
            seen.add(item.title)
            unique.append(item)
        return unique

    def filter_today_only(self, items: list[NewsItem]) -> list[NewsItem]:
        """只保留今天（按本地日期）发布的新闻。"""
        today = datetime.now().date()
        return [item for item in items if item.publish_time.date() == today]

    @staticmethod
    def _parse_time(s: str) -> datetime:
        """解析东财时间字符串。"""
        if not s:
            return datetime.now()
        s = str(s).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return datetime.now()

    @staticmethod
    def to_markdown(items: list[NewsItem], max_len: int = 300) -> str:
        """把新闻列表转成 Markdown。"""
        if not items:
            return "暂无新闻"
        lines = []
        for i, item in enumerate(items[:20], 1):
            summary = item.summary[:max_len] if item.summary else ""
            time_str = item.publish_time.strftime("%m-%d %H:%M")
            lines.append(f"**{i}. {item.title}**")
            lines.append(f"   _{time_str} | {item.source}_")
            if summary:
                lines.append(f"   {summary}...")
            lines.append("")
        return "\n".join(lines)
