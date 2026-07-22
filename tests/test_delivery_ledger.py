from atrade.notify.delivery import DeliveryAttempt, DeliveryResult
from atrade.notify.ledger import DeliveryLedger


def test_ledger_marks_delivered_idempotently(tmp_path):
    ledger = DeliveryLedger(tmp_path / "delivery.db")
    result = DeliveryResult(
        task_key="morning:2026-07-23",
        attempts=(DeliveryAttempt(channel="dingtalk", ok=True, message_id="m1"),),
    )
    ledger.record_result("早报", "hash1", result)
    assert ledger.is_delivered(result.task_key)
    ledger.record_result("早报", "hash1", result)
    assert ledger.get(result.task_key)["attempt_count"] == 1


def test_ledger_returns_failed_deliveries_for_retry(tmp_path):
    ledger = DeliveryLedger(tmp_path / "delivery.db")
    result = DeliveryResult(
        task_key="morning:2026-07-23",
        attempts=(DeliveryAttempt(channel="dingtalk", ok=False, error="timeout"),),
    )
    ledger.record_result("早报", "hash1", result, title="早报", markdown="正文")
    pending = ledger.pending_failures()
    assert len(pending) == 1
    assert pending[0]["task_key"] == result.task_key
    assert pending[0]["last_error"] == "timeout"
    assert pending[0]["title"] == "早报"


def test_ledger_retry_increments_attempt_count(tmp_path):
    ledger = DeliveryLedger(tmp_path / "delivery.db")
    failed = DeliveryResult(
        task_key="morning:2026-07-23",
        attempts=(DeliveryAttempt(channel="dingtalk", ok=False, error="timeout"),),
    )
    ledger.record_result("早报", "hash1", failed, title="早报", markdown="正文")
    ledger.record_result("早报", "hash1", failed, title="早报", markdown="正文")
    assert ledger.get(failed.task_key)["attempt_count"] == 2
