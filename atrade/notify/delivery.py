"""通知送达结果与错误契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class DeliveryError(RuntimeError):
    """单个通知通道的明确失败。"""

    def __init__(self, channel: str, message: str, response: Optional[dict] = None):
        super().__init__(message)
        self.channel = channel
        self.response = response or {}


@dataclass(frozen=True)
class DeliveryAttempt:
    channel: str
    ok: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    response_code: Optional[str] = None


@dataclass(frozen=True)
class DeliveryResult:
    task_key: str
    attempts: tuple[DeliveryAttempt, ...]
    skipped: bool = False

    @property
    def ok(self) -> bool:
        return self.skipped or any(attempt.ok for attempt in self.attempts)

    @property
    def successful_attempt(self) -> Optional[DeliveryAttempt]:
        return next((attempt for attempt in reversed(self.attempts) if attempt.ok), None)

    @property
    def channel(self) -> Optional[str]:
        attempt = self.successful_attempt
        return attempt.channel if attempt else None

    @property
    def message_id(self) -> Optional[str]:
        attempt = self.successful_attempt
        return attempt.message_id if attempt else None

    @property
    def last_error(self) -> Optional[str]:
        return next(
            (attempt.error for attempt in reversed(self.attempts) if attempt.error),
            None,
        )
