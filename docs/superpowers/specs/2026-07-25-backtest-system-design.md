# 2026-07-25 T+0 回测系统化 设计

## 1. 背景

目前已经有可工作的回测能力：
- `atrade/backtest/t0_simulator.py` — 事件驱动守恒账本 + 真实手续费 + 5 个因子
- `scripts/run_backtest.py` — CLI 入口，支持单股 / `--portfolio`

但作为"系统"还有三个缺口：
1. **入口不方便**：只能 SSH 到 VPS 跑 CLI
2. **结果覆盖**：每次跑覆盖 `reports/backtest_<symbol>_<stamp>.md`，没历史
3. **不能验证参数选择**：用户拍脑袋 +3% / -2%，没用网格扫描回测验证

## 2. 目标

**AC 一并交付**：
- A — Web/API + 钉钉推送
- C — 锁利/止损参数网格扫描，自动建议覆盖 `trailing_defaults` 和每只股覆盖

**非目标（本轮不做）**：
- 实时自动重跑（B 项）
- 因子自身调参
- 多账号/组合层优化

## 3. 架构

```
atrade/backtest/
├── t0_simulator.py       # 保持不变
├── storage.py            # 新增：BacktestJobStore + ReportStore
├── jobs.py               # 新增：BacktestRunner + JobStatus 状态机
├── sweep.py              # 新增：参数网格扫描 + Pareto 排名
└── api.py                # 新增：FastAPI 路由

scripts/run_backtest.py    # CLI 改为钉钉推送 + sweep 入口
atrade/web/app.py          # 注册 backtest 路由
atrade/scheduler/runner.py # 不动

数据落盘：
data/backtest/
├── jobs.json            # 所有 job 元数据索引（读写锁）
├── jobs/<job_id>/       # 每个 job 一份（状态、日志、产物）
└── reports/             # 最终报告 Markdown（不覆盖）

reports/backtest/        # 兼容 scripts CLI 的旧路径（保留）
```

## 4. API 设计

```
POST /api/backtest/run
  body: {
    symbol: str,                      # 必需
    cost_price: float,                # 必需
    quantity: int,                    # 必需
    start_date: str = "2024-01-01",
    end_date: str = "today",
    scale: str = "1d",
    sweep: bool = False,
    push: bool = True                 # 跑完推送到主通道
  }
  → 202 { job_id, status: "queued" }

POST /api/backtest/portfolio
  body: {
    start_date, end_date, scale, sweep, push
  }
  → 202 { job_id, total: N }           # 自动按 holdings

GET /api/backtest/jobs/{job_id}
  → { job_id, status: "running"|"completed"|"failed", progress: 0..1,
      result_summary?, error?, created_at, finished_at, symbol }

GET /api/backtest/jobs?symbol=600522&limit=10&status=completed
  → [{ job_id, symbol, status, created_at, summary_metrics }]

GET /api/backtest/report/{job_id}
  → Markdown 文本 or { path: "data/backtest/reports/..." }
```

## 5. 状态机

```
queued --[runner.take()]--> running --[ok]--> completed
                                  --[err]--> failed
completed 内的 sweep 任务还可细分：
  - 单股作业 100% 完成即 done
  - sweep 网格：每个组合结束累计 progress，全完才 done
```

## 6. Sweep 网格

锁利候选 `[0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]`（7 档）
止损候选 `[0.01, 0.02, 0.03, 0.04, 0.05]`（5 档）
默认 35 个组合 / 单只股，时间 OK（每组合 < 1s，10 分钟内跑完 2-3 只）

排名规则：
- **门槛**：胜率 ≥ 60%（与现在线上"减少误报，宁可少做"原则一致）
- **优先**：T 净收益 + 胜率 × log(笔数)（防高频刷单的高胜率）
- **Top 3 推荐** 入报告

**关键决策**：现有 `T0Simulator` 没有 take_profit/stop_loss 注入点。两种路径：
- (i) 给 `T0Simulator` 加 `take_profit_pct`/`stop_loss_pct` 参数，把 `force_close_loss_pct` 复用
- (ii) 在 sweep 层用 wrapper：跑 `run()` 后再人工检查每笔 T 仓的出场价，按阈值补齐统计

选择 **(i)**：扩展 `T0Simulator` 最小侵入，向后兼容（旧调用默认 `take_profit=None` 走原逻辑）。

## 7. 钉钉推送格式

```
📊 回测报告 [600522] @ ~61.86
- 区间：2024-01-01 ~ 2026-07-25
- T 净额：+127.45 元（已扣费用）
- 胜率：62%（13 胜 / 8 负）
- vs 死拿：-3.20%（中性）
- 报告：data/backtest/reports/backtest_600522_<job_id>.md

[扫到 3 个优组合]
锁利+3% / 止损-2%：胜率 65%，T +210 元  ← 推荐
锁利+5% / 止损-3%：胜率 60%，T +180 元
...
```

## 8. 失败 / 边界

- **数据不足**：< 30 根 K 线 → `failed` 状态，`error: "数据不足"`
- **股票代码不存在**：`failed`，`error: "<code> 行情拉取失败"`
- **并发出闸**：单实例串行（避免天天跑雪球）— 队列 + 信号量
- **磁盘占用**：`data/backtest/reports/*.md` 总量 > 50MB 时按时间最旧清理

## 9. 测试

- `tests/test_backtest_storage.py`：job 元数据读写、报告落盘
- `tests/test_backtest_sweep.py`：网格扫描 → 排名 → Pareto 输出
- `tests/test_backtest_jobs.py`：state machine 转换、并发串行化
- `tests/test_backtest_api.py`：3 个 HTTP 接口用 FastAPI TestClient
- `tests/test_run_backtest_cli.py`：CLI 参数 → 推动 push 路径

## 10. 风险与权衡

- **不实盘跑**：纯历史回测，不影响线上因子 / 信号引擎
- **VPS 资源**：单 sweep job 内存峰值 < 200MB，CPU 占用 < 2s/股
- **并发限制**：本实例一次只跑 1 个 job，避免雪球接口限频
- **API 鉴权**：与现有 holdings/t-settings 一致 — `require_bearer` 中间件

