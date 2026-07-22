"""钉钉主通道、QQ 降级通知路由。"""

from __future__ import annotations

import hashlib
from typing import Optional

from loguru import logger

from .delivery import DeliveryAttempt, DeliveryResult
from .dingtalk import render_for_dingtalk
from .ledger import DeliveryLedger


class DeliveryRouter:
    def __init__(self, primary, fallback=None, ledger: Optional[DeliveryLedger] = None):
        self.primary = primary
        self.fallback = fallback
        self.ledger = ledger or DeliveryLedger()

    @staticmethod
    def _message_id(response: dict) -> Optional[str]:
        return response.get("id") or response.get("message_id") or response.get("processQueryKey")

    @staticmethod
    def _success(channel: str, response: dict) -> bool:
        if channel == "dingtalk":
            return response.get("errcode") == 0
        return bool(response.get("id") or response.get("message_id"))

    def _attempt(self, channel: str, notifier, title: str, markdown: str) -> DeliveryAttempt:
        content = render_for_dingtalk(markdown) if channel == "dingtalk" else markdown
        try:
            if channel == "dingtalk":
                response = notifier.send_markdown(content, title=title)
            else:
                response = notifier.send_markdown(content)
            if not self._success(channel, response):
                return DeliveryAttempt(
                    channel=channel,
                    ok=False,
                    error=str(response.get("errmsg") or response),
                    response_code=str(response.get("errcode") or "invalid_response"),
                )
            return DeliveryAttempt(
                channel=channel,
                ok=True,
                message_id=self._message_id(response),
                response_code=str(response.get("errcode", 0)),
            )
        except Exception as error:
            return DeliveryAttempt(channel=channel, ok=False, error=str(error) or type(error).__name__)

    def send(
        self,
        task_key: str,
        title: str,
        markdown: str,
        task_name: Optional[str] = None,
    ) -> DeliveryResult:
        if self.ledger.is_delivered(task_key):
            return DeliveryResult(task_key=task_key, attempts=(), skipped=True)

        attempts = [self._attempt("dingtalk", self.primary, title, markdown)]
        if not attempts[-1].ok and self.fallback is not None:
            attempts.append(self._attempt("qq", self.fallback, title, markdown))

        result = DeliveryResult(task_key=task_key, attempts=tuple(attempts))
        content_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        self.ledger.record_result(
            task_name or title,
            content_hash,
            result,
            title=title,
            markdown=markdown,
        )
        if result.ok:
            logger.success(f"通知送达 task={task_key} channel={result.channel}")
        else:
            logger.error(f"通知失败 task={task_key} error={result.last_error}")
        return result

    def retry_failed(self, limit: int = 20) -> list[DeliveryResult]:
        results = []
        for row in self.ledger.pending_failures(limit=limit):
            results.append(
                self.send(
                    row["task_key"],
                    row["title"],
                    row["markdown"],
                    task_name=row["task_name"],
                )
            )
        return results
