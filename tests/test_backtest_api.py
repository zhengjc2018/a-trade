"""回测 Web API 集成测试（FastAPI TestClient）。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import time

import pytest


@pytest.fixture
def tmp_runner_setup(tmp_path, monkeypatch):
    """把 BacktestRunner / Store 切到临时目录，并 monkey-patch
    atrade.backtest.api._build_executor 让它使用 fake executor（不入网）。
    """
    monkeypatch.setattr("atrade.backtest.storage.JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr("atrade.backtest.storage.REPORTS_DIR", tmp_path / "reports")

    from atrade.backtest import api as api_mod
    from atrade.backtest.jobs import BacktestRunner
    from atrade.backtest.storage import BacktestJobStore, ReportStore

    runner = BacktestRunner(
        job_store=BacktestJobStore(path=tmp_path / "jobs.json"),
        report_store=ReportStore(base_dir=tmp_path / "reports"),
    )
    api_mod.set_runner(runner)

    def _fake_executor(job):
        jobs_path = tmp_path / "reports" / f"fake_{job.job_id}.md"
        jobs_path.parent.mkdir(parents=True, exist_ok=True)
        jobs_path.write_text(f"# fake report for {job.symbol}", encoding="utf-8")
        return {
            "summary": {
                "symbol": job.symbol,
                "ok": True,
                "trades": 7,
                "net_pnl": 100.0,
            },
            "report_path": str(jobs_path),
        }

    # 替换 api 模块的 _build_executor，让所有 post 走 fake
    monkeypatch.setattr(api_mod, "_build_executor", lambda notifier=None: _fake_executor)
    return runner, tmp_path


@pytest.fixture
def client(tmp_runner_setup):
    runner, tmp_path = tmp_runner_setup
    from fastapi.testclient import TestClient

    from atrade.web.app import app

    with TestClient(app) as c:
        yield c


def test_run_backtest_creates_job(client):
    resp = client.post(
        "/api/backtest/run",
        json={
            "symbol": "600522",
            "cost_price": 61.86,
            "quantity": 200,
            "start_date": "2024-01-01",
            "end_date": "2026-07-25",
        },
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "job_id" in body
    assert body["status"] == "queued"
    assert body["symbol"] == "600522"


def test_run_backtest_validates_input(client):
    resp = client.post(
        "/api/backtest/run",
        json={"symbol": "12345", "cost_price": 10, "quantity": 100},  # 5 位
    )
    assert resp.status_code in (400, 422)


def test_run_backtest_with_sweep_flag(client):
    resp = client.post(
        "/api/backtest/run",
        json={
            "symbol": "600522", "cost_price": 61.86, "quantity": 200,
            "sweep": True, "push": False,
        },
    )
    assert resp.status_code == 202


def test_run_portfolio(client, tmp_runner_setup, monkeypatch):
    runner, tmp_path = tmp_runner_setup

    holdings_path = tmp_path / "holdings.local.json"
    holdings_path.write_text(
        """{
            "holdings": [
                {"symbol": "600522", "name": "中天", "cost_price": 61.86, "quantity": 200, "buy_date": "", "note": ""}
            ],
            "watch_keywords": []
        }""",
        encoding="utf-8",
    )
    # load_holdings 读 .local.json，强制 monkey patch ENV
    monkeypatch.setenv("A_TRADE_HOLDINGS_PATH", str(holdings_path))

    resp = client.post(
        "/api/backtest/portfolio",
        json={"push": False, "start_date": "2024-01-01", "end_date": "2026-07-25"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["type"] == "portfolio"


def test_get_job_lifecycle(client):
    job_id = client.post(
        "/api/backtest/run",
        json={
            "symbol": "600522", "cost_price": 61.86, "quantity": 200,
            "push": False,
        },
    ).json()["job_id"]

    # 等待 job 结束
    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/backtest/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job


def test_get_report_returns_markdown(client):
    job_id = client.post(
        "/api/backtest/run",
        json={"symbol": "600522", "cost_price": 61.86, "quantity": 200,
              "push": False},
    ).json()["job_id"]
    # 等完成
    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/backtest/jobs/{job_id}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    resp = client.get(f"/api/backtest/report/{job_id}")
    assert resp.status_code == 200
    assert "fake report for 600522" in resp.json()["markdown"]


def test_list_jobs_filters(client, tmp_runner_setup):
    runner, tmp_path = tmp_runner_setup
    # submit 2 jobs for 600522, 1 for 600519
    for sym in ("600522", "600522", "600519"):
        runner.submit(__import__("atrade.backtest.jobs", fromlist=["BacktestJob"]).BacktestJob(
            job_id=f"id-{sym}-{time.time_ns()}",
            type="t0",
            symbol=sym,
            request={"cost_price": 10, "quantity": 100},
        ))
    time.sleep(0.4)
    resp = client.get("/api/backtest/jobs?symbol=600522&limit=10")
    assert resp.status_code == 200
    items = resp.json()
    assert all(it["symbol"] == "600522" for it in items)


def test_get_report_unknown_job_404(client):
    resp = client.get("/api/backtest/report/ghost")
    assert resp.status_code == 404


def test_run_endpoint_rejects_bad_symbol(client):
    resp = client.post("/api/backtest/run", json={"symbol": "BAD", "cost_price": 1, "quantity": 100})
    assert resp.status_code in (400, 422)
