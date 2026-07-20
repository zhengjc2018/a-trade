# 个股做 T 策略报告 CLI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `scripts/run_per_symbol_report.py`，按需为每只持仓生成包含波动性、做 T 适配度、风险指标的本地 Markdown 报告，样例股票为中天科技（600522）。

**Architecture:** 新增 `atrade/per_symbol/` 包（volatility / adaptive / risk / styler / report 五个独立模块），复用 `HistoryProvider.fetch_with_cache` 拉取日线和 5/15/30/60 分钟线，复用 `SignalEngine.scan` 仅做因子命中统计。CLI 不推送 QQ 群，纯本地落盘到 `reports/`。

**Tech Stack:** Python 3.9+、pandas、numpy、pytest、loguru（沿用现有依赖）

## Global Constraints

- Python 版本下限：3.9
- 样例股票：`600522`（中天科技），成本 `12.50`，数量 `2000`
- 数据范围：252 个日线 + 最近 30 个交易日的 5/15/30/60 分钟线
- 不修改现有业务模块的对外 API 与现有测试
- 不联网写消息、不修改 `data/cache/stock.db` 既有字段
- 不引入新依赖（pandas/numpy/loguru/pytest 已就位）
- 所有函数输入为 `pd.DataFrame` 或纯量，输出为 `dict` / 标量，可纯函数测试

---

### Task 1: 包骨架与接口定义

**Files:**
- Create: `atrade/per_symbol/__init__.py`
- Create: `atrade/per_symbol/volatility.py`
- Create: `atrade/per_symbol/adaptive.py`
- Create: `atrade/per_symbol/risk.py`
- Create: `atrade/per_symbol/styler.py`
- Create: `atrade/per_symbol/report.py`
- Create: `tests/test_per_symbol_init.py`

**Interfaces:**
- Consumes: 无
- Produces: 5 个空模块 + `atrade.per_symbol.report.SymbolReport` dataclass

- [ ] **Step 1: 写失败测试**

```python
# tests/test_per_symbol_init.py
from dataclasses import is_dataclass
from atrade.per_symbol.report import SymbolReport


def test_symbol_report_is_dataclass():
    assert is_dataclass(SymbolReport)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_per_symbol_init.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'atrade.per_symbol'`

- [ ] **Step 3: 实现最小代码**

```python
# atrade/per_symbol/__init__.py
"""个股做 T 策略报告模块。"""
```

```python
# atrade/per_symbol/volatility.py
"""波动性指标。"""
```

```python
# atrade/per_symbol/adaptive.py
"""做 T 适配度与因子命中统计。"""
```

```python
# atrade/per_symbol/risk.py
"""风险指标。"""
```

```python
# atrade/per_symbol/styler.py
"""风格归类与总结。"""
```

```python
# atrade/per_symbol/report.py
"""汇总生成 SymbolReport。"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SymbolReport:
    symbol: str
    name: str
    cost_price: float
    quantity: int
    lookback_days: int
    intraday_days: int
    generated_at: str
    volatility: dict
    adaptive: dict
    risk: dict
    style: str
    summary: str
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_per_symbol_init.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add atrade/per_symbol tests/test_per_symbol_init.py
git commit -m "feat(per_symbol): scaffold package and SymbolReport"
```

---

### Task 2: 波动性指标

**Files:**
- Modify: `atrade/per_symbol/volatility.py`
- Create: `tests/test_volatility.py`

**Interfaces:**
- Consumes: 日线 `pd.DataFrame`，列含 `date/open/high/low/close/volume`
- Produces: `compute_volatility(df: pd.DataFrame) -> dict`，字段含 `daily_amp_p50/p90/max`、`atr_14_pct`、`gap_abs_mean`、`gap_abs_gt2_pct`、`vol_zscore_60`、`streak_max_up`、`streak_max_down`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_volatility.py
import numpy as np
import pandas as pd
import pytest
from atrade.per_symbol.volatility import compute_volatility


