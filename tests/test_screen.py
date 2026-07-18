import pandas as pd
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.screen as s
from scripts.screen import filter_by_thresholds, load_snapshot


@pytest.fixture
def fake_snapshot(tmp_path):
    p = tmp_path / "market_snapshot.csv"
    df = pd.DataFrame([
        {"code": "600519", "name": "贵州茅台", "price": 125300, "pct_chg": -2.5,
         "change": -3200, "volume": 100, "amount": 1.25e9,
         "amplitude": 3.0, "high": 128000, "low": 123000,
         "total_mv": 1.5e12, "pe_ttm": 25.0},
        {"code": "000001", "name": "平安银行", "price": 1080, "pct_chg": -4.0,
         "change": -45, "volume": 1000, "amount": 1.08e10,
         "amplitude": 5.0, "high": 1120, "low": 1060,
         "total_mv": 2.0e11, "pe_ttm": 5.5},
        {"code": "601318", "name": "中国平安", "price": 4800, "pct_chg": 1.2,
         "change": 57, "volume": 500, "amount": 2.4e9,
         "amplitude": 2.0, "high": 4900, "low": 4780,
         "total_mv": 8.8e11, "pe_ttm": 9.0},
    ])
    df.to_csv(p, index=False)
    return p


class _A:
    pct_chg_min = None
    pct_chg_max = None
    amount_min = None
    code_in = None


def test_filter_pct_chg_range(fake_snapshot, monkeypatch):
    monkeypatch.setattr(s, "SNAPSHOT_FILE", fake_snapshot)
    raw = load_snapshot()
    a = _A()
    a.pct_chg_min, a.pct_chg_max = -3.0, 0.0
    out = filter_by_thresholds(raw, a)
    codes = set(out["code"].tolist())
    assert "600519" in codes  # -2.5
    assert "000001" not in codes  # -4 超出
    assert "601318" not in codes  # +1.2 超出


def test_filter_code_in(fake_snapshot, monkeypatch):
    monkeypatch.setattr(s, "SNAPSHOT_FILE", fake_snapshot)
    raw = load_snapshot()
    a = _A()
    a.code_in = "600519,000001"
    out = filter_by_thresholds(raw, a)
    assert len(out) == 2
    assert "601318" not in out["code"].tolist()


def test_filter_amount_min(fake_snapshot, monkeypatch):
    """过滤成交额 ≥ 5 亿元。仅 000001 平安银行满足（10.8 亿）。"""
    monkeypatch.setattr(s, "SNAPSHOT_FILE", fake_snapshot)
    raw = load_snapshot()
    a = _A()
    a.amount_min = 5e9
    out = filter_by_thresholds(raw, a)
    codes = set(out["code"].tolist())
    assert "600519" not in codes  # 1.25 亿
    assert "000001" in codes      # 10.8 亿 ✓
    assert "601318" not in codes  # 2.4 亿（< 5 亿 → 实际不应该入选）


def test_filter_combined(fake_snapshot, monkeypatch):
    """组合：跌 1-5% 且成交额 ≥ 5 亿。"""
    monkeypatch.setattr(s, "SNAPSHOT_FILE", fake_snapshot)
    raw = load_snapshot()
    a = _A()
    a.pct_chg_min, a.pct_chg_max = -5.0, -1.0
    a.amount_min = 5e9
    out = filter_by_thresholds(raw, a)
    codes = set(out["code"].tolist())
    # 跌 1-5% 内：600519(-2.5) 和 000001(-4.0)
    # 成交 ≥5亿：000001（10.8 亿），600519（1.25 亿不满足）
    assert codes == {"000001"}
