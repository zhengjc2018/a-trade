"""回测模块。

T+0 做 T 模拟器 + 任务管理 + 参数扫描。
"""

from .jobs import BacktestJob, BacktestRunner, JobStatus, SweepRequest, T0JobRequest
from .storage import BacktestJobStore, ReportStore
from .t0_simulator import T0BacktestResult, T0Simulator, T0Trade

__all__ = [
    "T0Simulator",
    "T0BacktestResult",
    "T0Trade",
    "T0JobRequest",
    "SweepRequest",
    "BacktestJob",
    "JobStatus",
    "BacktestRunner",
    "BacktestJobStore",
    "ReportStore",
]

# 可选：sweep 模块在 Phase 2 引入
try:
    from .sweep import SweepGrid, run_sweep  # noqa: F401

    __all__.extend(["SweepGrid", "run_sweep"])
except ImportError:  # pragma: no cover
    pass
