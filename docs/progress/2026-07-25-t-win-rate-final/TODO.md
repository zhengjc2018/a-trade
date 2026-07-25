# 2026-07-25 T 胜率优化收尾 TODO

**目标：** 把 trailing per-symbol 可配置 + 15:35 复盘合并 这一轮完全收尾，本地/VPS 双端配置同步、清理运行时产物、推送代码并提交状态文档。

**状态说明：** `[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

## 1. 锁定决策（来自上下文 checkpoint）
- [x] trailing 按股可配置，不填默认 +3% / -2%；通过 web/API 更新
- [x] 大盘双闸门（MA20<MA60 屏蔽 BUY；5 日跌幅 < -3% 屏蔽普通信号；STOP_LOSS/锁利 始终放行）
- [x] 复盘合并到 15:35 收盘日报顶部；09:30 reset
- [x] holdings 是 T 监控唯一股票源，monitor symbols 仅叠加 trailing 覆盖
- [x] 钉钉为主通道；web Bearer token 保留开关

## 2. 配置同步
- [ ] 本地 `config/holdings.local.json` 替换为 兴森 002436 + 中天 600522
- [ ] 本地 `config/monitor.local.json` 清空旧茅台/紫金 symbols，加 `trailing_defaults: {0.03, 0.02}`
- [ ] VPS `monitor.local.json` 补 `trailing_defaults` 字段
- [ ] VPS 重启 a-trade.service / a-trade-web.service

## 3. 运行时产物清理
- [ ] `a_trade.egg-info/`
- [ ] `data/cache/stock.db` `data/cache/t_state.json` `data/cache/t_monitor_state.json`

## 4. 验证
- [ ] `pytest` 全过
- [ ] `ruff check atrade tests` 全过
- [ ] VPS `load_holdings` / `load_monitor_config` 返回预期
- [ ] VPS 日志无 traceback

## 5. 推送
- [ ] GitHub：HTTP/1.1 重试直到成功
- [ ] VPS：`git push vps main` 触发 post-receive 自动重启
- [ ] STATUS 文档更新提交

