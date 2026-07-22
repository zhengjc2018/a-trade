"""SQLite 通知送达账本。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .delivery import DeliveryResult

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "delivery.db"


class DeliveryLedger:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DEFAULT_LEDGER_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery (
                    task_key TEXT PRIMARY KEY,
                    task_name TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    title TEXT,
                    markdown TEXT,
                    status TEXT NOT NULL,
                    channel TEXT,
                    message_id TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    delivered_at TEXT
                )
                """
            )

    def is_delivered(self, task_key: str) -> bool:
        row = self.get(task_key)
        return bool(row and row["status"] == "delivered")

    def get(self, task_key: str) -> Optional[dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM delivery WHERE task_key = ?",
                (task_key,),
            ).fetchone()
        return dict(row) if row else None

    def record_result(
        self,
        task_name: str,
        content_hash: str,
        result: DeliveryResult,
        title: str = "",
        markdown: str = "",
    ) -> None:
        if self.is_delivered(result.task_key):
            return
        status = "delivered" if result.ok else "failed"
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT attempt_count FROM delivery WHERE task_key = ?",
                (result.task_key,),
            ).fetchone()
            attempt_count = (existing["attempt_count"] if existing else 0) + 1
            connection.execute(
                """
                INSERT INTO delivery (
                    task_key, task_name, content_hash, title, markdown, status,
                    channel, message_id, attempt_count, last_error, updated_at, delivered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP,
                          CASE WHEN ? = 'delivered' THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(task_key) DO UPDATE SET
                    task_name=excluded.task_name,
                    content_hash=excluded.content_hash,
                    title=excluded.title,
                    markdown=excluded.markdown,
                    status=excluded.status,
                    channel=excluded.channel,
                    message_id=excluded.message_id,
                    attempt_count=excluded.attempt_count,
                    last_error=excluded.last_error,
                    updated_at=CURRENT_TIMESTAMP,
                    delivered_at=excluded.delivered_at
                """,
                (
                    result.task_key,
                    task_name,
                    content_hash,
                    title,
                    markdown,
                    status,
                    result.channel,
                    result.message_id,
                    attempt_count,
                    result.last_error,
                    status,
                ),
            )

    def pending_failures(self, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM delivery
                WHERE status = 'failed'
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
