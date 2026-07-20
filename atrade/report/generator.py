"""日报生成器：汇总行情 + 持仓 + 新闻 + 信号，输出 Markdown。

行情数据走 atrade.data.QuoteProvider（新浪 API，零频率限制）。
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from atrade.data.quotes import QuoteProvider
from atrade.news.collector import NewsCollector


class ReportGenerator:
    """生成不同时间段的报告。"""

    def __init__(
        self,
        holdings: list[dict] | None = None,
        watch_symbols: list[str] | None = None,
        watch_keywords: list[str] | None = None,
        quote_provider: QuoteProvider | None = None,
    ):
        self.holdings = holdings or []
        self.watch_symbols = watch_symbols or [h.get("symbol") for h in self.holdings]
        self.watch_keywords = watch_keywords or []

        self.quote_provider = quote_provider or QuoteProvider()
        self.news_collector = NewsCollector(
            watch_symbols=self.watch_symbols,
            watch_keywords=self.watch_keywords,
        )

    # ---------- 1. 收盘日报 ----------
    def generate_closing_report(self) -> str:
        now = datetime.now()
        lines = [
            "# 📊 a-trade 收盘日报",
            f"_{now.strftime('%Y-%m-%d %H:%M')}_",
            "",
        ]

        # A. 持仓概览
        lines.append("## 💼 持仓概览")
        lines.append(self._render_holdings())
        lines.append("")

        # B. 板块热点 TOP 5
        lines.append("## 🔥 板块热点 TOP 5")
        lines.append(self._render_hot_sectors())
        lines.append("")

        # C. 涨停板情绪
        lines.append("## 🚀 涨停板情绪")
        lines.append(self._render_zt_pool())
        lines.append("")

        # D. 持仓股新闻
        lines.append("## 📰 持仓股新闻")
        lines.append(self._render_holdings_news())
        lines.append("")

        # E. 宏观要闻
        lines.append("## 🌍 宏观要闻")
        lines.append(self._render_morning_brief())
        lines.append("")

        # F. 明日关注
        lines.append("## 👀 明日关注")
        lines.append(self._render_watchlist_news())
        lines.append("")

        lines.append("---")
        lines.append("_⚠️ 本日报由 a-trade 自动生成，仅供参考，投资有风险_")

        return "\n".join(lines)

    def generate_morning_brief(self) -> str:
        now = datetime.now()
        lines = [
            "# 🌅 a-trade 早盘快讯",
            f"_{now.strftime('%Y-%m-%d %H:%M')}_",
            "",
        ]
        lines.append("## 📰 财经早餐")
        lines.append(self.news_collector.to_markdown(
            self.news_collector.fetch_morning_brief(limit=3),
            max_len=250,
        ))
        lines.append("")
        lines.append("## 🔥 昨日涨停复盘")
        lines.append(self._render_zt_pool())
        lines.append("")
        lines.append("---")
        lines.append("_⚠️ 自动生成，仅供参考_")
        return "\n".join(lines)

    def generate_noon_report(self) -> str:
        now = datetime.now()
        lines = [
            "# ☀️ a-trade 午盘报告",
            f"_{now.strftime('%Y-%m-%d %H:%M')}_",
            "",
        ]
        lines.append("## 💼 持仓午盘")
        lines.append(self._render_holdings())
        lines.append("")
        lines.append("## 🔥 板块异动")
        lines.append(self._render_hot_sectors(top_n=8))
        lines.append("")
        lines.append("## 📰 午间盘中快讯")
        lines.append(self.news_collector.to_markdown(
            self.news_collector.fetch_global_news(limit=10),
            max_len=150,
        ))
        lines.append("")
        lines.append("---")
        lines.append("_⚠️ 自动生成，仅供参考_")
        return "\n".join(lines)

    # ============================================================
    # 内部渲染
    # ============================================================

    def _render_holdings(self) -> str:
        """渲染持仓概览（新浪行情 API）。"""
        if not self.holdings:
            return "暂无持仓"

        symbols = [h.get("symbol") for h in self.holdings if h.get("symbol")]
        quotes = self.quote_provider.batch(symbols)

        lines = [
            "| 代码 | 名称 | 成本 | 现价 | 涨跌 | 浮盈 | 持仓 |",
            "|---|---|---|---|---|---|---|",
        ]
        for h in self.holdings:
            symbol = h.get("symbol", "")
            name = h.get("name", "")
            cost = h.get("cost_price", 0)
            quantity = h.get("quantity", 0)

            q = quotes.get(symbol)
            if q and q.is_valid:
                price = q.price
                change_pct = q.change_pct
                profit_pct = (price - cost) / cost * 100 if cost else 0
                profit_str = f"{profit_pct:+.2f}%"
                price_str = f"{price:.2f}"
                change_str = f"{change_pct:+.2f}%"
                name = q.name or name
            else:
                price_str = change_str = profit_str = "N/A"

            lines.append(
                f"| {symbol} | {name} | {cost} | {price_str} | "
                f"{change_str} | {profit_str} | {quantity} |"
            )
        return "\n".join(lines)

    def _render_hot_sectors(self, top_n: int = 5) -> str:
        """渲染热点板块（从涨停股反推 + 全局新闻）。"""
        # 先拉涨停股，找热门板块
        try:
            import akshare as ak
            today = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_em(date=today)
            if len(df) == 0:
                return "今日无涨停股"
            # 涨停股按行业归类
            # AKShare 涨停池字段: 代码/名称/涨跌幅/换手率/...
            # 用股票名+新闻关键词推断板块
            top = df.head(top_n)
            lines = ["| 股票 | 涨幅 | 涨停原因（推断）|", "|---|---|---|"]
            for _, row in top.iterrows():
                code = row['代码']
                name = row['名称']
                pct = row['涨跌幅']
                # 拉新闻查原因
                reason = self._guess_reason(code, name)
                lines.append(f"| {name}({code}) | {pct:+.2f}% | {reason} |")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"板块渲染失败: {e}")
            return "板块数据拉取失败"

    def _guess_reason(self, symbol: str, name: str) -> str:
        """根据涨停股的最新新闻推断涨停原因。"""
        try:
            news = self.news_collector.fetch_stock_news(symbol, limit=1)
            if news:
                # 取新闻摘要前 30 字
                title = news[0].title[:30]
                return title
            return "—"
        except Exception:
            return "—"

    def _render_zt_pool(self) -> str:
        """渲染涨停板情绪。"""
        try:
            import akshare as ak
            today = datetime.now().strftime("%Y%m%d")
            df = ak.stock_zt_pool_em(date=today)
            if len(df) == 0:
                return "今日无涨停股"
            return f"今日涨停: **{len(df)}** 只\n\nTOP 5：\n" + "\n".join(
                f"- {row['名称']} ({row['代码']}) {row['涨跌幅']:+.2f}%"
                for _, row in df.head(5).iterrows()
            )
        except Exception as e:
            logger.warning(f"涨停池失败: {e}")
            return "涨停数据拉取失败"

    def _render_holdings_news(self) -> str:
        news = self.news_collector.fetch_all_watchlist_news(per_symbol=2)
        return self.news_collector.to_markdown(news[:6], max_len=200)

    def _render_morning_brief(self) -> str:
        briefs = self.news_collector.fetch_morning_brief(limit=3)
        return self.news_collector.to_markdown(briefs, max_len=250)

    def _render_watchlist_news(self) -> str:
        globals_news = self.news_collector.fetch_global_news(limit=30)
        stock_news = []
        for sym in self.watch_symbols:
            stock_news.extend(self.news_collector.fetch_stock_news(sym, limit=2))
        all_news = globals_news + stock_news
        filtered = self.news_collector.filter_by_keywords(all_news, hours=72)
        return self.news_collector.to_markdown(filtered[:5], max_len=200)
