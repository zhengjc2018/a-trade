# 首板次日高开研究器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可复现的首板次日高开研究器，用近 1 年沪深主板日线分析涨停启动特征，输出按特征分桶的胜率/平均高开和多因子 Top 20% 对比报告。

**Architecture:** 新增独立研究包 `atrade/research/limit_up_gap/`，分模块负责标签推导、特征计算、板块热度、统计、报告和主流程；`scripts/run_gap_study.py` 作为 CLI 入口。研究器只读历史数据、只写报告，不改现有选股/推送逻辑。

**Tech Stack:** Python 3.9+、pandas、requests、akshare、loguru、pytest、ruff。

## Global Constraints

- 股票池：沪深主板 `000 / 001 / 002 / 600 / 601 / 603 / 605`，剔除 ST/退市。
- 涨停：`close >= prev_close * 1.099`。
- 首板：当日涨停且前一日未涨停。
- 一字板：`open == high == low == close` 且涨停，策略候选排除、报告单列。
- 买入价：T 日收盘价；卖出价：T+1 开盘价。
- 胜：`open_{T+1} >= close_T * (1 + min_gap_pct / 100)`，默认 `min_gap_pct = 1.0`。
- T+1 停牌/无数据：策略统计剔除，报告中标记数量。
- 默认近 1 年，参数可扩展。
- 本次不修改现有选股/推送逻辑，不引入实盘下单。
- Python 版本 >= 3.9，代码用 `from __future__ import annotations`，ruff line-length 100。

---

### Task 1: 涨停标签推导

**Files:**
- Create: `atrade/research/__init__.py`
- Create: `atrade/research/limit_up_gap/__init__.py`
- Create: `atrade/research/limit_up_gap/labels.py`
- Test: `tests/test_limit_up_gap_labels.py`

**Interfaces:**
- Produces: `add_limit_labels(df: pd.DataFrame, min_gap_pct: float = 1.0, is_trade_day: Optional[Callable[[str], bool]] = None) -> pd.DataFrame`
  - 输入列：`open / high / low / close / volume`，按日期升序。
  - 输出新增列：`prev_close, is_limit_up, limit_streak, is_first_board, is_yiziban, next_open, next_open_exists, next_open_gap_pct, next_open_win`。

- [ ] **Step 1: Write the failing test**

```python
"""首板次日高开标签推导测试。"""
from __future__ import annotations

import pandas as pd
import pytest

from atrade.research.limit_up_gap.labels import add_limit_labels


def _df():
    # 日期升序：T-1 普通、T 首板、T+1 高开、T+2 一字（非连板）、T+3 普通
    return pd.DataFrame([
        {"date": "2026-07-29", "open": 10.0, "high": 10.3, "low": 9.9, "close": 10.1, "volume": 100_000},
        {"date": "2026-07-30", "open": 10.2, "high": 11.2, "low": 10.1, "close": 11.2, "volume": 300_000},
        {"date": "2026-07-31", "open": 11.5, "high": 11.8, "low": 11.2, "close": 11.5, "volume": 200_000},
        {"date": "2026-08-03", "open": 12.7, "high": 12.7, "low": 12.7, "close": 12.7, "volume": 50_000},
        {"date": "2026-08-04", "open": 12.8, "high": 13.0, "low": 12.6, "close": 12.9, "volume": 80_000},
    ])


def test_limit_labels():
    out = add_limit_labels(_df())
    assert list(out["is_limit_up"]) == [False, True, False, True, False]
    assert list(out["limit_streak"]) == [0, 1, 0, 1, 0]
    assert list(out["is_first_board"]) == [False, True, False, True, False]
    # 2026-08-03 是一字板；2026-07-30 不是
    assert list(out["is_yiziban"]) == [False, False, False, True, False]
    # T=2026-07-30 的 T+1 开盘 11.5，gap = 11.5/11.2 - 1 = 2.68%
    assert out.loc[1, "next_open_gap_pct"] == pytest.approx(2.6785, rel=1e-3)
    assert bool(out.loc[1, "next_open_win"])
    # 最后一根无 T+1
    assert not bool(out.loc[4, "next_open_exists"])


def test_min_gap_threshold():
    out = add_limit_labels(_df(), min_gap_pct=3.0)
    # gap 2.68% < 3%，不算胜
    assert not bool(out.loc[1, "next_open_win"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_limit_up_gap_labels.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.research'`

