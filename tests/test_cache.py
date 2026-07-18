import pandas as pd
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data.cache import LocalCache


@pytest.fixture
def tmp_cache(tmp_path):
    return LocalCache(db_path=str(tmp_path / "test.db"))


def test_create_db_tables(tmp_cache):
    with tmp_cache._conn() as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    tables = {r[0] for r in rows}
    assert "daily" in tables
    assert "fq_factor" in tables


def test_upsert_and_range(tmp_cache):
    df = pd.DataFrame([{
        "date": "2026-07-01", "code": "600519",
        "open": 1250.0, "high": 1260.0, "low": 1240.0, "close": 1255.0,
        "volume": 1000000, "amount": 1255000000.0,
    }])
    n = tmp_cache.upsert_daily(df)
    assert n == 1
    out = tmp_cache.range("600519")
    assert len(out) == 1
    assert out.iloc[0]["close"] == 1255.0
    assert out.iloc[0]["amount"] == 1255000000.0


def test_upsert_overwrite(tmp_cache):
    df = pd.DataFrame([
        {"date": "2026-07-01", "code": "600519", "open": 1250, "high": 1260, "low": 1240, "close": 1255, "volume": 1000},
        {"date": "2026-07-02", "code": "600519", "open": 1250, "high": 1260, "low": 1240, "close": 1265, "volume": 2000},
    ])
    tmp_cache.upsert_daily(df)
    df2 = pd.DataFrame([{"date": "2026-07-01", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}])
    tmp_cache.upsert_daily(df2)
    out = tmp_cache.range("600519")
    assert len(out) == 2
    assert out[out["date"] == "2026-07-01"].iloc[0]["close"] == 4.0


def test_ensure_columns_auto_add(tmp_cache):
    df = pd.DataFrame([{
        "date": "2026-07-01", "code": "600519",
        "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5,
        "pe_ttm": 25.0, "pb": 5.0, "future_field_xyz": 999.0,
    }])
    tmp_cache.upsert_daily(df)
    with tmp_cache._conn() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(daily)").fetchall()}
    assert "pe_ttm" in cols
    assert "pb" in cols
    assert "future_field_xyz" in cols


def test_range_with_window(tmp_cache):
    df = pd.DataFrame([
        {"date": "2026-07-01", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
        {"date": "2026-07-02", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
        {"date": "2026-07-03", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
    ])
    tmp_cache.upsert_daily(df)
    out = tmp_cache.range("600519", start="2026-07-02", end="2026-07-02")
    assert len(out) == 1
    assert out.iloc[0]["date"] == "2026-07-02"


def test_last_date_and_count(tmp_cache):
    df = pd.DataFrame([
        {"date": "2026-06-30", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
        {"date": "2026-07-01", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
    ])
    tmp_cache.upsert_daily(df)
    assert tmp_cache.last_date("600519") == "2026-07-01"
    assert tmp_cache.count("600519") == 2
