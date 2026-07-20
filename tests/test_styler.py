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
        {"preferred_factors": ["波段反弹", "趋势确认"], "position_pct": 0.25,
         "intra_amp_p50": 2.3},
    )
    assert "中天科技" in out
    assert "波段反弹" in out
    assert "趋势确认" in out
    assert "25%" in out
