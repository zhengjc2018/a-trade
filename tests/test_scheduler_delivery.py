from types import SimpleNamespace
from unittest.mock import Mock

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
    assert args[2] == "早报正文"
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
