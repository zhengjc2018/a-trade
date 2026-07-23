# 2026-07-23 安卓持仓配置 App 头脑风暴 TODO

**目标：** 设计一个安卓可用的入口，让用户能修改 T 监控的持仓配置（个数 / 成本价 / 备注 / 启停）。

**状态说明：** `[ ]` 未开始，`[-]` 进行中，`[x]` 已完成，`[!]` 受阻。

## 1. 上下文

- [x] 创建本次 TODO 与 STATUS 文件
- [x] 现有配置：本地 `config/holdings.local.json` + `config/monitor.local.json`（已 gitignore）
- [x] 调度器读取配置在启动时，VPS 上 `/opt/a-trade/` 持有副本
- [x] 用户反馈：茅台 / 银行非本人持仓（当前 local 文件里的示例数据需清掉）

## 2. 需求澄清

- [ ] 部署位置：手机本地 / VPS Web / 私有云
- [ ] 编辑目标：仅修改 monitor.t_monitor.symbols 还是 holdings 顶层
- [ ] 数据流：本地编辑 → 推送到 VPS？还是 VPS Web 直接编辑？
- [ ] 鉴权：是否需要登录？单用户 / 多用户？
- [ ] 实时生效：编辑后是否重启调度器？

## 3. 候选方案

- [ ] 候选 A：VPS 部署 FastAPI + 移动端 Web (PWA) ← 推荐
- [ ] 候选 B：原生 Kotlin Android App + REST 后端
- [ ] 候选 C：Tauri / Cordova 把 Web 套壳成 APK

## 4. 设计

- [ ] 输出 `docs/superpowers/specs/2026-07-23-android-holdings-app-design.md`
- [ ] 用户审阅设计文档
