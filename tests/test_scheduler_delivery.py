import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from apscheduler.schedulers.background import BackgroundScheduler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.notify.delivery import DeliveryAttempt, DeliveryResult
from atrade.scheduler.runner import DailyScheduler


def _scheduler_shell():
    scheduler = object.__new__(DailyScheduler)
    scheduler.calendar = Mock()
    scheduler.calendar.is_trade_day.return_value = True
    scheduler.calendar.is_open_for_intraday_scan.return_value = True
    scheduler.delivery_router = Mock()
    scheduler.delivery_router.send.return_value = DeliveryResult(
        task_key="x", attempts=(DeliveryAttempt(channel="dingtalk", ok=True),)
    )
    scheduler.delivery_ledger = Mock()
    scheduler.report_gen = Mock()
    scheduler.report_gen.generate_morning_brief.return_value = "早报正文"
    scheduler.report_gen.generate_noon_report.return_value = "午报正文"
    scheduler.report_gen.generate_closing_report.return_value = "收盘正文"
    scheduler.t_runner = Mock()
    return scheduler


def test_morning_report_routes_through_delivery_router():
    scheduler = _scheduler_shell()
    scheduler._job_morning_brief()
    args, kwargs = scheduler.delivery_router.send.call_args
    assert args[0].startswith("morning_brief:")
    assert args[1] == "🌅 a-trade 早盘快讯"
    # 优化后 markdown 顶部应追加醒目 banner
    assert "早报正文" in args[2]
    assert "🟢" in args[2]
    assert args[2].index("🟢") < args[2].index("早报正文")
    assert kwargs["task_name"] == "morning_brief"


def test_t_monitor_commits_only_after_delivery_success():
    scheduler = _scheduler_shell()
    alerts = [{"symbol": "600522", "__signal_key__": "k"}]
    scheduler.t_runner.run_once.return_value = alerts
    scheduler.t_runner.to_markdown.return_value = "做T信号"
    scheduler._job_t_monitor()
    scheduler.t_runner.commit_sent.assert_called_once_with(alerts)


def test_t_monitor_does_not_commit_after_dual_failure():
    scheduler = _scheduler_shell()
    alerts = [{"symbol": "600522", "__signal_key__": "k"}]
    scheduler.t_runner.run_once.return_value = alerts
    scheduler.t_runner.to_markdown.return_value = "做T信号"
    scheduler.delivery_router.send.return_value = DeliveryResult(
        task_key="x",
        attempts=(DeliveryAttempt(channel="dingtalk", ok=False, error="down"),),
    )
    scheduler._job_t_monitor()
    scheduler.t_runner.commit_sent.assert_not_called()


def test_guard_calls_callback_only_when_missing():
    scheduler = _scheduler_shell()
    callback = Mock()
    scheduler.delivery_ledger.is_delivered.return_value = False
    scheduler._job_delivery_guard("morning_brief", callback)
    callback.assert_called_once_with()
    callback.reset_mock()
    scheduler.delivery_ledger.is_delivered.return_value = True
    scheduler._job_delivery_guard("morning_brief", callback)
    callback.assert_not_called()


def test_heartbeat_mentions_primary_and_fallback_channels():
    scheduler = _scheduler_shell()
    scheduler._job_delivery_heartbeat()
    markdown = scheduler.delivery_router.send.call_args.args[2]
    assert "主通道：钉钉" in markdown
    assert "备用通道：QQ" in markdown


def test_t_status_summary_is_always_observable():
    scheduler = _scheduler_shell()
    scheduler.t_runner.status_markdown.return_value = "⏸️ 无信号"
    scheduler._job_t_status_summary()
    assert "⏸️ 无信号" in scheduler.delivery_router.send.call_args.args[2]


def test_retry_job_calls_router_queue():
    scheduler = _scheduler_shell()
    scheduler.delivery_router.retry_failed.return_value = [SimpleNamespace(ok=True)]
    results = scheduler._job_retry_failed()
    assert len(results) == 1


def test_t_state_reset_runs_at_trade_day():
    scheduler = _scheduler_shell()

    scheduler._job_t_state_reset()

    scheduler.t_runner.reset_t_state_day.assert_called_once_with()


def test_t_state_reset_skips_non_trade_day():
    scheduler = _scheduler_shell()
    scheduler.calendar.is_trade_day.return_value = False

    scheduler._job_t_state_reset()

    scheduler.t_runner.reset_t_state_day.assert_not_called()


def test_scheduler_registers_reset_and_closing_at_1535():
    scheduler = object.__new__(DailyScheduler)
    scheduler.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.monitor_config = {
        "screen": {"interval_minutes": 30},
        "t_monitor": {"scan_interval_minutes": 2},
    }

    scheduler._setup_jobs()

    jobs = {job.id: job for job in scheduler.scheduler.get_jobs()}
    assert "t_state_reset" in jobs
    assert "t_replay" in jobs  # 做T复盘独立推送（15:36）
    assert "pre_market_screen" in jobs  # 早盘选股 9:26
    assert "hour='9', minute='30'" in str(jobs["t_state_reset"].trigger)
    assert "hour='9', minute='26'" in str(jobs["pre_market_screen"].trigger)
    assert "hour='15', minute='35'" in str(jobs["closing_report"].trigger)
    assert "hour='15', minute='36'" in str(jobs["t_replay"].trigger)
    assert "hour='15', minute='40'" in str(jobs["closing_report_guard"].trigger)
