# 2026-07-25 钉钉通知醒目度优化 STATUS

- **总体状态：** ✅ 完成
- **完成时间（本地）：** 2026-07-25 19:30 CST
- **最终 commit：** `4246642 feat(notify): banner + at_all auto for daily tasks`
- **前一 commit：** `02c2999 feat(backtest): Web/API + sweep grid system`

## 已完成（全部 5 个 Phase）

### Phase 1 — DingTalk 渲染层
- `DingTalkNotifier.send_markdown(at_all=None)` at_all 可覆盖默认
- `render_banner(task_name, subtitle)` 11 个 task name → emoji + 加粗标题
- `render_for_dingtalk` 表格转换保持兼容

### Phase 2 — Router / Delivery 透传
- `DeliveryAttempt` 增加 `at_all` 字段
- `DeliveryRouter.send(at_all=None)`、`set_default_at_all()`
- `_safe_send(notifier, content, title, at_all)` 使用 inspect 兼容 Mock

### Phase 3 — Runner 自动横幅
- `DailyScheduler.AT_ALL_TASKS` = frozenset，列出 `morning_brief/auction_analysis/noon_report/closing_report/holdings_news/t_status_morning/t_status_closing`
- `_deliver` 顶部自动插 banner（任务 + 时间 + 副标题）
- `t_monitor` 保持 `at_all=False`（2 分钟一次不 @ 全体）

### Phase 4 — task_key 去重
- `_deliver` 默认 unique_suffix = 当前 HHMM 分钟
- 手动重发可传 `unique_suffix=":manual1"` 等进一步唯一化

### Phase 5 — 验证 + 推送
- pytest：**376 passed, 1 skipped**（原 362 + 14 新增）
- ruff：`All checks passed`
- VPS post-receive 自动 restart `a-trade + a-trade-web`
- 手动从 VPS 推送一条带 banner + at_all 的 noon_report 测试，errcode=0
- GitHub 第 4 次重试成功（commit 02c2999..4246642）

## 用户体验路径

- ✅ 早盘 / 午盘 / 收盘 / 竞价 / 持仓新闻 / 上午收盘汇总：从本 cron tick 开始每条顶部有醒目 banner + 自动 @ 全体，手机通知栏必弹
- ✅ t_monitor（盘中实时信号）：保持静默推送，不 @ 全体，避免骚扰
- ✅ 同一分钟内的手动重发：task_key 自动区分，不会被 dedup

## 测试覆盖

新增 14 项：
- `tests/test_dingtalk_banner.py`（7 项）：render_banner 映射、所有任务 emoji、render_for_dingtalk 表格兼容
- `tests/test_dingtalk_runner_banner.py`（7 项）：_deliver 默认 at_all、t_monitor 不 at_all、banner 插入、task_key 包含 HHMM、未知任务兜底

## 风险

- 一天一次的"重要"通知首次推送时会弹 @ 全体，可能会让一些人在群聊里点开觉得"吵"，但比"看不见"强
- 如果你只想看推送内容不长 banner 噪音，可在 `AT_ALL_TASKS` 里移除对应 task_name

