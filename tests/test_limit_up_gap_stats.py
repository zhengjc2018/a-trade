"""首板统计与打分测试。"""
from __future__ import annotations

import pandas as pd

from atrade.research.limit_up_gap.stats import (
    bucket_stats,
    compute_base,
    rank_factors,
    score_by_buckets,
    top_vs_all,
)


def _samples():
    return pd.DataFrame({
        "vol_ratio_5": [0.5, 0.6, 0.7, 2.0, 2.2, 2.4, 3.0, 3.2],
        "amplitude_pct": [2.0, 2.1, 2.2, 5.0, 5.1, 5.2, 8.0, 8.2],
        "next_open_gap_pct": [0.5, 0.6, 0.7, 1.1, 1.2, 1.3, 2.0, 2.1],
        "next_open_win": [False, False, False, True, True, True, True, True],
    })


def test_compute_base():
    base = compute_base(_samples())
    assert base["n"] == 8
    assert base["wins"] == 5
    assert base["win_rate"] == 0.625


def test_bucket_stats_respects_min_samples():
    buckets = bucket_stats(_samples(), "vol_ratio_5", min_samples=2)
    assert len(buckets) >= 1
    assert all(b.n >= 2 for b in buckets)


def test_rank_and_score_and_top():
    df = _samples()
    ranking = rank_factors(df, ["vol_ratio_5", "amplitude_pct"], min_samples=2)
    assert ranking
    best_buckets = [
        {"column": r["column"], "best_bucket": r["best_bucket"]}
        for r in ranking[:2]
    ]
    score = score_by_buckets(df, best_buckets, min_samples=2)
    assert score.max() >= 1
    top = top_vs_all(df, score, top_pct=0.5, min_samples=2)
    assert top["n"] == 4
    assert top["win_rate"] > 0.625
