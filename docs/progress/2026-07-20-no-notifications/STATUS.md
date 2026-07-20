# 2026-07-20 群消息未送达排查 STATUS

- **总体状态：** 已完成
- **当前阶段：** 5. 修复与回归
- **当前步骤：** 修复已部署，等待次日定时任务首次触发
- **已完成：** 定位根因、补装依赖、重启服务并验证 botpy READY 和任务注册
- **下一步：** 观察明日 08:00 早盘快讯与盘中任务；本周内推进全量修复
- **阻塞项：** 无
- **最后更新：** 2026-07-20 21:00（Asia/Shanghai）

## 结论摘要

- **根因：** VPS 的 `.venv` 缺少 `akshare`（`requirements.txt` 也漏写了它，且 `botpy` 包名应为 `qq-botpy`）。systemd 因导入失败一直在 10 秒间隔内重启进程，定时任务和 botpy WebSocket 从未运行。
- **修复：** 在 `/opt/a-trade/.venv` 一次性补装 `akshare` 和 `qq-botpy`，随后 `systemctl restart a-trade.service`，服务已进入 `active (running)`，botpy READY 成功，6 个任务已注册。
- **验证命令：** `systemctl status a-trade.service --no-pager`，`tail -n 40 /opt/a-trade/logs/scheduler.out.log`。

## 阶段进展

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 1. 信息采集 | 已完成 | 确认 launchd 未加载、VPS 服务在循环重启 |
| 2. 调度器与机器人生命周期 | 已完成 | systemd 重启频率 10s，每次导入失败 |
| 3. 通知端口与去重 | 已完成 | 通道本身未运行，无须排查去重 |
| 4. 网络与平台 | 已完成 | bots.qq.com / api.sgroup.qq.com / web.ifzq 全部可达 |
| 5. 修复与回归 | 已完成 | akshare + qq-botpy 安装后服务稳定运行 |

## 关键证据

- `/opt/a-trade/logs/scheduler.err.log` 修复前：每 10 秒一次 `导入失败: No module named akshare`。
- `systemctl is-active a-trade.service` 修复前 `activating`、修复后 `active`。
- `scheduler.out.log` 最新行：`✅ botpy 客户端已就绪`、`✅ 调度器已启动`、6 个任务下次时间、`✅ a-trade Bot ready: 机器人1903580590`。
- VPS 缓存 `data/cache/stock.db` 当前为空（首次启动未拉取），08:00 早盘任务触发时会自动 upsert。

## 跟进项

- `requirements.txt` 漏写 `akshare`、`botpy` 包名错误：这两项已列入全量修复设计文档的 P0-3，会随代码层修复一并处理。
