# A-Trade 全量问题修复状态

- **总体状态：** 完成
- **当前阶段：** 7. 验证与交付
- **当前步骤：** 全量修复 P0-P3 已完成；pytest 104 通过、ruff 0 错误、compileall/shell/CLI 通过
- **已完成：** 全部 7 个阶段（P0-P3）
- **下一步：** 提交修复（用户尚未要求自动 git commit）
- **阻塞项：** 无
- **最后更新：** 2026-07-20（Asia/Shanghai）

## 阶段进展

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 0. 止血 | ✅ 已完成 | P0-2/P0-3/P1-1/P1-2/P1-3 |
| 1. 设计与计划 | ✅ 已完成 | 设计文档 + 分阶段 TODO |
| 2. 配置与安全 | ✅ 已完成 | P0-4 脱敏 + atrade/config.py |
| 3. 行情与缓存 | ✅ 已完成 | is_cache_stale、amount 修正、TTM 按周期、字段契约 |
| 4. 回测账本 | ✅ 已完成 | P0-1 T0Simulator 事件驱动守恒账本重写 |
| 5. 通知与调度 | ✅ 已完成 | P1-4 送达后提交 + TTL、P1-5 通知统一、P1-6 字节截断 |
| 6. 部署与工程化 | ✅ 已完成 | P1-7 原子化部署 + pyproject + Ruff + GitHub Actions |
| 7. 验证与交付 | ✅ 已完成 | 104 passed、ruff all checks passed |

## P0-P3 修复清单

### P0
- ✅ P0-1 重写 `atrade/backtest/t0_simulator.py` 为事件驱动守恒账本
- ✅ P0-2 `scripts/screen.py` 东财字段映射修正（f2/f3/f6/f7/f9/f10/f15/f16/f20/f23，全部为实际价格/数值）
- ✅ P0-3 `requirements.txt` 加入 akshare 与版本约束
- ✅ P0-4 配置脱敏：holdings/monitor 拆出 `*.local.json`（Git 忽略）+ `*.example.json`（可提交）；VPS IP / root 部署从文档移除

### P1
- ✅ P1-1 日线缓存按最后日期新鲜度判断增量刷新
- ✅ P1-2 历史 K 线成交额改为 `close * volume`（去除 ×100）
- ✅ P1-3 财报 TTM EPS 按 REPORT_TYPE 匹配上年同期（中报 / 三季报 / 一季报）
- ✅ P1-4 做 T 告警改为送达后提交 + TTL；旧状态格式兼容
- ✅ P1-5 统一 `atrade.notify.load_notifier()` 接口；`--push` 修复为走统一接口
- ✅ P1-6 Markdown 按 UTF-8 字节切分（优先段落边界），不再按字符截断
- ✅ P1-7 部署脚本改为 release 目录 + 软链接原子切换 + 健康检查失败回滚
- ✅ P1-8 回测验证：新增 5 项事件驱动账本不变量测试

### P2 工程化
- ✅ pyproject.toml（构建、pytest、Ruff、Coverage 配置）
- ✅ requirements-dev.txt（pytest / pytest-cov / ruff / coverage）
- ✅ Ruff 配置（line-length=100，target py39，启用 E/F/W/I/B/UP）
- ✅ GitHub Actions CI（Python 3.9-3.12 矩阵 + smoke import + ruff + pytest + compileall + shell + CLI --help）

### P3 文档与一致性
- ✅ `scripts/screen.py --help` 修复（% 转义）
- ✅ README 重写
- ✅ VPS 部署文档脱敏（移除公网 IP 与 root 部署）
- ✅ pre_push 脚本占位符 `deploy@your-vps`
- ✅ AGENTS.md 已存在并要求进度跟踪

## 验证结果

| 项 | 结果 |
| --- | --- |
| pytest | ✅ 104 passed |
| ruff check | ✅ All checks passed |
| compileall | ✅ atrade/ 全通过 |
| shell 语法 | ✅ 4 个部署脚本通过 |
| CLI --help | ✅ screen / run_backtest / run_per_symbol_report 全部正常 |

## 更新日志

| 时间 | 变更 |
| --- | --- |
| 2026-07-19 | 初始化全量修复 TODO 与 STATUS |
| 2026-07-19 | 用户批准兼容式分阶段重构设计方向 |
| 2026-07-19 | 完成设计文档自检 |
| 2026-07-20 | 备份原 TODO/STATUS；引入分阶段 0-7 实施计划 |
| 2026-07-20 | 完成阶段 0：P0-3/P0-2/P1-2/P1-3 |
| 2026-07-20 | 完成阶段 B：P0-4 配置脱敏 + atrade/config.py |
| 2026-07-20 | 完成阶段 D：P0-1 T0Simulator 重写 |
| 2026-07-20 | 完成阶段 E：P1-4/P1-5/P1-6 通知与调度 |
| 2026-07-20 | 完成阶段 F：P1-7 部署原子化 + pyproject + Ruff + CI |
| 2026-07-20 | 完成阶段 G：全部验证通过 |
