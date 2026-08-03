"""首板次日高开研究主流程。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from .features import add_features
from .industry import daily_industry_heat, merge_industry_heat
from .labels import add_limit_labels
from .report import GapStudyResult
from .stats import (
    bucket_stats,
    compute_base,
    rank_factors,
    score_by_buckets,
    top_vs_all,
)

BASE_FACTOR_COLUMNS = [
    "vol_ratio_5",
    "amplitude_pct",
    "body_ratio",
    "pos_ma20",
    "pos_ma60",
    "dist_high60",
    "dist_low60",
    "amount_yi",
]
INDUSTRY_FACTOR_COLUMNS = ["industry_limit_count", "industry_is_top3"]
# 与 ztpool.ZT_FACTOR_COLUMNS 保持一致；ztpool 不可用时列不存在，统计会跳过
ZT_FACTOR_COLUMNS = [
    "zt_turnover",
    "zt_float_mv_yi",
    "zt_break_count",
    "zt_seal_amount_yi",
]
FACTOR_COLUMNS = (
    BASE_FACTOR_COLUMNS
    + INDUSTRY_FACTOR_COLUMNS
    + ZT_FACTOR_COLUMNS
)


@dataclass
class StudyConfig:
    min_gap_pct: float = 1.0
    min_samples: int = 30
    top_pct: float = 0.2
    max_symbols: int = 0
    min_bars: int = 80
    lookback_bars: int = 515
    with_zt_pool: bool = False


def collect_samples(
    codes: list[str],
    hp,
    industry_fn: Callable[[str], str],
    config: StudyConfig,
    is_trade_day: Optional[Callable[[str], bool]] = None,
) -> tuple[pd.DataFrame, dict]:
    limit_rows: list[pd.DataFrame] = []
    sample_rows: list[pd.DataFrame] = []
    excluded = {"yiziban": 0, "no_next_open": 0, "first_board": 0, "lianban": 0}
    selected = codes[: config.max_symbols] if config.max_symbols > 0 else codes
    for code in selected:
        df = hp.fetch_with_cache(
            code,
            scale="1d",
            datalen=config.lookback_bars,
            use_snapshot=False,
        )
        if df is None or len(df) < config.min_bars:
            continue
        df = add_limit_labels(
            df,
            min_gap_pct=config.min_gap_pct,
            is_trade_day=is_trade_day,
        )
        df = add_features(df)
        industry = industry_fn(code) or "未知行业"

        board = df[df["is_limit_up"] & df["next_open_exists"]].copy()
        if not board.empty:
            board["code"] = code
            board["industry"] = industry
            limit_rows.append(board[["date", "code", "industry"]])

        first = df[df["is_first_board"] & df["next_open_exists"]].copy()
        excluded["yiziban"] += int(first["is_yiziban"].sum())
        first = first[~first["is_yiziban"]]
        excluded["no_next_open"] += int(
            (df["is_first_board"] & ~df["next_open_exists"]).sum()
        )
        excluded["first_board"] += int(df["is_first_board"].sum())
        excluded["lianban"] += int(
            (df["is_limit_up"] & (df["limit_streak"] >= 2)).sum()
        )
        if not first.empty:
            first["code"] = code
            first["industry"] = industry
            keep = ["date", "code", "industry", "next_open_gap_pct", "next_open_win"]
            sample_rows.append(first[keep + BASE_FACTOR_COLUMNS])

    if not sample_rows:
        return pd.DataFrame(), excluded
    samples = pd.concat(sample_rows, ignore_index=True)
    if limit_rows:
        heat = daily_industry_heat(pd.concat(limit_rows, ignore_index=True))
        samples = merge_industry_heat(samples, heat)
    else:
        samples["industry_limit_count"] = 0
        samples["industry_is_top3"] = False
    base_factors = BASE_FACTOR_COLUMNS + INDUSTRY_FACTOR_COLUMNS
    samples = samples.dropna(subset=base_factors).reset_index(drop=True)
    return samples, excluded


def run_study(
    codes: list[str],
    hp,
    industry_fn: Callable[[str], str],
    config: StudyConfig,
    zt_enrich: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = None,
    is_trade_day: Optional[Callable[[str], bool]] = None,
) -> GapStudyResult:
    samples, excluded = collect_samples(
        codes,
        hp,
        industry_fn,
        config,
        is_trade_day=is_trade_day,
    )
    if config.with_zt_pool and zt_enrich is not None:
        samples = zt_enrich(samples)
    available_zt = [
        c
        for c in ZT_FACTOR_COLUMNS
        if c in samples.columns
        and int(samples[c].notna().sum()) >= config.min_samples
    ]
    factor_cols = BASE_FACTOR_COLUMNS + INDUSTRY_FACTOR_COLUMNS + available_zt
    if samples.empty:
        factor_cols = []
    if factor_cols:
        samples = samples.dropna(subset=factor_cols).reset_index(drop=True)
    base = compute_base(samples)
    factor_buckets = {
        column: bucket_stats(samples, column, config.min_samples)
        for column in factor_cols
    }
    ranking = rank_factors(samples, factor_cols, config.min_samples)
    best_buckets = [
        {"column": r["column"], "best_bucket": r["best_bucket"]}
        for r in ranking[:5]
    ]
    score = score_by_buckets(samples, best_buckets, config.min_samples)
    top = top_vs_all(samples, score, config.top_pct, config.min_samples)
    return GapStudyResult(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        base=base,
        factor_buckets=factor_buckets,
        ranking=ranking,
        top=top,
        excluded=excluded,
        top_pct=config.top_pct,
        min_gap_pct=config.min_gap_pct,
    )
