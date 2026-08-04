"""每日定时任务调度器。"""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime, time
from typing import Optional

import botpy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from botpy import logging
from botpy.message import GroupMessage
from dotenv import load_dotenv
from loguru import logger

from atrade.config import (
    load_holdings_with_meta as load_holdings_with_meta_config,
)
from atrade.config import (
    load_monitor_config as load_monitor_config_from_module,
)
from atrade.config import (
    load_watch_keywords,
)
from atrade.data import QuoteProvider
from atrade.monitor import ScreenMonitorRunner, TMonitorRunner, TradingCalendar
from atrade.monitor.screen_ledger import RecommendationLedger
from atrade.monitor.screen_review import build_screen_review
from atrade.news.collector import NewsCollector
from atrade.notify import DeliveryLedger, DeliveryRouter, DingTalkNotifier, OpenClawNotifier
from atrade.notify.dingtalk import render_banner
from atrade.report.generator import ReportGenerator
from atrade.scheduler.recovery import RecoveryTask, recover_missed_tasks

_log = logging.get_logger()
load_dotenv()

# 热重载 socket 路径：web 服务通过这个 unix socket 通知 scheduler 重读配置
_RELOAD_SOCK_PATH = os.getenv(
    "A_TRADE_RELOAD_SOCK", "/var/run/a-trade-reload.sock"
)

# 配置文件统一由 atrade.config 加载；本模块不再直接读 JSON。


def _derive_t_symbols(
    holdings: list[dict],
    disabled: set[str],
    symbol_overrides: list[dict],
) -> list[dict]:
    """以 holdings 为唯一股票源，仅叠加 monitor 中的 trailing 覆盖。"""
    overrides = {
        str(item.get("symbol", "")).zfill(6): dict(item.get("trailing") or {})
        for item in symbol_overrides
        if isinstance(item, dict) and item.get("symbol") and item.get("trailing")
    }
    result = []
    for holding in holdings:
        symbol = str(holding.get("symbol", "")).zfill(6)
        if symbol in disabled:
            continue
        item = {
            "symbol": symbol,
            "name": holding.get("name", ""),
            "cost_price": holding.get("cost_price", 0.0),
            "quantity": holding.get("quantity", 0),
            "note": holding.get("note", ""),
        }
        if symbol in overrides:
            item["trailing"] = overrides[symbol]
        result.append(item)
    return result


