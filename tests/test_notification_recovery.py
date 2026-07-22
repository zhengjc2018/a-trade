from datetime import datetime, time

from atrade.scheduler.recovery import RecoveryTask, recover_missed_tasks


def _run(now, delivered=False):
    calls = []
    tasks = [
        RecoveryTask("morning_brief", time(8, 0), time(10, 0), lambda: calls.append("morning")),
        RecoveryTask("noon_report", time(12, 30), time(14, 0), lambda: calls.append("noon")),
    ]
    recovered = recover_missed_tasks(
        now,
        True,
        lambda key: delivered,
        tasks,
    )
    return calls, recovered


def test_recovers_morning_at_0830():
    calls, recovered = _run(datetime(2026, 7, 23, 8, 30))
    assert calls == ["morning"]
    assert recovered == ["morning_brief:2026-07-23"]


def test_does_not_recover_morning_after_deadline():
    calls, recovered = _run(datetime(2026, 7, 23, 10, 1))
    assert calls == []
    assert recovered == []


def test_does_not_duplicate_delivered_task():
    calls, recovered = _run(datetime(2026, 7, 23, 8, 30), delivered=True)
    assert calls == []
    assert recovered == []


def test_recovers_noon_at_1300():
    calls, recovered = _run(datetime(2026, 7, 23, 13, 0))
    assert calls == ["noon"]
    assert recovered == ["noon_report:2026-07-23"]
