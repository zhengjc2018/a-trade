# 2026-07-25 T 胜率优化收尾 STATUS

- **总体状态：** 全部完成 ✅
- **完成时间（本地）：** 2026-07-25 14:43 CST
- **最终 commit：** `84cb6e8` (chore(ignore): cache t_state under data/cache/)
- **父提交：** `732cd4c` feat(report): merge daily T review into 15:35 close

## 已完成
1. 本地 `config/holdings.local.json` 替换为真实持仓：002436 兴森 100@41.093 + 600522 中天 200@61.863
2. 本地 `config/monitor.local.json` 清空旧茅台/紫金 symbols，加 `trailing_defaults: {0.03, 0.02}` 显式字段
3. VPS `monitor.local.json` 同步显式 `trailing_defaults`，并 `systemctl restart a-trade a-trade-web`，两服务均 `active`
4. VPS 端冒烟：`/api/health` ok=true，`/api/holdings` 返回 2 只真实持仓 + trailing_defaults，journalctl 无 traceback
5. 运行时产物清理：`a_trade.egg-info/` 删除；`.gitignore` 加上 `data/cache/` 兜底
6. 验证：pytest `324 passed, 1 skipped`；`ruff check atrade tests` All checks passed
7. 冒烟 `TrailingConfig.from_dict`：默认 / 按股 / 空值回退 / locked 不触发 四种路径行为正确
8. VPS 推送：`git push vps main` 触发 post-receive 自动重启
9. GitHub 推送：HTTPS 重试 4 次（第 4 次成功），commit `614fd6a..84cb6e8 main -> main`

## 代码 → 用户期望映射
- ✅ trailing 按股可配置（`take_profit_pct` / `stop_loss_pct`），未填回退默认 +3 / -2
- ✅ 通过 web UI（卡片锁利%/止损% 输入框）与 API（`PUT /api/t-settings/{symbol}`）实时更新；空值视为回退默认
- ✅ scheduler 始终从 holdings 派生做 T 股票，monitor symbols 仅叠加 trailing 覆盖，避免旧茅台/银行再次主导
- ✅ 15:35 收盘日报顶部嵌入 T 复盘（胜率 / 盈亏比 / 最多 5 条明细；无成交显示「今日无已闭环 T 交易」）
- ✅ 09:30 显式 reset T 仓状态、20:00 自然换日；STOP_LOSS/锁利不受大盘双闸门阻断
- ✅ 钉钉主通道；web Bearer token 保留开关（环境变量 `A_TRADE_WEB_TOKEN` 启用）

## GitHub 不稳定的根因
- 本机 `github.com:443/HTTPS` 期间频繁 `Connection reset / Failed to connect after 75s`
- `curl -I https://api.github.com` 通，但 `https://github.com/.../info/refs` 走 git 协议时拿不到回复
- 重试 4 次成功，并未引入新依赖或重写远程 URL

## 风险与遗留
- 实盘首份合并复盘待下个交易日 15:35 自动验收
- 本机 → GitHub 推送仍是不稳定通道，建议加 GH_TOKEN 或配置 SSH key 作为后续优化项
