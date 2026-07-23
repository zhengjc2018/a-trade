# 2026-07-23 a-trade 持仓配置 Web 接口设计

## 背景

用户（A股个人投资者）通过 `a-trade` 调度器在 VPS 上跑每日定时通知。
当前唯一修改持仓的方式是 SSH 上 VPS 改 `config/holdings.local.json`，然后
`systemctl restart a-trade.service`。该方式：

- 需要 SSH 凭据
- 触发服务重启（早盘期间不可接受）
- 手机端不可达

用户为安卓机，希望通过手机能"动态"修改持仓并立即生效。

## 目标

1. 在 VPS 上新增 HTTP/Web 服务，监听 `0.0.0.0:8765`，提供：
   - REST API 用于程序化编辑持仓（可选 Bearer Token 鉴权）
   - 单页 HTML UI 让手机浏览器可直接编辑
2. 编辑后**热重载**调度器持仓配置，无需重启服务。
3. 个人使用，单用户；默认公开，可选启用 Bearer Token 鉴权。

## 非目标

- 多用户/权限管理
- 富交易/下单
- 历史持仓快照（暂时不做）
- 图表、回测面板

## 架构

```
VPS (96.30.194.21) — root 运行
  ├─ a-trade.service (现有)
  │    └─ APScheduler + DeliveryRouter + 通知链路
  │    └─ 新增: Unix socket server /var/run/a-trade-reload.sock
  │                └─ 接收 reload 命令，重读 holdings + monitor JSON
  │
  └─ a-trade-web.service (新增)
       └─ FastAPI + uvicorn，监听 0.0.0.0:8765
       └─ 可选 Bearer Token 中间件
       └─ 写 /opt/a-trade/config/holdings.local.json (原子)
       └─ 通过 socket 通知 scheduler reload
```

手机浏览器 → http://96.30.194.21:8765/ → 单页 HTML → PWA 加到主屏。

## 组件

### 1. `atrade/web/app.py` — FastAPI 应用

路由：
- `GET  /api/health`              — 无鉴权，返回 `{ok: true}`
- `GET  /api/holdings`            — 鉴权，返回当前 holdings 列表
- `PUT  /api/holdings/{symbol}`   — 鉴权，部分字段更新；返回更新后对象
- `POST /api/reload`              — 鉴权，触发 socket reload；返回 `{jobs: N}`
- `GET  /`                        — 单页 HTML UI（无需鉴权，但前端带 Token 输入框）
- `GET  /static/app.js`           — 前端 JS
- `GET  /static/app.css`          — 前端样式

中间件：
- 无（公开访问）
- 唯一约束：写操作加 IP 日志

### 2. `atrade/web/storage.py` — 原子写入

- 读 `load_holdings()` 走 `atrade.config` 现有路径
- 写入：写 `holdings.local.json.tmp` → `os.replace()` 原子改名
- 文件锁：进程内 `threading.Lock`，避免并发写

### 3. `atrade/web/reload_client.py` — socket 客户端

- 启动时连 `/var/run/a-trade-reload.sock`
- 发送 `b"reload\n"`
- 读回响应（超时 5s）
- 失败抛 `ReloadError` → 接口 502

### 4. `atrade/scheduler/runner.py` — 增加 socket server + reload

新增方法：

```python
def reload_from_disk(self) -> dict:
    """重读 holdings + monitor JSON，更新内部状态。"""
    self.holdings = load_holdings()
    self.watch_symbols = [h["symbol"] for h in self.holdings]
    self.watch_keywords = load_watch_keywords()
    monitor = load_monitor_config()
    self.t_runner.config.symbols = [
        TMonitorItem(**{k: v for k, v in h.items() if k in TMonitorItem.__dataclass_fields__})
        for h in monitor["t_monitor"]["symbols"]
    ]
    self.report_gen.holdings = self.holdings
    self.report_gen.watch_symbols = self.watch_symbols
    self.report_gen.watch_keywords = self.watch_keywords
    return {
        "holdings": len(self.holdings),
        "t_symbols": len(self.t_runner.config.symbols),
    }

def _start_reload_socket(self) -> None:
    """在后台线程启动 Unix socket 服务，接收 reload 命令。"""
    import threading, socketserver
    SOCK = "/var/run/a-trade-reload.sock"
    if os.path.exists(SOCK):
        os.remove(SOCK)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            cmd = self.rfile.readline().strip().decode()
            if cmd == "reload":
                try:
                    result = self.server.scheduler.reload_from_disk()
                    self.wfile.write(f"OK {result}".encode())
                except Exception as e:
                    self.wfile.write(f"ERR {e}".encode())
            else:
                self.wfile.write(b"ERR unknown command")

    class Server(socketserver.ThreadingUnixStreamServer):
        def __init__(self, addr, handler_cls, scheduler):
            super().__init__(addr, handler_cls)
            self.scheduler = scheduler

    server = Server(SOCK, Handler, self)
    os.chmod(SOCK, 0o660)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="reload-socket")
    t.start()
```

`DailyScheduler.start()` 末尾调用 `self._start_reload_socket()`。

### 5. `atrade/web/static/index.html` — 单页 UI

布局（手机单列）：

```
┌─────────────────────────────┐
│ ⚙️ a-trade 持仓配置          │
├─────────────────────────────┤
│ Token: [**************]  [登录]│
├─────────────────────────────┤
│ 600522 中天科技              │
│ 成本 [  62.00  ]             │
│ 数量 [  200   ]             │
│ 备注 [............]          │
│ [启用 ✓]   [保存] [删除]     │
├─────────────────────────────┤
│ 601318 中国平安              │
│ ...                          │
├─────────────────────────────┤
│ [+ 新增持仓]  [🔄 重载配置]   │
│ [上次重载: 23:45 / 3 持仓]   │
└─────────────────────────────┘
```