- [ ] **Step 3: Create package and minimal implementation**

`atrade/research/__init__.py`:

```python
"""A 股量化研究模块。"""
```

`atrade/research/limit_up_gap/__init__.py`:

```python
"""首板次日高开研究。"""
```

`atrade/research/limit_up_gap/labels.py`:

```python
"""涨停/首板/连板/一字板推导与 T+1 高开标签。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Optional

import pandas as pd

LIMIT_UP_PCT = 0.099


def add_limit_labels(
    df: pd.DataFrame,
    min_gap_pct: float = 1.0,
    is_trade_day: Optional[Callable[[str], bool]] = None,
) -> pd.DataFrame:
    """按日期升序输入日线，追加涨停与次日高开相关列。"""
    out = df.copy()
    out["prev_close"] = out["close"].shift(1)
    out["is_limit_up"] = (
        (out["close"] >= out["prev_close"] * (1 + LIMIT_UP_PCT))
        & (out["prev_close"] > 0)
    )
    streak: list[int] = []
    current = 0
    for flag in out["is_limit_up"].tolist():
        current = current + 1 if flag else 0
        streak.append(current)
    out["limit_streak"] = streak
    out["is_first_board"] = out["limit_streak"] == 1
    out["is_yiziban"] = (
        out["is_limit_up"]
        & (out["open"] == out["high"])
        & (out["high"] == out["low"])
        & (out["low"] == out["close"])
    )
    if is_trade_day is None:
        out["next_open"] = out["open"].shift(-1)
    else:
        date_strs = out["date"].astype(str).str[:10].tolist()
        date_to_open = dict(zip(date_strs, out["open"].tolist()))
        next_open_values: list[float] = []
        for date_str in date_strs:
            current = datetime.strptime(date_str, "%Y-%m-%d").date()
            next_date: Optional[str] = None
            for _ in range(10):
                current += timedelta(days=1)
                candidate = current.strftime("%Y-%m-%d")
                if is_trade_day(candidate):
                    next_date = candidate
                    break
            next_open_values.append(
                date_to_open.get(next_date, float("nan"))
                if next_date is not None
                else float("nan")
            )
        out["next_open"] = next_open_values
    out["next_open_exists"] = out["next_open"].notna() & (out["next_open"] > 0)
    out["next_open_gap_pct"] = (out["next_open"] / out["close"] - 1) * 100
    out["next_open_win"] = (
        out["next_open_gap_pct"].ge(min_gap_pct).fillna(False)
    )
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_limit_up_gap_labels.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add atrade/research tests/test_limit_up_gap_labels.py
git commit -m "feat(research): 涨停/首板/连板/一字板与次日高开标签"
```

---

### Task 2: 量价特征

**Files:**
- Create: `atrade/research/limit_up_gap/features.py`
- Test: `tests/test_limit_up_gap_features.py`

**Interfaces:**
- Consumes: `add_limit_labels` 的输出（含 `pre_close`）。
- Produces: `add_features(df: pd.DataFrame) -> pd.DataFrame`
  - 输入列：`open / high / low / close / volume`，可选 `pre_close / amount`。
  - 输出新增列：`vol_ratio_5, amplitude_pct, close_is_high, body_ratio, pos_ma20, pos_ma60, dist_high60, dist_low60, amount_yi`。

- [ ] **Step 1: Write the failing test**

