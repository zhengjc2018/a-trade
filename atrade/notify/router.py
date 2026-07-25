"""钉钉主通道、QQ 降级通知路由。"""

from __future__ import annotations

import hashlib
from typing import Optional

from loguru import logger

from .delivery import DeliveryAttempt, DeliveryResult
from .dingtalk import render_for_dingtalk
from .ledger import DeliveryLedger


def _supports_at_all(notifier) -> bool:
    """Fast inspect: does this notifier's send_markdown accept at_all?"""
    import inspect
    try:
        sig = inspect.signature(notifier.send_markdown)
    except (TypeError, ValueError):
        return False
    return "at_all" in sig.parameters


def _safe_send(notifier, content, title, at_all):
    """按 send_markdown 的实际签名调用，避免 Mock 严格 kwargs 报错。"""
    import inspect
    try:
        sig = inspect.signature(notifier.send_markdown)
        kwargs = {}
        if "title" in sig.parameters and title is not None:
            kwargs["title"] = title
        if "at_all" in sig.parameters:
            kwargs["at_all"] = at_all
        return notifier.send_markdown(content, **kwargs)
    except (TypeError, ValueError):
        return notifier.send_markdown(content)


class DeliveryRouter:
    def __init__(self, primary, fallback=None, ledger: Optional[DeliveryLedger] = None):
        self.primary = primary
        self.fallback = fallback
        self.ledger = ledger or DeliveryLedger()
        self._default_at_all = False

    def set_default_at_all(self, enabled: bool) -> None:
        """设置默认 at_all 行为（可被 send() at_all 参数覆盖）。"""
        self._default_at_all = bool(enabled)

    @staticmethod
    def _message_id(response: dict) -> Optional[str]:
        return response.get("id") or response.get("message_id") or response.get("processQueryKey")

    @staticmethod
    def _success(channel: str, response: dict) -> bool:
        if channel == "dingtalk":
            return response.get("errcode") == 0
        return bool(response.get("id") or response.get("message_id"))

    def _attempt(
        self,
        channel: str,
        notifier,
        title: str,
        markdown: str,
        at_all: bool,
    ) -> DeliveryAttempt:
        content = render_for_dingtalk(markdown) if channel == "dingtalk" else markdown
        try:
            if channel == "dingtalk":
                response = _safe_send(notifier, content, title, at_all)
            else:
                response = _safe_send(notifier, content, None, at_all)
            if not self._success(channel, response):
                return DeliveryAttempt(
                    channel=channel,
                    ok=False,
                    error=str(response.get("errmsg") or response),
                    response_code=str(response.get("errcode") or "invalid_response"),
                    at_all=at_all,
                )
            return DeliveryAttempt(
                channel=channel,
                ok=True,
                message_id=self._message_id(response),
                response_code=str(response.get("errcode", 0)),
                at_all=at_all,
            )
        except Exception as error:
            return DeliveryAttempt(channel=channel, ok=False, error=str(error) or type(error).__name__, at_all=at_all)

    def send(
        self,
        task_key: str,
        title: str,
        markdown: str,
        task_name: Optional[str] = None,
        at_all: Optional[bool] = None,
    ) -> DeliveryResult:
        if self.ledger.is_delivered(task_key):
            return DeliveryResult(task_key=task_key, attempts=(), skipped=True)

        # at_all 默认值：实例设置全局 + task 级覆盖
        if at_all is None:
            at_all = bool(getattr(self, "_default_at_all", False))

        attempts = [self._attempt("dingtalk", self.primary, title, markdown, at_all=at_all)]
        if not attempts[-1].ok and self.fallback is not None:
            attempts.append(self._attempt("qq", self.fallback, title, markdown, at_all=at_all))

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
