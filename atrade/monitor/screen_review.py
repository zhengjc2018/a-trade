"""今日荐股胜率复盘渲染。"""

from __future__ import annotations

from datetime import datetime

from atrade.data.quotes import Quote

from .screen_ledger import Recommendation


def _row_markdown(row: dict) -> str:
    symbol = row["symbol"]
    name = row["name"]
    push_price = row["push_price"]
    close_price = row["close_price"]
    if close_price is None:
        return f"| {symbol} | {name} | {push_price:.2f} | N/A | N/A | N/A |"
    pnl = row["pnl"]
    pnl_pct = row["pnl_pct"]
    sign = "+" if pnl > 0 else ""
    return (
        f"| {symbol} | {name} | {push_price:.2f} | {close_price:.2f} | "
        f"{sign}{pnl:.2f} | {sign}{pnl_pct:.2f}% |"
    )


def build_screen_review(
    records: list[Recommendation],
    quotes: dict[str, Quote],
    now: datetime | None = None,
) -> str:
    """生成当日荐股复盘 Markdown；无记录返回空字符串。"""
    if not records:
        return ""

    rows = []
    wins = losses = ties = 0
    total_pnl = 0.0
    for rec in records:
        quote = quotes.get(rec.symbol)
        if quote is None or not quote.is_valid:
            rows.append({
                "symbol": rec.symbol,
                "name": rec.name,
                "push_price": rec.price,
                "close_price": None,
                "pnl": 0.0,
                "pnl_pct": 0.0,
            })
            continue
        close = quote.price
        pnl = close - rec.price
        pnl_pct = (close / rec.price - 1) * 100 if rec.price > 0 else 0.0
        total_pnl += pnl
        if close > rec.price:
            wins += 1
        elif close < rec.price:
            losses += 1
        else:
            ties += 1
        rows.append({
            "symbol": rec.symbol,
            "name": rec.name,
            "push_price": rec.price,
            "close_price": close,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })

    evaluated = wins + losses + ties
    win_rate_text = f"{wins / evaluated:.1%}" if evaluated else "N/A"
    ts = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 📊 a-trade 今日荐股胜率",
        f"_{ts}_",
        "",
        f"今日推荐 **{len(records)}** 只，**{wins}胜 {losses}负 {ties}平**，"
        f"胜率 **{win_rate_text}**",
        "",
        "| 代码 | 名称 | 买入价(推送价) | 收盘价 | 盈亏(元) | 涨跌% |",
        "|---|---|---:|---:|---:|---:|",
    ]
    lines.extend(_row_markdown(row) for row in rows)
    lines.extend([
        "",
        f"- 合计盈亏：**{total_pnl:+.2f} 元**（每只 1 股口径）",
        "- 口径：买入价=当日首次推送价；盈亏=收盘价-推送价",
        "",
        "_⚠️ 仅供参考，投资有风险_",
    ])
    return "\n".join(lines)
