# 2026-07-25 钉钉通知醒目度优化 TODO

**目标：** 让早晨/午盘/收盘/持仓新闻 等非 t_monitor 类任务在钉钉 App 里不再被折叠 / 不再被忽略。

## Phase 1 — DingTalk 渲染层增强
- [ ] `atrade/notify/dingtalk.py` 增加 `render_banner(title, subtitle, level)` 工具
- [ ] `send_markdown` 增加 `at_all: bool = None` 覆盖默认
- [ ] `DingTalkNotifier` 接受入参 `priority` / `category`（钉钉 markdown 不支持，但加 banner 用 emoji + 加粗替代）

## Phase 2 — Router / Delivery 透传
- [ ] `atrade/notify/delivery.py` 增 `DeliveryAttempt.at_all` / `sent_via` 字段
- [ ] `atrade/notify/router.py` 接收 `at_all` 参数并传给 notifier

## Phase 3 — Runner 改造
- [ ] `_deliver` 默认在 markdown 顶部插横幅（基于 task_name + 当前时间）
- [ ] morning_brief / auction_analysis / noon_report / closing_report / holdings_news 默认 at_all=True
- [ ] t_monitor 保持 at_all=False（避免 2 分钟一次 @ 全体骚扰）

## Phase 4 — Banner 与唯一性
- [ ] banner 含任务名 + 时间戳 + emoji + 显眼加粗
- [ ] router 内 task_key 增加精确到分钟的后缀避免同日重复 dedup

## Phase 5 — 验证 + 推送
- [ ] pytest 通过
- [ ] ruff 通过
- [ ] 手动推送一条增强后的 noon_report 验证钉钉渲染
- [ ] 推 VPS + GitHub

