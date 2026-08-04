"""次日高开研究（今日未涨停样本）。

两种口径：
- all_next_gap：任意非涨停日 X 的特征 -> X+1 开盘高开 ≥1%。
- first_board_predecessor：首板前一日 X 的特征 -> X+1（首板日）开盘高开 ≥1%。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from .features import add_features
from .industry import daily_industry_heat, merge_industry_heat
from .labels import add_limit_labels
from .qualifiers import industry_allowed, price_ok
from .report import GapStudyResult
from .stats import (
    bucket_stats,
    compute_base,
    rank_factors,
    score_by_buckets,
    top_vs_all,
)
from .study import BASE_FACTOR_COLUMNS, FACTOR_COLUMNS, INDUSTRY_FACTOR_COLUMNS


@dataclass
class NextGapConfig:
    mode: str = "all_next_gap"
    min_gap_pct: float = 1.0
    min_samples: int = 30
    top_pct: float = 0.2
    max_symbols: int = 0
    min_bars: int = 80
    lookback_bars: int = 515
    allowed_codes: Optional[set[str]] = None


def collect_next_gap_samples(
    codes: list[str],
    hp,
    industry_fn: Callable[[str], str],
    config: NextGapConfig,
) -> tuple[pd.DataFrame, dict]:
    limit_rows: list[pd.DataFrame] = []
    sample_rows: list[pd.DataFrame] = []
    excluded = {"no_next_open": 0, "price": 0, "industry": 0, "fundamental": 0}
    selected = codes[: config.max_symbols] if config.max_symbols > 0 else codes

    for code in selected:
        if config.allowed_codes is not None and code not in config.allowed_codes:
            excluded["fundamental"] += 1
            continue
        df = hp.fetch_with_cache(
            code,
            scale="1d",
            datalen=config.lookback_bars,
            use_snapshot=False,
        )
        if df is None or len(df) < config.min_bars:
            continue
        industry = industry_fn(code) or "未知行业"
        if not industry_allowed(industry):
            excluded["industry"] += 1
            continue

        df = add_limit_labels(df, min_gap_pct=config.min_gap_pct)
        df = add_features(df)
        if config.mode == "first_board_predecessor":
            mask = (
                df["is_first_board"].shift(-1).eq(True)
                & ~df["is_limit_up"]
                & df["next_open_exists"]
            )
        else:
            mask = df["next_open_exists"] & ~df["is_limit_up"]

        board = df[df["is_limit_up"] & df["next_open_exists"]].copy()
        if not board.empty:
            board["code"] = code
            board["industry"] = industry
            limit_rows.append(board[["date", "code", "industry"]])

        candidates = df[mask].copy()
        if candidates.empty:
            excluded["no_next_open"] += int((~df["next_open_exists"]).sum())
            continue
        candidates = candidates[candidates["close"].apply(price_ok)]
        if candidates.empty:
            excluded["price"] += int(mask.sum())
            continue
        excluded["no_next_open"] += int(
            (mask & ~df["next_open_exists"]).sum()
        )
        candidates["code"] = code
        candidates["industry"] = industry
        keep = ["date", "code", "industry", "next_open_gap_pct", "next_open_win"]
        sample_rows.append(candidates[keep + BASE_FACTOR_COLUMNS])

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


def run_next_gap_study(
    codes: list[str],
    hp,
    industry_fn: Callable[[str], str],
    config: NextGapConfig,
) -> GapStudyResult:
    samples, excluded = collect_next_gap_samples(codes, hp, industry_fn, config)
    factor_cols = [column for column in FACTOR_COLUMNS if column in samples.columns]
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


def render_next_gap_report(result: GapStudyResult) -> str:
    base = result.base
    lines = [
        "# 次日高开研究（今日未涨停）",
        f"_{result.generated_at}_",
        "",
        f"总样本：**{base['n']}** 个非涨停日，胜率 **{base['win_rate']:.1%}**，"
        f"平均高开 **{base['mean_gap']:.2f}%**，中位高开 **{base['median_gap']:.2f}%**",
        "",
        f"排除：行业 {result.excluded.get('industry', 0)}、"
        f"价格 {result.excluded.get('price', 0)}、"
        f"基本面 {result.excluded.get('fundamental', 0)}、"
        f"无 T+1 {result.excluded.get('no_next_open', 0)}",
        "",
    ]
    if base["n"] == 0:
        lines.append("_样本不足，无法输出统计结论。_")
        return "\n".join(lines)

    lines.append("## 单因子最佳桶")
    if result.ranking:
        lines.append("| 因子 | 最佳桶 | 样本 | 胜率 | 平均高开 | 相对基线 |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for r in result.ranking:
            lines.append(
                f"| {r['column']} | {r['best_bucket']} | {r['n']} | "
                f"{r['win_rate']:.1%} | {r['mean_gap']:.2f}% | "
                f"{r['lift']:+.1%} |"
            )
    else:
        lines.append("_无满足最小样本的因子。_")

    top = result.top
    lines.extend([
        "",
        f"## 多因子 Top {result.top_pct:.0%}",
        f"- Top {top['n']} 个：胜率 **{top['win_rate']:.1%}**，"
        f"平均高开 **{top['mean_gap']:.2f}%**，相对基线提升 **{top['lift']:+.1%}**",
        "",
    ])
    for column, buckets in result.factor_buckets.items():
        lines.append(f"### {column}")
        lines.append("| 桶 | 样本 | 胜率 | 平均高开 |")
        lines.append("|---|---:|---:|---:|")
        for b in buckets:
            lines.append(
                f"| {b.bucket} | {b.n} | {b.win_rate:.1%} | {b.mean_gap:.2f}% |"
            )
        lines.append("")
    lines.append("---")
    lines.append(
        f"_口径：今日未涨停，T+1 开盘高开 ≥{result.min_gap_pct:g}% 算胜；"
        "已排除 ST/科创/创业/白酒/证券/消费/房地产，价格 >80 与基本面差个股。_"
    )
    return "\n".join(lines)
