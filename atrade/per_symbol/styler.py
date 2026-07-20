"""风格归类与自然语言总结。"""
from __future__ import annotations


def classify_style(volatility: dict, risk: dict, adaptive: dict) -> str:
    atr = volatility.get("atr_14_pct", 0.0)
    gap_abs = volatility.get("gap_abs_mean", 0.0)
    p90 = volatility.get("daily_amp_p90", 0.0)

    if atr < 1.5 and gap_abs < 0.5:
        return "low_vol"
    if atr > 4.0 or p90 > 6.0:
        return "high_vol"
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
