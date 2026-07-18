"""盘中选股通知。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from scripts.screen import fetch_market_snapshot, filter_by_thresholds, load_snapshot


@dataclass
class ScreenConfig:
    enabled: bool = True
    interval_minutes: int = 30
    pct_chg_min: Optional[float] = 2.0
    pct_chg_max: Optional[float] = None
    amount_min: Optional[float] = 300000000
    code_in: list[str] = field(default_factory=list)


class ScreenMonitorRunner:
    """盘中选股扫描与通知。"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.config = ScreenConfig(
            enabled=bool(cfg.get("enabled", True)),
            interval_minutes=int(cfg.get("interval_minutes", 30)),
            pct_chg_min=cfg.get("pct_chg_min", 2.0),
            pct_chg_max=cfg.get("pct_chg_max"),
            amount_min=cfg.get("amount_min", 300000000),
            code_in=list(cfg.get("code_in") or []),
        )

    def run_once(self) -> str:
        """返回 Markdown 选股结果，没有结果时返回空字符串。"""
        if not self.config.enabled:
            return ""

        try:
            fetch_market_snapshot()
            df = load_snapshot()
            if df.empty:
                return ""

            class _Args:
                pct_chg_min = self.config.pct_chg_min
                pct_chg_max = self.config.pct_chg_max
                amount_min = self.config.amount_min
                code_in = ",".join(self.config.code_in) if self.config.code_in else None

            if any([
                self.config.pct_chg_min is not None,
                self.config.pct_chg_max is not None,
                self.config.amount_min is not None,
                self.config.code_in,
            ]):
                df = filter_by_thresholds(df, _Args)

            if df.empty:
                return ""

            # print_table 只打印，这里再构造 markdown 供群发。
            lines = [
                "# 📈 a-trade 盘中选股",
                "",
                "| 代码 | 名称 | 现价 | 涨幅% | 振幅% | 成交额(亿) | 总市值(亿) | PE_TTM |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
            for _, r in df.head(20).iterrows():
                amount_yi = (r.get("amount") or 0) / 1e8
                mv_yi = (r.get("total_mv") or 0) / 1e8
                price = (r.get("price") or 0) / 100
                lines.append(
                    f"| {r['code']} | {str(r['name'])[:12]} | {price:.2f} | "
                    f"{(r.get('pct_chg') or 0):.2f} | {(r.get('amplitude') or 0):.2f} | "
                    f"{amount_yi:.2f} | {mv_yi:.2f} | {(r.get('pe_ttm') or 0):.2f} |"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"盘中选股失败: {e}")
            return ""
