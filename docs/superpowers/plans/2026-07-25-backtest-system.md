# 2026-07-25 T+0 回测系统化 实施计划

**依赖**：spec 已批准 `docs/superpowers/specs/2026-07-25-backtest-system-design.md`
**进度文件**：`docs/progress/2026-07-25-backtest-system/{TODO.md, STATUS.md}`

## Phase 1 — 基础设施（storage + jobs）

| 步骤 | 文件 | 说明 |
|---|---|---|
| 1.1 | `atrade/backtest/__init__.py` | 导出新模块 |
| 1.2 | `atrade/backtest/storage.py` | `BacktestJobStore`：原子读写 `data/backtest/jobs.json`，列表/详情/状态更新 |
| 1.3 | `atrade/backtest/storage.py` | `ReportStore`：单 .md 落盘到 `data/backtest/reports/<job_id>.md` |
| 1.4 | `atrade/backtest/jobs.py` | `Job` dataclass + `JobStatus` enum（queued/running/completed/failed/cancelled） |
| 1.5 | `atrade/backtest/jobs.py` | `BacktestRunner`：单线程串行化（threading.Semaphore=1），提供 `submit / status / cancel` |
| 1.6 | `tests/test_backtest_storage.py` | jobs.json round-trip + 并发安全 |
| 1.7 | `tests/test_backtest_jobs.py` | state transitions + cancel |

## Phase 2 — Sweep 网格

| 步骤 | 文件 | 说明 |
|---|---|---|
| 2.1 | `atrade/backtest/t0_simulator.py` | 给 `T0Simulator` 加 `take_profit_pct`/`stop_loss_pct` 参数，向后兼容；改动 `force_close_loss_pct` 用法 |
| 2.2 | `atrade/backtest/sweep.py` | `SweepGrid` dataclass + `run_sweep(symbol, cost, qty, take_profits, stop_losses)` |
| 2.3 | `atrade/backtest/sweep.py` | Pareto 排名：胜率门槛 + 综合得分 |
| 2.4 | `atrade/backtest/sweep.py` | `to_markdown()` 输出表格 + 推荐覆盖块 |
| 2.5 | `tests/test_backtest_sweep.py` | 已知 fixture 验证排名正确性 |
| 2.6 | `tests/test_t0_simulator.py` | 补 take_profit/stop_loss 路径单测 |

## Phase 3 — CLI & 通知

| 步骤 | 文件 | 说明 |
|---|---|---|
| 3.1 | `scripts/run_backtest.py` | 添加 `--sweep` 和 `--push`（默认钉钉） |
| 3.2 | `atrade/notify/dingtalk.py` | 已有 DingTalkNotifier，增加 `send_job_result()` 方法（带 @ 文本） |
| 3.3 | `tests/test_run_backtest_cli.py` | 关键参数解析 + push 模拟 |

## Phase 4 — Web API

| 步骤 | 文件 | 说明 |
|---|---|---|
| 4.1 | `atrade/backtest/api.py` | 路由 helper：`run_job / portfolio / jobs / report` |
| 4.2 | `atrade/web/app.py` | `app.include_router(backtest_router, ...)` 4 个端点 |
| 4.3 | `atrade/web/static/index.html` + `app.js` | 增加「📊 回测」按钮 + 单股回测对话框 + 历史列表 |
| 4.4 | `tests/test_backtest_api.py` | FastAPI TestClient 覆盖 4 个端点 |

## Phase 5 — 验证与上线

| 步骤 | 说明 |
|---|---|
| 5.1 | `pytest` 全过（含新增 ~30 项） |
| 5.2 | `ruff check atrade tests` |
| 5.3 | 本地起 web，跑 `POST /api/backtest/run` 单股 600522，验证返回 + 状态 |
| 5.4 | 本地起 web，跑 `POST /api/backtest/run {sweep:true}` 验证网格推荐 |
| 5.5 | 提交 + 推 VPS + 推 GitHub（HTTP/1.1） |
| 5.6 | STATUS 文档更新 |

## Risk & Rollback

- 每次回测跑历史 K 线，不动 `t_monitor` / `t_state` 任何线上数据
- 单实例串行避免触发雪球接口限频；用户跑两次会排队，不会崩
- 报错时 jobs 状态保留可查，不会丢日志

