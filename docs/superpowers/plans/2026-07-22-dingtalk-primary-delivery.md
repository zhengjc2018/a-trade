# DingTalk Primary Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all scheduled notifications through DingTalk first, fall back to QQ, persist delivery status, recover missed reports, and make no-signal T monitoring observable.

**Architecture:** Add a focused delivery package containing result models, a persistent ledger, and a primary/fallback router. Keep report generation unchanged; make `DailyScheduler` generate task-keyed messages and delegate delivery, recovery, retry, and guards to the new package.

**Tech Stack:** Python 3.9, APScheduler 3.x, requests, SQLite, pytest, existing DingTalk/OpenClaw notifiers.

## Global Constraints

- DingTalk is the primary channel; OpenClaw/QQ is fallback.
- Real tokens remain only in VPS `.env` and never enter Git or logs.
- A task is delivered only after a platform success response.
- A delivered `task_key` is idempotent and cannot be resent by guards or restart recovery.
- Failed deliveries retry every 5 minutes.
- Morning recovery deadline is 10:00; noon recovery deadline is 14:00; closing/news recover until end of day.
- T-monitor no-signal summaries run at 11:35 and 15:05 without changing the real-time scan interval.

---

### Task 1: Delivery Result and Error Contract

**Files:**
- Create: `atrade/notify/delivery.py`
- Modify: `atrade/notify/dingtalk.py`
- Test: `tests/test_delivery_contract.py`

**Interfaces:**
- Produces: `DeliveryError`, `DeliveryAttempt`, `DeliveryResult`, and strict DingTalk failure behavior.
- Consumes: Existing notifier `send_markdown(content, title=...)` responses.

- [ ] Write tests asserting `DeliveryResult.ok`, channel/message ID capture, and `DingTalkNotifier` raising `DeliveryError` for nonzero `errcode`.
- [ ] Run `python3 -m pytest tests/test_delivery_contract.py -q` and verify failure.
- [ ] Implement immutable dataclasses and strict response validation without logging secrets.
- [ ] Run `python3 -m pytest tests/test_delivery_contract.py -q` and verify pass.

### Task 2: Persistent Delivery Ledger

**Files:**
- Create: `atrade/notify/ledger.py`
- Test: `tests/test_delivery_ledger.py`

**Interfaces:**
- Produces: `DeliveryLedger(db_path)`, `record_attempt(...)`, `mark_delivered(...)`, `is_delivered(task_key)`, `pending_failures(limit)`.
- Consumes: `DeliveryAttempt` and `DeliveryResult` from Task 1.

- [ ] Write tests for delivered idempotency, failed attempt persistence, retry count, and pending query ordering.
- [ ] Run `python3 -m pytest tests/test_delivery_ledger.py -q` and verify failure.
- [ ] Implement SQLite table initialization and atomic upserts keyed by `task_key`.
- [ ] Run `python3 -m pytest tests/test_delivery_ledger.py -q` and verify pass.

### Task 3: DingTalk-First Router with QQ Fallback

**Files:**
- Create: `atrade/notify/router.py`
- Modify: `atrade/notify/__init__.py`
- Test: `tests/test_delivery_router.py`

**Interfaces:**
- Produces: `DeliveryRouter(primary, fallback, ledger).send(task_key, title, markdown) -> DeliveryResult`.
- Consumes: notifier adapters, `render_for_dingtalk`, byte-safe splitting, and ledger APIs.

- [ ] Write tests for primary success without fallback, primary failure/fallback success, dual failure persistence, and delivered-key idempotency.
- [ ] Run `python3 -m pytest tests/test_delivery_router.py -q` and verify failure.
- [ ] Implement channel-specific rendering and success validation; never swallow dual-channel failure.
- [ ] Run `python3 -m pytest tests/test_delivery_router.py -q` and verify pass.

### Task 4: Scheduler Integration and Task Keys

**Files:**
- Modify: `atrade/scheduler/runner.py`
- Test: `tests/test_scheduler_delivery.py`

**Interfaces:**
- Produces: `_deliver(task_name, title, markdown, day=None)` and stable keys `<task_name>:<YYYY-MM-DD>`.
- Consumes: `DeliveryRouter` from Task 3 and existing report generators.

