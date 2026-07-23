# 2026-07-23 安卓持仓配置 App STATUS

- **总体状态：** 已完成
- **当前阶段：** 6. 收尾（VPS 部署 + 端到端验证）
- **当前步骤：** 等用户用手机浏览器访问
- **已完成：** 10 个 task 全部交付；185 passed, 1 skipped；ruff 全绿；origin + vps 推送；web 服务 systemd 装好；端到端 curl 测试通过
- **下一步：** 用户用手机浏览器打开 http://96.30.194.21:8765/，编辑后保存
- **阻塞项：** 无
- **最后更新：** 2026-07-23 22:17（Asia/Shanghai）

## 交付清单

新增：
- `atrade/web/{__init__,app,storage,reload_client}.py`
- `atrade/web/static/{index.html,app.css,app.js}`
- `deploy/a-trade-web.service`
- `scripts/install_web_service.sh`
- `tests/test_config_disabled.py` (3)
- `tests/test_scheduler_reload.py` (2)
- `tests/test_scheduler_reload_socket.py` (3)
- `tests/test_web_storage.py` (9)
- `tests/test_web_reload_client.py` (5)
- `tests/test_web_app.py` (9)
- `tests/test_web_e2e.py` (4)

修改：
- `atrade/config.py` — `load_holdings_with_meta()` + 校验
- `atrade/scheduler/runner.py` — `reload_from_disk()` + `_start_reload_socket()` + `start()` 调用
- `config/holdings.example.json` — `disabled_symbols` + `watch_keywords` 字段
- `.env.example` — `A_TRADE_WEB_TOKEN=` 注释

## VPS 部署

- 端口 8765 已开
- systemd unit: `/etc/systemd/system/a-trade-web.service`（enabled）
- 端到端验证（curl）：
  - GET /api/health → `{"ok":true,"auth_enabled":false}`
  - GET /api/holdings → 完整列表
  - PUT /api/holdings/600519 → 更新成功
  - PUT /api/holdings/000001 {enabled:false} → 停用成功
  - POST /api/reload → `{"holdings":2,"t_symbols":2,"disabled":1}`
  - 静态资源 `/static/app.css` `/static/app.js` `/` → 200

## 手机访问

浏览器打开 http://96.30.194.21:8765/ 即可编辑持仓。
iOS Safari / Android Chrome 均支持"添加到主屏"作为 PWA。
默认无鉴权；要启用 Bearer 鉴权，在 VPS 上：
```
echo "A_TRADE_WEB_TOKEN=$(openssl rand -hex 32)" >> /opt/a-trade/.env
systemctl restart a-trade-web
```
