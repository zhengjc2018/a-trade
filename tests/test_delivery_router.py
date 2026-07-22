from unittest.mock import Mock

from atrade.notify.ledger import DeliveryLedger
from atrade.notify.router import DeliveryRouter


def _notifier(response=None, error=None):
    notifier = Mock()
    if error:
        notifier.send_markdown.side_effect = error
    else:
        notifier.send_markdown.return_value = response or {"errcode": 0, "errmsg": "ok"}
    return notifier


def test_primary_success_skips_fallback(tmp_path):
    primary = _notifier({"errcode": 0, "errmsg": "ok"})
    fallback = _notifier({"id": "qq1"})
    ledger = DeliveryLedger(tmp_path / "delivery.db")
    router = DeliveryRouter(primary, fallback, ledger)
    result = router.send("morning:2026-07-23", "早报", "股票正文")
    assert result.ok
    assert result.channel == "dingtalk"
    fallback.send_markdown.assert_not_called()
    assert ledger.is_delivered(result.task_key)


def test_primary_failure_uses_fallback(tmp_path):
    primary = _notifier(error=RuntimeError("dingtalk down"))
    fallback = _notifier({"id": "qq1"})
    router = DeliveryRouter(primary, fallback, DeliveryLedger(tmp_path / "delivery.db"))
    result = router.send("morning:2026-07-23", "早报", "股票正文")
    assert result.ok
    assert result.channel == "qq"
    assert len(result.attempts) == 2


def test_dual_failure_is_persisted(tmp_path):
    ledger = DeliveryLedger(tmp_path / "delivery.db")
    router = DeliveryRouter(
        _notifier(error=RuntimeError("dingtalk down")),
        _notifier(error=RuntimeError("qq down")),
        ledger,
    )
    result = router.send("morning:2026-07-23", "早报", "股票正文")
    assert result.ok is False
    assert len(ledger.pending_failures()) == 1


def test_delivered_task_key_is_not_sent_twice(tmp_path):
    primary = _notifier()
    router = DeliveryRouter(primary, _notifier(), DeliveryLedger(tmp_path / "delivery.db"))
    router.send("morning:2026-07-23", "早报", "股票正文")
    second = router.send("morning:2026-07-23", "早报", "股票正文")
    assert second.ok
    assert second.skipped is True
    assert primary.send_markdown.call_count == 1
