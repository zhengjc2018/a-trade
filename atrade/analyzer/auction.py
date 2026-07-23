"""集合竞价分析。

9:25 集合竞价撮合后调用，给出当日热门板块与领涨股。

数据源：新浪行业板块（ak.stock_sector_spot）
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

from loguru import logger


@dataclass
class SectorAuction:
    name: str
    change_pct: float          # 板块涨幅 %
    leader_symbol: str         # 板块领涨股代码
    leader_name: str           # 板块领涨股名称
    leader_change_pct: float   # 领涨股涨幅 %
    turnover: float            # 板块总成交额（元）


def fetch_sector_auction(top_n: int = 10) -> list[SectorAuction]:
    """拉取今日板块行情（新浪行业），按涨幅倒序取 TOP N。

    返回 list[SectorAuction]，失败时返回空列表。
    """
    try:
        import akshare as ak
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = ak.stock_sector_spot(indicator="新浪行业")
    except Exception as e:
        logger.error(f"❌ 板块行情拉取失败: {e}")
        return []

    if df is None or df.empty:
        logger.warning("板块行情为空")
        return []

    out: list[SectorAuction] = []
    for _, row in df.iterrows():
        try:
            change_pct = float(row.get("涨跌幅", 0) or 0)
            turnover = float(row.get("总成交额", 0) or 0)
            out.append(SectorAuction(
                name=str(row.get("板块", "")),
                change_pct=change_pct,
                leader_symbol=str(row.get("股票代码", "")),
                leader_name=str(row.get("股票名称", "")),
                leader_change_pct=float(row.get("个股-涨跌幅", 0) or 0),
                turnover=turnover,
            ))
        except Exception:
            continue

    # 应用全局筛选：排除 ST/创业板/科创板/京板 的领涨股所在板块
    from atrade.filters.stock_filter import StockFilterConfig, is_allowed
    cfg = StockFilterConfig()
    out = [
        s for s in out
        if is_allowed(s.leader_symbol, name=s.leader_name, config=cfg)
    ]
    out.sort(key=lambda s: s.change_pct, reverse=True)
    top = out[:top_n]
    logger.info(f"✅ 板块行情: 筛选后 {len(out)} 个，取 TOP {len(top)}")
    return top


def fetch_top_gainers(top_n: int = 10) -> list[dict]:
    """拉取所有行业板块的领涨股，按领涨股涨幅倒序。"""
    sectors = fetch_sector_auction(top_n=200)  # 拉全量
    leaders = [
        {
            "sector": s.name,
            "symbol": s.leader_symbol,
            "name": s.leader_name,
            "change_pct": s.leader_change_pct,
        }
        for s in sectors if s.leader_symbol
    ]
    leaders.sort(key=lambda x: x["change_pct"], reverse=True)
    return leaders[:top_n]
