import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.screen as s
from scripts.screen import (
    fetch_market_snapshot,
    filter_by_thresholds,
    load_snapshot,
)


@pytest.fixture
def fake_snapshot(tmp_path):
    """新字段契约：价格 / 金额已是实际数值，不再 ×100。"""
    p = tmp_path / "market_snapshot.csv"
    df = pd.DataFrame([
        {"code": "600519", "name": "贵州茅台", "price": 1253.0, "pct_chg": -2.5,
         "change": -32.0, "volume_lots": 100, "amount": 1.25e9,
         "amplitude": 3.0, "high": 1280.0, "low": 1230.0,
         "total_mv": 1.5e12, "pe_ttm": 25.0, "pb": 8.0},
        {"code": "000001", "name": "平安银行", "price": 10.8, "pct_chg": -4.0,
         "change": -0.45, "volume_lots": 1000, "amount": 1.08e10,
         "amplitude": 5.0, "high": 11.2, "low": 10.6,
         "total_mv": 2.0e11, "pe_ttm": 5.5, "pb": 0.6},
        {"code": "601318", "name": "中国平安", "price": 48.0, "pct_chg": 1.2,
         "change": 0.57, "volume_lots": 500, "amount": 2.4e9,
         "amplitude": 2.0, "high": 49.0, "low": 47.8,
         "total_mv": 8.8e11, "pe_ttm": 9.0, "pb": 1.1},
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


def test_apply_quality_filters_uses_fundamental_snapshot(monkeypatch):
    df = pd.DataFrame([
        {"code": "600123", "name": "某主板股", "price": 12.0, "pe_ttm": None, "pb": None},
    ])
    monkeypatch.setattr(s, "is_main_board_code", lambda code: True)
    monkeypatch.setattr(s, "is_st_name", lambda name: False)
    monkeypatch.setattr(s, "is_excluded_industry", lambda code: False)
    monkeypatch.setattr(s, "close_above_ma5", lambda code, price, history=None: True)

    out = s.apply_quality_filters(df)
    assert len(out) == 1
    assert out.iloc[0]["code"] == "600123"


def test_apply_quality_filters_rejects_high_pe(monkeypatch):
    """PE 过高应被剔除。"""
    df = pd.DataFrame([
        {"code": "600124", "name": "某主板股", "price": 12.0, "pe_ttm": 80.0, "pb": 2.2},
    ])
    monkeypatch.setattr(s, "is_main_board_code", lambda code: True)
    monkeypatch.setattr(s, "is_st_name", lambda name: False)
    monkeypatch.setattr(s, "is_excluded_industry", lambda code: False)
    monkeypatch.setattr(s, "close_above_ma5", lambda code, price, history=None: True)

    out = s.apply_quality_filters(df)
    assert out.empty


def test_apply_quality_filters_rejects_high_price(monkeypatch):
    """价格 > MAX_PRICE (80) 应被剔除。"""
    df = pd.DataFrame([
        {"code": "600125", "name": "某主板股", "price": 99.0, "pe_ttm": 10.0, "pb": 1.0},
    ])
    monkeypatch.setattr(s, "is_main_board_code", lambda code: True)
    monkeypatch.setattr(s, "is_st_name", lambda name: False)
    monkeypatch.setattr(s, "is_excluded_industry", lambda code: False)
    monkeypatch.setattr(s, "close_above_ma5", lambda code, price, history=None: True)

    out = s.apply_quality_filters(df)
    assert out.empty


def test_fetch_market_snapshot_field_mapping(monkeypatch):
    """fetch_market_snapshot 应使用新的字段契约（f2/f6/f7/f9/f23）。"""
    captured = {}

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload
        def raise_for_status(self): pass
        def json(self): return self._payload

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["fields"] = params.get("fields", "")
        captured["fltt"] = params.get("fltt", "")
        return FakeResp({
            "data": {
                "diff": [
                    {"f12": "600519", "f14": "贵州茅台",
                     "f2": 1253.0, "f3": -2.5, "f4": -32.0,
                     "f5": 100, "f6": 1.25e9, "f7": 3.0,
                     "f8": 0.5, "f9": 25.0, "f10": 1.2,
                     "f15": 1280.0, "f16": 1230.0,
                     "f20": 1.5e12, "f23": 8.0},
                ]
            }
        })

    monkeypatch.setattr("scripts.screen.requests.get", fake_get)
    monkeypatch.setattr("scripts.screen.SNAPSHOT_FILE", Path("/tmp/_test_snap.csv"))
    monkeypatch.setattr("scripts.screen.time.sleep", lambda *_: None)

    df = fetch_market_snapshot(page_size=200, max_pages=1)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["price"] == 1253.0      # f2 = 实际价格，不再 ×100
    assert row["amount"] == 1.25e9      # f6 = 实际成交额（元）
    assert row["amplitude"] == 3.0      # f7 = 振幅%
    assert row["pe_ttm"] == 25.0        # f9 = 动态市盈率
    assert row["pb"] == 8.0             # f23 = 市净率
    # 验证请求字段不含 f1/f5(旧×100) 也不再错用 f7/f9/f23
    fields_str = captured["fields"]
    assert "f2" in fields_str           # 最新价（不再用 f1）
    assert "f6" in fields_str           # 成交额
    assert "f7" in fields_str           # 振幅
    assert "f9" in fields_str           # 动态市盈率
    assert "f10" in fields_str          # 量比
    assert "f23" in fields_str          # 市净率
    assert captured["fltt"] == "2"
