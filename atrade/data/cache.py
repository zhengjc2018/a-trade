"""本地缓存层（设计参考 free-stockdb 思路）。

数据建模对齐 A 股日 K 线需要：
    date, code, name,
    open, high, low, close, pre_close,
    volume, amount, amplitude, pct_chg, turnover, vol_ratio,
    float_mv, total_mv, float_share, total_share,
    pe_ttm, pb, is_st

复权通过 ah_factor（累积复权因子）派生，按需 qfq/hfq/none 变换价格列。

设计要点（借鉴 free-stockdb）：
- 增量 upsert：同一 (code, date) 主键冲突则覆盖
- 字段自动扩列：新拉的字段不在 schema 里则 ALTER TABLE 添加
- 二级索引：code + date 联合索引便于范围查询
- 原子提交：拉一批一 commit
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger


_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "cache" / "stock.db"


SCHEMA_DAILY = {
    "date": "TEXT",            # YYYY-MM-DD
    "code": "TEXT",            # 6 位代码（不带前缀）
    "name": "TEXT",
    "open": "REAL",
    "high": "REAL",
    "low": "REAL",
    "close": "REAL",
    "pre_close": "REAL",      # 昨收
    "volume": "INTEGER",       # 成交量（手）
    "amount": "REAL",          # 成交额（元）
    "amplitude": "REAL",       # 振幅 %
    "pct_chg": "REAL",         # 涨跌幅 %
    "turnover": "REAL",        # 换手率 %
    "vol_ratio": "REAL",       # 量比
    "float_mv": "REAL",        # 流通市值（元）
    "total_mv": "REAL",        # 总市值（元）
    "float_share": "INTEGER",  # 流通股
    "total_share": "INTEGER",  # 总股本
    "pe_ttm": "REAL",          # 滚动市盈率
    "pb": "REAL",              # 市净率
    "is_st": "INTEGER",        # 是否 ST（0/1）
    "ah_factor": "REAL",       # 累积前复权因子（默认 1.0）
}


class LocalCache:
    """SQLite 本地缓存。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        logger.info(f"本地缓存 DB: {self.db_path}")

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(str(self.db_path))
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def _init_db(self):
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS daily (
                    date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT,
                    PRIMARY KEY (code, date)
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_daily_date ON daily(date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_daily_code ON daily(code)")
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS fq_factor (
                    date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    cum_factor REAL NOT NULL,
                    PRIMARY KEY (code, date)
                )
                """
            )
            c.commit()

    def _ensure_columns(self, cursor, table: str, columns: dict[str, str]):
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
        for col, sqltype in columns.items():
            if col not in existing:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {sqltype}")
                logger.debug(f"[cache] ALTER {table} ADD COLUMN {col} {sqltype}")

    def upsert_daily(self, df: pd.DataFrame) -> int:
        """Upsert 日 K 数据。df 至少有 date/open/high/low/close/volume/code。"""
        if df is None or len(df) == 0:
            return 0
        if "code" not in df.columns or "date" not in df.columns:
            raise ValueError("df 缺少 code 或 date 列")

        with self._conn() as c:
            self._ensure_columns(c, "daily", SCHEMA_DAILY)
            payload = []
            for _, row in df.iterrows():
                rec = {}
                for col in SCHEMA_DAILY:
                    v = row.get(col)
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        rec[col] = None
                    else:
                        rec[col] = v
                payload.append(rec)

            cols = list(SCHEMA_DAILY.keys())
            placeholders = ",".join(["?"] * len(cols))
            col_list = ",".join(cols)
            sql = (
                f"INSERT OR REPLACE INTO daily ({col_list}) VALUES ({placeholders})"
            )
            c.executemany(sql, [[r[c] for c in cols] for r in payload])
            c.commit()
            logger.info(f"[cache] upsert daily {df['code'].iloc[0]} {len(df)} 行")
            return len(payload)

    def upsert_fq(self, df: pd.DataFrame) -> int:
        """Upsert 复权因子表。df 含 date/code/cum_factor。"""
        if df is None or len(df) == 0:
            return 0
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO fq_factor (date, code, cum_factor) VALUES (?, ?, ?)",
                [
                    (
                        r["date"],
                        str(r["code"]).zfill(6),
                        float(r["cum_factor"]),
                    )
                    for _, r in df.iterrows()
                ],
            )
            c.commit()
            return len(df)

    def range(
        self,
        code: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        fq: Optional[str] = None,
    ) -> pd.DataFrame:
        """读取缓存的日 K 范围。"""
        with self._conn() as c:
            sql = "SELECT * FROM daily WHERE code = ?"
            params: list = [str(code).zfill(6)]
            if start:
                sql += " AND date >= ?"
                params.append(start)
            if end:
                sql += " AND date <= ?"
                params.append(end)
            sql += " ORDER BY date ASC"
            df = pd.read_sql_query(sql, c, params=params)

        if df.empty:
            return df

        if fq in ("qfq", "hfq"):
            df = _apply_fq(df, mode=fq)
        return df

    def last_date(self, code: str) -> Optional[str]:
        with self._conn() as c:
            row = c.execute(
                "SELECT MAX(date) AS d FROM daily WHERE code = ?",
                (str(code).zfill(6),),
            ).fetchone()
            return row["d"] if row else None

    def count(self, code: str) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM daily WHERE code = ?",
                (str(code).zfill(6),),
            ).fetchone()
            return row["n"] if row else 0


def _apply_fq(df: pd.DataFrame, mode: str = "qfq") -> pd.DataFrame:
    """应用复权。复权因子如缺失则不处理。"""
    if df.empty or "ah_factor" not in df.columns:
        return df
    factor = df["ah_factor"].astype(float).fillna(1.0)
    if mode == "hfq":
        # 后复权：以最新累积因子为基准
        latest = factor.iloc[-1] if len(factor) else 1.0
        factor = factor / latest
    for col in ["open", "high", "low", "close", "pre_close"]:
        df[col] = df[col] * factor
    df["volume"] = (df["volume"] / factor).round().astype("Int64")
    return df
