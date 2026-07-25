# 2026-07-25 T+0 回测系统化 TODO

**范围：** A — Web/API + 钉钉推送；C — 锁利/止损参数网格扫描  
**设计：** `docs/superpowers/specs/2026-07-25-backtest-system-design.md`  
**计划：** `docs/superpowers/plans/2026-07-25-backtest-system.md`

## Phase 1 — 基础设施（storage + jobs）
- [ ] BacktestJobStore：data/backtest/jobs.json 原子读写
- [ ] ReportStore：单 .md 落盘到 data/backtest/reports/
- [ ] Job dataclass + JobStatus enum
- [ ] BacktestRunner：threading.Semaphore=1 串行化
- [ ] test_backtest_storage.py + test_backtest_jobs.py

## Phase 2 — Sweep 网格
- [ ] T0Simulator 增加 take_profit_pct / stop_loss_pct 参数（向后兼容）
- [ ] SweepGrid + run_sweep + Pareto 排名
- [ ] SweepResult.to_markdown()
- [ ] 测试：t0_simulator 新参数 + sweep 排名

## Phase 3 — CLI + 通知
- [ ] scripts/run_backtest.py 加 --sweep/--push（默认走钉钉）
- [ ] DingTalkNotifier.send_job_result() (可选增强)
- [ ] CLI 测试覆盖

## Phase 4 — Web API
- [ ] atrade/backtest/api.py 4 个端点
- [ ] atrade/web/app.py 注册路由
- [ ] web/static 增加 📊 回测按钮 + 对话框
- [ ] test_backtest_api.py 用 TestClient

## Phase 5 — 验证 + 上线
- [ ] pytest 全过
- [ ] ruff check atrade tests
- [ ] 本地 web 端到端：单股 + sweep + 推送
- [ ] 提交 + 推 VPS + 推 GitHub
- [ ] STATUS 文档完成

