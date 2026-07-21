from atrade.per_symbol.report import build_report, render_markdown


def test_build_report_returns_symbol_report():
    rep = build_report(
        symbol="600522", name="中天科技", cost_price=12.5, quantity=2000,
        volatility={"atr_14_pct": 2.6}, risk={"annual_vol_pct": 28.7},
        adaptive={"intra_amp_p50": 2.3, "preferred_factors": ["波段反弹"], "position_pct": 0.25},
        style="range", summary="ok",
        latest_price=34.63,
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
        latest_price=34.63,
    )
    md = render_markdown(rep)
    for section in ("# 中天科技", "## 1. 风格归类", "## 2. 波动性",
                    "## 3. 做 T 适配度", "## 4. 风险指标", "## 5. 自然语言总结"):
        assert section in md, section
    assert "成本价（用户输入）：12.50" in md
    assert "最新收盘价：34.63" in md
