# 2026-07-20 通知修复验证 STATUS

- **总体状态：** 已完成
- **当前阶段：** 5. 修复与回归
- **当前步骤：** 验证全部通过，等待次日定时任务自然触发
- **已完成：** 服务存活、botpy READY、6 个任务注册、OpenClaw 主动推送一条消息成功
- **下一步：** 明日 08:00 早盘快讯、12:30 午盘、15:30 收盘日报、17:00 持仓新闻自然触发
- **阻塞项：** 无
- **最后更新：** 2026-07-20 21:10（Asia/Shanghai）

## 验证结果

| 项 | 结果 | 证据 |
| --- | --- | --- |
| `a-trade.service` 运行中 | ✅ active | `systemctl is-active` 返回 `active`；MainPID 697534 |
| botpy 连接 | ✅ READY | `✅ a-trade Bot ready: 机器人1903580590` |
| 定时任务注册 | ✅ 6 个 | `✅ 定时任务注册完成: 6 个`，分别是做T监控 21:02、盘中选股 21:30、早盘 08:00、午盘 12:30、收盘 15:30、新闻 17:00 |
| 做T监控任务触发 | ✅ 已触发 | `2026-07-20 20:58:01` 和 `21:02:01` 两次都看到 `trading_calendar._load_trade_dates` 重新加载，因 20:55 已是非盘中时段直接 return |
| OpenClaw 推送链路 | ✅ 成功 | 手动调用返回消息 ID `ROBOT1.0_sWEIQA2BX.TxCZTo.0eU7tR-...`，timestamp `2026-07-20T21:08:28+08:00` |
| access_token | ✅ 可获取 | `access_token 获取成功，有效期 6416 秒` |
| 群 openid | ✅ 有效 | 推送目标 `群 9AF12D111FCCA67624811005E51EC4C2` |

## 已修复的旁证

- 修复前：`scheduler.err.log` 每 10 秒循环 `导入失败: No module named 'akshare'`。
- 修复后：21:00:43 收到 SIGTERM 触发一次正常关停，21:00:44 干净重启，botpy 在 21:00:49 再次 READY，调度器稳定运行。
- 服务自 21:00:49 起稳定 10+ 分钟，无再次重启。

## 注意事项

- `scheduler.out.log` 为空：因为 systemd 把 loguru 的 INFO 全部转发到 stderr，这是当前部署预期行为；如果你希望区分，建议在 systemd unit 里把 `StandardOutput` 切到 `journald`。
- 今日是非盘中时段，做T监控/盘中选股被 `is_open_for_intraday_scan()` 早返回属正常；最直接的端到端证据就是 21:08 手动推送成功拿到官方消息 ID。

## 跟进项

- 明日 08:00 早盘快讯、12:30 午盘报告、15:30 收盘日报、17:00 持仓新闻会自动触发；任一任务失败请把 `scheduler.err.log` 发我定位。
- 已在 P0-3 中标记 `requirements.txt` 缺 `akshare`、`botpy` 包名错误，会随全量修复一起根治。
