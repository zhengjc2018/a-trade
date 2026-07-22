# 2026-07-22 头部结论置顶 + 保守双阶段做T TODO

**目标：** 把 2026-07-21-notification-priority-output 与 2026-07-21-t-message-accuracy-brainstorm 合并落地：
1. 所有通知首屏展示明确的买/卖/止损/观望结论与置信度。
2. 做 T 监控增加连续确认门槛（候选 → 确认两阶段），减少误报。

**状态说明：** `[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

## 1. 准备

- [x] 创建本次 TODO 与 STATUS 文件
- [x] 复用 2026-07-21 两个 brainstorm 文档结论
- [x] 确认当前 T 信号引擎、monitor、scheduler 的耦合点

## 2. 头部结论渲染

- [x] 新增 `atrade/notify/headline.py`：结论 → 头部行
- [x] 在 `atrade/monitor/t_monitor.py` 的 `to_markdown` 中置顶结论
- [x] 同步 `status_markdown()` 在无信号时显式标注"观望"
- [x] 写 `tests/test_headline.py`：BUY / SELL / STOP_LOSS / WATCH / NO_SIGNAL 渲染

## 3. 保守双阶段确认

- [x] 新增 `atrade/monitor/t_confirmer.py`：候选入队 → 连续 K 根确认才放行
- [x] 默认 BUY / SELL 需 2 根同向 K 线确认；STOP_LOSS 强制放行
- [x] 候选过期时间 30 分钟
- [x] 在 `TMonitorRunner.run_once()` 串入 confirmer
- [x] 在 `TMonitorRunner` 增加 `pending_count` / `confirmed_count` 计数
- [x] 写 `tests/test_t_confirmer.py`：候选入队、确认、过期、放行 STOP_LOSS

## 4. 集成与可配置

- [x] 在 `config/monitor.json` 增加 `t_monitor.confirm_bars` 与 `t_monitor.candidate_ttl_minutes`
- [x] 在 `atrade/config.py` 校验新字段（默认 2 / 30）
- [x] `status_markdown()` 报告候选数 / 已确认数 / 跳过数

## 5. 验证

- [x] `python3 -m pytest -q` 全绿
- [x] `python3 -m ruff check atrade/ tests/` 全绿
- [x] 手动渲染样例：买入强 / 卖出强 / 观望三条样例

## 6. 收尾

- [x] 更新两个上游 brainstorm 文档指向本目录
- [x] 提交并同步 origin + vps
- [x] 标记本次 STATUS 完成
