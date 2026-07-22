# 2026-07-22 头部结论置顶 + 保守双阶段做T STATUS

- **总体状态：** 已完成
- **当前阶段：** 6. 收尾
- **当前步骤：** 等待远端同步
- **已完成：** 创建合并目录与 TODO；实现 `atrade/notify/headline.py` 头部渲染；实现 `atrade/monitor/t_confirmer.py` 双阶段确认；接入 TMonitorRunner；新增监控配置字段；新增 / 更新单测；全量测试 + ruff 通过；提交到 main
- **下一步：** git push origin + vps；标注两个上游 brainstorm 已结案
- **阻塞项：** 无
- **最后更新：** 2026-07-22 23:50（Asia/Shanghai）

## 决策摘要

- **头部格式**：每条通知首行加 `🔴 操作结论: 卖出 (置信: 强)` / `🟢 操作结论: 买入 (置信: 中)` / `🚨 操作结论: 止损` / `⏸️ 操作结论: 观望`。
- **双阶段**：候选信号先入队，连续 `confirm_bars` 根（默认 2）同向 K 线命中才升级为可推送；候选超过 `candidate_ttl_minutes`（默认 30）自动丢弃；`STOP_LOSS` 例外，立即推送。
- **可配置**：`config/monitor.json` 的 `t_monitor` 段新增 `confirm_bars` / `candidate_ttl_minutes`。
- **观测**：`TMonitorRunner.status_markdown()` 报告 候选 / 已确认 / 跳过 三类计数。
