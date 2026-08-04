"""盘中选股通知。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger

from scripts.screen import fetch_market_snapshot, filter_screen_candidates, load_snapshot

from .screen_ledger import RecommendationLedger


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

    def __init__(
        self,
        config: Optional[dict] = None,
        ledger: Optional[RecommendationLedger] = None,
    ):
        cfg = config or {}
        self.config = ScreenConfig(
            enabled=bool(cfg.get("enabled", True)),
            interval_minutes=int(cfg.get("interval_minutes", 30)),
            pct_chg_min=cfg.get("pct_chg_min", 2.0),
            pct_chg_max=cfg.get("pct_chg_max"),
            amount_min=cfg.get("amount_min", 300000000),
            code_in=list(cfg.get("code_in") or []),
        )
        self.ledger = ledger or RecommendationLedger()

    def run_once(self, source: str = "screen") -> str:
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

            df = filter_screen_candidates(df, _Args)

            if df.empty:
                return ""

            # print_table 只打印，这里再构造 markdown 供群发。
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            pushed_at = now.isoformat(timespec="seconds")
            picks = []
            lines = [
                "# 📈 a-trade 盘中选股",
                "",
                "| 代码 | 名称 | 现价 | 涨幅% | 振幅% | 成交额(亿) | 总市值(亿) | PE_TTM |",
                "|---|---|---:|---:|---:|---:|---:|---:|",
            ]
            for _, r in df.head(20).iterrows():
                amount_yi = (r.get("amount") or 0) / 1e8
                mv_yi = (r.get("total_mv") or 0) / 1e8
                # 快照字段契约：price 已是实际元（fltt=2），不再 ×100
                price = r.get("price") or 0
                picks.append({
                    "symbol": r["code"],
                    "name": str(r.get("name", "")),
                    "price": price,
                    "pushed_at": pushed_at,
                })
                lines.append(
                    f"| {r['code']} | {str(r['name'])[:12]} | {price:.2f} | "
                    f"{(r.get('pct_chg') or 0):.2f} | {(r.get('amplitude') or 0):.2f} | "
                    f"{amount_yi:.2f} | {mv_yi:.2f} | {(r.get('pe_ttm') or 0):.2f} |"
                )
            try:
                self.ledger.add_many(today, picks, source=source)
            except Exception as e:
                logger.warning(f"荐股台账写入失败（不影响推送）: {e}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"盘中选股失败: {e}")
            return ""