def make_df(n=300):
    np.random.seed(0)
    close = 10 + np.cumsum(np.random.normal(0, 0.1, n))
    high = close * 1.01
    low = close * 0.99
    open_ = close + np.random.normal(0, 0.05, n)
    volume = np.random.randint(100000, 200000, n)
    date = pd.date_range("2025-06-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "date": date, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_compute_volatility_returns_required_keys():
    out = compute_volatility(make_df())
    for k in ("daily_amp_p50", "daily_amp_p90", "daily_amp_max",
              "atr_14_pct", "gap_abs_mean", "gap_abs_gt2_pct",
              "vol_zscore_60", "streak_max_up", "streak_max_down"):
        assert k in out, k


def test_compute_volatility_atr_in_range():
    out = compute_volatility(make_df())
    assert 0 < out["atr_14_pct"] < 20


def test_compute_volatility_rejects_short_df():
    df = make_df(10)
    with pytest.raises(ValueError):
        compute_volatility(df)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_volatility.py -v`
Expected: FAIL with `ImportError` / `AttributeError`

- [ ] **Step 3: 实现 compute_volatility**

```python
# atrade/per_symbol/volatility.py
"""波动性指标。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_volatility(df: pd.DataFrame) -> dict:
    """计算波动性特征。

    输入 df 必须含 open/high/low/close/volume，至少 60 行。
    """
    if df is None or len(df) < 60:
        raise ValueError("日线数据不足 60 行")
    out = df.sort_values("date").reset_index(drop=True)

    high = out["high"].astype(float)
    low = out["low"].astype(float)
    close = out["close"].astype(float)
    pre_close = close.shift(1)

    amp = (high - low) / pre_close * 100
    amp = amp.dropna()

    # ATR-14：以 (high-low)、abs(high-pre_close)、abs(low-pre_close) 最大值平均
    tr = pd.concat([
        (high - low),
        (high - pre_close).abs(),
        (low - pre_close).abs(),
    ], axis=1).max(axis=1)
    atr14 = tr.rolling(14, min_periods=14).mean().iloc[-1]
    atr14_pct = float(atr14 / close.iloc[-1] * 100)

    # 跳空 = open / pre_close - 1
    gap = (out["open"].astype(float) / pre_close - 1).dropna() * 100
    gap_abs = gap.abs()
    gap_abs_mean = float(gap_abs.mean())
    gap_abs_gt2_pct = float((gap_abs > 2).mean() * 100)

    # 量 z-score（60 日）
    vol = out["volume"].astype(float)
    vol_ma = vol.rolling(60, min_periods=20).mean()
    vol_std = vol.rolling(60, min_periods=20).std()
    vol_z = ((vol - vol_ma) / vol_std).dropna()
    vol_zscore_60 = float(vol_z.iloc[-1]) if len(vol_z) else 0.0

    # 连续涨跌
    pct = close.pct_change().fillna(0)
    up = (pct > 0).astype(int)
    down = (pct < 0).astype(int)
    streak_max_up = int(_max_run(up))
    streak_max_down = int(_max_run(down))

    return {
        "daily_amp_p50": float(np.percentile(amp, 50)),
        "daily_amp_p90": float(np.percentile(amp, 90)),
        "daily_amp_max": float(amp.max()),
        "atr_14_pct": round(atr14_pct, 3),
        "gap_abs_mean": round(gap_abs_mean, 3),
        "gap_abs_gt2_pct": round(gap_abs_gt2_pct, 3),
        "vol_zscore_60": round(vol_zscore_60, 3),
        "streak_max_up": streak_max_up,
        "streak_max_down": streak_max_down,
    }


def _max_run(series: pd.Series) -> int:
    max_run = run = 0
    for v in series:
        if v == 1:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_volatility.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add atrade/per_symbol/volatility.py tests/test_volatility.py
git commit -m "feat(per_symbol): add volatility indicators"
```

---

### Task 3: 风险指标

**Files:**
- Modify: `atrade/per_symbol/risk.py`
- Create: `tests/test_risk.py`

**Interfaces:**
- Consumes: 日线 `pd.DataFrame`
- Produces: `compute_risk(df: pd.DataFrame) -> dict`，字段含 `annual_vol_pct`、`max_drawdown_1y_pct`、`monthly_max_dd_pct`、`loss_streak_max`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_risk.py
import numpy as np
import pandas as pd
import pytest
from atrade.per_symbol.risk import compute_risk


def make_df(n=300):
    np.random.seed(1)
    close = 10 + np.cumsum(np.random.normal(0, 0.1, n))
    return pd.DataFrame({
        "date": pd.date_range("2025-06-01", periods=n, freq="B").strftime("%Y-%m-%d"),
        "open": close, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": np.random.randint(100000, 200000, n),
    })


def test_compute_risk_keys():
    out = compute_risk(make_df())
    for k in ("annual_vol_pct", "max_drawdown_1y_pct",
              "monthly_max_dd_pct", "loss_streak_max"):
        assert k in out


def test_compute_risk_rejects_short_df():
    with pytest.raises(ValueError):
        compute_risk(make_df(10))


def test_compute_risk_values_reasonable():
    out = compute_risk(make_df())
    assert 0 < out["annual_vol_pct"] < 200
    assert out["max_drawdown_1y_pct"] <= 0
    assert out["monthly_max_dd_pct"] <= 0
    assert out["loss_streak_max"] >= 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_risk.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 实现 compute_risk**

```python
# atrade/per_symbol/risk.py
"""风险指标。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_risk(df: pd.DataFrame) -> dict:
    """计算风险指标。"""
    if df is None or len(df) < 60:
        raise ValueError("日线数据不足 60 行")
    out = df.sort_values("date").reset_index(drop=True)
    close = out["close"].astype(float)
    pct = close.pct_change().dropna()

    annual_vol = float(pct.std() * np.sqrt(252) * 100)

    # 1y 最大回撤（最近 252 个交易日）
    tail = close.tail(252)
    dd = _drawdown_series(tail)
    max_dd_1y = float(dd.min() * 100)

    # 月度最大回撤（按月分桶）
    monthly_max_dd = _monthly_max_drawdown(tail)

    # 连续亏损天数（pct < 0 连续次数）
    loss_streak = int(_max_run((pct < 0).astype(int)))

    return {
        "annual_vol_pct": round(annual_vol, 3),
        "max_drawdown_1y_pct": round(max_dd_1y, 3),
        "monthly_max_dd_pct": round(monthly_max_dd, 3),
        "loss_streak_max": loss_streak,
    }


def _drawdown_series(close: pd.Series) -> pd.Series:
    peak = close.cummax()
    return close / peak - 1


def _monthly_max_drawdown(close: pd.Series) -> float:
    df = close.to_frame("close")
    df["month"] = df.index.to_period("M") if isinstance(df.index, pd.DatetimeIndex) else (
        pd.to_datetime(df["date"]).dt.to_period("M") if "date" in df.columns else None
    )
    if df["month"].isna().all():
        return 0.0
    worst = 0.0
    for _, sub in df.groupby("month"):
        dd = _drawdown_series(sub["close"]).min()
        if pd.notna(dd):
            worst = min(worst, float(dd))
    return worst * 100


def _max_run(series: pd.Series) -> int:
    max_run = run = 0
    for v in series:
        if v == 1:
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return max_run
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_risk.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add atrade/per_symbol/risk.py tests/test_risk.py
git commit -m "feat(per_symbol): add risk indicators"
```

---

### Task 4: 适配度与因子命中统计

**Files:**
- Modify: `atrade/per_symbol/adaptive.py`
- Create: `tests/test_adaptive.py`

**Interfaces:**
- Consumes: 5 分钟 K 线 DataFrame（至少 60 行）；可选 `signal_engine` 与 `factor_fn` 用于测试
- Produces: `compute_adaptive(intraday_df, signals_factory=None) -> dict`，字段含 `intra_amp_p50/p90`、`hold_minutes_p90`、`factor_score`、`preferred_factors`、`position_pct`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_adaptive.py
import numpy as np
import pandas as pd
from atrade.per_symbol.adaptive import compute_adaptive


def make_5m(n=240):
    np.random.seed(2)
    close = 10 + np.cumsum(np.random.normal(0, 0.05, n))
    high = close * 1.005
    low = close * 0.995
    open_ = close + np.random.normal(0, 0.02, n)
    volume = np.random.randint(1000, 5000, n)
    idx = pd.date_range("2026-07-01 09:30", periods=n, freq="5min")
    return pd.DataFrame({
        "date": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_compute_adaptive_keys():
    out = compute_adaptive(make_5m(), signals_factory=lambda df: [])
    for k in ("intra_amp_p50", "intra_amp_p90", "hold_minutes_p90",
              "factor_score", "preferred_factors", "position_pct"):
        assert k in out


def test_compute_adaptive_position_in_range():
    out = compute_adaptive(make_5m(), signals_factory=lambda df: [])
    assert 0.1 <= out["position_pct"] <= 0.5


def test_compute_adaptive_preferred_factors_max_two():
    out = compute_adaptive(make_5m(), signals_factory=lambda df: [])
    assert len(out["preferred_factors"]) <= 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_adaptive.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 实现 compute_adaptive**

```python
# atrade/per_symbol/adaptive.py
"""做 T 适配度与因子命中统计。"""
from __future__ import annotations

from collections import Counter
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd


FACTORS = ("波段反弹", "趋势确认", "放量突破", "超卖反弹")


def _classify(signal) -> Optional[str]:
    """从 Signal 对象的 factor_hits / name 推断命中的因子名。"""
    if signal is None:
        return None
    hits = getattr(signal, "factor_hits", None) or []
    if hits:
        return hits[0]
    name = getattr(signal, "name", "")
    for f in FACTORS:
        if f in name:
            return f
    return None


def compute_adaptive(
    intraday_df: pd.DataFrame,
    signals_factory: Optional[Callable[[pd.DataFrame], Iterable]] = None,
    interval_minutes: int = 5,
) -> dict:
    """日内做 T 适配度。

    intraday_df：5 分钟 K 线，至少 60 行。
    signals_factory：接受 DataFrame 返回 Iterable[Signal]，用于测试隔离。
    """
    if intraday_df is None or len(intraday_df) < 60:
        raise ValueError("分钟线数据不足 60 行")
    df = intraday_df.sort_values("date").reset_index(drop=True)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    pre_close = df["close"].shift(1)
    amp = ((high - low) / pre_close * 100).dropna()

    # 振幅恢复 90% 的时间：以日内最大回撤为基准，找到回升至 90% 的最短时间
    close = df["close"].astype(float)
    hold_min = _hold_minutes_p90(close, interval_minutes=interval_minutes)

    # 因子命中统计
    counter: Counter[str] = Counter()
    if signals_factory is not None:
        try:
            signals_iter = signals_factory(df)
        except Exception:
            signals_iter = []
        for sig in signals_iter:
            tag = _classify(sig)
            if tag:
                counter[tag] += 1
    else:
        # 默认路径：尝试复用现有 SignalEngine
        try:
            from atrade.signals import SignalEngine  # 延迟导入，便于测试
            engine = SignalEngine()
            for i in range(60, len(df) + 1):
                sub = df.iloc[:i]
                try:
                    signals = engine.scan("000000", sub)
                except Exception:
                    continue
                for sig in signals:
                    tag = _classify(sig)
                    if tag:
                        counter[tag] += 1
        except Exception:
            counter = Counter()

    factor_score = {f: int(counter.get(f, 0)) for f in FACTORS}
    preferred = [f for f, _ in sorted(counter.items(), key=lambda kv: -kv[1])[:2]]

    # 仓位建议：以日内振幅 P50 决定
    p50 = float(np.percentile(amp, 50))
    if p50 < 0.5:
        position_pct = 0.1
    elif p50 > 2.0:
        position_pct = 0.5
    else:
        # 0.5%-2% 区间线性映射到 0.1-0.5
        position_pct = round(0.1 + (p50 - 0.5) / 1.5 * 0.4, 3)
    position_pct = max(0.1, min(0.5, position_pct))

    return {
        "intra_amp_p50": round(float(np.percentile(amp, 50)), 3),
        "intra_amp_p90": round(float(np.percentile(amp, 90)), 3),
        "hold_minutes_p90": hold_min,
        "factor_score": factor_score,
        "preferred_factors": preferred,
        "position_pct": position_pct,
    }


def _hold_minutes_p90(close: pd.Series, interval_minutes: int) -> int:
    """振幅恢复 90% 所需的最短时间。"""
    if len(close) < 2:
        return 0
    mn = close.cummin()
    mx = close.cummax()
    spread = mx - mn
    peak_idx = int(spread.idxmax())
    peak_value = spread.iloc[peak_idx]
    if peak_value <= 0:
        return 0
    target = peak_value * (1 - 0.9)  # 振幅恢复 90% = spread 收缩至 10%
    for i in range(peak_idx, len(close)):
        if spread.iloc[i] <= target:
            return int((i - peak_idx) * interval_minutes)
    return int((len(close) - 1 - peak_idx) * interval_minutes)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_adaptive.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add atrade/per_symbol/adaptive.py tests/test_adaptive.py
git commit -m "feat(per_symbol): add adaptive scoring and factor stats"
```

---

### Task 5: 风格归类与总结

**Files:**
- Modify: `atrade/per_symbol/styler.py`
- Create: `tests/test_styler.py`

**Interfaces:**
- Consumes: 波动性 dict、风险 dict、适配度 dict
- Produces: `classify_style(volatility, risk, adaptive) -> str`、`summarize(symbol, style, vol, risk, adaptive) -> str`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_styler.py
from atrade.per_symbol.styler import classify_style, summarize


def base_vol(atr=2.0, gap=0.4, p90=3.0):
    return {"atr_14_pct": atr, "gap_abs_mean": gap, "daily_amp_p90": p90}


def test_classify_style_low_vol():
    assert classify_style(base_vol(atr=1.0, gap=0.3, p90=1.5), {}, {}) == "low_vol"


def test_classify_style_high_vol():
    assert classify_style(base_vol(atr=5.0, gap=0.8, p90=7.0), {}, {}) == "high_vol"


def test_classify_style_default_range():
    assert classify_style(base_vol(atr=2.0, gap=0.4, p90=3.0), {}, {}) == "range"


def test_summarize_includes_factors():
    out = summarize(
        "中天科技", "range",
        base_vol(atr=2.6, gap=0.58, p90=3.9),
        {"monthly_max_dd_pct": -9.1, "annual_vol_pct": 28.7},
        {"preferred_factors": ["波段反弹", "趋势确认"], "position_pct": 0.25},
    )
    assert "中天科技" in out
    assert "波段反弹" in out
    assert "趋势确认" in out
    assert "25%" in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_styler.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: 实现 classify_style 与 summarize**

```python
# atrade/per_symbol/styler.py
"""风格归类与自然语言总结。"""
from __future__ import annotations


def classify_style(volatility: dict, risk: dict, adaptive: dict) -> str:
    """根据波动性、风险、适配度指标把股票归为四种风格之一。"""
    atr = volatility.get("atr_14_pct", 0.0)
    gap_abs = volatility.get("gap_abs_mean", 0.0)
    p90 = volatility.get("daily_amp_p90", 0.0)

    if atr < 1.5 and gap_abs < 0.5:
        return "low_vol"
    if atr > 4.0 or p90 > 6.0:
        return "high_vol"
    # trend 由后续报告层判断（依赖均线斜率）
    return "range"


def summarize(symbol: str, style: str, volatility: dict, risk: dict, adaptive: dict) -> str:
    factors = adaptive.get("preferred_factors") or []
    factor_phrase = "、".join(factors) if factors else "通用"
    pos_pct = adaptive.get("position_pct", 0.0)
    monthly_dd = risk.get("monthly_max_dd_pct", 0.0)
    atr = volatility.get("atr_14_pct", 0.0)
    p50 = adaptive.get("intra_amp_p50", 0.0)
    return (
        f"{symbol}属于 {style} 风格，14 日 ATR {atr:.2f}%，日内振幅中位数 {p50:.2f}%。"
        f"建议关注 {factor_phrase} 因子，单笔仓位不超过 {int(pos_pct*100)}%，"
        f"最大月度回撤约 {abs(monthly_dd):.1f}%。"
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_styler.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add atrade/per_symbol/styler.py tests/test_styler.py
git commit -m "feat(per_symbol): add style classification and summary"
```

---

### Task 6: 报告汇总

**Files:**
- Modify: `atrade/per_symbol/report.py`
- Create: `tests/test_report.py`

**Interfaces:**
- Consumes: 标的、波动性、风险、适配度、风格、总结
- Produces: `build_report(symbol, name, cost, qty, volatility, risk, adaptive, style, summary) -> SymbolReport`、`render_markdown(report: SymbolReport) -> str`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report.py
from atrade.per_symbol.report import build_report, render_markdown


def test_build_report_returns_symbol_report():
    rep = build_report(
        symbol="600522", name="中天科技", cost_price=12.5, quantity=2000,
        volatility={"atr_14_pct": 2.6}, risk={"annual_vol_pct": 28.7},
        adaptive={"intra_amp_p50": 2.3, "preferred_factors": ["波段反弹"], "position_pct": 0.25},
        style="range", summary="ok",
    )
    assert rep.symbol == "600522"
    assert rep.style == "range"


def test_render_markdown_contains_sections():
    rep = build_report(
        symbol="600522", name="中天科技", cost_price=12.5, quantity=2000,
        volatility={"daily_amp_p50": 2.3, "daily_amp_p90": 3.9, "daily_amp_max": 5.2,
                    "atr_14_pct": 2.6, "gap_abs_mean": 0.58, "gap_abs_gt2_pct": 5.8,
                    "vol_zscore_60": 0.4, "streak_max_up": 4, "streak_max_down": 5},
        risk={"annual_vol_pct": 28.7, "max_drawdown_1y_pct": -18.3,
              "monthly_max_dd_pct": -9.1, "loss_streak_max": 5},
        adaptive={"intra_amp_p50": 2.3, "intra_amp_p90": 3.9,
                  "hold_minutes_p90": 30,
                  "factor_score": {"波段反弹": 9, "趋势确认": 6, "放量突破": 2, "超卖反弹": 3},
                  "preferred_factors": ["波段反弹", "趋势确认"], "position_pct": 0.25},
        style="range",
        summary="中天科技属于 range 风格",
    )
    md = render_markdown(rep)
    for section in ("# 中天科技", "## 1. 风格归类", "## 2. 波动性",
                    "## 3. 做 T 适配度", "## 4. 风险指标", "## 5. 自然语言总结"):
        assert section in md, section
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 build_report 与 render_markdown**

```python
# atrade/per_symbol/report.py
"""汇总生成 SymbolReport 并渲染 Markdown。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SymbolReport:
    symbol: str
    name: str
    cost_price: float
    quantity: int
    lookback_days: int
    intraday_days: int
    generated_at: str
    volatility: dict
    adaptive: dict
    risk: dict
    style: str
    summary: str


def build_report(
    symbol: str,
    name: str,
    cost_price: float,
    quantity: int,
    volatility: dict,
    risk: dict,
    adaptive: dict,
    style: str,
    summary: str,
    lookback_days: int = 252,
    intraday_days: int = 30,
    generated_at: Optional[str] = None,
) -> SymbolReport:
    return SymbolReport(
        symbol=symbol,
        name=name,
        cost_price=cost_price,
        quantity=quantity,
        lookback_days=lookback_days,
        intraday_days=intraday_days,
        generated_at=generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        volatility=volatility,
        adaptive=adaptive,
        risk=risk,
        style=style,
        summary=summary,
    )


def render_markdown(report: SymbolReport) -> str:
    v = report.volatility
    r = report.risk
    a = report.adaptive
    lines = [
        f"# {report.name} ({report.symbol}) 做 T 策略报告",
        "",
        f"- 成本价：{report.cost_price:.2f} / 数量：{report.quantity}",
        f"- 报告时间：{report.generated_at}",
        f"- 数据范围：{report.lookback_days} 个日线 + {report.intraday_days} 个交易日的 5/15/30/60 分钟线",
        "",
        "## 1. 风格归类",
        "",
        report.style,
        "",
        "## 2. 波动性",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 日内振幅 P50 | {v.get('daily_amp_p50', 0):.2f}% |",
        f"| 日内振幅 P90 | {v.get('daily_amp_p90', 0):.2f}% |",
        f"| 日内振幅 Max | {v.get('daily_amp_max', 0):.2f}% |",
        f"| 14 日 ATR | {v.get('atr_14_pct', 0):.2f}% |",
        f"| 跳空绝对均值 | {v.get('gap_abs_mean', 0):.2f}% |",
        f"| 跳空 >2% 概率 | {v.get('gap_abs_gt2_pct', 0):.2f}% |",
        f"| 量比 z-score（60 日） | {v.get('vol_zscore_60', 0):.2f} |",
        f"| 最大连涨天数 | {v.get('streak_max_up', 0)} |",
        f"| 最大连跌天数 | {v.get('streak_max_down', 0)} |",
        "",
        "## 3. 做 T 适配度",
        "",
        "| 项目 | 建议 |",
        "|---|---|",
        f"| 最佳单笔持仓时长 | {a.get('hold_minutes_p90', 0)} 分钟 |",
        f"| 建议单笔仓位 | {int((a.get('position_pct', 0)) * 100)}% |",
        f"| 首选因子 | {'、'.join(a.get('preferred_factors', [])) or '通用'} |",
        "",
        "因子命中（5 分钟粒度）：",
    ]
    score = a.get("factor_score") or {}
    if score:
        for f, n in score.items():
            lines.append(f"- {f}：{n}")
    else:
        lines.append("- 无命中样本")
    lines.extend([
        "",
        "## 4. 风险指标",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 年化波动 | {r.get('annual_vol_pct', 0):.2f}% |",
        f"| 单年最大回撤 | {r.get('max_drawdown_1y_pct', 0):.2f}% |",
        f"| 月度最大回撤 | {r.get('monthly_max_dd_pct', 0):.2f}% |",
        f"| 最大连亏天数 | {r.get('loss_streak_max', 0)} |",
        "",
        "## 5. 自然语言总结",
        "",
        report.summary,
        "",
    ])
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add atrade/per_symbol/report.py tests/test_report.py
git commit -m "feat(per_symbol): add report builder and markdown renderer"
```

---

### Task 7: CLI 入口与持仓集成

**Files:**
- Create: `scripts/run_per_symbol_report.py`
- Create: `tests/test_run_per_symbol_report.py`

**Interfaces:**
- Consumes: 命令行参数 (`--symbol/--cost/--qty/--portfolio/--scale/--intraday-days`)
- Produces: 落盘到 `reports/per_symbol_<symbol>_<timestamp>.md`，并打印到 stdout

- [ ] **Step 1: 写失败测试**

```python
# tests/test_run_per_symbol_report.py
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_per_symbol_report  # noqa: E402


class FakeProvider:
    def __init__(self, daily, intraday):
        self.daily = daily
        self.intraday = intraday

    def fetch_with_cache(self, symbol, scale, datalen, use_snapshot=False):
        return self.daily if scale == "1d" else self.intraday


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    daily = pd.DataFrame({
        "date": pd.date_range("2025-06-01", periods=120, freq="B").strftime("%Y-%m-%d"),
        "open": [10 + i * 0.01 for i in range(120)],
        "high": [10 + i * 0.01 + 0.1 for i in range(120)],
        "low": [10 + i * 0.01 - 0.1 for i in range(120)],
        "close": [10 + i * 0.01 for i in range(120)],
        "volume": [100000] * 120,
    })
    intraday = pd.DataFrame({
        "date": pd.date_range("2026-07-01 09:30", periods=240, freq="5min").strftime("%Y-%m-%d %H:%M:%S"),
        "open": [10] * 240,
        "high": [10.05] * 240,
        "low": [9.95] * 240,
        "close": [10] * 240,
        "volume": [1000] * 240,
    })
    monkeypatch.setattr(run_per_symbol_report, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(run_per_symbol_report, "HistoryProvider", lambda: FakeProvider(daily, intraday))
    monkeypatch.setattr(run_per_symbol_report, "SignalEngine", lambda: None)
    monkeypatch.setattr(
        run_per_symbol_report,
        "load_holdings",
        lambda: [{"symbol": "600522", "name": "中天科技", "cost_price": 12.5, "quantity": 2000}],
    )
    return tmp_path


def test_cli_portfolio_creates_report(fake_env):
    rc = run_per_symbol_report.main(["--portfolio"])
    assert rc == 0
    files = list(fake_env.glob("per_symbol_*.md"))
    assert files
    text = files[0].read_text()
    assert "中天科技" in text
    assert "## 5. 自然语言总结" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_run_per_symbol_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 CLI**

```python
# scripts/run_per_symbol_report.py
"""按需生成个股做 T 策略报告。

用法:
    .venv/bin/python scripts/run_per_symbol_report.py --portfolio
    .venv/bin/python scripts/run_per_symbol_report.py --symbol 600522 --cost 12.5 --qty 2000
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data import HistoryProvider  # noqa: E402
from atrade.per_symbol.adaptive import compute_adaptive  # noqa: E402
from atrade.per_symbol.report import build_report, render_markdown  # noqa: E402
from atrade.per_symbol.risk import compute_risk  # noqa: E402
from atrade.per_symbol.styler import classify_style, summarize  # noqa: E402
from atrade.per_symbol.volatility import compute_volatility  # noqa: E402
from atrade.signals import SignalEngine  # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
HOLDINGS_FILE = Path(__file__).resolve().parents[1] / "config" / "holdings.json"


def load_holdings() -> list[dict]:
    if not HOLDINGS_FILE.exists():
        return []
    return json.loads(HOLDINGS_FILE.read_text()).get("holdings", [])


def report_one(symbol: str, name: str, cost_price: float, quantity: int,
               intraday_days: int = 30) -> str:
    hp = HistoryProvider()
    daily = hp.fetch_with_cache(symbol, scale="1d", datalen=252)
    if daily is None or len(daily) < 60:
        raise ValueError(f"{symbol} 日线数据不足")
    intraday = hp.fetch_with_cache(symbol, scale="5m", datalen=240)

    volatility = compute_volatility(daily)
    risk = compute_risk(daily)
    adaptive = compute_adaptive(intraday) if intraday is not None and len(intraday) >= 60 else {
        "intra_amp_p50": 0.0,
        "intra_amp_p90": 0.0,
        "hold_minutes_p90": 0,
        "factor_score": {},
        "preferred_factors": [],
        "position_pct": 0.1,
    }
    style = classify_style(volatility, risk, adaptive)
    summary = summarize(name or symbol, style, volatility, risk, adaptive)
    rep = build_report(
        symbol=symbol, name=name or symbol,
        cost_price=cost_price, quantity=quantity,
        volatility=volatility, risk=risk, adaptive=adaptive,
        style=style, summary=summary, intraday_days=intraday_days,
    )
    return render_markdown(rep)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="个股做 T 策略报告")
    parser.add_argument("--symbol", help="股票代码")
    parser.add_argument("--cost", type=float, default=0.0)
    parser.add_argument("--qty", type=int, default=0)
    parser.add_argument("--portfolio", action="store_true",
                        help="使用 config/holdings.json 中的所有持仓")
    parser.add_argument("--intraday-days", type=int, default=30)
    args = parser.parse_args(argv)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    targets = []
    if args.portfolio:
        targets = [(h["symbol"], h.get("name", h["symbol"]),
                    h.get("cost_price", 0.0), h.get("quantity", 0)) for h in load_holdings()]
    elif args.symbol:
        targets = [(args.symbol, args.symbol, args.cost, args.qty)]
    else:
        parser.print_help()
        return 1

    rc = 0
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for symbol, name, cost, qty in targets:
        try:
            md = report_one(symbol, name, cost, qty, intraday_days=args.intraday_days)
            path = REPORTS_DIR / f"per_symbol_{symbol}_{stamp}.md"
            path.write_text(md, encoding="utf-8")
            print(f"✅ {symbol} -> {path}")
        except Exception as e:
            rc = 2
            print(f"⚠️ {symbol} 失败: {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_run_per_symbol_report.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/run_per_symbol_report.py tests/test_run_per_symbol_report.py
git commit -m "feat(per_symbol): add CLI entry for per-symbol report"
```

---

### Task 8: 端到端验证与收尾

**Files:**
- Run: 现有 `pytest` 全集
- Run: `python3 scripts/run_per_symbol_report.py --portfolio`（在样例股票 600522 上）

- [ ] **Step 1: 运行完整 pytest**

Run: `python3 -m pytest -q`
Expected: 49 个原有测试 + 新增 per_symbol 测试全部通过

- [ ] **Step 2: 运行 CLI（可离线则 mock）**

Run: `python3 scripts/run_per_symbol_report.py --portfolio`
Expected: 在 `reports/` 下生成 `per_symbol_600522_*.md`，内容含 5 个必要章节

- [ ] **Step 3: 编写收尾状态**

更新 `docs/progress/2026-07-20-per-symbol-t-strategy/STATUS.md`，把阶段标记为“已完成”，记录最终验证命令与结果。
