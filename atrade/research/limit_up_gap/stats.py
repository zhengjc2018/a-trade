"""首板样本分桶统计、单因子排序与多因子打分。"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BucketStat:
    bucket: str
    n: int
    wins: int
    win_rate: float
    mean_gap: float
    median_gap: float


def _bucket_label(series: pd.Series) -> pd.Series:
    """数值列按排名分 4 桶，布尔/字符串列直接转字符串。"""
    if series.dtype == bool or series.dtype == object:
        return series.astype(str)
    try:
        return pd.qcut(
            series.rank(method="first"),
            q=4,
            labels=["Q1", "Q2", "Q3", "Q4"],
        )
    except ValueError:
        return series.astype(str)


def compute_base(df: pd.DataFrame) -> dict:
    n = len(df)
    wins = int(df["next_open_win"].sum()) if n else 0
    return {
        "n": n,
        "wins": wins,
        "win_rate": wins / n if n else 0.0,
        "mean_gap": float(df["next_open_gap_pct"].mean()) if n else 0.0,
        "median_gap": float(df["next_open_gap_pct"].median()) if n else 0.0,
    }


def bucket_stats(
    df: pd.DataFrame,
    column: str,
    min_samples: int = 30,
) -> list[BucketStat]:
    labels = _bucket_label(df[column])
    out: list[BucketStat] = []
    for label, group in df.assign(_bucket=labels).groupby(
        "_bucket",
        sort=False,
        observed=False,
    ):
        stat = compute_base(group)
        if stat["n"] < min_samples:
            continue
        out.append(BucketStat(
            bucket=str(label),
            n=stat["n"],
            wins=stat["wins"],
            win_rate=stat["win_rate"],
            mean_gap=stat["mean_gap"],
            median_gap=stat["median_gap"],
        ))
    return out


def rank_factors(
    df: pd.DataFrame,
    factor_columns: list[str],
    min_samples: int = 30,
) -> list[dict]:
    base = compute_base(df)
    ranking: list[dict] = []
    used_buckets: set[str] = set()
    for column in factor_columns:
        if column not in df.columns:
            continue
        buckets = bucket_stats(df, column, min_samples=min_samples)
        if not buckets:
            continue
        best = max(buckets, key=lambda b: b.win_rate)
        tied_best = [b for b in buckets if b.win_rate == best.win_rate]
        selected = next(
            (b for b in tied_best if b.bucket not in used_buckets),
            best,
        )
        used_buckets.add(selected.bucket)
        ranking.append({
            "column": column,
            "best_bucket": selected.bucket,
            "n": selected.n,
            "win_rate": selected.win_rate,
            "mean_gap": selected.mean_gap,
            "lift": selected.win_rate - base["win_rate"],
        })
    return sorted(ranking, key=lambda r: r["lift"], reverse=True)


def score_by_buckets(
    df: pd.DataFrame,
    best_buckets: list[dict],
    min_samples: int = 30,
) -> pd.Series:
    """按每个因子的最佳桶命中数打分。"""
    score = pd.Series(0, index=df.index, dtype=int)
    for rule in best_buckets:
        column = rule["column"]
        if column not in df.columns:
            continue
        labels = _bucket_label(df[column])
        score = score + (labels == rule["best_bucket"]).astype(int)
    return score


def top_vs_all(
    df: pd.DataFrame,
    score: pd.Series,
    top_pct: float = 0.2,
    min_samples: int = 30,
) -> dict:
    n = len(df)
    if n < min_samples:
        return {
            "top_pct": top_pct,
            "n": 0,
            "win_rate": 0.0,
            "mean_gap": 0.0,
            "lift": 0.0,
        }
    top_n = max(1, int(round(n * top_pct)))
    if top_n < min_samples:
        return {
            "top_pct": top_pct,
            "n": 0,
            "win_rate": 0.0,
            "mean_gap": 0.0,
            "lift": 0.0,
        }
    top = df.assign(_score=score).nlargest(top_n, "_score")
    top_stat = compute_base(top)
    base_stat = compute_base(df)
    return {
        "top_pct": top_pct,
        "n": top_n,
        "win_rate": top_stat["win_rate"],
        "mean_gap": top_stat["mean_gap"],
        "lift": top_stat["win_rate"] - base_stat["win_rate"],
    }