class ATradeClient(botpy.Client):
    """a-trade 机器人 Client，挂在调度器上用于推送。"""

    def __init__(self, *args, scheduler: Optional[DailyScheduler] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._scheduler = scheduler

    async def on_ready(self):
        logger.success(f"✅ a-trade Bot ready: {self.robot.name}")

    async def on_group_at_message_create(self, message: GroupMessage):
        """群 @ 消息 — 简单 echo（命令路由可在后续扩展）。"""
        logger.info(
            f"收到群消息: {message.author.member_openid} -> {message.content[:50]}"
        )
        await message._api.post_group_message(
            group_openid=message.group_openid,
            msg_type=0,
            msg_id=message.id,
            content="✅ a-trade 已收到\n\n"
                    "自动推送已配置，无需手动触发。\n"
                    "下次推送: 收盘日报 15:30",
        )


class DailyScheduler:
    """每日定时任务调度器。"""

    def __init__(self):
        holdings_meta = load_holdings_with_meta_config()
        self.holdings = holdings_meta["holdings"]
        self.watch_symbols = [h.get("symbol") for h in self.holdings if h.get("symbol")]
        self.watch_keywords = load_watch_keywords() or self._load_keywords()
        self.monitor_config = load_monitor_config_from_module()
        self.calendar = TradingCalendar()
        self.quote_provider = QuoteProvider()
        self.screen_ledger = RecommendationLedger()
        self.screen_runner = ScreenMonitorRunner(
            self.monitor_config.get("screen"),
            ledger=self.screen_ledger,
        )
        tmon_cfg = dict(self.monitor_config.get("t_monitor") or {})
        tmon_cfg["symbols"] = _derive_t_symbols(
            self.holdings,
            set(holdings_meta.get("disabled_symbols") or []),
            tmon_cfg.get("symbols") or [],
        )
        self.t_runner = TMonitorRunner(tmon_cfg)

        self.report_gen = ReportGenerator(
            holdings=self.holdings,
            watch_symbols=self.watch_symbols,
            watch_keywords=self.watch_keywords,
            quote_provider=self.quote_provider,
        )

        self.group_openid = os.getenv("QQ_TARGET_GROUP")
        self.appid = os.getenv("QQ_BOT_APPID")
        self.secret = os.getenv("QQ_BOT_APPSECRET")

        if not all([self.appid, self.secret, self.group_openid]):
            raise ValueError("请在 .env 配置 QQ_BOT_APPID / SECRET / TARGET_GROUP")

        primary_name = os.getenv("NOTIFY_PRIMARY", "dingtalk").lower()
        fallback_name = os.getenv("NOTIFY_FALLBACK", "openclaw").lower()
        if primary_name != "dingtalk":
            raise ValueError("NOTIFY_PRIMARY 当前仅支持 dingtalk")
        primary = DingTalkNotifier()
        fallback = OpenClawNotifier() if fallback_name == "openclaw" else None
        self.delivery_ledger = DeliveryLedger()
        self.delivery_router = DeliveryRouter(primary, fallback, self.delivery_ledger)

        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._client: Optional[ATradeClient] = None
        self._bot_thread: Optional[threading.Thread] = None
        self._bot_loop: Optional[asyncio.AbstractEventLoop] = None

        self._setup_jobs()

    def _load_keywords(self) -> list[str]:
        """加载关注关键词（可扩展）。"""
        return ["茅台", "白酒", "半导体", "新能源", "美联储", "央行", "降息", "降准"]

    def _setup_jobs(self):
        """注册定时任务。"""
        # 集合竞价分析：每个交易日 9:25（集合竞价结束后）
        self.scheduler.add_job(
            self._job_auction_analysis,
            CronTrigger(hour=9, minute=25),
            id="auction_analysis",
            name="集合竞价分析",
            coalesce=True,
            misfire_grace_time=1800,
        )

        # 早盘选股：每个交易日 9:26（竞价分析完成后）
        # 覆盖 9:00-9:30 的空档，开盘前给用户推荐候选清单
        self.scheduler.add_job(
            self._job_pre_market_screen,
            CronTrigger(hour=9, minute=26),
            id="pre_market_screen",
            name="早盘选股",
            coalesce=True,
            misfire_grace_time=3600,
        )

        # 今日荐股胜率：每个交易日 15:00（收盘后，推送价→收盘价）
        self.scheduler.add_job(
            self._job_screen_review,
            CronTrigger(hour=15, minute=0),
            id="screen_review",
            name="今日荐股胜率",
            coalesce=True,
            misfire_grace_time=7200,
        )

        # 早盘快讯：每个交易日 8:00
        self.scheduler.add_job(
            self._job_delivery_heartbeat,
            CronTrigger(hour=7, minute=55),
            id="delivery_heartbeat",
            name="通知心跳",
            coalesce=True,
            misfire_grace_time=3600,
        )

        self.scheduler.add_job(
            self._job_morning_brief,
            CronTrigger(hour=8, minute=0),
            id="morning_brief",
            name="早盘快讯",
            coalesce=True,
            misfire_grace_time=7200,
        )

        # 午盘报告：每个交易日 12:30
        self.scheduler.add_job(
            self._job_noon_report,
            CronTrigger(hour=12, minute=30),
            id="noon_report",
            name="午盘报告",
            coalesce=True,
            misfire_grace_time=5400,
        )

        # 每个交易日 09:30 清空前一交易日的 T 仓状态
        self.scheduler.add_job(
            self._job_t_state_reset,
            CronTrigger(hour=9, minute=30),
            id="t_state_reset",
            name="做T状态日切",
            coalesce=True,
            misfire_grace_time=1800,
        )

        # 收盘日报 + 做T复盘：每个交易日 15:35
        self.scheduler.add_job(
            self._job_closing_report,
            CronTrigger(hour=15, minute=35),
            id="closing_report",
            name="收盘日报",
            coalesce=True,
            misfire_grace_time=21600,
        )

        # 做T复盘独立推送：每个交易日 15:40（晚于 closing_report 5 分钟）
        # closing_report 先到消化，T 复盘后到作为补刀，避免被长内容挤掉
        self.scheduler.add_job(
            self._job_t_replay,
            CronTrigger(hour=15, minute=40),
            id="t_replay",
            name="做T复盘独立推送",
            coalesce=True,
            misfire_grace_time=21600,
        )

        # 持仓新闻汇总：每个交易日 17:00
        self.scheduler.add_job(
            self._job_holdings_news,
            CronTrigger(hour=17, minute=0),
            id="holdings_news",
            name="持仓新闻",
            coalesce=True,
            misfire_grace_time=21600,
        )

        # 盘中选股：每 N 分钟扫描一次，只在交易日盘中运行
        self.scheduler.add_job(
            self._job_screen_monitor,
            CronTrigger(minute="*/{}".format(max(1, int(self.monitor_config.get("screen", {}).get("interval_minutes", 30))))),
            id="screen_monitor",
            name="盘中选股",
        )

        # 做 T 监控：每 N 分钟扫描一次，只在交易日盘中运行
        self.scheduler.add_job(
            self._job_t_monitor,
            CronTrigger(minute="*/{}".format(max(1, int(self.monitor_config.get("t_monitor", {}).get("scan_interval_minutes", 2))))),
            id="t_monitor",
            name="做T监控",
        )

        for hour, minute, task_name, callback in [
            (8, 5, "morning_brief", self._job_morning_brief),
            (9, 30, "auction_analysis", self._job_auction_analysis),
            (9, 35, "pre_market_screen", self._job_pre_market_screen),
            (12, 35, "noon_report", self._job_noon_report),
            (15, 40, "closing_report", self._job_closing_report),
            (17, 5, "holdings_news", self._job_holdings_news),
        ]:
            self.scheduler.add_job(
                lambda name=task_name, cb=callback: self._job_delivery_guard(name, cb),
                CronTrigger(hour=hour, minute=minute),
                id=f"{task_name}_guard",
                name=f"{task_name}送达检查",
                coalesce=True,
                misfire_grace_time=3600,
            )

        self.scheduler.add_job(
            self._job_retry_failed,
            CronTrigger(minute="*/5"),
            id="retry_failed_deliveries",
            name="通知失败重试",
            coalesce=True,
            misfire_grace_time=300,
        )
        self.scheduler.add_job(
            self._job_t_status_summary,
            CronTrigger(hour=11, minute=35),
            id="t_status_morning",
            name="做T上午汇总",
        )
        self.scheduler.add_job(
            self._job_t_status_summary,
            CronTrigger(hour=15, minute=5),
            id="t_status_closing",
            name="做T收盘汇总",
        )

        logger.info(f"✅ 定时任务注册完成: {len(self.scheduler.get_jobs())} 个")

    # ============================================================
    # 推送辅助
    # ============================================================

    # 默认需要 at_all 的任务（一天一次的"重要"通知）
    AT_ALL_TASKS = frozenset({
        "morning_brief",
        "auction_analysis",
        "noon_report",
        "closing_report",
        "holdings_news",
        "t_status_morning",
        "t_status_closing",
        "screen_review",
    })

    def _deliver(
        self,
        task_name: str,
        title: str,
        markdown: str,
        unique_suffix: str = "",
        *,
        at_all: Optional[bool] = None,
        banner_subtitle: str = "",
    ):
        """统一推送。

        Args:
            task_name: ledger 的 task_key 前缀。
            title: 钉钉消息标题。
            markdown: 推送正文。
            unique_suffix: 时间后缀避免同日多次 dedup。
            at_all: True 强制 @ 全体；False 显式不 @；None 走任务默认。
            banner_subtitle: 横幅副标题（推送内容最顶部的醒目 banner）。
        """
        day = datetime.now().strftime("%Y-%m-%d")
        # task_key 加 minute 精度，避免同日同一任务（例如手动重发）被判 delivered
        minute = datetime.now().strftime("%H%M")
        suffix = unique_suffix or f":{minute}"
        task_key = f"{task_name}:{day}{suffix}"
        if at_all is None:
            at_all = task_name in self.AT_ALL_TASKS

        # 顶部插入醒目 banner（避免被折叠 / 与 t_monitor 噪声混淆）
        # 默认副标题留空，避免与消息卡片标题重复，减少移动端折叠概率
        banner = render_banner(task_name, banner_subtitle or "")
        content = f"{banner}\n{markdown}"

        return self.delivery_router.send(
            task_key,
            title,
            content,
            task_name=task_name,
            at_all=at_all,
        )

    def _should_run_now(self) -> bool:
        return self.calendar.is_open_for_intraday_scan()

    # ============================================================
    # 定时任务
    # ============================================================

    def _job_morning_brief(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 早盘快讯")
        report = self.report_gen.generate_morning_brief()
        return self._deliver("morning_brief", "🌅 a-trade 早盘快讯", report)

    def _job_noon_report(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 午盘报告")
        report = self.report_gen.generate_noon_report()
        return self._deliver("noon_report", "☀️ a-trade 午盘报告", report)

    def _job_closing_report(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 收盘日报")
        report = self.report_gen.generate_closing_report()
        return self._deliver("closing_report", "📊 a-trade 收盘日报", report)

    def _job_t_replay(self):
        """独立推送做 T 复盘（与收盘日报解耦，确保必达）。

        推送时间 15:40（晚于 closing_report 5 分钟），便于：
        1. 收盘日报先到、T 复盘后到，避免被 closing 长内容挤掉
        2. 信号=0 时静默早退，避免每天推一条"无事发生"
        3. banner 副标题带触发/执行/拦截数字，一眼看到今日要点
        """
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 做T复盘独立推送")
        today = datetime.now().strftime("%Y-%m-%d")
        report = self.report_gen.generate_t_replay_report(today)
        from atrade.report.generator import T_REPLAY_EMPTY_MARKER
        if T_REPLAY_EMPTY_MARKER in report:
            logger.info("⏸️ 今日无任何 T 信号触发，跳过 t_replay 独立推送（closing_report 嵌入段已含）")
            return
        # banner 副标题从报告首段（摘要行）抽取，保证首屏醒目
        subtitle = self._extract_t_replay_subtitle(report)
        return self._deliver(
            "t_replay", "📊 a-trade 今日做T总结", report,
            banner_subtitle=subtitle,
        )

    @staticmethod
    def _extract_t_replay_subtitle(report: str) -> str:
        """从 generate_t_replay_report 输出中抽取摘要行作为 banner 副标题。"""
        for line in report.splitlines():
            line = line.strip()
            if line.startswith("🎯 今日摘要："):
                return line.replace("🎯 今日摘要：", "", 1).strip()
        return "今日做T总结"

    def _job_holdings_news(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 持仓新闻汇总")
        collector = NewsCollector(
            watch_symbols=self.watch_symbols,
            watch_keywords=self.watch_keywords,
        )
        news = collector.fetch_all_watchlist_news(per_symbol=3)
        if not news:
            logger.info("无持仓相关新闻")
            return
        md = "# 📰 持仓股新闻汇总\n\n" + collector.to_markdown(news, max_len=250)
        return self._deliver("holdings_news", "持仓新闻汇总", md)

    def _job_auction_analysis(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 集合竞价分析")
        report = self.report_gen.generate_auction_report()
        suffix = f":{datetime.now().strftime('%H%M')}"
        return self._deliver("auction_analysis", "📈 a-trade 竞价分析", report, suffix)

    def _job_pre_market_screen(self):
        """早盘选股推送：每个交易日 9:26 跑，覆盖 9:00-9:30 空档。

        与盘中选股的区别：
        - 不检查 is_open_for_intraday_scan（9:26 时还未开盘）
        - 仍会刷新 snapshot（取前一日收盘 + 集合竞价累计）
        - 推送标题加"早盘"以区分盘中选股
        """
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 早盘选股")
        md = self.screen_runner.run_once(source="pre_market")
        if not md:
            return
        suffix = f":{datetime.now().strftime('%H%M')}"
        return self._deliver(
            "pre_market_screen",
            "🌅 a-trade 早盘选股",
            md,
            suffix,
            banner_subtitle="今日开盘前候选清单",
        )

    def _job_screen_monitor(self):
        if not self.calendar.is_open_for_intraday_scan():
            return
        logger.info("⏰ 触发: 盘中选股")
        md = self.screen_runner.run_once(source="intraday")
        if not md:
            return
        suffix = f":{datetime.now().strftime('%H%M')}"
        return self._deliver("screen_monitor", "📈 a-trade 盘中选股", md, suffix)

    def _job_screen_review(self):
        """15:00 推送今日荐股胜率：买入价=首次推送价，盈亏=收盘价-推送价。"""
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 今日荐股胜率")
        today = datetime.now().strftime("%Y-%m-%d")
        records = self.screen_ledger.first_picks(today)
        if not records:
            logger.info("今日无荐股推送，跳过胜率复盘")
            return
        quotes = self.quote_provider.batch([r.symbol for r in records])
        md = build_screen_review(records, quotes)
        if not md:
            return
        suffix = f":{datetime.now().strftime('%H%M')}"
        return self._deliver("screen_review", "📊 a-trade 今日荐股胜率", md, suffix)

    def _job_t_monitor(self):
        if not self.calendar.is_open_for_intraday_scan():
            return
        logger.info("⏰ 触发: 做T监控")
        alerts = self.t_runner.run_once()
        if not alerts:
            return
        md = self.t_runner.to_markdown(alerts)
        suffix = f":{datetime.now().strftime('%H%M%S')}"
        try:
            result = self._deliver("t_monitor", "🔔 a-trade 做T信号", md, suffix)
            if not result.ok:
                raise RuntimeError(result.last_error or "双通道均失败")
            self.t_runner.commit_sent(alerts)
            logger.info(f"✅ {len(alerts)} 条做T告警已提交")
            # 自动执行（默认开启）
            from atrade.monitor.t_executor import TTradeExecutor
            executor = getattr(self, "t_executor", None)
            if executor is None:
                tmon_cfg = self.monitor_config.get("t_monitor", {})
                executor = TTradeExecutor(
                    tmon_cfg,
                    state_store=self.t_runner.t_state_store,
                )
                self.t_executor = executor
            for alert in alerts:
                trade = executor.execute(alert)
                if trade and not trade.get("skipped_reason"):
                    logger.success(f"📒 T-trade: {trade['direction']} {trade['symbol']} {trade['shares']} 股")
                elif trade and trade.get("skipped_reason"):
                    logger.info(f"⏭️ T-trade 跳过: {trade['symbol']} - {trade['skipped_reason']}")
        except Exception as e:
            logger.error(f"❌ 做T推送失败，告警不提交以便重试: {e}")

    def _start_reload_socket(self) -> None:
        """后台启动 Unix socket 服务，接收 reload 命令。"""
        import socketserver
        import threading

        sock_path = _RELOAD_SOCK_PATH
        if os.path.exists(sock_path):
            try:
                os.remove(sock_path)
            except OSError:
                pass

        outer = self  # capture for handler closure

        class _ReloadHandler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    line = self.rfile.readline()
                    cmd = line.strip().decode("utf-8", errors="ignore") if line else ""
                    if cmd == "reload":
                        try:
                            result = outer.reload_from_disk()
                            self.wfile.write(f"OK {result}\n".encode())
                        except Exception as e:
                            self.wfile.write(f"ERR reload failed: {e}\n".encode())
                    else:
                        self.wfile.write(b"ERR unknown command\n")
                except Exception as e:
                    try:
                        self.wfile.write(f"ERR handler: {e}\n".encode())
                    except Exception:
                        pass

        class _ThreadedUnixServer(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        server = _ThreadedUnixServer(sock_path, _ReloadHandler)
        try:
            os.chmod(sock_path, 0o660)
        except OSError:
            pass
        t = threading.Thread(target=server.serve_forever, daemon=True, name="reload-socket")
        t.start()
        logger.info(f"🔌 reload socket listening at {sock_path}")

    def reload_from_disk(self) -> dict:
        """重读 holdings + monitor JSON，更新内存中的 holdings、watch 列表、
        T 监控 symbols 与报告器持有。不重启 APScheduler。
        """
        from atrade.config import load_holdings_with_meta, load_monitor_config
        from atrade.monitor.t_monitor import TMonitorItem
        from atrade.monitor.t_trailing import TrailingConfig

        holdings_meta = load_holdings_with_meta()
        monitor = load_monitor_config()

        self.holdings = holdings_meta["holdings"]
        self.watch_symbols = [h["symbol"] for h in self.holdings]
        self.watch_keywords = holdings_meta.get("watch_keywords") or []

        disabled = set(holdings_meta.get("disabled_symbols") or [])
        t_monitor_config = monitor.get("t_monitor") or {}
        trailing_defaults = t_monitor_config.get("trailing_defaults") or {}
        lots_per_trade = float(t_monitor_config.get("lots_per_trade", 1.0))
        t_symbols_filtered = _derive_t_symbols(
            self.holdings,
            disabled,
            t_monitor_config.get("symbols") or [],
        )
        self.t_runner.config.symbols = [
            TMonitorItem(
                symbol=str(s["symbol"]).zfill(6),
                name=str(s.get("name", "")),
                cost_price=float(s.get("cost_price", 0.0)),
                quantity=int(s.get("quantity", 0)),
                note=str(s.get("note", "")),
                trailing=TrailingConfig.from_dict(
                    trailing_defaults,
                    s.get("trailing") or {},
                    exit_lots=lots_per_trade,
                ),
            )
            for s in t_symbols_filtered
        ]
        self.t_runner.config.trailing_defaults = trailing_defaults
        self.t_runner.config.lots_per_trade = lots_per_trade
        self.monitor_config = monitor
        if hasattr(self, "t_executor"):
            del self.t_executor

        if hasattr(self, "report_gen") and self.report_gen is not None:
            self.report_gen.holdings = self.holdings
            self.report_gen.watch_symbols = self.watch_symbols
            self.report_gen.watch_keywords = self.watch_keywords

        logger.info(
            f"🔁 配置已重载: holdings={len(self.holdings)} "
            f"t_symbols={len(self.t_runner.config.symbols)} "
            f"disabled={len(disabled)}"
        )
        return {
            "holdings": len(self.holdings),
            "t_symbols": len(self.t_runner.config.symbols),
            "disabled": len(disabled),
        }

    def _job_delivery_heartbeat(self):
        if not self.calendar.is_trade_day():
            return
        markdown = "\n".join([
            "# ✅ a-trade 调度心跳",
            "",
            "- 主通道：钉钉",
            "- 备用通道：QQ",
            "- 今日任务：08:00 早报、12:30 午报、15:30 收盘、17:00 新闻",
            "- 做T：盘中每 2 分钟扫描，11:35/15:05 状态汇总",
            "- 状态：调度器已就绪",
        ])
        return self._deliver("delivery_heartbeat", "✅ a-trade 调度心跳", markdown)

    def _job_delivery_guard(self, task_name: str, callback):
        day = datetime.now().strftime("%Y-%m-%d")
        if not self.delivery_ledger.is_delivered(f"{task_name}:{day}"):
            logger.warning(f"送达检查发现漏发: {task_name}")
            return callback()

    def _job_retry_failed(self):
        results = self.delivery_router.retry_failed()
        if results:
            logger.info(f"通知失败重试完成: {len(results)} 条")
        return results

    def _job_t_status_summary(self):
        if not self.calendar.is_trade_day():
            return
        suffix = f":{datetime.now().strftime('%H%M')}"
        return self._deliver(
            "t_status",
            "🔎 a-trade 做T状态",
            self.t_runner.status_markdown(),
            suffix,
        )

    def _job_t_state_reset(self):
        if not self.calendar.is_trade_day():
            return
        self.t_runner.reset_t_state_day()
        logger.info("🔄 做T当日状态已重置")

    def _recover_missed_tasks(self):
        now = datetime.now()
        tasks = [
            RecoveryTask("morning_brief", time(8, 0), time(10, 0), self._job_morning_brief),
            RecoveryTask("auction_analysis", time(9, 25), time(10, 0), self._job_auction_analysis),
            RecoveryTask("noon_report", time(12, 30), time(14, 0), self._job_noon_report),
            RecoveryTask("closing_report", time(15, 35), time(23, 59), self._job_closing_report),
            RecoveryTask("t_replay", time(15, 40), time(23, 59), self._job_t_replay),
            RecoveryTask("holdings_news", time(17, 0), time(23, 59), self._job_holdings_news),
        ]
        return recover_missed_tasks(
            now,
            self.calendar.is_trade_day(now),
            self.delivery_ledger.is_delivered,
            tasks,
        )

    # ============================================================
    # 启动/停止
    # ============================================================

    def start(self, *, ready_timeout: float = 30.0):
        """启动调度器和 botpy client。

        Args:
            ready_timeout: 等待 botpy READY 事件的最长时间（秒）。
        """
        logger.info("🚀 启动 a-trade 调度器")

        # 启动 botpy（后台线程跑事件循环）
        self._client = ATradeClient(
            intents=botpy.Intents(public_messages=True),
            scheduler=self,
        )

        def _run_bot():
            self._bot_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._bot_loop)
            try:
                self._bot_loop.run_until_complete(
                    self._client.run(appid=self.appid, secret=self.secret)
                )
            finally:
                self._bot_loop.close()

        self._bot_thread = threading.Thread(target=_run_bot, daemon=True)
        self._bot_thread.start()

        # 等 botpy READY 事件，超时则报错退出而非静默启动
        import time
        start = time.time()
        while time.time() - start < ready_timeout:
            if self._client and getattr(self._client, "robot", None):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"botpy 客户端在 {ready_timeout}s 内未就绪，请检查网络与凭据"
            )
        logger.success("✅ botpy 客户端已就绪")

        # 启动调度器
        self.scheduler.start()
        logger.success("✅ 调度器已启动")
        self._start_reload_socket()
        self._print_next_jobs()
        recovered = self._recover_missed_tasks()
        if recovered:
            logger.info(f"启动补发任务: {recovered}")

    def _print_next_jobs(self):
        """打印下次任务时间。"""
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            logger.info(f"  📅 {job.name}: 下次 {next_run}")

    def stop(self):
        """停止调度器。"""
        logger.info("停止调度器...")
        self.scheduler.shutdown()
        if self._client:
            asyncio.run_coroutine_threadsafe(
                self._client.close(), self._bot_loop
            )
