import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data import HistoryProvider
from atrade.data.eastmoney import fetch_snap


# 构造一份固定的 10 行 OHLCV
FAKE_DF = pd.DataFrame([
    {"date": f"2026-06-{i+1:02d}", "open": 100.0 + i, "high": 105.0 + i,
     "low": 99.0 + i, "close": 102.0 + i, "volume": 1000000 + i * 1000}
    for i in range(10)
])


@pytest.fixture
def hp(tmp_path):
    return HistoryProvider(cache_path=str(tmp_path / "test.db"))


def test_fetch_with_cache_adds_derived_fields(hp):
    """fetch_with_cache 应当把派生字段加进去。"""
    with patch.object(hp, "fetch", return_value=FAKE_DF.copy()):
        df = hp.fetch_with_cache("600519", scale="1d", datalen=10)
    for col in ["pre_close", "pct_chg", "amplitude", "amount",
                "turnover", "vol_ratio", "is_st", "ah_factor"]:
        assert col in df.columns, f"缺少派生字段: {col}"


def test_derived_values_basic(hp):
    """amplitude 等派生公式正确。"""
    with patch.object(hp, "fetch", return_value=FAKE_DF.copy()):
        df = hp.fetch_with_cache("600519", scale="1d", datalen=10)
    row = df.iloc[5]  # 跳过第一行（pre_close = NaN）
    expected_amp = (row["high"] - row["low"]) / row["pre_close"] * 100
    assert abs(row["amplitude"] - expected_amp) < 1e-6
    assert (df["ah_factor"] == 1.0).all()


def test_cache_persists_data(hp):
    """第二次调用应走 cache，不再调用 fetch（即网络）。snap 也 mock。"""
    # 准备 60 个不重复日期 + ignore_index=True 避免索引重复
    dates = pd.date_range("2024-01-01", periods=60, freq="D").strftime("%Y-%m-%d")
    big_df = pd.DataFrame({
        "date": dates,
        "open": [100.0] * 60,
        "high": [105.0] * 60,
        "low":  [99.0]  * 60,
        "close": [102.0] * 60,
        "volume": [1000000] * 60,
    })
    with patch.object(hp, "fetch", return_value=big_df.copy()) as mock_fetch, \
         patch("atrade.data.history.fetch_snap", return_value=None):
        df1 = hp.fetch_with_cache("600519", scale="1d", datalen=60)
        # 第二次应命中 cache，不调 fetch
        df2 = hp.fetch_with_cache("600519", scale="1d", datalen=60)
    assert mock_fetch.call_count == 1, f"fetch 被调用 {mock_fetch.call_count} 次（应只 1 次）"
    assert len(df1) == len(df2) == 60
    assert (df1["close"].values == df2["close"].values).all()


def test_fetch_with_cache_pulls_snap(hp):
    """use_snapshot=True 时调用 eastmoney.fetch_snap 一次。"""
    fake_snap = {
        "code": "600519", "name": "贵州茅台",
        "price": 1253.0, "pre_close": 1259.0,
        "pe_ttm": 25.0, "pb": 8.5, "total_mv": 1.5e12, "float_mv": 1.5e12,
        "float_share": 1e9, "total_share": 1e9,
    }
    with patch.object(hp, "fetch", return_value=FAKE_DF.copy()), \
         patch("atrade.data.history.fetch_snap", return_value=fake_snap) as mock_snap:
        df = hp.fetch_with_cache("600519", scale="1d", datalen=10, use_snapshot=True)
    assert mock_snap.called
    # 最后一行应当带 pe_ttm / pb
    last = df.iloc[-1]
    assert last["pe_ttm"] == 25.0
    assert last["pb"] == 8.5
    assert last["name"] == "贵州茅台"


def test_fetch_with_cache_snap_failure_degrades(hp):
    """东财失败时返回的数据仍可用，PE/PB 缺失。"""
    with patch.object(hp, "fetch", return_value=FAKE_DF.copy()), \
         patch("atrade.data.history.fetch_snap", return_value=None):
        df = hp.fetch_with_cache("600519", scale="1d", datalen=10, use_snapshot=True)
    assert len(df) == 10
    # pe_ttm 应为 None / NaN
    assert pd.isna(df["pe_ttm"].iloc[-1])