```python
"""量价特征测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atrade.research.limit_up_gap.features import add_features


def _df():
    n = 70
    closes = np.linspace(10.0, 15.0, n)
    return pd.DataFrame({
        "open": closes * 0.99,
        "high": closes * 1.03,
        "low": closes * 0.98,
        "close": closes,
        "volume": np.full(n, 100_000),
    })


def test_add_features():
    out = add_features(_df())
    last = out.iloc[-1]
    assert last["vol_ratio_5"] == pytest.approx(1.0, rel=1e-6)
    assert last["amplitude_pct"] > 0
    assert not bool(last["close_is_high"])
    assert 0.0 < last["body_ratio"] < 1.0
    assert last["pos_ma20"] > 0
    assert last["pos_ma60"] > 0
    assert last["dist_high60"] < 0
    assert last["dist_low60"] >= 0
    assert last["amount_yi"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_limit_up_gap_features.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.research.limit_up_gap.features'`

- [ ] **Step 3: Write minimal implementation**

`atrade/research/limit_up_gap/features.py`:

```python
"""首板量价特征。"""

from __future__ import annotations

import pandas as pd


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """按日期升序输入日线，追加量价特征列。"""
    out = df.copy()
    out["vol_ratio_5"] = out["volume"] / out["volume"].rolling(5).mean().shift(1)
    prev_close = out["pre_close"] if "pre_close" in out.columns else out["close"].shift(1)
    out["amplitude_pct"] = (out["high"] - out["low"]) / prev_close * 100
    out["close_is_high"] = out["close"] >= out["high"]
    span = out["high"] - out["low"]
    out["body_ratio"] = ((out["close"] - out["open"]) / span).where(span > 0, 1.0)
    out["pos_ma20"] = out["close"] / out["close"].rolling(20).mean() - 1
    out["pos_ma60"] = out["close"] / out["close"].rolling(60).mean() - 1
    high60 = out["high"].rolling(60).max().shift(1)
    low60 = out["low"].rolling(60).min().shift(1)
    out["dist_high60"] = out["close"] / high60 - 1
    out["dist_low60"] = out["close"] / low60 - 1
    amount = out["amount"] if "amount" in out.columns else out["close"] * out["volume"]
    out["amount_yi"] = amount / 1e8
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_limit_up_gap_features.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add atrade/research/limit_up_gap/features.py tests/test_limit_up_gap_features.py
git commit -m "feat(research): 首板量价特征"
```

---

### Task 3: 行业标签与板块热度

**Files:**
- Create: `atrade/research/limit_up_gap/industry.py`
- Test: `tests/test_limit_up_gap_industry.py`

**Interfaces:**
- Produces:
  - `industry_of(code: str) -> str`：返回行业名，失败返回 `""`，结果带 `lru_cache`。
  - `daily_industry_heat(limit_rows: pd.DataFrame) -> pd.DataFrame`：列 `date, industry, limit_count, is_top3`。
  - `merge_industry_heat(samples: pd.DataFrame, heat: pd.DataFrame) -> pd.DataFrame`：为样本新增 `industry_limit_count, industry_is_top3`。

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_limit_up_gap_industry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.research.limit_up_gap.industry'`

- [ ] **Step 3: Write minimal implementation**

`atrade/research/limit_up_gap/industry.py`:

```python
"""行业标签与同行业涨停热度。"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
import requests


@lru_cache(maxsize=4096)
def industry_of(code: str) -> str:
    """腾讯行业接口；失败返回空字符串。"""
    code = str(code).zfill(6)
    market = "sh" + code if code.startswith(("5", "6", "7", "9")) else "sz" + code
    url = f"https://web.ifzq.gtimg.cn/appstock/app/MarketLayout?code={market}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        info = resp.json().get("data", {}).get(market, {})
        return str(info.get("industry") or info.get("hyName") or "").strip()
    except Exception:
        return ""


def daily_industry_heat(limit_rows: pd.DataFrame) -> pd.DataFrame:
    """统计每个交易日各行业的涨停家数，并标记前 3。"""
    if limit_rows.empty:
        return pd.DataFrame(columns=["date", "industry", "limit_count", "is_top3"])
    grouped = (
        limit_rows.groupby(["date", "industry"], dropna=False)
        .size()
        .rename("limit_count")
        .reset_index()
    )
    grouped["is_top3"] = (
        grouped.groupby("date")["limit_count"]
        .rank(method="first", ascending=False)
        <= 3
    )
    return grouped


def merge_industry_heat(
    samples: pd.DataFrame,
    heat: pd.DataFrame,
) -> pd.DataFrame:
    """把板块热度合并到首板样本，缺失行业按 0 处理。"""
    merged = samples.merge(heat, on=["date", "industry"], how="left")
    merged["industry_limit_count"] = merged["limit_count"].fillna(0).astype(int)
    merged["industry_is_top3"] = merged["is_top3"].fillna(False).astype(bool)
    return merged.drop(columns=["limit_count", "is_top3"], errors="ignore")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_limit_up_gap_industry.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add atrade/research/limit_up_gap/industry.py tests/test_limit_up_gap_industry.py
git commit -m "feat(research): 行业标签与板块涨停热度"
```

