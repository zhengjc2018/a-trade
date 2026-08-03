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
        excluded={"yiziban": 0, "no_next_open": 0, "first_board": 0},
    )
    md = render_report(result)
    assert "样本不足" in md


def test_run_study_keeps_base_when_zt_enrich_fails():
    result = run_study(
        ["600001"],
        _FakeHistory(),
        _industry,
        StudyConfig(min_samples=2, lookback_bars=100, with_zt_pool=True),
        zt_enrich=lambda samples: samples,
    )
    assert result.base["n"] > 0
    for column in ("zt_turnover", "zt_float_mv_yi", "zt_break_count", "zt_seal_amount_yi"):
        assert column not in result.factor_buckets


def test_render_report_uses_actual_config_values():
    result = GapStudyResult(
        generated_at="2026-08-03 15:00:00",
        base={"n": 4, "wins": 2, "win_rate": 0.5, "mean_gap": 1.5, "median_gap": 1.2},
        top_pct=0.5,
        min_gap_pct=2.0,
        factor_buckets={},
        ranking=[],
        top={"top_pct": 0.5, "n": 2, "win_rate": 0.75, "mean_gap": 2.5, "lift": 0.25},
        excluded={"yiziban": 1, "no_next_open": 2, "first_board": 7, "lianban": 3},
    )
    md = render_report(result)
    assert "## 多因子 Top 50%" in md
    assert "高开 ≥2% 算胜" in md
    assert "连板 3" in md
