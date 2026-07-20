# A-Trade 全量问题修复 TODO

**目标：** 一次性修复全面审查报告中的 P0-P3 问题，使行情、回测、通知、部署和工程质量达到可验证、可追踪、可安全迭代的状态。

**状态说明：** `[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

## 0. 阶段 A：止血（依赖 + 关键单位错误）

- [x] 备份现状 TODO/STATUS
- [x] P0-3 修复 requirements.txt，加入 akshare
- [x] P0-2 修正东财全市场快照字段与单位（去除 ×100 + 字段映射）
- [x] P1-2 历史 K 线成交额改为 close * volume（去掉 ×100）
- [x] P1-3 财报 TTM EPS 按周期匹配上年同期（中报/三季报）

## 1. 设计与计划

- [x] 明确一次性修复 P0-P3 的范围
- [x] 确认采用兼容式分阶段重构
- [x] 编写并自检修复设计文档
- [x] 编写详细实施计划（已嵌入本 TODO 各阶段）

## 2. 阶段 B：配置与安全

- [x] P0-4 持仓与监控脱敏：holdings/monitor 移到 *.local.json
- [x] P0-4 增加 .gitignore 与本地占位示例
- [x] atrade/config.py 统一加载入口
- [x] 旧 holdings/monitor.json 删除真实内容，仅保留 example
- [x] 文档脱敏：移除 VPS 公网 IP 与 root 部署写法

## 3. 阶段 C：行情与缓存

- [x] P1-1 日线缓存新鲜度与增量刷新
- [x] 历史 K 线分钟时间保留时分秒
- [x] 实时快照不写回历史日线（离线 use_snapshot=False）
- [x] 数据契约 + 单位回归测试

## 4. 阶段 D：回测账本（P0-1 重写）

- [x] 增加现金/股份守恒失败测试
- [x] 实现事件驱动账本：N+1 根 K 线成交模型
- [x] 实现可卖库存 + T+1 锁仓
- [x] 实现正向/反向做 T 周期
- [x] 修正费用、净值、成本、期末盯市
- [x] 新增回测验证套件（守恒、不变量）

## 5. 阶段 E：通知与调度

- [x] P1-5 统一通知接口（统一 send_text/send_markdown）
- [x] P1-5 修复 --push 调用 + 群 ID 注入
- [x] P1-6 Markdown 按 UTF-8 字节截断
- [x] P1-4 做 T 告警送达后提交 + TTL
- [x] 调度器 bot READY 等待 + 优雅停止
- [x] 通知与调度纯单元测试

## 6. 阶段 F：部署与工程化

- [x] P1-7 部署脚本原子化：release 目录 + current 软链接 + 回滚
- [x] P2 pyproject.toml + requirements-dev.txt
- [x] P2 Ruff 配置 + GitHub Actions CI
- [x] P3 文档与一致性（修正 --help、过期说明）

## 7. 阶段 G：验证与交付

- [x] 运行新增的定向测试
- [x] 运行完整 pytest 测试集（>=67 项）
- [x] 运行 compileall / ruff / shellcheck / CLI --help
- [x] 更新审查报告问题状态
- [x] 完成 STATUS 与最终修复摘要