---

### Task 4: 统计与多因子打分

**Files:**
- Create: `atrade/research/limit_up_gap/stats.py`
- Test: `tests/test_limit_up_gap_stats.py`

**Interfaces:**
- Produces:
  - `compute_base(df) -> dict`：`n / wins / win_rate / mean_gap / median_gap`。
  - `bucket_stats(df, column, min_samples=30) -> list[BucketStat]`。
  - `rank_factors(df, factor_columns, min_samples=30) -> list[dict]`。
  - `score_by_buckets(df, best_buckets, min_samples=30) -> pd.Series`。
  - `top_vs_all(df, score, top_pct=0.2, min_samples=30) -> dict`。

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_limit_up_gap_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.research.limit_up_gap.stats'`

- [ ] **Step 3: Write minimal implementation**

`atrade/research/limit_up_gap/stats.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_limit_up_gap_stats.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add atrade/research/limit_up_gap/stats.py tests/test_limit_up_gap_stats.py
git commit -m "feat(research): 分桶统计与多因子打分"
```

---

### Task 5: 主流程与报告

**Files:**
- Create: `atrade/research/limit_up_gap/report.py`
- Create: `atrade/research/limit_up_gap/study.py`
- Test: `tests/test_limit_up_gap_report.py`

**Interfaces:**
- Consumes: `add_limit_labels`、`add_features`、`daily_industry_heat`、`merge_industry_heat`、`compute_base`、`bucket_stats`、`rank_factors`、`score_by_buckets`、`top_vs_all`。
- Produces:
  - `StudyConfig(min_gap_pct=1.0, min_samples=30, top_pct=0.2, max_symbols=0, min_bars=80, lookback_bars=515, with_zt_pool=False)`。
  - `collect_samples(codes, hp, industry_fn, config, is_trade_day=None) -> (pd.DataFrame, dict)`。
  - `run_study(codes, hp, industry_fn, config, zt_enrich=None, is_trade_day=None) -> GapStudyResult`。
  - `GapStudyResult(generated_at, base, top_pct=0.2, min_gap_pct=1.0, factor_buckets={}, ranking=[], top={}, excluded={})`。
  - `render_report(result) -> str`。

- [ ] **Step 1: Write the failing test**