- [ ] Write tests ensuring every report job calls the router, successful T delivery commits alerts, and failed delivery does not commit.
- [ ] Run `python3 -m pytest tests/test_scheduler_delivery.py -q` and verify failure.
- [ ] Replace direct botpy `_push_markdown` usage with router delivery while keeping botpy connected for fallback.
- [ ] Run `python3 -m pytest tests/test_scheduler_delivery.py -q` and verify pass.

### Task 5: Retry Queue and Missed-Task Recovery

**Files:**
- Create: `atrade/scheduler/recovery.py`
- Modify: `atrade/scheduler/runner.py`
- Test: `tests/test_notification_recovery.py`

**Interfaces:**
- Produces: `RecoveryPolicy`, `recover_missed_tasks(now, ledger, callbacks)`, and retry callback behavior.
- Consumes: ledger pending failures and scheduler report callbacks.

- [ ] Write clock-controlled tests for 08:30 morning recovery, 10:01 morning skip, 13:00 noon recovery, same-day closing/news recovery, and no duplicate after delivery.
- [ ] Run `python3 -m pytest tests/test_notification_recovery.py -q` and verify failure.
- [ ] Implement pure recovery decision functions and register startup recovery plus five-minute retry job.
- [ ] Run `python3 -m pytest tests/test_notification_recovery.py -q` and verify pass.

### Task 6: Heartbeat, Guards, and No-Signal Summaries

**Files:**
- Modify: `atrade/scheduler/runner.py`
- Modify: `atrade/monitor/t_monitor.py`
- Test: `tests/test_delivery_guards.py`

**Interfaces:**
- Produces: heartbeat at 07:55, delivery guards, and T-monitor summaries at 11:35/15:05.
- Consumes: router/ledger state and T-monitor scan counters/errors.

- [ ] Write tests for heartbeat content, guard resending only missing tasks, no-signal summary, and scan-error summary.
- [ ] Run `python3 -m pytest tests/test_delivery_guards.py -q` and verify failure.
- [ ] Register cron jobs with `coalesce=True` and explicit `misfire_grace_time`; add T-monitor daily counters.
- [ ] Run `python3 -m pytest tests/test_delivery_guards.py -q` and verify pass.

### Task 7: Configuration and Regression Verification

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/progress/2026-07-22-notification-delivery-brainstorm/TODO.md`
- Modify: `docs/progress/2026-07-22-notification-delivery-brainstorm/STATUS.md`

**Interfaces:**
- Produces: documented environment contract and final verification evidence.
- Consumes: all prior tasks.

- [ ] Add notifier routing variables and recovery schedule documentation without real secrets.
- [ ] Run focused tests: `python3 -m pytest tests/test_delivery_contract.py tests/test_delivery_ledger.py tests/test_delivery_router.py tests/test_scheduler_delivery.py tests/test_notification_recovery.py tests/test_delivery_guards.py -q`.
- [ ] Run full tests: `python3 -m pytest -q`.
- [ ] Run lint: `python3 -m ruff check atrade/ tests/`.

### Task 8: VPS Configuration and Live Acceptance

**Files:**
- Modify on VPS only: `/opt/a-trade/.env`

**Interfaces:**
- Produces: deployed DingTalk-first scheduler with verified real delivery.
- Consumes: user-provided DingTalk token and keyword `股票`.

- [ ] Commit implementation and push `main` to GitHub and VPS.
- [ ] Set `NOTIFY_PRIMARY=dingtalk`, `NOTIFY_FALLBACK=openclaw`, `DINGTALK_ACCESS_TOKEN`, and `DINGTALK_KEYWORD=股票` on VPS without printing secrets.
- [ ] Restart `a-trade.service` and verify `systemctl is-active a-trade.service` returns `active`.
- [ ] Manually trigger heartbeat and morning report; verify DingTalk `errcode=0` and ledger `delivered` rows.
- [ ] Verify scheduler lists 07:55 heartbeat, 08:00 early report, guards, retry job, and 11:35/15:05 T summaries.