def test_eastmoney_fetch_snap_returns_dict():
    """直接的 fetch_snap 调用走得通解析。"""
    import requests
    fake_resp = {
        "data": {
            "f43": 125300, "f57": "600519", "f58": "贵州茅台",
            "f60": 125900, "f84": 1256000000, "f85": 1256000000,
            "f116": 1574400000000, "f117": 1574400000000,
            "f167": 25.5, "f168": 8.2,
        }
    }
    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return fake_resp
    with patch("atrade.data.eastmoney.requests.get", return_value=FakeResp()):
        snap = fetch_snap("600519")
    assert snap["code"] == "600519"
    assert snap["price"] == 1253.0
    assert snap["pe_ttm"] == 25.5


def test_fetch_snap_falls_back_to_tx():
    """东财反爬时，fetch_snap 应自动 fallback 到腾讯。"""
    from atrade.data.eastmoney import fetch_snap, _fetch_eastmoney, _fetch_tx

    fake_em = None
    fake_tx = {
        "code": "600519", "name": "贵州茅台", "price": 1253.0,
        "pre_close": 1258.99, "open": 1269.01, "pct_chg": None,
        "amplitude": None, "vol_ratio": None, "turnover": 0.47,
        "total_mv": 1.5e12, "float_mv": 1.5e12,
        "total_share": None, "float_share": None,
        "pe_ttm": None, "pb": None, "source": "tx",
    }
    from unittest.mock import patch
    with patch("atrade.data.eastmoney._fetch_eastmoney", return_value=fake_em), \
         patch("atrade.data.eastmoney._fetch_tx", return_value=fake_tx), \
         patch("atrade.data.eastmoney._fetch_datacenter", return_value=None):
        snap = fetch_snap("600519")
    assert snap is not None
    assert snap["source"] == "tx"
    assert snap["price"] == 1253.0
    assert snap["pe_ttm"] is None
    assert snap["pb"] is None


# ---- datacenter fallback 测试 ----

def test_fetch_snap_datacenter_derives_pe_pb():
    """东财 + 腾讯都失败时, datacenter 财报接口应该能反推 PE/PB。"""
    from atrade.data.eastmoney import fetch_snap, _fetch_eastmoney, _fetch_tx, _fetch_datacenter

    fake_em = None  # push2 反爬
    fake_tx = {
        "code": "600519", "name": "贵州茅台", "price": 1253.0,
        "pre_close": 1258.99, "open": 1269.01, "pct_chg": None,
        "amplitude": None, "vol_ratio": None, "turnover": 0.47,
        "total_mv": 1.5e12, "float_mv": 1.5e12,
        "total_share": None, "float_share": None,
        "pe_ttm": None, "pb": None, "source": "tx",
    }
    fake_dc = {
        "code": "600519", "name": None, "price": None,
        "pre_close": None, "open": None, "pct_chg": None,
        "amplitude": None, "vol_ratio": None, "turnover": None,
        "total_mv": None, "float_mv": None,
        "total_share": 1252270215, "float_share": None,
        "pe_ttm": None, "pb": None,
        "bvps": 224.50, "ttm_eps": 66.04, "source": "datacenter",
    }
    from unittest.mock import patch
    with patch("atrade.data.eastmoney._fetch_eastmoney", return_value=fake_em), \
         patch("atrade.data.eastmoney._fetch_tx", return_value=fake_tx), \
         patch("atrade.data.eastmoney._fetch_datacenter", return_value=fake_dc) as mock_dc:
        snap = fetch_snap("600519")
    assert mock_dc.called
    assert snap is not None
    # PE = 1253 / 66.04 = 18.97
    assert abs(snap["pe_ttm"] - 18.97) < 0.1
    # PB = 1253 / 224.50 = 5.58
    assert abs(snap["pb"] - 5.58) < 0.1
    assert snap["bvps"] == 224.50
    assert snap["ttm_eps"] == 66.04
    assert snap["total_share"] == 1252270215
    assert snap["source"] == "tx+datacenter"


def test_fetch_snap_datacenter_fails_returns_tx_without_pe():
    """datacenter 也失败时, 返回腾讯层（PE/PB=None），不报错。"""
    from atrade.data.eastmoney import fetch_snap
    from unittest.mock import patch

    fake_tx = {
        "code": "600519", "name": "贵州茅台", "price": 1253.0,
        "pre_close": 1258.99, "open": 1269.01, "pct_chg": None,
        "amplitude": None, "vol_ratio": None, "turnover": 0.47,
        "total_mv": 1.5e12, "float_mv": 1.5e12,
        "total_share": None, "float_share": None,
        "pe_ttm": None, "pb": None, "source": "tx",
    }
    with patch("atrade.data.eastmoney._fetch_eastmoney", return_value=None), \
         patch("atrade.data.eastmoney._fetch_tx", return_value=fake_tx), \
         patch("atrade.data.eastmoney._fetch_datacenter", return_value=None):
        snap = fetch_snap("600519")
    assert snap is not None
    assert snap["source"] == "tx"
    assert snap["pe_ttm"] is None
    assert snap["pb"] is None