```python
"""研究主流程与报告渲染测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from atrade.research.limit_up_gap.report import GapStudyResult, render_report
from atrade.research.limit_up_gap.study import StudyConfig, run_study


class _FakeHistory:
    def fetch_with_cache(self, code, scale="1d", datalen=515, use_snapshot=False):
        n = 100
        closes = np.linspace(10.0, 15.0, n)
        closes[-3] = 10.0
        closes[-2] = 11.2   # 首板涨停
        closes[-1] = 11.5   # T+1 高开
        df = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
            "open": closes * 0.99,
            "high": closes * 1.03,
            "low": closes * 0.98,
            "close": closes,
            "volume": np.full(n, 100_000),
        })
        return df


def _industry(code):
    return "半导体" if code in {"600001", "600002", "600003"} else "白酒"


def test_run_study_returns_report():
    codes = ["600001", "600002", "600003", "000001"]
    result = run_study(
        codes,
        _FakeHistory(),
        _industry,
        StudyConfig(min_samples=2, lookback_bars=100),
    )
    md = render_report(result)
    assert "# 首板次日高开研究" in md
    assert "样本" in md
    assert "industry_limit_count" in md or "胜率" in md


def test_render_report_handles_empty():
    result = GapStudyResult(
        generated_at="2026-08-03 15:00:00",
        base={"n": 0, "wins": 0, "win_rate": 0.0, "mean_gap": 0.0, "median_gap": 0.0},
        top_pct=0.2,
        min_gap_pct=1.0,
        factor_buckets={},
        ranking=[],
        top={"top_pct": 0.2, "n": 0, "win_rate": 0.0, "mean_gap": 0.0, "lift": 0.0},
        excluded={"yiziban": 0, "no_next_open": 0, "first_board": 0, "lianban": 0},
    )
    md = render_report(result)
    assert "样本不足" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_limit_up_gap_report.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.research.limit_up_gap.study'`

- [ ] **Step 3: Write minimal implementation**

`atrade/research/limit_up_gap/report.py`:

```python
"""首板研究结果 Markdown 渲染。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .stats import BucketStat


@dataclass
class GapStudyResult:
    generated_at: str
    base: dict
    top_pct: float = 0.2
    min_gap_pct: float = 1.0
    factor_buckets: dict[str, list[BucketStat]] = field(default_factory=dict)
    ranking: list[dict] = field(default_factory=list)
    top: dict = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)


def render_report(result: GapStudyResult) -> str:
    base = result.base
    lines = [
        "# 首板次日高开研究",
        f"_{result.generated_at}_",
        "",
        f"总样本：**{base['n']}** 个首板，胜率 **{base['win_rate']:.1%}**，"
        f"平均高开 **{base['mean_gap']:.2f}%**，中位高开 **{base['median_gap']:.2f}%**",
        "",
        f"排除口径：一字板 {result.excluded.get('yiziban', 0)}、"
        f"无 T+1 数据 {result.excluded.get('no_next_open', 0)}、"
        f"连板 {result.excluded.get('lianban', 0)}、"
        f"全部首板 {result.excluded.get('first_board', 0)}",
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
        f"- Top {top['n']} 只：胜率 **{top['win_rate']:.1%}**，"
        f"平均高开 **{top['mean_gap']:.2f}%**，相对基线提升 **{top['lift']:+.1%}**",
        "",
        "## 特征分桶明细",
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
        f"_口径：T 日收盘买入，T+1 开盘卖出，"
        f"高开 ≥{result.min_gap_pct:g}% 算胜；一字板已排除。_"
    )
    return "\n".join(lines)
```

`atrade/research/limit_up_gap/study.py`:

```python
"""首板次日高开研究主流程。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

from .features import add_features, daily_industry_heat, merge_industry_heat
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_limit_up_gap_report.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add atrade/research/limit_up_gap/report.py atrade/research/limit_up_gap/study.py tests/test_limit_up_gap_report.py
git commit -m "feat(research): 首板研究主流程与报告"
```

---

### Task 6: 涨停池可选增强

**Files:**
- Create: `atrade/research/limit_up_gap/ztpool.py`
- Test: `tests/test_limit_up_gap_ztpool.py`

**Interfaces:**
- Produces:
  - `ZT_FACTOR_COLUMNS = ["zt_turnover", "zt_float_mv_yi", "zt_break_count", "zt_seal_amount_yi"]`
  - `fetch_zt_day(date: str) -> pd.DataFrame | None`
  - `enrich_samples(samples: pd.DataFrame, fetch_day=None) -> pd.DataFrame`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_limit_up_gap_ztpool.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.research.limit_up_gap.ztpool'`

- [ ] **Step 3: Write minimal implementation**

`atrade/research/limit_up_gap/ztpool.py`:

