"""通知漏发恢复时间窗。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Callable


@dataclass(frozen=True)
class RecoveryTask:
    task_name: str
    earliest: time
    deadline: time
    callback: Callable[[], object]


def recover_missed_tasks(
    now: datetime,
    is_trade_day: bool,
    is_delivered: Callable[[str], bool],
    tasks: list[RecoveryTask],
) -> list[str]:
    if not is_trade_day:
        return []
    day = now.strftime("%Y-%m-%d")
    recovered = []
    for task in tasks:
        if not (task.earliest <= now.time() <= task.deadline):
            continue
        task_key = f"{task.task_name}:{day}"
        if is_delivered(task_key):
            continue
        task.callback()
        recovered.append(task_key)
    return recovered
