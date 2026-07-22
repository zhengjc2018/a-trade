from atrade.notify.delivery import DeliveryAttempt, DeliveryError, DeliveryResult


def test_delivery_result_ok_and_message_id():
    attempt = DeliveryAttempt(channel="dingtalk", ok=True, message_id="m1")
    result = DeliveryResult(task_key="morning:2026-07-23", attempts=(attempt,))
    assert result.ok is True
    assert result.channel == "dingtalk"
    assert result.message_id == "m1"


def test_delivery_result_failed_contains_last_error():
    attempt = DeliveryAttempt(channel="dingtalk", ok=False, error="timeout")
    result = DeliveryResult(task_key="morning:2026-07-23", attempts=(attempt,))
    assert result.ok is False
    assert result.last_error == "timeout"


def test_delivery_error_keeps_channel_and_response():
    error = DeliveryError("dingtalk", "keyword mismatch", response={"errcode": 310000})
    assert error.channel == "dingtalk"
    assert error.response["errcode"] == 310000
