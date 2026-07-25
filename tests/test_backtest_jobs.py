"""BacktestRunner state machine + 串行化单测。"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from atrade.backtest.jobs import (
    BacktestJob,
    BacktestRunner,
    JobStatus,
    SweepRequest,
    T0JobRequest,
)


@pytest.fixture
def runner_factory(tmp_path):
    def _make(executor=None):
        from atrade.backtest.storage import BacktestJobStore, ReportStore
        return BacktestRunner(
            job_store=BacktestJobStore(path=tmp_path / "jobs.json"),
            report_store=ReportStore(base_dir=tmp_path / "reports"),
            executor=executor,
        )

    return _make


def _good_executor(payload):
    payload.summary = {"ok": True}
    return {"ok": True}


def test_t0_request_validates(runner_factory):
    with pytest.raises(ValueError):
        T0JobRequest.from_dict({"symbol": "abc", "cost_price": 10, "quantity": 100})
    with pytest.raises(ValueError):
        T0JobRequest.from_dict({"symbol": "600522", "cost_price": -1, "quantity": 100})
    with pytest.raises(ValueError):
        T0JobRequest.from_dict({"symbol": "600522", "cost_price": 10, "quantity": 0})
    req = T0JobRequest.from_dict({"symbol": "600522", "cost_price": 10, "quantity": 100})
    assert req.scale == "1d"
    assert req.push is True


def test_sweep_request_default_grids(runner_factory):
    req = SweepRequest.from_dict(
        {"symbol": "600522", "cost_price": 10, "quantity": 100}
    )
    assert req.take_profits == [0.01, 0.02, 0.03, 0.05, 0.07, 0.10]
    assert req.stop_losses == [0.01, 0.02, 0.03, 0.05]


def test_sweep_request_parses_csv(runner_factory):
    req = SweepRequest.from_dict(
        {
            "symbol": "600522",
            "cost_price": 10,
            "quantity": 100,
            "take_profits": "0.02, 0.05",
            "stop_losses": "0.02",
        }
    )
    assert req.take_profits == [0.02, 0.05]
    assert req.stop_losses == [0.02]


def test_sweep_request_rejects_garbage(runner_factory):
    with pytest.raises(ValueError):
        SweepRequest.from_dict(
            {
                "symbol": "600522",
                "cost_price": 10,
                "quantity": 100,
                "take_profits": "abc,def",
            }
        )
    with pytest.raises(ValueError):
        SweepRequest.from_dict(
            {
                "symbol": "600522",
                "cost_price": 10,
                "quantity": 100,
                "take_profits": "1.5",
            }
        )


def test_runner_state_transitions(runner_factory, tmp_path):
    executed = []
    done_evt = __import__("threading").Event()
    def slow_executor(j):
        # 让轮询有机会观察到 running 状态
        time.sleep(0.1)
        done_evt.set()
        executed.append(j.job_id)
        return {"ok": True}

    runner = runner_factory(executor=slow_executor)

    job = BacktestJob(
        job_id="j1", type="t0", symbol="600522",
        request={"cost_price": 10, "quantity": 100},
    )
    runner.submit(job)
    # 等待 lifecycle 走到终态：必须先到 running，再完成（避免 queued 时 false break）
    deadline = time.time() + 5
    seen_running = False
    seen_done = False
    entry = None
    while time.time() < deadline:
        entry = runner.status("j1")
        if entry and entry["status"] == "running":
            seen_running = True
        if seen_running and entry and entry["status"] in ("completed", "failed", "cancelled"):
            seen_done = True
            break
        time.sleep(0.02)
    assert seen_running, f"未观察到 running 状态: {entry}"
    assert seen_done, f"未观察到终态: {entry}"
    assert entry["status"] == JobStatus.COMPLETED.value
    assert entry["progress"] == pytest.approx(1.0)
    assert entry["started_at"] is not None
    assert entry["finished_at"] is not None


def test_runner_failure_marks_failed(runner_factory):
    def bad(_):
        raise RuntimeError("kaboom")

    runner = runner_factory(executor=bad)
    job = BacktestJob(job_id="j2", type="t0", symbol="600522", request={})
    runner.submit(job)
    deadline = time.time() + 3
    while time.time() < deadline:
        if runner.status("j2") and runner.status("j2").get("status") in (
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
        ):
            break
        time.sleep(0.05)
    entry = runner.status("j2")
    assert entry["status"] == JobStatus.FAILED.value
    assert "kaboom" in entry["error"]


def test_runner_serializes_jobs(runner_factory):
    inflight = 0
    max_inflight = 0
    lock = __import__("threading").Lock()

    def slow(_):
        nonlocal inflight, max_inflight
        with lock:
            inflight += 1
            max_inflight = max(max_inflight, inflight)
        time.sleep(0.2)
        with lock:
            inflight -= 1
        return {"ok": True}

    runner = runner_factory(executor=slow)
    for i in range(3):
        runner.submit(BacktestJob(job_id=f"j{i}", type="t0", symbol="600522", request={}))
    time.sleep(1.5)
    assert max_inflight == 1


def test_runner_cancel_queued(runner_factory):
    def slow(_):
        time.sleep(0.5)
        return {"ok": True}

    runner = runner_factory(executor=slow)
    runner.submit(BacktestJob(job_id="j1", type="t0", symbol="600522", request={}))
    runner.submit(BacktestJob(job_id="j2", type="t0", symbol="600522", request={}))
    runner.submit(BacktestJob(job_id="j3", type="t0", symbol="600522", request={}))
    time.sleep(0.05)
    runner.cancel("j2")
    runner.cancel("j3")
    time.sleep(0.8)
    statuses = {runner.status(jid)["status"] for jid in ["j1", "j2", "j3"]}
    assert JobStatus.CANCELLED.value in statuses
