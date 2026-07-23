# 2026-07-23 T 信号自动执行 TODO

**目标：** T 信号默认自动执行；SELL 自动减仓；防止一日内反复卖。

**状态说明：** `[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

## 1. 设计

- [x] auto_execute 开关（默认 true）
- [x] 单只每日 1 次 SELL/STOP_LOSS
- [x] SELL/STOP_LOSS 持仓不足 → 跳过
- [x] BUY 仅记账不减仓

## 2. 模块

- [x] `atrade/monitor/t_executor.py`：execute(alert) → Trade
- [x] `data/cache/t_trades.json`：trade log
- [x] TMonitorRunner 过滤 quantity <= 0
- [x] scheduler _job_t_monitor 调用 executor

## 3. 配置

- [x] `t_monitor.auto_execute: true`
- [x] `t_monitor.lots_per_trade: 1`

## 4. 通知

- [x] 头部结论加 `✅ 已自动执行 X 手`

## 5. UI/API

- [x] `GET /api/t-trades`（今日）
- [x] UI 加「今日成交」section

## 6. 测试

- [x] tests/test_t_executor.py
- [x] tests/test_t_trades_api.py
- [x] 全量测试 + ruff

## 7. 部署

- [x] push origin + vps
- [x] VPS 重启服务
