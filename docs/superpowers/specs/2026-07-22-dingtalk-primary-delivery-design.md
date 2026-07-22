# 钉钉主通道与通知必达保障设计

## 1. 目标

将钉钉设为所有定时通知的主通道，QQ 设为自动降级通道；对早报、午报、收盘日报、持仓新闻、盘中选股和做 T 信号建立统一的送达回执、失败重试、漏发补发和可观测状态，避免“服务正常但用户收不到消息”。

## 2. 已确认故障

- 2026-07-22 VPS 服务于 12:18 才启动，08:00 早报已经错过，APScheduler 默认不会补发。
- 做 T 监控在 13:14 至 13:28 多次生成候选告警，但 QQ 推送等待 10 秒后超时。
- `DailyScheduler._push_markdown()` 捕获异常后不向调用者抛出，外层无法区分成功、部分成功和失败。
- VPS 仅配置 QQ 凭据，没有钉钉 token；定时任务没有接入 `DingTalkNotifier`。
- 无做 T 信号时完全静默，用户无法判断是“没有信号”还是“任务没有执行”。

## 3. 通知架构

新增 `DeliveryRouter` 作为调度器唯一通知入口：

1. 优先调用 `DingTalkNotifier`。
2. 钉钉成功时记录消息回执并停止。
3. 钉钉失败、超时或返回非零 `errcode` 时自动调用 QQ notifier。
4. 两个通道均失败时写入失败队列，由独立重试任务每 5 分钟重试。
5. 调度任务只能根据 `DeliveryResult.ok` 判断送达，不再依赖被吞掉的异常。

所有消息保留现有 Markdown 内容，钉钉发送前执行 `render_for_dingtalk()`；消息按 UTF-8 字节安全切分。

## 4. 送达账本

新增持久化送达记录，字段包括 `task_key`、`task_name`、计划/生成/送达时间、通道、状态、尝试次数、最后错误、平台消息 ID 和消息摘要哈希。

状态包括 `pending`、`delivered`、`failed`、`skipped_no_signal`。同一 `task_key` 成功后不得重复发送；失败记录保留并可重试。

## 5. 调度与补发

- `07:55 delivery_heartbeat`：发送当天调度就绪、主通道和计划任务列表。
- `08:00 morning_brief`。
- `08:05 morning_delivery_guard`：若早报未送达则立即补发。
- `12:35 noon_delivery_guard`、`15:35 closing_delivery_guard`、`17:05 news_delivery_guard`。
- `*/5 retry_failed_deliveries`：重试失败队列。
- 服务启动时执行 `recover_missed_tasks()`：早报可补发至 10:00，午报可补发至 14:00，收盘日报和新闻可在当日补发。

APScheduler 任务配置 `misfire_grace_time` 与 `coalesce=True`，避免短暂停机后永久丢失或重复触发。

## 6. 做 T 无信号可观测性

- 有信号：实时发送做 T 消息，成功后才提交信号去重状态。
- 无信号：实时扫描仍不刷屏；在 11:35 和 15:05 各汇总一次“当前无满足执行门槛的做 T 信号”。
- 扫描失败：发送故障摘要而不是伪装成无信号。
- 告警消息第一屏按后续“结论置顶”设计展示操作方向；该格式优化与本次送达保障解耦。

## 7. 配置与安全

VPS `.env` 增加 `NOTIFY_PRIMARY=dingtalk`、`NOTIFY_FALLBACK=openclaw`、`DINGTALK_ACCESS_TOKEN`、`DINGTALK_KEYWORD=股票` 和可选 `DINGTALK_SECRET`。

真实 token 仅写入 VPS `.env`，不进入 Git、日志、状态文件或测试快照。

## 8. 错误处理

- `DingTalkNotifier` 对平台非零错误码抛出明确错误。
- QQ 推送必须返回成功消息 ID，否则视为失败。
- 调度推送不再吞异常；路由层统一形成送达尝试结果。
- 日志包含任务 key、通道、尝试次数、平台响应码和耗时，不记录 token 或完整 webhook。

## 9. 测试与验收

单元测试覆盖钉钉成功、QQ 降级、两通道失败、重试成功、任务去重、服务晚启动补发、无信号汇总和做 T 送达后提交。

部署后必须验证真实钉钉 `errcode=0`、VPS 服务 active、任务下次时间正确、手动心跳/早报送达及账本 delivered，并在下一交易日核验 07:55 和 08:00 自然触发。

## 10. 明日成功标准

- 07:55 收到钉钉调度心跳。
- 08:00 收到钉钉早报；08:05 guard 能发现并补发漏报。
- 盘中有做 T 信号时实时送达；无信号时 11:35/15:05 收到状态汇总。
- 每次送达均有账本记录；失败自动重试并记录明确错误。