def test_calc_ttm_eps_uses_annual_when_only_annual():
    """只有年报时, 直接用 EPSJB。"""
    from atrade.data.eastmoney import _calc_ttm_eps
    rows = [{"REPORT_TYPE": "年报", "EPSJB": 65.66, "REPORT_DATE": "2025-12-31"}]
    assert _calc_ttm_eps(rows) == 65.66


def test_calc_ttm_eps_uses_latest_quarter_when_no_annual():
    """只有季报时, 用最新季。"""
    from atrade.data.eastmoney import _calc_ttm_eps
    rows = [{"REPORT_TYPE": "一季报", "EPSJB": 21.76, "REPORT_DATE": "2026-03-31"}]
    assert _calc_ttm_eps(rows) == 21.76


def test_calc_ttm_eps_cross_year():
    """跨年场景: TTM = 上一年年报 + 本年Q1 - 上一年Q1。"""
    from atrade.data.eastmoney import _calc_ttm_eps
    rows = [
        {"REPORT_TYPE": "一季报", "EPSJB": 21.76, "REPORT_DATE": "2026-03-31"},
        {"REPORT_TYPE": "年报",   "EPSJB": 65.66, "REPORT_DATE": "2025-12-31"},
        {"REPORT_TYPE": "三季报", "EPSJB": 51.53, "REPORT_DATE": "2025-09-30"},
        {"REPORT_TYPE": "中报",   "EPSJB": 36.18, "REPORT_DATE": "2025-06-30"},
        {"REPORT_TYPE": "一季报", "EPSJB": 21.38, "REPORT_DATE": "2025-03-31"},
    ]
    # TTM = 65.66 + 21.76 - 21.38 = 66.04
    assert abs(_calc_ttm_eps(rows) - 66.04) < 1e-6


def test_calc_ttm_eps_same_year():
    """同年年报+季报（罕见），退化为直接用年报。"""
    from atrade.data.eastmoney import _calc_ttm_eps
    rows = [
        {"REPORT_TYPE": "一季报", "EPSJB": 21.76, "REPORT_DATE": "2025-03-31"},
        {"REPORT_TYPE": "年报",   "EPSJB": 65.66, "REPORT_DATE": "2025-12-31"},
    ]
    assert _calc_ttm_eps(rows) == 65.66


def test_calc_ttm_eps_empty():
    from atrade.data.eastmoney import _calc_ttm_eps
    assert _calc_ttm_eps([]) is None


def test_merge_pe_pb_basic():
    """_merge_pe_pb 把 BVPS/TTM_EPS 转为 PE/PB。"""
    from atrade.data.eastmoney import _merge_pe_pb
    base = {"price": 100.0, "source": "tx"}
    fin = {"bvps": 10.0, "ttm_eps": 5.0, "total_share": 1e9}
    out = _merge_pe_pb(base, fin)
    assert out["pe_ttm"] == 20.0
    assert out["pb"] == 10.0
    assert out["bvps"] == 10.0
    assert out["ttm_eps"] == 5.0
    assert out["source"] == "tx+datacenter"


def test_merge_pe_pb_no_price():
    """没价格就不算 PE/PB。"""
    from atrade.data.eastmoney import _merge_pe_pb
    base = {"price": None, "source": "tx"}
    fin = {"bvps": 10.0, "ttm_eps": 5.0, "total_share": 1e9}
    out = _merge_pe_pb(base, fin)
    assert "pe_ttm" not in out
    assert out["source"] == "tx"


def test_merge_pe_pb_negative_eps_skipped():
    """EPS <= 0 时不算 PE。"""
    from atrade.data.eastmoney import _merge_pe_pb
    base = {"price": 100.0, "source": "tx"}
    fin = {"bvps": 10.0, "ttm_eps": -1.0, "total_share": 1e9}
    out = _merge_pe_pb(base, fin)
    assert "pe_ttm" not in out
    assert out["pb"] == 10.0
