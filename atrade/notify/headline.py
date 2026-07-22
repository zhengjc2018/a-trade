"""通知结论置顶渲染。

把"操作结论"放在通知第一行，便于手机推送 / 群消息一眼可见。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

# 结论 -> emoji + 标签
_CONCLUSION_META: Mapping[str, tuple[str, str]] = {
    "buy": ("🟢", "买入"),
    "sell": ("🔴", "卖出"),
    "stop_loss": ("🚨", "止损"),
    "watch": ("⏸️", "观望"),
    "no_signal": ("⏸️", "观望"),
}

# 中文置信标签
_STRENGTH_META: Mapping[str, str] = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
}

# 中文信号名映射（与 atrade.signals.engine 保持一致）
_SIGNAL_NAME_CN: Mapping[str, str] = {
    "buy": "低吸",
    "sell": "高抛",
    "stop_loss": "止损",
    "watch": "观察",
}


def render_headline(
    conclusion: str,
    *,
    strength: str | None = None,
    symbols: Iterable[str] | None = None,
) -> str:
    """生成单行结论字符串。

    Args:
        conclusion: buy / sell / stop_loss / watch / no_signal
        strength:  strong / medium / weak（无则不显示）
        symbols:   相关股票代码，会出现在末尾（如 "[600519]"）

    Returns:
        `🟢 操作结论: 买入 (置信: 强) [600522]`
    """
    emoji, label = _CONCLUSION_META.get(conclusion, _CONCLUSION_META["watch"])
    parts = [f"{emoji} 操作结论: {label}"]
    if strength and conclusion not in ("watch", "no_signal"):
        s_label = _STRENGTH_META.get(strength.lower(), strength)
        parts.append(f"(置信: {s_label})")
    symbol_list = [s for s in (symbols or []) if s]
    if symbol_list:
        parts.append(f"[{', '.join(symbol_list)}]")
    return " ".join(parts)


def infer_conclusion(alerts: list[dict]) -> tuple[str, str | None]:
    """从候选告警列表推断结论。

    优先级：STOP_LOSS > SELL > BUY > WATCH。
    返回 (conclusion, strength)。
    """
    if not alerts:
        return "no_signal", None
    priority = {"stop_loss": 3, "sell": 2, "buy": 1, "watch": 0}
    best = max(alerts, key=lambda a: priority.get(a.get("signal_type", "watch"), 0))
    sig_type = str(best.get("signal_type", "watch")).lower()
    conclusion = sig_type if sig_type in priority else "watch"
    strength = str(best.get("strength", "")).lower() or None
    return conclusion, strength


def prepend_headline(
    markdown: str,
    *,
    conclusion: str,
    strength: str | None = None,
    symbols: Iterable[str] | None = None,
) -> str:
    """把头部结论加到 Markdown 顶部。"""
    headline = render_headline(conclusion, strength=strength, symbols=symbols)
    if not markdown:
        return headline
    return f"{headline}\n\n{markdown}"


def split_by_symbol_headlines(
    alerts: list[dict],
) -> list[tuple[str, str, str | None]]:
    """按股票聚合告警：[(symbol, conclusion, strength), ...]

    同一只股票的多个信号取优先级最高的结论。
    """
    by_symbol: dict[str, list[dict]] = {}
    for a in alerts:
        sym = str(a.get("symbol", "")).strip()
        if sym:
            by_symbol.setdefault(sym, []).append(a)
    out: list[tuple[str, str, str | None]] = []
    priority = {"stop_loss": 3, "sell": 2, "buy": 1, "watch": 0}
    for sym, items in by_symbol.items():
        best = max(items, key=lambda a: priority.get(str(a.get("signal_type", "watch")).lower(), 0))
        sig_type = str(best.get("signal_type", "watch")).lower()
        conclusion = sig_type if sig_type in priority else "watch"
        strength = str(best.get("strength", "")).lower() or None
        out.append((sym, conclusion, strength))
    return out


def chinese_signal_label(signal_type: str) -> str:
    """信号类型中文名。"""
    return _SIGNAL_NAME_CN.get(signal_type.lower(), signal_type)