```python
"""东财涨停池历史增强（可选）。

默认不启用；`--with-zt-pool` 打开后，按日期拉取涨停池，补充换手率、
流通市值、炸板次数、封单资金。接口不可用/失败时原样返回。
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional

import pandas as pd

ZT_COLUMN_MAP = {
    "代码": "code",
    "换手率": "zt_turnover",
    "流通市值": "zt_float_mv_yi",
    "炸板次数": "zt_break_count",
    "封单资金": "zt_seal_amount_yi",
}
ZT_FACTOR_COLUMNS = [
    "zt_turnover",
    "zt_float_mv_yi",
    "zt_break_count",
    "zt_seal_amount_yi",
]


def fetch_zt_day(date: str) -> Optional[pd.DataFrame]:
    """拉取某交易日涨停池；失败返回 None。"""
    try:
        import akshare as ak

        compact = datetime.strptime(date, "%Y-%m-%d").strftime("%Y%m%d")
        df = ak.stock_zt_pool_em(date=compact)
        if df is None or df.empty:
            return None
        return df
    except Exception:
        return None


def enrich_samples(
    samples: pd.DataFrame,
    fetch_day: Optional[Callable[[str], Optional[pd.DataFrame]]] = None,
) -> pd.DataFrame:
    """按 date+code 合并涨停池字段；缺失值保留 NA。"""
    if samples.empty:
        return samples
    fetch_day = fetch_day or fetch_zt_day
    pieces: list[pd.DataFrame] = []
    for date in sorted(samples["date"].unique()):
        day = samples[samples["date"] == date].copy()
        zt = fetch_day(date)
        if zt is None or zt.empty:
            for col in ZT_FACTOR_COLUMNS:
                day[col] = pd.NA
            pieces.append(day)
            continue
        zt = zt.rename(columns=ZT_COLUMN_MAP).copy()
        zt["code"] = zt["code"].astype(str).str.zfill(6)
        zt = zt.drop_duplicates("code")
        merge_cols = [col for col in ZT_FACTOR_COLUMNS if col in zt.columns]
        day = day.merge(zt[["code"] + merge_cols], on="code", how="left")
        if "zt_float_mv_yi" in day.columns:
            day["zt_float_mv_yi"] = day["zt_float_mv_yi"] / 1e8
        if "zt_seal_amount_yi" in day.columns:
            day["zt_seal_amount_yi"] = day["zt_seal_amount_yi"] / 1e8
        for col in ZT_FACTOR_COLUMNS:
            if col not in day.columns:
                day[col] = pd.NA
        pieces.append(day)
    return pd.concat(pieces, ignore_index=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_limit_up_gap_ztpool.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add atrade/research/limit_up_gap/ztpool.py tests/test_limit_up_gap_ztpool.py
git commit -m "feat(research): 涨停池历史可选增强"
```

---

### Task 7: CLI 与端到端冒烟

**Files:**
- Create: `scripts/run_gap_study.py`
- Test: `tests/test_run_gap_study.py`

**Interfaces:**
- Consumes: `run_study`、`render_report`、`StudyConfig`、`industry_of`、`ztpool.enrich_samples`。
- Produces: `scripts/run_gap_study.py`，命令 `python3 scripts/run_gap_study.py --days 365 --min-samples 30 --min-gap 1.0`。

- [ ] **Step 1: Write the failing test**

```python
"""CLI 端到端冒烟测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_cli_writes_report(tmp_path, monkeypatch):
    import scripts.run_gap_study as cli

    monkeypatch.setattr(cli, "MAIN_BOARD_PREFIXES", ("600",))

    def fake_codes():
        return pd.DataFrame({
            "code": ["600001", "600002"],
            "name": ["测试A", "测试B"],
        })

    monkeypatch.setattr(cli.ak, "stock_info_a_code_name", fake_codes)

    class FakeHistory:
        def fetch_with_cache(self, code, scale="1d", datalen=515, use_snapshot=False):
            import numpy as np
            n = 100
            closes = np.linspace(10.0, 15.0, n)
            closes[-3] = 10.0
            closes[-2] = 11.2
            closes[-1] = 11.5
            return pd.DataFrame({
                "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
                "open": closes * 0.99,
                "high": closes * 1.03,
                "low": closes * 0.98,
                "close": closes,
                "volume": np.full(n, 100_000),
            })

    monkeypatch.setattr(cli, "HistoryProvider", lambda: FakeHistory())
    monkeypatch.setattr(cli, "industry_of", lambda code: "半导体")
    out = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_gap_study.py",
            "--min-samples", "2",
            "--lookback-bars", "100",
            "--out", str(out),
        ],
    )
    cli.main()
    assert out.exists()
    assert "# 首板次日高开研究" in out.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_gap_study.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.run_gap_study'`

