"""股票筛选：ST / 创业板 / 科创板 / 京板 排除。

默认排除规则：
- ST / *ST / 退市股（按名称判断）
- 创业板（300xxx / 301xxx）
- 科创板（688xxx / 689xxx）
- 京板（8xxxxx / 9xxxxx 的北交所股票）

保留：
- 沪深主板：000xxx / 001xxx / 002xxx / 600xxx / 601xxx / 603xxx / 605xxx
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

# 主板前缀
MAIN_BOARD_PREFIXES: tuple[str, ...] = (
    "000", "001", "002", "600", "601", "603", "605",
)
# 创业板
CHINEXT_PREFIXES: tuple[str, ...] = ("300", "301")
# 科创板
STAR_PREFIXES: tuple[str, ...] = ("688", "689")
# 北交所 / 京板
BSE_PREFIXES: tuple[str, ...] = ("8", "92", "43", "83")


@dataclass
class StockFilterConfig:
    """筛选配置：默认全部排除创业板/科创板/京板/ST。"""
    exclude_st: bool = True
    exclude_chinext: bool = True
    exclude_star: bool = True
    exclude_bse: bool = True
    allowed_prefixes: tuple[str, ...] = MAIN_BOARD_PREFIXES


_DEFAULT_CONFIG = StockFilterConfig()


def _board_of(symbol: str) -> str:
    """返回股票所属板块。"""
    code = str(symbol).strip()
    if code.lower().startswith(("sh", "sz", "bj")):
        code = code[2:]
    code = code.zfill(6)
    if code.startswith(CHINEXT_PREFIXES):
        return "chinext"  # 创业板
    if code.startswith(STAR_PREFIXES):
        return "star"  # 科创板
    if any(code.startswith(p) for p in BSE_PREFIXES):
        return "bse"  # 北交所
    if code.startswith(MAIN_BOARD_PREFIXES):
        return "main"  # 主板
    return "unknown"


def is_st_name(name: str) -> bool:
    """是否 ST/*ST/退市股。"""
    if not name:
        return False
    upper = str(name).upper()
    return upper.startswith("*ST") or upper.startswith("ST") or "退" in upper


def is_allowed(
    symbol: str,
    name: Optional[str] = None,
    config: Optional[StockFilterConfig] = None,
) -> bool:
    """单只股票是否符合筛选规则。

    Args:
        symbol: 6 位股票代码
        name:   股票名称（可选，用于 ST 判断）
        config: 筛选配置（None = 默认）

    Returns:
        True = 通过；False = 被排除
    """
    cfg = config or _DEFAULT_CONFIG
    code = str(symbol).strip()
    if code.lower().startswith(("sh", "sz", "bj")):
        code = code[2:]
    code = code.zfill(6)

    # ST 名称判断
    if cfg.exclude_st and is_st_name(name or ""):
        return False

    # 主板前缀 → 始终通过
    if code.startswith(cfg.allowed_prefixes):
        return True

    # 其他板块按开关
    board = _board_of(code)
    if board == "chinext" and cfg.exclude_chinext:
        return False
    if board == "star" and cfg.exclude_star:
        return False
    if board == "bse" and cfg.exclude_bse:
        return False

    # 未识别板块（unknown）保守放行（避免误杀）
    return True


def filter_symbols(
    symbols: Iterable[str],
    names: Optional[dict[str, str]] = None,
    config: Optional[StockFilterConfig] = None,
) -> list[str]:
    """从代码列表中筛掉不符合的，返回保留列表（按 6 位代码去重）。"""
    seen: set[str] = set()
    out: list[str] = []
    for sym in symbols:
        s = str(sym).strip()
        if s.lower().startswith(("sh", "sz", "bj")):
            s = s[2:]
        s = s.zfill(6)
        if s in seen:
            continue
        seen.add(s)
        name = (names or {}).get(sym, "")
        if is_allowed(s, name=name, config=config):
            out.append(s)
    return out


def exclude_reason(
    symbol: str,
    name: Optional[str] = None,
    config: Optional[StockFilterConfig] = None,
) -> Optional[str]:
    """返回被排除的具体原因（如 'ST', '创业板'）；通过则 None。"""
    if is_allowed(symbol, name=name, config=config):
        return None
    cfg = config or _DEFAULT_CONFIG
    if cfg.exclude_st and is_st_name(name or ""):
        return "ST"
    board = _board_of(str(symbol).zfill(6))
    if board == "chinext" and cfg.exclude_chinext:
        return "创业板"
    if board == "star" and cfg.exclude_star:
        return "科创板"
    if board == "bse" and cfg.exclude_bse:
        return "北交所"
    return "其他"
