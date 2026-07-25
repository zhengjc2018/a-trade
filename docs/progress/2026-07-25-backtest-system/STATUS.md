# 2026-07-25 T+0 回测系统化 STATUS

- **总体状态：** 全部完成 ✅
- **完成时间（本地）：** 2026-07-25 17:34 CST

## 已完成

### Phase 1 — 基础设施
- BacktestJobStore（jobs.json 原子读写 + 并发安全 + status/symbol/limit 过滤）
- ReportStore（report 落盘 + 容量清理）
- BacktestRunner（threading.Semaphore 串行 + state machine + cancel）
- T0JobRequest / SweepRequest（含字段校验：symbol 必须严格 6 位）
- 8 项 storage + 8 项 jobs 单测

### Phase 2 — Sweep 网格
- T0Simulator 注入 `take_profit_pct` / `stop_loss_pct` 注入点（向后兼容：None 走旧路径）
- SweepGrid（24 个默认组合，max_combos 兜底）
- 综合评分（胜率奖励 + 净收益 + 笔数门槛）
- 排名规则：胜率 ≥ 60% + 笔数 ≥ 2 + 综合得分
- 8 项 sweep 单测 + 3 项 T0Simulator 新注入测试

### Phase 3 — CLI + 推送
- `scripts/run_backtest.py` 加 `--sweep` / `--take-profit` / `--stop-loss`
- `--push` 默认走钉钉（不再 openclaw）
- 3 项 CLI 测试

### Phase 4 — Web API + UI
- 5 个新端点：`POST /run`、`POST /portfolio`、`GET /jobs/{id}`、`GET /jobs`、`GET /report/{id}`
- 集成到现有 FastAPI，附带 Bearer auth 复用
- Runner 捕获 executor 返回值写入 `summary` / `report_path`
- HTML/JS：📊 回测按钮 + 对话框（单股/组合）+ 历史列表
- 9 项 API 集成测试

### Phase 5 — 验证
- pytest：`362 passed, 1 skipped, 1 warning`（原 324 + 新 38）
- ruff：`All checks passed`
- 端到端冒烟：单股 + portfolio + lifecycle + report list 全部通过

## 测试基线
- 之前：324 passed
- 现在：362 passed（新增 38 项：storage 8、jobs 8、sweep 8、t0_simulator 3、CLI 3、API 9、相邻新增）

## API 形态概览
```
POST /api/backtest/run       单股 + 可选 sweep
POST /api/backtest/portfolio 持仓组合 sweep
GET  /api/backtest/jobs      列表（symbol / status 过滤）
GET  /api/backtest/jobs/{id} 单个 job 详情
GET  /api/backtest/report/{id} 报告 Markdown
```
所有端点继承 Bearer auth；提交即返回 job_id；job 在独立线程执行；runner 串行化避免雪球限频。

## 数据落盘
```
data/backtest/
├── jobs.json                # job 元数据
└── reports/
    └── backtest_<job_id>.md # 单报告（永不覆盖）
```

## 风险与遗留
- 端口 8765 上的 web admin 暴露公网 — `A_TRADE_WEB_TOKEN` 失效后任何人可访问，请确保 token 开启
- 单 job 跑完 sweep 需要 < 2 分钟（24 组合 × 每只股 ≈ 1s）；持仓组合扫描在 VPS 上体验稍慢
- 回测拉真实行情，依赖东方财富可用性（与 t_monitor 同源）
- 本机 → GitHub 推送继续走 HTTP/1.1 重试策略

