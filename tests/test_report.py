import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.per_symbol.report import build_report, render_markdown
from atrade.report.generator import ReportGenerator


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


def _replay_trades():
    return [
        {
            "timestamp": "2026-07-25T10:00:00",
            "symbol": "600522",
            "name": "中天科技",
            "direction": "BUY",
            "shares": 100,
            "lots": 1.0,
            "price": 100.0,
            "signal_name": "BUY(2因子共振)",
            "reason": "test",
            "holding_qty_after": 200,
            "skipped_reason": "",
            "factor_hits": ["趋势确认"],
            "risk_action": "",
        },
        {
            "timestamp": "2026-07-25T14:00:00",
            "symbol": "600522",
            "name": "中天科技",
            "direction": "SELL",
            "shares": 100,
            "lots": 1.0,
            "price": 103.0,
            "signal_name": "T仓锁利",
            "reason": "test",
            "holding_qty_after": 100,
            "skipped_reason": "",
            "factor_hits": ["take_profit"],
            "risk_action": "take_profit",
        },
    ]


def test_t_replay_report_puts_result_first(monkeypatch):
    monkeypatch.setattr("atrade.report.generator.load_trades", _replay_trades)
    generator = ReportGenerator()

    report = generator.generate_t_replay_report("2026-07-25")

    assert report.startswith("# 📈 做T复盘\n\n✅ 今日做T：1胜0负")
    assert "胜率 **100.0%**" in report
    assert "中天科技(600522)" in report
    assert "+300.00" in report
    assert "未扣手续费" in report


def test_empty_replay_is_still_observable(monkeypatch):
    monkeypatch.setattr("atrade.report.generator.load_trades", lambda: [])
    generator = ReportGenerator()

    report = generator.generate_t_replay_report("2026-07-25")

    assert report.startswith("# 📈 做T复盘\n\n⏸️ 今日无已闭环 T 交易")


def test_closing_report_embeds_replay_before_other_sections(monkeypatch):
    monkeypatch.setattr("atrade.report.generator.load_trades", _replay_trades)
    generator = ReportGenerator()
    monkeypatch.setattr(generator, "_render_holdings", lambda: "持仓")
    monkeypatch.setattr(generator, "_render_hot_sectors", lambda top_n=5: "板块")
    monkeypatch.setattr(generator, "_render_zt_pool", lambda: "涨停")
    monkeypatch.setattr(generator, "_render_holdings_news", lambda: "持仓新闻")
    monkeypatch.setattr(generator, "_render_morning_brief", lambda: "宏观")
    monkeypatch.setattr(generator, "_render_watchlist_news", lambda: "关注")

    report = generator.generate_closing_report()

    assert report.index("## 📈 做T复盘") < report.index("## 💼 持仓概览")
    assert "✅ 今日做T：1胜0负" in report
