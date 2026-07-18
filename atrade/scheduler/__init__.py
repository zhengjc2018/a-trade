"""a-trade 定时调度模块。

支持定时任务：
- 早盘快讯（每个交易日 8:00）
- 午盘报告（每个交易日 12:30）
- 收盘日报（每个交易日 15:30）
- 持仓新闻汇总（每个交易日 17:00）
"""
from .runner import DailyScheduler

__all__ = ["DailyScheduler"]
