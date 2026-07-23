"""股票筛选器测试。"""
from atrade.filters.stock_filter import (
    StockFilterConfig,
    exclude_reason,
    filter_symbols,
    is_allowed,
    is_st_name,
)


def test_main_board_allowed():
    for code in ["600519", "000001", "002436", "603021", "601318", "605168", "001979"]:
        assert is_allowed(code), f"主板应通过: {code}"


def test_chinext_excluded_by_default():
    assert not is_allowed("300750", "宁德时代")
    assert not is_allowed("301236", "软通动力")


def test_star_excluded_by_default():
    assert not is_allowed("688981", "中芯国际")
    assert not is_allowed("689009", "九号公司")


def test_bse_excluded_by_default():
    assert not is_allowed("830799", "北交所股票")
    assert not is_allowed("920222", "北交所股票")


def test_st_name_excluded():
    assert not is_allowed("600519", "ST茅台")  # 实际不存在，但测试逻辑
    assert not is_allowed("000001", "*ST平安")
    assert not is_allowed("600000", "退市股")


def test_st_chinext_combined():
    assert not is_allowed("300750", "*ST宁德")


def test_can_disable_exclusions():
    cfg = StockFilterConfig(
        exclude_chinext=False,
        exclude_star=False,
        exclude_bse=False,
    )
    assert is_allowed("300750", config=cfg)
    assert is_allowed("688981", config=cfg)
    # ST 默认仍排除
    assert not is_allowed("000001", "*ST", config=cfg)


def test_st_can_be_allowed():
    cfg = StockFilterConfig(exclude_st=False)
    assert is_allowed("000001", "*ST", config=cfg)


def test_filter_symbols():
    codes = ["600519", "300750", "688981", "000001", "830799"]
    names = {"600519": "贵州茅台", "000001": "平安银行"}
    out = filter_symbols(codes, names)
    assert out == ["600519", "000001"]


def test_filter_symbols_no_names():
    codes = ["600519", "300750"]
    assert filter_symbols(codes) == ["600519"]


def test_is_st_name_edge_cases():
    assert is_st_name("ST华联") is True
    assert is_st_name("*ST华联") is True
    assert is_st_name("退市华联") is True
    assert is_st_name("贵州茅台") is False
    assert is_st_name("st华联") is True  # 大小写不敏感
    assert is_st_name("") is False
    assert is_st_name(None) is False


def test_exclude_reason():
    assert exclude_reason("300750", "宁德时代") == "创业板"
    assert exclude_reason("688981", "中芯国际") == "科创板"
    assert exclude_reason("600519", "贵州茅台") is None
    assert exclude_reason("000001", "*ST平安") == "ST"


def test_with_exchange_prefix():
    """新浪数据返回 sh600519 / sz300750 / bj830799 等格式。"""
    assert is_allowed("sh600519") is True
    assert is_allowed("sz000001") is True
    assert is_allowed("sz300750") is False  # 创业板
    assert is_allowed("sz300407") is False
    assert is_allowed("sh688981") is False  # 科创板
    assert is_allowed("bj830799") is False  # 北交所
    assert is_allowed("bj920222") is False


def test_auction_symbols_filtered():
    """验证 auction 用到的 symbol 格式被正确过滤（去重 + 归一化）。"""
    from atrade.filters.stock_filter import filter_symbols
    symbols = ["sh600519", "sz300750", "sh688981", "sz000001", "bj830799", "sh600519"]
    out = filter_symbols(symbols)
    assert out == ["600519", "000001"]  # 归一化为 6 位 + 去重
