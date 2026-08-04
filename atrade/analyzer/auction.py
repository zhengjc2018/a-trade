"""集合竞价分析。

9:25 集合竞价撮合后调用，给出当日热门板块与领涨股。

数据源：
- 主源：新浪行业板块（ak.stock_sector_spot），多个 indicator 逐个尝试
- 备用源：东方财富行业板块（ak.stock_board_industry_name_em）
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from functools import lru_cache

from loguru import logger


@dataclass
class SectorAuction:
    name: str
    change_pct: float          # 板块涨幅 %
    leader_symbol: str         # 板块领涨股代码
    leader_name: str           # 板块领涨股名称
    leader_change_pct: float   # 领涨股涨幅 %
    turnover: float            # 板块总成交额（元）


_SINA_INDICATORS = ("新浪行业", "行业", "启明星行业")


def _to_float(value, default: float = 0.0) -> float:
    """安全转 float，NaN / None / 空字符串返回 default。"""
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_missing(value) -> bool:
    """判断行情字段是否缺失（None / NaN / 空字符串 / --）。"""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() in ("", "--", "nan")


def _sectors_from_df(df) -> list[SectorAuction]:
    """把新浪板块 DataFrame 转成 SectorAuction 列表。"""
    out: list[SectorAuction] = []
    for _, row in df.iterrows():
        try:
            out.append(SectorAuction(
                name=str(row.get("板块", "")).strip(),
                change_pct=_to_float(row.get("涨跌幅")),
                leader_symbol=str(row.get("股票代码", "")).strip(),
                leader_name=str(row.get("股票名称", "")).strip(),
                leader_change_pct=_to_float(row.get("个股-涨跌幅")),
                turnover=_to_float(row.get("总成交额")),
            ))
        except Exception:
            continue
    return out


def _fetch_sina_sector(indicator: str):
    """拉取新浪板块 DataFrame，失败返回 None。"""
    try:
        import akshare as ak
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = ak.stock_sector_spot(indicator=indicator)
        if df is None or df.empty:
            logger.warning(f"新浪板块({indicator})为空")
            return None
        return df
    except Exception as e:
        logger.warning(f"新浪板块({indicator})拉取失败: {e}")
        return None


@lru_cache(maxsize=1)
def _fetch_stock_name_map() -> dict[str, str]:
    """全市场 名称->代码 映射（备用源用来反查领涨股代码）。"""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        return {
            "".join(str(name).split()): str(code).zfill(6)
            for code, name in zip(df["code"], df["name"])
        }
    except Exception as e:
        logger.warning(f"全市场代码表拉取失败: {e}")
        return {}


def _sectors_from_em() -> list[SectorAuction]:
    """东财行业板块备用源：板块名 + 领涨股名 + 涨幅。"""
    try:
        import akshare as ak
        boards = ak.stock_board_industry_name_em()
        if boards is None or boards.empty:
            return []
        name_map = _fetch_stock_name_map()
        out: list[SectorAuction] = []
        for _, row in boards.iterrows():
            leader_name = str(row.get("领涨股票", "")).strip()
            if not leader_name or _is_missing(row.get("领涨股票-涨跌幅")):
                continue
            symbol = name_map.get("".join(leader_name.split()), "")
            if not symbol:
                continue
            out.append(SectorAuction(
                name=str(row.get("板块名称", "")).strip(),
                change_pct=_to_float(row.get("涨跌幅")),
                leader_symbol=symbol,
                leader_name=leader_name,
                leader_change_pct=_to_float(row.get("领涨股票-涨跌幅")),
                turnover=0.0,
            ))
        logger.info(f"✅ 东财板块备用源: {len(out)} 个")
        return out
    except Exception as e:
        logger.warning(f"东财板块备用源拉取失败: {e}")
        return []


def _has_enough_leader_data(sectors: list[SectorAuction]) -> bool:
    """至少一半板块有完整领涨股信息，才认为个股字段可用。"""
    if not sectors:
        return False
    valid = sum(
        1 for s in sectors
        if s.leader_symbol and s.leader_name
    )
    return valid >= max(1, len(sectors) // 2)


def fetch_sector_auction(top_n: int = 10) -> list[SectorAuction]:
    """拉取今日板块行情，按涨幅倒序取 TOP N。

    返回 list[SectorAuction]，失败时返回空列表。
    """
    sectors: list[SectorAuction] = []
    for indicator in _SINA_INDICATORS:
        df = _fetch_sina_sector(indicator)
        if df is None:
            continue
        candidates = _sectors_from_df(df)
        if _has_enough_leader_data(candidates):
            sectors = candidates
            logger.info(f"✅ 新浪板块({indicator}): {len(sectors)} 个，个股字段可用")
            break
        logger.warning(f"新浪板块({indicator})个股字段为空，尝试下一个数据源")

    if not _has_enough_leader_data(sectors):
        em_sectors = _sectors_from_em()
        if _has_enough_leader_data(em_sectors):
            sectors = em_sectors

    # 应用全局筛选：排除 ST/创业板/科创板/京板 的领涨股所在板块
    from atrade.filters.stock_filter import StockFilterConfig, is_allowed
    cfg = StockFilterConfig()
    out = [
        s for s in sectors
        if s.leader_symbol and s.leader_name
        and is_allowed(s.leader_symbol, name=s.leader_name, config=cfg)
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
