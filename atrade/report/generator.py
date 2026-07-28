"""日报生成器：汇总行情 + 持仓 + 新闻 + 信号，输出 Markdown。

行情数据走 atrade.data.QuoteProvider（新浪 API，零频率限制）。
"""

from __future__ import annotations

from datetime import datetime

from loguru import logger

from atrade.data.quotes import QuoteProvider
from atrade.monitor.t_executor import load_trades
from atrade.monitor.t_replay import (
    compute_execution_stats,
    compute_round_trips,
    compute_stats,
)
from atrade.news.collector import NewsCollector

# t_replay 报告"无任何信号触发"的专用 sentinel（scheduler 据此跳过推送）
T_REPLAY_EMPTY_MARKER = "⏸️ 今日无任何 T 信号触发"


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

        replay = self.generate_t_replay_report(now.strftime("%Y-%m-%d"))
        replay_lines = replay.splitlines()
        if replay_lines:
            replay_lines[0] = replay_lines[0].replace("# ", "## ", 1)
        lines.extend(replay_lines)
        lines.append("")

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

    def generate_t_replay_report(self, date: str | None = None) -> str:
        """生成当天做 T 复盘：摘要 + 按个股信号执行汇总 + 闭环收益。

        输出顺序（保证首屏一眼看到今天做了什么）：
            1. 🎯 今日摘要（净买入/净卖出股数）
            2. 🔍 按个股信号执行汇总（始终输出，钉钉原生 markdown 不渲染表格 → 项目列表）
            3. 📈 闭环收益（仅当 BUY→SELL/STOP_LOSS 有配对时）

        返回空字符串 = 今天完全无任何信号触发，调用方应跳过推送（避免噪声）。
        """
        trade_date = date or datetime.now().strftime("%Y-%m-%d")
        all_trades = load_trades()
        trips = compute_round_trips(all_trades, trade_date)
        stats = compute_stats(trips)
        execution = compute_execution_stats(all_trades, trade_date)

        # 触发=0 → 返回简洁 marker（让 closing_report 嵌入有内容，scheduler 据此跳过独立推送）
        if execution["total_trades"] <= 0 and not trips:
            return "# 📈 做T复盘\n\n⏸️ 今日无任何 T 信号触发（无需总结）"

        # 净买入/净卖出股数（仅计实际执行的交易）
        net_shares = 0
        net_buy_shares = 0
        net_sell_shares = 0
        for symbol, _info in execution["by_symbol"].items():
            buy_shares = 0
            sell_shares = 0
            for trade in all_trades:
                ts = trade.get("timestamp", "")
                if not ts.startswith(trade_date):
                    continue
                if str(trade.get("symbol", "")).zfill(6) != symbol:
                    continue
                direction = str(trade.get("direction", "")).upper()
                if trade.get("skipped_reason") or int(trade.get("shares", 0) or 0) <= 0:
                    continue
                if direction == "BUY":
                    buy_shares += int(trade.get("shares", 0))
                elif direction in {"SELL", "STOP_LOSS"}:
                    sell_shares += int(trade.get("shares", 0))
            net_buy_shares += buy_shares
            net_sell_shares += sell_shares
            net_shares += buy_shares - sell_shares

        lines = ["# 📈 做T复盘", ""]
        # --- A. 今日摘要（首屏一眼看完）---
        summary_parts = [f"触发 **{execution['total_trades']}** 次"]
        summary_parts.append(f"执行 **{execution['total_executed']}** 次")
        if execution["total_skipped"] > 0:
            summary_parts.append(f"拦截 **{execution['total_skipped']}** 次")
        if trips:
            result = f"{stats['wins']}胜{stats['losses']}负"
            if stats["breakevens"]:
                result += f"{stats['breakevens']}平"
            summary_parts.append(
                f"闭环 **{stats['count']}** 笔"
                f"，毛收益 **{stats['total_pnl']:+.2f} 元**"
            )
        lines.append("🎯 今日摘要：" + " ｜ ".join(summary_parts))
        if net_buy_shares or net_sell_shares:
            parts = []
            if net_buy_shares:
                parts.append(f"买入 **{net_buy_shares}** 股")
            if net_sell_shares:
                parts.append(f"卖出 **{net_sell_shares}** 股")
            lines.append("- 净操作：" + " ｜ ".join(parts))
        lines.append("")

        # --- B. 按个股信号执行汇总（始终输出，项目列表格式）---
        lines.append("## 🔍 按个股信号执行汇总")
        for symbol, info in execution["by_symbol"].items():
            display_name = info["name"] or symbol
            direction_text = " / ".join(
                f"{d}×{n}" for d, n in sorted(info["directions"].items())
            )
            holding_text = f"持仓 {info['last_holding_qty_after']} 股"
            lines.append(
                f"- **{display_name}({symbol})**："
                f"触发 {info['trades_count']} 次，"
                f"执行 {info['executed_count']} 次，"
                f"拦截 {info['skipped_count']} 次 ｜ "
                f"方向 {direction_text} ｜ {holding_text}"
            )
        if execution["total_skipped"] > 0:
            lines.append(
                "- 💡 拦截多为『持仓不足 / 今日已执行过 SELL』"
                "——系统已自动避免重复卖出。"
            )
        lines.append("")

        # --- C. 闭环收益（仅当有 BUY→SELL/STOP_LOSS 配对时）---
        if trips:
            result = f"{stats['wins']}胜{stats['losses']}负"
            if stats["breakevens"]:
                result += f"{stats['breakevens']}平"
            lines.append("## 📈 闭环收益")
            lines.append(
                f"- 胜率 **{stats['win_rate']:.1%}** ｜ "
                f"毛收益 **{stats['total_pnl']:+.2f} 元** ｜ "
                f"{result}"
            )
            profit_factor = stats["profit_factor"]
            profit_factor_text = "∞" if profit_factor is None else f"{profit_factor:.2f}"
            lines.append(
                f"- 闭环：{stats['count']} 笔 ｜ "
                f"平均收益：{stats['avg_pnl_pct']:+.2%} ｜ "
                f"盈亏比：{profit_factor_text}"
            )
            lines.append("- 口径：按实际记录股数计算毛收益，未扣手续费和滑点。")
            lines.append("")
            for trip in trips[-5:]:
                display_name = trip.name or trip.symbol
                lines.append(
                    f"- {display_name}({trip.symbol}) "
                    f"{trip.entry_price:.2f} → {trip.exit_price:.2f}，"
                    f"{trip.shares} 股，"
                    f"**{trip.pnl:+.2f} 元** ({trip.pnl_pct:+.2%})，"
                    f"持有 {trip.holding_minutes} 分钟"
                )
            if stats["by_factor"]:
                factor_parts = [
                    f"{factor} {group['wins']}/{group['count']}胜"
                    for factor, group in sorted(
                        stats["by_factor"].items(),
                        key=lambda item: (-item[1]["count"], item[0]),
                    )[:3]
                ]
                lines.append("- 因子表现：" + "；".join(factor_parts))
        else:
            lines.append("## 📈 闭环收益")
            lines.append("- ⏸️ 今日无已闭环 T 交易（BUY→SELL/STOP_LOSS 配对为空）")
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

    def generate_auction_report(self) -> str:
        """9:25 竞价分析：板块榜 TOP 5 + 领涨股 TOP 10。"""
        from datetime import datetime

        from atrade.analyzer.auction import fetch_sector_auction, fetch_top_gainers
        now = datetime.now()
        sectors = fetch_sector_auction(top_n=5)
        leaders = fetch_top_gainers(top_n=10)

        if not sectors:
            return "# 📈 竞价分析\n\n_暂无数据（可能尚未开盘或数据源失败）_"

        # 头部结论：找最强的方向
        top = sectors[0]
        if top.change_pct >= 3:
            conclusion = f"🟢 竞价强势：{top.name} {top.change_pct:+.2f}%"
        elif top.change_pct >= 1:
            conclusion = f"🟡 竞价偏强：{top.name} {top.change_pct:+.2f}%"
        elif top.change_pct >= 0:
            conclusion = f"⚪ 竞价平淡：{top.name} {top.change_pct:+.2f}%"
        else:
            conclusion = f"🔴 竞价走弱：{top.name} {top.change_pct:+.2f}%"

        lines = [
            "# 📈 集合竞价分析",
            f"_{now.strftime('%Y-%m-%d %H:%M')}_",
            "",
            conclusion,
            "",
            "## 🔥 板块榜 TOP 5",
            "",
            "| 板块 | 涨幅 | 领涨股 | 个股涨幅 |",
            "|---|---:|---|---|",
        ]
        for s in sectors:
            lines.append(
                f"| {s.name} | {s.change_pct:+.2f}% | "
                f"{s.leader_name}({s.leader_symbol}) | "
                f"{s.leader_change_pct:+.2f}% |"
            )

        lines.extend([
            "",
            "## 🚀 领涨股 TOP 10",
            "",
            "| 代码 | 名称 | 涨幅 | 所属板块 |",
            "|---|---|---:|---|",
        ])
        for ld in leaders:
            lines.append(
                f"| {ld['symbol']} | {ld['name']} | "
                f"{ld['change_pct']:+.2f}% | {ld['sector']} |"
            )

        lines.extend([
            "",
            "---",
            "_⚠️ 仅供参考，投资有风险_",
        ])
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
