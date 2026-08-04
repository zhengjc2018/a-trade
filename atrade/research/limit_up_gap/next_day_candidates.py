"""每日尾盘“明日高开”候选。

筛选今日未涨停、通过行业/价格/基本面硬过滤的主板个股，用研究阶段验证过的
因子等权评分，推送综合评分 Top N（默认 3）。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .features import add_features
from .labels import add_limit_labels
from .qualifiers import (
    fundamentals_ok,
    industry_allowed,
    is_main_board,
    is_st_name,
    not_limit_up,
    price_ok,
)

# 研究阶段 B（今日未涨停次日高开）验证出的方向：
# 放量、高振幅、强趋势、远离 60 日低点、板块热度高 -> 高值有利
SCORE_FACTORS_HIGH = (
    "amplitude_pct",
    "pos_ma20",
    "pos_ma60",
    "dist_low60",
    "amount_yi",
    "vol_ratio_5",
    "industry_limit_count",
)
# 距 60 日高点越近（dist_high60 越低）越有利
SCORE_FACTORS_LOW = ("dist_high60",)


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def build_next_day_candidates(
    snapshot_df: pd.DataFrame,
    zt_df: pd.DataFrame,
    hp,
    industry_fn,
    trade_date: str,
) -> list[dict]:
    """从全市场快照筛选今日未涨停、基本面合格的候选。"""
    out: list[dict] = []
    for _, row in snapshot_df.iterrows():
        code = str(row.get("code", "")).zfill(6)
        name = str(row.get("name", ""))
        if not is_main_board(code) or is_st_name(name):
            continue
        if not price_ok(row.get("price")):
            continue
        if not fundamentals_ok(row.get("pe_ttm"), row.get("pb")):
            continue
        if not not_limit_up(row.get("pct_chg")):
            continue
        industry = industry_fn(code) or "未知行业"
        if not industry_allowed(industry):
            continue

        hist = hp.fetch_with_cache(code, scale="1d", datalen=150, use_snapshot=False)
        if hist is None or len(hist) < 65:
            continue

        price = _to_float(row.get("price"))
        today = {
            "date": trade_date,
            "open": price,
            "high": _to_float(row.get("high"), price),
            "low": _to_float(row.get("low"), price),
            "close": price,
            "volume": int(_to_float(row.get("volume_lots"), 0) * 100),
        }
        hist = hist[["date", "open", "high", "low", "close", "volume"]].copy()
        last_date = str(hist["date"].astype(str).str[:10].iloc[-1])
        if last_date == trade_date:
            hist.loc[hist.index[-1], ["open", "high", "low", "close", "volume"]] = [
                today["open"],
                today["high"],
                today["low"],
                today["close"],
                today["volume"],
            ]
            df = hist
        else:
            df = pd.concat([hist, pd.DataFrame([today])], ignore_index=True)
        df = add_limit_labels(df)
        df = add_features(df)
        last = df.iloc[-1]
        features = {
            "vol_ratio_5": _to_float(last.get("vol_ratio_5")),
            "amplitude_pct": _to_float(last.get("amplitude_pct")),
            "dist_high60": _to_float(last.get("dist_high60")),
            "dist_low60": _to_float(last.get("dist_low60")),
            "pos_ma20": _to_float(last.get("pos_ma20")),
            "pos_ma60": _to_float(last.get("pos_ma60")),
            "amount_yi": _to_float(last.get("amount_yi")),
        }
        if any(pd.isna(v) for v in features.values()):
            continue
        out.append({
            "code": code,
            "name": name,
            "price": price,
            "change_pct": _to_float(row.get("pct_chg")),
            "industry": industry,
            **features,
        })

    if not out:
        return []

    industry_col = "所属行业" if "所属行业" in zt_df.columns else "industry"
    heat = (
        zt_df.assign(_industry=zt_df[industry_col].fillna("未知行业").astype(str))
        .groupby("_industry")
        .size()
    )
    for candidate in out:
        candidate["industry_limit_count"] = int(
            heat.get(candidate["industry"], 0)
        )
    return out


def score_candidates(candidates: list[dict]) -> list[dict]:
    """按研究因子的中位数方向等权打分并排序。"""
    if not candidates:
        return []
    df = pd.DataFrame(candidates)
    for column in SCORE_FACTORS_HIGH:
        df[f"{column}_hit"] = df[column] >= df[column].median()
    for column in SCORE_FACTORS_LOW:
        df[f"{column}_hit"] = df[column] <= df[column].median()
    hit_columns = [
        f"{column}_hit"
        for column in SCORE_FACTORS_HIGH + SCORE_FACTORS_LOW
    ]
    df["score"] = df[hit_columns].sum(axis=1).astype(int)
    df = df.sort_values(
        ["score", "industry_limit_count"],
        ascending=[False, False],
    )
    return df.to_dict("records")


def render_next_day_candidates(
    candidates: list[dict],
    top_n: int = 3,
    now: datetime | None = None,
) -> str:
    """渲染明日高开候选 Markdown；无候选返回空字符串。"""
    if not candidates:
        return ""
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    shown = candidates[:top_n]
    lines = [
        "# 🚀 a-trade 明日高开候选",
        f"_{ts}_",
        "",
        f"今日未涨停、基本面合格候选 **{len(candidates)}** 只，"
        f"综合评分 Top {len(shown)}：",
        "",
        "| 排名 | 代码 | 名称 | 现价 | 量比 | 振幅% | 板块涨停 | 得分 |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for rank, candidate in enumerate(shown, 1):
        lines.append(
            f"| {rank} | {candidate['code']} | {candidate['name']} | "
            f"{candidate['price']:.2f} | {candidate['vol_ratio_5']:.2f} | "
            f"{candidate['amplitude_pct']:.2f} | "
            f"{candidate['industry_limit_count']} | {candidate['score']} |"
        )
    lines.extend([
        "",
        "- 口径：今日未涨停，目标 T+1 开盘高开 ≥1%；评分基于量比/振幅/板块热度/价格位置。",
        "_仅供参考，投资有风险_",
    ])
    return "\n".join(lines)
