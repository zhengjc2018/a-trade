"""选股硬过滤规则（主板 / ST / 行业 / 价格 / 基本面）。"""

from __future__ import annotations

MAIN_BOARD_PREFIXES = ("000", "001", "002", "600", "601", "603", "605")

BLOCKED_INDUSTRY_KEYWORDS = (
    "白酒",
    "证券",
    "消费",
    "房地产",
    "食品",
    "饮料",
    "零售",
    "商贸",
    "家电",
)

MAX_PRICE = 80.0
MAX_PE_TTM = 100.0
MAX_PB = 5.0
NOT_LIMIT_PCT = 9.8  # 主板涨停 10%，尾盘低于 9.8% 视为“今日没有板”


def is_main_board(code: str) -> bool:
    return str(code).zfill(6).startswith(MAIN_BOARD_PREFIXES)


def is_st_name(name: str) -> bool:
    upper = str(name).upper()
    return upper.startswith("ST") or upper.startswith("*ST") or "退" in upper


def industry_allowed(industry: str) -> bool:
    return not any(keyword in str(industry) for keyword in BLOCKED_INDUSTRY_KEYWORDS)


def price_ok(price) -> bool:
    try:
        return 0.0 < float(price) <= MAX_PRICE
    except (TypeError, ValueError):
        return False


def fundamentals_ok(pe_ttm=None, pb=None) -> bool:
    if pe_ttm is not None:
        try:
            if float(pe_ttm) <= 0 or float(pe_ttm) > MAX_PE_TTM:
                return False
        except (TypeError, ValueError):
            return False
    if pb is not None:
        try:
            if float(pb) > MAX_PB:
                return False
        except (TypeError, ValueError):
            return False
    return True


def not_limit_up(pct_chg) -> bool:
    try:
        return float(pct_chg) < NOT_LIMIT_PCT
    except (TypeError, ValueError):
        return False
