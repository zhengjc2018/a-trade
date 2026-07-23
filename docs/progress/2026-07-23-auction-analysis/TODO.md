# 2026-07-23 竞价分析 TODO

**目标：** 9:25 集合竞价结束后，钉钉推送"板块榜 TOP 5 + 每个板块领涨股 TOP 3"。

## 1. 模块
- [x] atrade/analyzer/__init__.py
- [x] atrade/analyzer/auction.py: fetch_sector_auction() + fetch_sector_leaders()
- [x] atrade/report/generator.py: generate_auction_report()

## 2. 定时
- [x] 09:25 auction_analysis 推送（仅交易日）
- [x] 09:30 guard（如漏发补一次）

## 3. 测试
- [x] tests/test_auction_analyzer.py
- [x] 全量测试 + ruff

## 4. 部署
- [x] push origin + vps
- [x] VPS 重启服务
