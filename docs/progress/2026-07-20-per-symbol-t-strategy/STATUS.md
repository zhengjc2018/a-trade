# 2026-07-20 个股做 T 策略 STATUS

- **总体状态：** 已完成
- **当前阶段：** 实施完成，端到端验证通过
- **当前步骤：** 收尾与交付
- **已完成：** Task 1-8 全部落地；67 项测试全部通过；CLI 帮助正常；离线冒烟在 600522（中天科技）上生成 713 字节报告并包含 5 个必要章节
- **下一步：** 用户在 600522 等持仓上按需运行 `python3 scripts/run_per_symbol_report.py --portfolio` 拿到真实报告
- **阻塞项：** 无
- **最后更新：** 2026-07-20 22:10（Asia/Shanghai）

## 已锁定的边界

- 产出形态：D（策略报告 + 回测验证；CLI 按需，本地落盘）
- 数据范围：D（1 年日线 + 5/15/30/60 分钟线最近 30 个交易日）
- 指标集合：A + C + D（波动性 + 适配度 + 风险）
- 触发方式：D（`scripts/run_per_symbol_report.py --portfolio|--symbol`，不推送 QQ 群）
- 样例股票：中天科技（600522），成本 12.50，数量 2000

## 交付物

- 包：`atrade/per_symbol/`（volatility / adaptive / risk / styler / report）
- CLI：`scripts/run_per_symbol_report.py`
- 测试：`tests/test_{per_symbol_init,volatility,risk,adaptive,styler,report,run_per_symbol_report}.py` 共 17 项新增
- 设计文档：`docs/superpowers/specs/2026-07-20-per-symbol-t-strategy-design.md`
- 实施计划：`docs/superpowers/plans/2026-07-20-per-symbol-t-strategy.md`

## 验证结果

- `python3 -m pytest -q` → `67 passed, 2 warnings`（49 个原有 + 18 个新增）
- `python3 scripts/run_per_symbol_report.py --help` → 正常展示参数
- `python3 scripts/run_per_symbol_report.py --portfolio`（mock 环境）→ 报告含 5 个章节
- 真实冒烟：调用 `report_one("600522", ...)` 走真实 Sina K 线，生成 713 字符报告，`# 中天科技` / `## 1-5` 全在
- `git diff --check` → PASS

## 使用方式

```
# 全部持仓
python3 scripts/run_per_symbol_report.py --portfolio

# 单只
python3 scripts/run_per_symbol_report.py --symbol 600522 --cost 12.5 --qty 2000

# 自定义分钟线窗口
python3 scripts/run_per_symbol_report.py --portfolio --intraday-days 30
```

报告落到 `reports/per_symbol_<symbol>_<timestamp>.md`。

## 阶段进展

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 1. 头脑风暴上下文 | 已完成 | 已读现有审查与设计 |
| 2. 探索核心意图 | 已完成 | 4 个澄清问题全部答复 |
| 3. 候选方向与权衡 | 已完成 | 选择 D（报告+回测验证）作为本次目标 |
| 4. 设计文档与计划 | 已完成 | 设计 + TDD 计划已落盘并通过自检 |
| 5. 实施 Task 1-8 | 已完成 | 全部任务通过测试 |
| 6. 端到端验证 | 已完成 | pytest + CLI 帮助 + 真实冒烟 全绿 |
