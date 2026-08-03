"""行业标签与板块热度测试。"""
from __future__ import annotations

import pandas as pd

from atrade.research.limit_up_gap.industry import (
    daily_industry_heat,
    merge_industry_heat,
)


def test_daily_industry_heat_counts_and_top3():
    rows = pd.DataFrame([
        {"date": "2026-07-30", "code": "600001", "industry": "半导体"},
        {"date": "2026-07-30", "code": "600002", "industry": "半导体"},
        {"date": "2026-07-30", "code": "600003", "industry": "白酒"},
        {"date": "2026-07-30", "code": "600004", "industry": "白酒"},
        {"date": "2026-07-30", "code": "600005", "industry": "白酒"},
        {"date": "2026-07-30", "code": "600006", "industry": "证券"},
        {"date": "2026-07-30", "code": "600010", "industry": "银行"},
        {"date": "2026-07-31", "code": "600007", "industry": "半导体"},
    ])
    heat = daily_industry_heat(rows)
    assert len(heat) == 5
    top = heat[heat["date"] == "2026-07-30"]
    assert top.loc[top["industry"] == "白酒", "limit_count"].iloc[0] == 3
    assert bool(top.loc[top["industry"] == "白酒", "is_top3"].iloc[0])
    assert not bool(top.loc[top["industry"] == "银行", "is_top3"].iloc[0])


def test_merge_industry_heat_fills_missing():
    samples = pd.DataFrame([
        {"date": "2026-07-30", "code": "600001", "industry": "半导体"},
        {"date": "2026-07-30", "code": "600009", "industry": "未知行业"},
    ])
    heat = pd.DataFrame([
        {"date": "2026-07-30", "industry": "半导体", "limit_count": 2, "is_top3": True},
    ])
    out = merge_industry_heat(samples, heat)
    assert out.loc[0, "industry_limit_count"] == 2
    assert bool(out.loc[0, "industry_is_top3"])
    assert out.loc[1, "industry_limit_count"] == 0
    assert not bool(out.loc[1, "industry_is_top3"])
