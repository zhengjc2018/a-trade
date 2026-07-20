"""每日定时任务调度器。"""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Optional

import botpy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from botpy import logging
from botpy.message import GroupMessage
from botpy.types.message import MarkdownPayload
from dotenv import load_dotenv
from loguru import logger

from atrade.config import (
    load_holdings as load_holdings_config,
)
from atrade.config import (
    load_monitor_config as load_monitor_config_from_module,
)
from atrade.config import (
    load_watch_keywords,
)
from atrade.monitor import ScreenMonitorRunner, TMonitorRunner, TradingCalendar
from atrade.news.collector import NewsCollector
from atrade.report.generator import ReportGenerator

_log = logging.get_logger()
load_dotenv()

# 配置文件统一由 atrade.config 加载；本模块不再直接读 JSON。


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
        self.holdings = load_holdings_config()
        self.watch_symbols = [h.get("symbol") for h in self.holdings if h.get("symbol")]
        self.watch_keywords = load_watch_keywords() or self._load_keywords()
        self.monitor_config = load_monitor_config_from_module()
        self.calendar = TradingCalendar()
        self.screen_runner = ScreenMonitorRunner(self.monitor_config.get("screen"))
        self.t_runner = TMonitorRunner(self.monitor_config.get("t_monitor"))

        self.report_gen = ReportGenerator(
            holdings=self.holdings,
            watch_symbols=self.watch_symbols,
            watch_keywords=self.watch_keywords,
        )

        self.group_openid = os.getenv("QQ_TARGET_GROUP")
        self.appid = os.getenv("QQ_BOT_APPID")
        self.secret = os.getenv("QQ_BOT_APPSECRET")

        if not all([self.appid, self.secret, self.group_openid]):
            raise ValueError("请在 .env 配置 QQ_BOT_APPID / SECRET / TARGET_GROUP")

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
        # 早盘快讯：每个交易日 8:00
        self.scheduler.add_job(
            self._job_morning_brief,
            CronTrigger(hour=8, minute=0),
            id="morning_brief",
            name="早盘快讯",
        )

        # 午盘报告：每个交易日 12:30
        self.scheduler.add_job(
            self._job_noon_report,
            CronTrigger(hour=12, minute=30),
            id="noon_report",
            name="午盘报告",
        )

        # 收盘日报：每个交易日 15:30
        self.scheduler.add_job(
            self._job_closing_report,
            CronTrigger(hour=15, minute=30),
            id="closing_report",
            name="收盘日报",
        )

        # 持仓新闻汇总：每个交易日 17:00
        self.scheduler.add_job(
            self._job_holdings_news,
            CronTrigger(hour=17, minute=0),
            id="holdings_news",
            name="持仓新闻",
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

        logger.info("✅ 定时任务注册完成: 6 个")

    # ============================================================
    # 推送辅助
    # ============================================================

    async def _push_markdown(self, title: str, markdown: str):
        """通过 botpy API 推 Markdown 到群。

        使用 atrade.notify.split_markdown_by_bytes 按 UTF-8 字节切分；
        超过平台 4096 字节上限时会分多条发送（带尾部省略）。
        """
        from atrade.notify import split_markdown_by_bytes
        if not self._client:
            logger.error("botpy client 未启动")
            return
        full_md = f"# {title}\n\n{markdown}"
        chunks = split_markdown_by_bytes(full_md, max_bytes=3800)
        for i, chunk in enumerate(chunks):
            try:
                result = await self._client.api.post_group_message(
                    group_openid=self.group_openid,
                    msg_type=2,
                    markdown=MarkdownPayload(content=chunk),
                )
                logger.success(
                    f"✅ 推送成功 [{i+1}/{len(chunks)}]: id={result.get('id')}"
                )
            except Exception as e:
                logger.error(f"❌ 推送失败 [{i+1}/{len(chunks)}]: {e}")

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
        asyncio.run_coroutine_threadsafe(
            self._push_markdown("🌅 a-trade 早盘快讯", report),
            self._bot_loop,
        )

    def _job_noon_report(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 午盘报告")
        report = self.report_gen.generate_noon_report()
        asyncio.run_coroutine_threadsafe(
            self._push_markdown("☀️ a-trade 午盘报告", report),
            self._bot_loop,
        )

    def _job_closing_report(self):
        if not self.calendar.is_trade_day():
            return
        logger.info("⏰ 触发: 收盘日报")
        report = self.report_gen.generate_closing_report()
        asyncio.run_coroutine_threadsafe(
            self._push_markdown("📊 a-trade 收盘日报", report),
            self._bot_loop,
        )

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
        asyncio.run_coroutine_threadsafe(
            self._push_markdown("持仓新闻汇总", md),
            self._bot_loop,
        )

    def _job_screen_monitor(self):
        if not self.calendar.is_open_for_intraday_scan():
            return
        logger.info("⏰ 触发: 盘中选股")
        md = self.screen_runner.run_once()
        if not md:
            return
        asyncio.run_coroutine_threadsafe(
            self._push_markdown("📈 a-trade 盘中选股", md),
            self._bot_loop,
        )

    def _job_t_monitor(self):
        if not self.calendar.is_open_for_intraday_scan():
            return
        logger.info("⏰ 触发: 做T监控")
        alerts = self.t_runner.run_once()
        if not alerts:
            return
        md = self.t_runner.to_markdown(alerts)
        future = asyncio.run_coroutine_threadsafe(
            self._push_markdown("🔔 a-trade 做T信号", md),
            self._bot_loop,
        )
        # P1-4：等待推送结果，成功后才提交已发送状态
        try:
            future.result(timeout=10)
            self.t_runner.commit_sent(alerts)
            logger.info(f"✅ {len(alerts)} 条做T告警已提交")
        except Exception as e:
            logger.error(f"❌ 做T推送失败，告警不提交以便重试: {e}")

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
        self._print_next_jobs()

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
