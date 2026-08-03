"""涨停池历史增强测试。"""
from __future__ import annotations

import pandas as pd
import pytest

from atrade.research.limit_up_gap.ztpool import enrich_samples


def test_enrich_samples_merges_zt_fields():
    samples = pd.DataFrame([
        {"date": "2026-07-30", "code": "600001"},
        {"date": "2026-07-30", "code": "600002"},
    ])

    def fake_fetch(date):
        assert date == "2026-07-30"
        return pd.DataFrame([
            {
                "代码": "600001",
                "换手率": 12.5,
                "流通市值": 8.0e9,
                "炸板次数": 0,
                "封单资金": 2.5e8,
            },
        ])

    out = enrich_samples(samples, fetch_day=fake_fetch)
    assert out.loc[0, "zt_turnover"] == pytest.approx(12.5)
    assert out.loc[0, "zt_float_mv_yi"] == pytest.approx(80.0, rel=1e-6)
    assert out.loc[0, "zt_break_count"] == 0
    assert out.loc[0, "zt_seal_amount_yi"] == pytest.approx(2.5, rel=1e-6)
    assert pd.isna(out.loc[1, "zt_turnover"])


def test_enrich_samples_keeps_missing_dates_na():
    samples = pd.DataFrame([{"date": "2026-07-31", "code": "600001"}])
    out = enrich_samples(samples, fetch_day=lambda date: None)
    assert pd.isna(out.loc[0, "zt_turnover"])
