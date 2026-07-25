"""BacktestJobStore + ReportStore 单测。"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from atrade.backtest.storage import BacktestJobStore, ReportStore


@pytest.fixture
def tmp_store(tmp_path):
    return BacktestJobStore(path=tmp_path / "jobs.json")


@pytest.fixture
def tmp_reports(tmp_path):
    return ReportStore(base_dir=tmp_path / "reports")


def test_jobs_file_initialized_on_first_upsert(tmp_store):
    job = {"job_id": "abc123", "symbol": "600522", "status": "queued"}
    tmp_store.upsert(job)
    assert tmp_store.path.exists()


def test_upsert_patch_get_roundtrip(tmp_store):
    job = {"job_id": "id1", "symbol": "600522", "status": "queued"}
    tmp_store.upsert(job)
    tmp_store.patch("id1", status="running", progress=0.3)
    entry = tmp_store.get("id1")
    assert entry["status"] == "running"
    assert entry["progress"] == pytest.approx(0.3)


def test_patch_missing_returns_none(tmp_store):
    assert tmp_store.patch("ghost") is None


def test_list_filters_and_orders(tmp_store):
    rows = [
        ("id0", "600522", "queued", "2026-07-25T10:00:00"),
        ("id1", "600522", "queued", "2026-07-25T10:01:00"),
        ("id2", "600522", "queued", "2026-07-25T10:02:00"),
        ("id_other", "000001", "queued", "2026-07-25T10:03:00"),
        ("id_done", "600522", "completed", "2026-07-25T10:04:00"),
    ]
    for jid, sym, status, created_at in rows:
        tmp_store.upsert(
            {"job_id": jid, "symbol": sym, "status": status, "created_at": created_at}
        )

    only_600 = tmp_store.list(symbol="600522", limit=10)
    assert {e["job_id"] for e in only_600} == {"id0", "id1", "id2", "id_done"}

    only_completed = tmp_store.list(status="completed", limit=10)
    assert only_completed[0]["job_id"] == "id_done"

    latest_first = tmp_store.list(limit=10)
    # 倒序排中，id_done 最早 → 排第一
    assert latest_first[0]["job_id"] == "id_done"
    assert [e["job_id"] for e in latest_first] == [
        "id_done",
        "id_other",
        "id2",
        "id1",
        "id0",
    ]


def test_concurrent_upsert_is_safe(tmp_store):
    def worker(start):
        for i in range(start, start + 10):
            tmp_store.upsert(
                {"job_id": f"j{i}", "symbol": "600522", "status": "queued"}
            )

    threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = json.loads(tmp_store.path.read_text())
    assert len(data) == 50


def test_report_store_writes_reads(tmp_reports):
    path = tmp_reports.write("jobA", "# report A\n body")
    assert Path(path).exists()
    assert tmp_reports.read("jobA") == "# report A\n body"


def test_report_store_read_missing_returns_none(tmp_reports):
    assert tmp_reports.read("missing") is None


def test_report_store_cleanup(tmp_reports):
    for i in range(5):
        tmp_reports.write(f"id{i}", str(i))
    removed = tmp_reports.cleanup_oldest(keep=3)
    remaining = list(tmp_reports.base_dir.glob("backtest_*.md"))
    assert len(remaining) == 3
    assert len(removed) == 2
