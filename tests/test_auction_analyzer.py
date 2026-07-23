"""竞价分析器测试。"""
from unittest.mock import patch

import pandas as pd


def _fake_df():
    return pd.DataFrame([
        {"板块": "发电设备", "涨跌幅": 5.74, "总成交额": 1e10,
         "股票代码": "sh600343", "股票名称": "航天动力", "个股-涨跌幅": 20.04},
        {"板块": "电器行业", "涨跌幅": 4.96, "总成交额": 8e9,
         "股票代码": "sh601616", "股票名称": "广电电气", "个股-涨跌幅": 14.96},
        {"板块": "下跌板块", "涨跌幅": -1.50, "总成交额": 5e9,
         "股票代码": "sz000001", "股票名称": "平安银行", "个股-涨跌幅": -1.50},
        {"板块": "创业板测试", "涨跌幅": 9.99, "总成交额": 1e10,
         "股票代码": "sz300062", "股票名称": "中能电气", "个股-涨跌幅": 25.0},
    ])


def test_fetch_sector_auction_sorts_by_change_pct():
    with patch("akshare.stock_sector_spot", return_value=_fake_df()):
        from atrade.analyzer.auction import fetch_sector_auction
        result = fetch_sector_auction(top_n=10)
        # 创业板板块被过滤掉 → 应剩 3 个
        assert len(result) == 3
        # 排序：5.74 > 4.96 > -1.50
        assert result[0].name == "发电设备"
        assert result[1].name == "电器行业"
        assert result[2].name == "下跌板块"
        assert result[0].leader_symbol == "sh600343"


def test_fetch_sector_auction_handles_failure():
    with patch("akshare.stock_sector_spot", side_effect=RuntimeError("network")):
        from atrade.analyzer.auction import fetch_sector_auction
        assert fetch_sector_auction(top_n=5) == []


def test_fetch_top_gainers_sorted():
    with patch("akshare.stock_sector_spot", return_value=_fake_df()):
        from atrade.analyzer.auction import fetch_top_gainers
        result = fetch_top_gainers(top_n=10)
        # 创业板 sz300062 应被全局筛选掉
        assert result[0]["change_pct"] == 20.04
        assert result[0]["name"] == "航天动力"
        assert all("sz300" not in r["symbol"] for r in result)


def test_report_contains_headline_and_sectors():
    fake = _fake_df()
    with patch("akshare.stock_sector_spot", return_value=fake):
        from atrade.report.generator import ReportGenerator
        gen = ReportGenerator(holdings=[], watch_symbols=[])
        md = gen.generate_auction_report()
        assert "# 📈 集合竞价分析" in md
        assert "发电设备" in md
        assert "+5.74%" in md
        # 航天动力是主板，应被选中
        assert "航天动力" in md
        # 中能电气是创业板，应被排除
        assert "中能电气" not in md


def test_report_handles_empty():
    with patch("akshare.stock_sector_spot", return_value=pd.DataFrame()):
        from atrade.report.generator import ReportGenerator
        gen = ReportGenerator(holdings=[], watch_symbols=[])
        md = gen.generate_auction_report()
        assert "暂无数据" in md
