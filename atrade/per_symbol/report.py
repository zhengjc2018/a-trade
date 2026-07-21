"""汇总生成 SymbolReport 并渲染 Markdown。"""
from __future__ import annotations

from dataclasses import dataclass
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
    latest_price: Optional[float] = None


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
    latest_price: Optional[float] = None,
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
        latest_price=latest_price,
    )


def render_markdown(report: SymbolReport) -> str:
    v = report.volatility
    r = report.risk
    a = report.adaptive
    lines = [
        f"# {report.name} ({report.symbol}) 做 T 策略报告",
        "",
        f"- 成本价（用户输入）：{report.cost_price:.2f} / 数量：{report.quantity}",
        (
            f"- 最新收盘价：{report.latest_price:.2f}"
            if report.latest_price is not None
            else "- 最新收盘价：未获取"
        ),
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