- [ ] **Step 3: Write minimal implementation**

`scripts/run_gap_study.py`:

```python
"""首板次日高开研究 CLI。

用法:
    python3 scripts/run_gap_study.py
    python3 scripts/run_gap_study.py --days 365 --min-samples 30 --min-gap 1.0
    python3 scripts/run_gap_study.py --max-symbols 50 --out /tmp/gap_study.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import akshare as ak

from atrade.data import HistoryProvider
from atrade.monitor import TradingCalendar
from atrade.research.limit_up_gap.industry import industry_of
from atrade.research.limit_up_gap.report import render_report
from atrade.research.limit_up_gap.study import StudyConfig, run_study
from atrade.research.limit_up_gap import ztpool

MAIN_BOARD_PREFIXES = ("000", "001", "002", "600", "601", "603", "605")


def _codes() -> list[str]:
    df = ak.stock_info_a_code_name()
    out: list[str] = []
    for code, name in zip(df["code"], df["name"]):
        code = str(code).zfill(6)
        upper_name = str(name).upper()
        if (
            code.startswith(MAIN_BOARD_PREFIXES)
            and "ST" not in upper_name
            and "退" not in upper_name
        ):
            out.append(code)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="首板次日高开研究")
    parser.add_argument("--days", type=int, default=365, help="研究天数，默认 365")
    parser.add_argument("--min-samples", type=int, default=30, help="分桶最小样本数")
    parser.add_argument("--min-gap", type=float, default=1.0, help="高开算胜的最小百分比")
    parser.add_argument("--top-pct", type=float, default=0.2, help="多因子 Top 比例")
    parser.add_argument("--max-symbols", type=int, default=0, help="只跑前 N 只（0=全部）")
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=0,
        help="拉取日线条数，默认 days+150",
    )
    parser.add_argument(
        "--with-zt-pool",
        action="store_true",
        help="启用东财涨停池历史增强",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / f"gap_study_{datetime.now().strftime('%Y%m%d')}.md",
    )
    args = parser.parse_args()

    codes = _codes()
    print(f"股票池: {len(codes)} 只")
    config = StudyConfig(
        min_gap_pct=args.min_gap,
        min_samples=args.min_samples,
        top_pct=args.top_pct,
        max_symbols=args.max_symbols,
        lookback_bars=args.lookback_bars or args.days + 150,
        with_zt_pool=args.with_zt_pool,
    )
    zt_enrich = ztpool.enrich_samples if args.with_zt_pool else None
    result = run_study(
        codes,
        HistoryProvider(),
        industry_of,
        config,
        zt_enrich=zt_enrich,
        is_trade_day=TradingCalendar().is_trade_day,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_report(result), encoding="utf-8")
    print(f"报告已写入: {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_run_gap_study.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: Run ruff**

Run: `.venv/bin/python -m ruff check atrade/research scripts/run_gap_study.py tests/test_limit_up_gap_*.py tests/test_run_gap_study.py`
Expected: All checks passed

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 全部通过（1 skipped 为真实钉钉推送用例）

- [ ] **Step 7: Commit**

```bash
git add scripts/run_gap_study.py tests/test_run_gap_study.py
git commit -m "feat(research): 首板次日高开研究 CLI"
```

---

## Post-Implementation

- 在真实环境跑一次全市场研究：`python3 scripts/run_gap_study.py --days 365 --min-samples 30 --min-gap 1.0`。
- 把报告结论整理成下一步“每日首板候选”功能的设计输入。
