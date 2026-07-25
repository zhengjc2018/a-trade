"""回测系统的元数据 / 报告持久化。

- BacktestJobStore：data/backtest/jobs.json 原子读写
- ReportStore：data/backtest/reports/<job_id>.md 落盘
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

JOBS_FILE = Path(__file__).resolve().parents[2] / "data" / "backtest" / "jobs.json"
REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest" / "reports"
_lock = threading.RLock()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, payload: str) -> None:
    _ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)


class BacktestJobStore:
    """jobs.json 字典式存储。

    结构：
    {
      "<job_id>": {
        "job_id": str,
        "type": "t0" | "sweep" | "portfolio",
        "symbol": str | "",
        "status": "queued" | "running" | "completed" | "failed" | "cancelled",
        "request": {...},
        "created_at": iso8601,
        "started_at": iso8601 | null,
        "finished_at": iso8601 | null,
        "progress": 0.0..1.0,
        "error": str | null,
        "summary": {...} | null,
        "report_path": str | null
      }
    }
    """

    def __init__(self, path: Path = JOBS_FILE) -> None:
        self.path = path

    # ---- 内部 ----
    def _read_all(self) -> dict[str, dict]:
        with _lock:
            if not self.path.exists():
                return {}
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}

    def _write_all(self, data: dict[str, dict]) -> None:
        with _lock:
            _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2))

    # ---- CRUD ----
    def upsert(self, job: dict) -> None:
        with _lock:
            data = self._read_all()
            data[str(job["job_id"])] = job
            self._write_all(data)

    def patch(self, job_id: str, **changes: Any) -> Optional[dict]:
        with _lock:
            data = self._read_all()
            entry = data.get(str(job_id))
            if not entry:
                return None
            entry.update(changes)
            data[str(job_id)] = entry
            self._write_all(data)
            return entry

    def get(self, job_id: str) -> Optional[dict]:
        with _lock:
            return self._read_all().get(str(job_id))

    def list(
        self,
        *,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        with _lock:
            entries = list(self._read_all().values())
        if symbol:
            entries = [e for e in entries if str(e.get("symbol", "")) == str(symbol)]
        if status:
            entries = [e for e in entries if str(e.get("status", "")) == status]
        entries.sort(key=lambda e: str(e.get("created_at", "")), reverse=True)
        return entries[: max(1, int(limit))]


class ReportStore:
    """单 .md 文件落盘，路径按 job_id 命名（永不覆盖）。"""

    def __init__(self, base_dir: Path = REPORTS_DIR) -> None:
        self.base_dir = base_dir

    def write(self, job_id: str, markdown: str) -> str:
        path = self.base_dir / f"backtest_{job_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        return str(path)

    def read(self, job_id: str) -> Optional[str]:
        path = self.base_dir / f"backtest_{job_id}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def path_for(self, job_id: str) -> str:
        return str(self.base_dir / f"backtest_{job_id}.md")

    def cleanup_oldest(self, keep: int = 100) -> list[str]:
        """按文件名时间戳排序，删掉最旧的超过 keep 的文件。"""
        if not self.base_dir.exists():
            return []
        files = sorted(self.base_dir.glob("backtest_*.md"))
        if len(files) <= keep:
            return []
        removed = []
        for fp in files[: -keep]:
            try:
                fp.unlink()
                removed.append(str(fp))
            except OSError:
                pass
        return removed


def iter_jobs(store: BacktestJobStore) -> Iterable[dict]:
    return store.list(limit=10_000)
