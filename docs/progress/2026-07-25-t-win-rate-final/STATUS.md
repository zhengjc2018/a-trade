# 2026-07-25 T 胜率优化收尾 STATUS

- **总体状态：** 全部完成 ✅
- **完成时间（本地）：** 2026-07-25 14:30 CST

## 已完成
1. 本地 `config/holdings.local.json` 替换为真实持仓：002436 兴森 100@41.093 + 600522 中天 200@61.863
2. 本地 `config/monitor.local.json` 清空旧茅台/紫金 symbols，t_monitor.symbols=[]，新增 `trailing_defaults: {0.03, 0.02}` 显式字段
3. VPS `monitor.local.json` 补 `trailing_defaults: {0.03, 0.02}`，`systemctl restart a-trade.service a-trade-web.service` 后两者均 `active`
4. VPS 端冒烟：`load_holdings()` 返回 2 项，`t_monitor.symbols=[]`，`trailing_defaults={'take_profit_pct': 0.03, 'stop_loss_pct': 0.02}`，journalctl 无 traceback
5. 清理运行时产物：`a_trade.egg-info/`、`data/cache/*.db/json` 已删除；`git status` 干净
6. 验证：pytest `324 passed, 1 skipped`；`ruff check atrade tests` All checks passed
7. 冒烟：`TrailingConfig.from_dict` 默认 / 按股 / 空值回退 / locked 不触发 四种路径行为正确

## 最终 commit
- 见 `git log -1` 输出（本轮内由 `docs(progress): ...` 和 `chore(config): ...` 提交）

## 用户期望 vs. 现状
- ✅ trailing 按股可配置（`take_profit_pct` / `stop_loss_pct`），未填回退默认 +3/-2
- ✅ 通过 web UI（锁利%/止损% 输入框）与 API（`PUT /api/t-settings/{symbol}`）实时更新
- ✅ 15:35 收盘日报顶部嵌入 T 复盘（胜率 / 盈亏比 / 最多 5 条明细；无成交显示「今日无已闭环 T 交易」）
- ✅ scheduler 始终从 holdings 派生做 T 股票，monitor symbols 仅叠加 trailing 覆盖

## 风险与遗留
- 实盘首份合并复盘待下个交易日 15:35 自动验收
- VPS `monitor.local.json` 中 `t_monitor.symbols=[]`，因此 `_derive_t_symbols` 直接使用 holdings，无需担心旧茅台/银行再出现
- 测试基线 324 比前轮 252 多约 72 项（trailing / t_state / t_replay / web / config 五组累计）