前端流程：
- 进入页面要求输入 Token（保存到 `localStorage`）
- `GET /api/holdings` → 渲染卡片
- 修改卡片字段 → 点保存 → `PUT /api/holdings/{symbol}`
- 点新增 → 弹窗输入 symbol → 后端 GET 行情拉名称 → 新建
- 点重载 → `POST /api/reload`

### 6. `deploy/a-trade-web.service` — systemd unit

```ini
[Unit]
Description=a-trade web admin
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/a-trade
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONPATH=/opt/a-trade
ExecStart=/opt/a-trade/.venv/bin/python -m uvicorn atrade.web.app:app --host 0.0.0.0 --port 8765
Restart=always
RestartSec=5
StandardOutput=append:/opt/a-trade/logs/web.out.log
StandardError=append:/opt/a-trade/logs/web.err.log

[Install]
WantedBy=multi-user.target
```

### 7. `.env`

无需新增 token 字段（无鉴权）。日志目录 `/opt/a-trade/logs/` 复用现有。

## API 契约

```http
GET  /api/health
→ 200 {"ok": true}

GET  /api/holdings
→ 200 [
    {
      "symbol": "600522",
      "name": "中天科技",
      "cost_price": 62.0,
      "quantity": 200,
      "buy_date": "2026-05-01",
      "note": "满仓被套",
      "enabled": true
    },
    ...
  ]

PUT  /api/holdings/{symbol}
  Body: {
    "cost_price"?: number,    # > 0
    "quantity"?: integer,     # > 0
    "buy_date"?: "YYYY-MM-DD",
    "note"?: string,          # <= 200 chars
    "enabled"?: boolean
  }
→ 200 {updated object}
→ 400 if validation fails
→ 404 if symbol not in holdings

POST /api/reload
→ 200 {"jobs": 9, "holdings": 2, "t_symbols": 2}
→ 502 if socket reload fails
```

`enabled` 字段：写入时存到 `note` 前缀 `_DISABLED_`，reload 时解析；或在 JSON
结构上增加顶层 `disabled_symbols: [symbol]` 字段。后者更清晰，本设计采用后者。

实际结构调整：

```json
{
  "holdings": [...],          // 全量持仓
  "disabled_symbols": ["601318"],  // 停用列表
  "watch_keywords": [...]
}
```

`TMonitorConfig.symbols` 在 reload 时排除 `disabled_symbols` 中的项。

## 数据流

```
PUT /api/holdings/600522 {cost_price: 62.5}
  → storage.load_holdings() (read)
  → mutate holding[symbol=600522]
  → atomic_write(path, json)
  → reload_client.request("/var/run/a-trade-reload.sock", "reload")
    → scheduler.reload_from_disk()
      → load_holdings() again
      → t_runner.config.symbols = ...
      → report_gen.holdings = ...
  → return 200 {symbol: ..., cost_price: 62.5}
```

## 安全

- **无鉴权**：用户决定纯公开访问（个人单机自用，IP 不易猜到且持仓非高敏）
- 监听 `0.0.0.0:8765`：任何人能访问 IP:端口都能编辑
- 写文件路径白名单：仅 `holdings.local.json`（不允许改 monitor JSON；
  monitor 配置涉及更复杂字段，留给 ssh 改）
- 日志记录所有写操作 + 来源 IP（审计追溯）
- **缓解措施**：VPS 安全组可限制 IP 段；后续可加 basic auth

## 部署

1. 本地：
   - 推送代码到 origin + vps
   - pre-push hook 同步 `.env` 到 VPS（无 token 字段）
2. VPS：
   - 部署 `a-trade-web.service`：`cp deploy/a-trade-web.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now a-trade-web`
   - 验证：`curl http://<public-ip>:8765/api/health`

## 测试

单测（`tests/test_web.py`）：
- 鉴权缺失/错误 → 401
- `GET /api/holdings` 返回结构
- `PUT /api/holdings/{symbol}` 校验：cost_price>0、quantity>0、symbol 6 位
- 写文件原子性（mock）
- reload socket mock
- 前端 HTML 包含表单元素

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 手机 4G/5G 访问公网 IP 不稳定 | 文档建议加入主屏并配置书签；可选后续接 frp / cloudflare tunnel |
| 端口 8765 暴露公网 | 用户选择无鉴权；个人单机风险低；可后续加 IP 白名单或 basic auth |
| scheduler reload 时正推送 | reload 只重建 symbols 列表，不打断正在跑的 APScheduler job；下一次 T 扫描生效 |
| socket 权限 | 0660 + socket 文件归 root；web service 也以 root 跑避免跨用户问题 |

## 影响范围

新增：
- `atrade/web/__init__.py`
- `atrade/web/app.py`
- `atrade/web/storage.py`
- `atrade/web/reload_client.py`
- `atrade/web/static/index.html`
- `atrade/web/static/app.js`
- `atrade/web/static/app.css`
- `deploy/a-trade-web.service`
- `tests/test_web.py`
- `tests/test_reload.py`

修改：
- `atrade/scheduler/runner.py`（加 `reload_from_disk` + socket server，`start()` 调用）
- `atrade/config.py`（`disabled_symbols` 字段透传）
- `config/holdings.example.json`（加 `disabled_symbols: []`）
- `.env.example`（加 `A_TRADE_WEB_TOKEN=`）
- `docs/progress/2026-07-23-android-holdings-app/{TODO,STATUS}.md`

不动：通知链路、信号引擎、T 监控核心（除 reload 时更新 symbols）。
