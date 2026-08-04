"""每日尾盘首板高开候选。

思路：取当日涨停池，筛选沪深主板首板（连板数=1）、排除一字板，叠加当日
行情与历史日线计算研究阶段验证过的因子，等权打分后推送 Top N。
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .features import add_features
from .labels import add_limit_labels

MAIN_BOARD_PREFIXES = ("000", "001", "002", "600", "601", "603", "605")

# 研究阶段“高值有利”的因子
SCORE_FACTORS_HIGH = ("industry_limit_count", "dist_high60", "pos_ma20")
# 研究阶段“低值有利”的因子
SCORE_FACTORS_LOW = ("vol_ratio_5", "amplitude_pct")


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


def build_daily_candidates(
    zt_df: pd.DataFrame,
    hp,
    quote_map: dict,
    trade_date: str,
) -> list[dict]:
    """从当日涨停池构建首板候选（含研究因子）。"""
    out: list[dict] = []
    for _, row in zt_df.iterrows():
        code = str(row.get("代码", "")).zfill(6)
        name = str(row.get("名称", ""))
        if not code.startswith(MAIN_BOARD_PREFIXES):
            continue
        if "ST" in name.upper() or "退" in name:
            continue
        if _to_int(row.get("连板数"), 1) != 1:
            continue

        quote = quote_map.get(code)
        if quote is None or not quote.is_valid:
            continue
        # 一字板：开盘=最高=最低=现价，尾盘实际买不到
        if quote.open == quote.high == quote.low == quote.price:
            continue

        hist = hp.fetch_with_cache(code, scale="1d", datalen=150, use_snapshot=False)
        if hist is None or len(hist) < 65:
            continue

        today = {
            "date": trade_date,
            "open": float(quote.open),
            "high": float(quote.high),
            "low": float(quote.low),
            "close": float(quote.price),
            "volume": int(quote.volume or 0),
        }
        hist = hist[["date", "open", "high", "low", "close", "volume"]].copy()
        last_date = str(hist["date"].astype(str).str[:10].iloc[-1])
        if last_date == trade_date:
            # 日线已含今日：用实时行情覆盖最后一根，避免重复追加导致 prev_close 错位
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
        if not bool(last.get("is_first_board", False)):
            continue
        if bool(last.get("is_yiziban", False)):
            continue

        features = {
            "vol_ratio_5": _to_float(last.get("vol_ratio_5")),
            "amplitude_pct": _to_float(last.get("amplitude_pct")),
            "dist_high60": _to_float(last.get("dist_high60")),
            "pos_ma20": _to_float(last.get("pos_ma20")),
        }
        if any(pd.isna(v) for v in features.values()):
            continue
        out.append({
            "code": code,
            "name": name,
            "price": float(quote.price),
            "change_pct": _to_float(row.get("涨跌幅")),
            "industry": str(row.get("所属行业", "") or "未知行业"),
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


def render_daily_candidates(
    candidates: list[dict],
    top_n: int = 15,
    now: datetime | None = None,
) -> str:
    """渲染每日首板候选 Markdown；无候选返回空字符串。"""
    if not candidates:
        return ""
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 🚀 a-trade 首板高开候选",
        f"_{ts}_",
        "",
        f"今日首板候选 **{len(candidates)}** 只，按研究因子评分：",
        "",
        "| 代码 | 名称 | 现价 | 板块涨停 | 量比 | 振幅% | 得分 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for candidate in candidates[:top_n]:
        lines.append(
            f"| {candidate['code']} | {candidate['name']} | "
            f"{candidate['price']:.2f} | {candidate['industry_limit_count']} | "
            f"{candidate['vol_ratio_5']:.2f} | {candidate['amplitude_pct']:.2f} | "
            f"{candidate['score']} |"
        )
    lines.extend([
        "",
        "- 口径：今日首板、非一字板；买入参考尾盘价，目标 T+1 高开 ≥1%。",
        "_仅供参考，投资有风险_",
    ])
    return "\n".join(lines)
