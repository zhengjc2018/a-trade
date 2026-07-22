# a-trade

A 股做 T 信号、盘中选股、回测与 QQ 群机器人推送。

## 功能

- 历史 K 线 + 缓存（按日期新鲜度增量刷新）
- 东财全市场快照（真实价格单位，无 ×100 错误）
- 单股多周期指标 + 信号引擎
- T+0 做 T 事件驱动守恒回测（支持正反向做 T、T+1 锁仓、费用守恒）
- 盘中选股（价量 + 主板 + 排除行业 + PE/PB 质量过滤）
- 做 T 监控（TTL 去重、送达后提交）
- 早盘/午盘/收盘日报、持仓新闻汇总、盘中选股、做 T 信号 6 个定时任务
- QQ 群推送（OpenClaw REST + botpy WebSocket 双通道；统一抽象）
- 钉钉主通道 + QQ 自动降级、送达账本、失败重试和漏报补发
- 个股做 T 策略报告（波动性 + 适配度 + 风险 + 回测验证）

## 快速开始

```bash
# 安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 准备本地配置（不要提交到 Git）
cp config/holdings.example.json config/holdings.local.json
cp config/monitor.example.json config/monitor.local.json
# 编辑 .local.json 填入真实持仓 / 监控配置

# 跑测试
pytest

# 跑回测
python3 scripts/run_backtest.py --symbol 600522 --cost 12.5 --qty 2000
python3 scripts/run_per_symbol_report.py --symbol 600522 --cost 12.5 --qty 2000

# 跑调度器
python3 scripts/run_scheduler.py
```

## 配置

- `config/holdings.local.json`：本地真实持仓（Git 忽略）
- `config/monitor.local.json`：本地真实监控配置（Git 忽略）
- `config/*.example.json`：脱敏示例，可提交
- 环境变量 `A_TRADE_HOLDINGS_PATH` / `A_TRADE_MONITOR_PATH`：可显式覆盖

详细字段校验规则见 `atrade/config.py`。

## 部署

参见 `docs/deploy_vps_git_push.md`。本仓库使用非 root 部署用户 + 原子 release 切换 + 健康检查失败回滚。

## 安全

- 公开仓库只保留脱敏配置和示例
- 真实持仓 / 监控 / 凭据放在 `.local.json`（`.gitignore`）
- 历史中已脱敏 AppID/group_openid；如怀疑 AppSecret 泄露请轮换
- 部署用户 `atrade` 无 root 权限，仅可重启服务
