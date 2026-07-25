"""回测 Job 状态机 + 单线程串行 Runner。

状态机：
    queued --[take()]--> running --[ok]--> completed
                                    --[err]--> failed
    queued/running 可被 cancel() 转换为 cancelled。

并发：使用 threading.Semaphore(1) 把所有回测 job 串行化，避免雪球 API 限频。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from loguru import logger

from .storage import BacktestJobStore, ReportStore


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _validate_symbol(value: str) -> str:
    """原值必须是 6 位数字（不允许 zfill）。"""
    text = str(value).strip() if isinstance(value, str) else str(value)
    if not text or not text.isdigit() or len(text) != 6:
        raise ValueError(f"symbol 必须是 6 位数字: {value!r}")
    return text


def _validate_quantity(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"quantity 必须为正整数: {value!r}")
    return value


def _validate_price(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} 必须 > 0: {value!r}")
    return float(value)


@dataclass
class T0JobRequest:
    symbol: str
    cost_price: float
    quantity: int
    start_date: str = "2024-01-01"
    end_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    scale: str = "1d"
    push: bool = True
    sweep: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> T0JobRequest:
        if not isinstance(payload, dict):
            raise ValueError("request body 必须是 dict")
        body = dict(payload)
        raw_symbol = str(body.get("symbol", "") or "")
        if len(raw_symbol) != 6 or not raw_symbol.isdigit():
            raise ValueError(
                f"symbol 必须是 6 位数字, 收到 {raw_symbol!r}"
            )
        return cls(
            symbol=raw_symbol,
            cost_price=_validate_price(body["cost_price"], "cost_price"),
            quantity=_validate_quantity(int(body["quantity"])),
            start_date=str(body.get("start_date") or "2024-01-01"),
            end_date=str(
                body.get("end_date") or datetime.now().strftime("%Y-%m-%d")
            ),
            scale=str(body.get("scale", "1d")),
            push=bool(body.get("push", True)),
            sweep=bool(body.get("sweep", False)),
        )


@dataclass
class SweepRequest:
    symbol: str
    cost_price: float
    quantity: int
    start_date: str = "2024-01-01"
    end_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    scale: str = "1d"
    take_profits: list[float] = field(default_factory=lambda: [0.01, 0.02, 0.03, 0.05, 0.07, 0.10])
    stop_losses: list[float] = field(default_factory=lambda: [0.01, 0.02, 0.03, 0.05])
    push: bool = True

    @classmethod
    def from_dict(cls, payload: dict) -> SweepRequest:
        if not isinstance(payload, dict):
            raise ValueError("sweep body 必须是 dict")
        body = dict(payload)
        raw_symbol = str(body.get("symbol", "") or "")
        if len(raw_symbol) != 6 or not raw_symbol.isdigit():
            raise ValueError(
                f"symbol 必须是 6 位数字, 收到 {raw_symbol!r}"
            )
        symbol = raw_symbol
        cost = _validate_price(body["cost_price"], "cost_price")
        qty = _validate_quantity(int(body["quantity"]))

        def _parse_percents(key: str, default: list[float]) -> list[float]:
            v = body.get(key, default)
            if v in (None, ""):
                v = default
            if isinstance(v, str):
                v = [float(x.strip()) for x in v.split(",") if x.strip()]
            if not isinstance(v, (list, tuple)) or not v:
                v = default
            out = []
            for x in v:
                try:
                    f = float(x)
                except (TypeError, ValueError) as e:
                    raise ValueError(f"{key} 元素非法: {x!r}") from e
                if not 0 < f < 1:
                    raise ValueError(f"{key} 必须在 0..1 之间: {f!r}")
                out.append(f)
            return sorted(out)

        return cls(
            symbol=symbol,
            cost_price=cost,
            quantity=qty,
            start_date=str(body.get("start_date") or "2024-01-01"),
            end_date=str(
                body.get("end_date") or datetime.now().strftime("%Y-%m-%d")
            ),
            scale=str(body.get("scale", "1d")),
            take_profits=_parse_percents(
                "take_profits",
                [0.01, 0.02, 0.03, 0.05, 0.07, 0.10],
            ),
            stop_losses=_parse_percents(
                "stop_losses",
                [0.01, 0.02, 0.03, 0.05],
            ),
            push=bool(body.get("push", True)),
        )


@dataclass
class BacktestJob:
    job_id: str
    type: str  # "t0" | "sweep" | "portfolio"
    symbol: str
    request: dict
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    created_at: str = field(default_factory=_now)
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    summary: Optional[dict] = None
    report_path: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["status"] = self.status.value
        return body


# ---- Runner ----
class BacktestRunner:
    """单线程串行回测执行器。

    - ``submit`` 返回 job_id，立即返回；执行在后台线程。
    - 同时只能跑一个 job；其余排队。
    - ``status`` 读 BacktestJobStore。
    """

    def __init__(
        self,
        job_store: Optional[BacktestJobStore] = None,
        report_store: Optional[ReportStore] = None,
        executor: Optional[Callable[[BacktestJob], dict]] = None,
    ) -> None:
        self.jobs = job_store or BacktestJobStore()
        self.reports = report_store or ReportStore()
        self._executor = executor  # type: ignore[assignment]
        self._sema = threading.Semaphore(1)
        self._cancel_flags: dict[str, threading.Event] = {}
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ---- 控制 ----
    def set_executor(self, func: Callable[[BacktestJob], dict]) -> None:
        """注入执行函数（构造回测 job 的关键逻辑）。"""
        self._executor = func

    def submit(self, job: BacktestJob) -> str:
        self.jobs.upsert(job.to_dict())
        cancel_evt = threading.Event()
        self._cancel_flags[job.job_id] = cancel_evt
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._loop,
                    name=f"backtest-runner-{job.job_id[:8]}",
                    daemon=True,
                )
                self._worker.start()
        return job.job_id

    def cancel(self, job_id: str) -> bool:
        evt = self._cancel_flags.get(str(job_id))
        if not evt:
            return False
        evt.set()
        if self.jobs.patch(str(job_id), status=JobStatus.CANCELLED.value) is not None:
            logger.info(f"🛑 回测任务取消: {job_id}")
        return True

    def status(self, job_id: str) -> Optional[dict]:
        return self.jobs.get(str(job_id))

    # ---- 后台 ----
    def _loop(self) -> None:
        """主循环：处理完当前 job 后，从存储里取出最早 queued 继续。"""
        while True:
            target = self._take_queued()
            if target is None:
                return
            self._sema.acquire()
            try:
                self._run_one(target["job_id"])
            finally:
                self._sema.release()
                self._cancel_flags.pop(target["job_id"], None)

    def _take_queued(self) -> Optional[dict]:
        for entry in self.jobs.list(status=JobStatus.QUEUED.value, limit=200):
            return entry
        return None

    def _run_one(self, job_id: str) -> None:
        cancel_evt = self._cancel_flags.get(str(job_id))
        if cancel_evt and cancel_evt.is_set():
            return
        if not self.jobs.patch(
            str(job_id),
            status=JobStatus.RUNNING.value,
            started_at=_now(),
            progress=0.05,
        ):
            return
        job = self.jobs.get(str(job_id))
        if not job:
            return
        try:
            if self._executor is None:
                raise RuntimeError("executor 未注入")
            logger.info(f"🧪 回测任务开始: {job_id} ({job.get('type', 't0')}/{job.get('symbol', '')})")
            executor_result = self._executor(self._hydrate(job)) or {}  # type: ignore[misc]
            if isinstance(executor_result, dict):
                self.jobs.patch(
                    str(job_id),
                    summary=executor_result.get("summary"),
                    report_path=executor_result.get("report_path"),
                )
        except Exception as e:
            logger.exception(f"❌ 回测任务失败: {job_id}")
            self.jobs.patch(
                str(job_id),
                status=JobStatus.FAILED.value,
                error=str(e),
                finished_at=_now(),
                progress=1.0,
            )
            return
        finished = self.jobs.get(str(job_id))
        if finished and finished.get("status") != JobStatus.CANCELLED.value:
            self.jobs.patch(
                str(job_id),
                status=JobStatus.COMPLETED.value,
                finished_at=_now(),
                progress=1.0,
            )

    @staticmethod
    def _hydrate(payload: dict) -> BacktestJob:
        return BacktestJob(
            job_id=payload["job_id"],
            type=payload.get("type", "t0"),
            symbol=payload.get("symbol", ""),
            request=payload.get("request", {}),
            status=JobStatus(payload.get("status", JobStatus.QUEUED.value)),
            progress=float(payload.get("progress", 0.0)),
            created_at=payload.get("created_at", _now()),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            error=payload.get("error"),
            summary=payload.get("summary"),
            report_path=payload.get("report_path"),
        )


def make_job_id() -> str:
    return uuid.uuid4().hex[:12]
