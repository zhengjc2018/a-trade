# a-trade 持仓配置 Web 接口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 VPS 上新增 Web 服务（FastAPI + 单页 HTML），让手机浏览器能编辑持仓配置并触发调度器热重载，无需 SSH 或重启服务。

**Architecture:** 两个独立 systemd 服务 (`a-trade.service` + `a-trade-web.service`) 通过 Unix socket `/var/run/a-trade-reload.sock` 通信；web 服务读/写 `holdings.local.json`，reload 命令让 scheduler 重读 JSON 并重建内存中的 holdings + T 监控 symbols。

**Tech Stack:** FastAPI + uvicorn (web), stdlib `socketserver` (IPC), Jinja2-free HTML, pytest, stdlib only IPC.

## Global Constraints

- Python 3.10+
- VPS root 运行，端口 8765 绑定 0.0.0.0
- 不引入新第三方依赖（uvicorn/fastapi 已确认可用；否则加到 requirements.txt）
- 所有 JSON 写入用 `os.replace()` 原子操作
- reload 只重建 `symbols` 列表，不打断正在运行的 APScheduler job
- 鉴权：可选 Bearer Token（环境变量 `A_TRADE_WEB_TOKEN` 留空 = 公开，非空 = 启用）
- 单页 UI，纯 HTML + vanilla JS，无构建步骤

---

## File Structure

新增：
- `atrade/web/__init__.py`
- `atrade/web/storage.py` — 读/写 holdings.local.json（含 disabled_symbols）
- `atrade/web/reload_client.py` — Unix socket 客户端
- `atrade/web/app.py` — FastAPI 应用 + 路由
- `atrade/web/static/index.html` — 单页 UI
- `atrade/web/static/app.js`
- `atrade/web/static/app.css`
- `deploy/a-trade-web.service` — systemd unit
- `tests/test_web_storage.py`
- `tests/test_web_reload_client.py`
- `tests/test_web_app.py`

修改：
- `atrade/config.py` — `disabled_symbols` 字段校验
- `config/holdings.example.json` — 加 `disabled_symbols: []`
- `.env.example` — 加 `A_TRADE_WEB_TOKEN=`（注释说明可选）
- `atrade/scheduler/runner.py` — `reload_from_disk()` + `_start_reload_socket()`

---

### Task 1: Add `disabled_symbols` to holdings config schema

**Files:**
- Modify: `atrade/config.py:90-110` (`_validate_holding` 与 `load_holdings`)
- Modify: `config/holdings.example.json`
- Test: `tests/test_config_disabled.py`

**Interfaces:**
- Consumes: 现有 `holdings.json` / `holdings.local.json` 顶层字段
- Produces: `_validate_holding` 后 holdings dict 列表；顶层 `disabled_symbols` list

- [ ] **Step 1: Write failing test**

```python
# tests/test_config_disabled.py
from atrade.config import load_holdings


def test_disabled_symbols_passthrough(tmp_path, monkeypatch):
    (tmp_path / "holdings.json").write_text(
        '{"holdings": [{"symbol": "600519", "name": "茅台", '
        '"cost_price": 1500, "quantity": 100}], '
        '"disabled_symbols": ["600519"], "watch_keywords": []}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "holdings.json")
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "holdings.local.json")
    # Config 模块返回 holdings 列表；disabled_symbols 走单独 API
    from atrade.config import load_holdings_with_meta
    result = load_holdings_with_meta()
    assert result["holdings"][0]["symbol"] == "600519"
    assert result["disabled_symbols"] == ["600519"]


def test_invalid_disabled_symbol_format(tmp_path, monkeypatch):
    (tmp_path / "holdings.json").write_text(
        '{"holdings": [], "disabled_symbols": ["abc"]}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "holdings.json")
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "holdings.local.json")
    from atrade.config import load_holdings_with_meta
    import pytest
    with pytest.raises(Exception) as exc:
        load_holdings_with_meta()
    assert "6 位" in str(exc.value) or "must be" in str(exc.value).lower()
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python3 -m pytest tests/test_config_disabled.py -v`
Expected: ImportError for `load_holdings_with_meta`

- [ ] **Step 3: Implement `load_holdings_with_meta()` and validation**

In `atrade/config.py`, add after existing `load_holdings()`:

```python
def load_holdings_with_meta() -> dict:
    """加载 holdings 完整结构（含 disabled_symbols 与 watch_keywords）。"""
    for path in _candidate_paths("holdings", DEFAULT_HOLDINGS, LOCAL_HOLDINGS, ENV_HOLDINGS):
        if path.exists():
            cfg = _read_json(path)
            raw_holdings = cfg.get("holdings") or []
            validated = [_validate_holding(item, idx) for idx, item in enumerate(raw_holdings)]
            disabled = cfg.get("disabled_symbols") or []
            if not isinstance(disabled, list):
                raise ConfigError("disabled_symbols 必须是列表")
            for i, sym in enumerate(disabled):
                s = str(sym).zfill(6)
                if not _CODE_RE.match(s):
                    raise ConfigError(f"disabled_symbols[{i}] 必须是 6 位数字，实际: {sym!r}")
            keywords = cfg.get("watch_keywords") or []
            if not isinstance(keywords, list):
                raise ConfigError("watch_keywords 必须是列表")
            return {
                "holdings": validated,
                "disabled_symbols": [str(s).zfill(6) for s in disabled],
                "watch_keywords": [str(k) for k in keywords],
            }
    raise ConfigError("未找到 holdings 配置文件")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_config_disabled.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Update example config**

Modify `config/holdings.example.json`, add top-level fields:

```json
{
  "holdings": [...],
  "disabled_symbols": [],
  "watch_keywords": []
}
```

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest -q`
Expected: existing tests pass, new tests pass

- [ ] **Step 7: Commit**

```bash
git add atrade/config.py config/holdings.example.json tests/test_config_disabled.py
git commit -m "feat(config): add disabled_symbols field to holdings schema"
```

---

### Task 2: Add `reload_from_disk()` to DailyScheduler

**Files:**
- Modify: `atrade/scheduler/runner.py` (add method to `DailyScheduler`)
- Test: `tests/test_scheduler_reload.py`

**Interfaces:**
- Consumes: `atrade.config.load_holdings_with_meta`, `atrade.config.load_monitor_config`
- Produces: `DailyScheduler.reload_from_disk() -> dict`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scheduler_reload.py
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from atrade.scheduler.runner import DailyScheduler


def _make_scheduler():
    return DailyScheduler.__new__(DailyScheduler)  # skip __init__


def test_reload_from_disk_updates_holdings(tmp_path, monkeypatch):
    sched = _make_scheduler()
    sched.holdings = [{"symbol": "600519"}]
    sched.watch_symbols = ["600519"]
    sched.watch_keywords = []
    sched.t_runner = type("R", (), {"config": type("C", (), {"symbols": []})()})()
    sched.report_gen = type("G", (), {})()

    new_cfg = {
        "holdings": [{"symbol": "600522", "name": "中天科技",
                      "cost_price": 62.0, "quantity": 200, "buy_date": "",
                      "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    }
    monitor_cfg = {
        "t_monitor": {"symbols": [{"symbol": "600522", "name": "中天科技",
                                   "cost_price": 62.0, "quantity": 200}]},
    }
    monkeypatch.setattr("atrade.config.load_holdings_with_meta", lambda: new_cfg)
    monkeypatch.setattr("atrade.config.load_monitor_config", lambda: monitor_cfg)

    result = sched.reload_from_disk()
    assert result["holdings"] == 1
    assert sched.holdings[0]["symbol"] == "600522"
    assert sched.t_runner.config.symbols[0].symbol == "600522"
```

- [ ] **Step 2: Run test, verify fail**

Run: `python3 -m pytest tests/test_scheduler_reload.py::test_reload_from_disk_updates_holdings -v`
Expected: AttributeError on `reload_from_disk`

- [ ] **Step 3: Implement `reload_from_disk()`**

In `atrade/scheduler/runner.py`, add method to `DailyScheduler` class:

```python
def reload_from_disk(self) -> dict:
    """重读 holdings + monitor JSON，更新内存中的 holdings、watch 列表、
    T 监控 symbols 与报告器持有。不重启 APScheduler。"""
    from atrade.config import load_holdings_with_meta, load_monitor_config
    from atrade.monitor.t_monitor import TMonitorItem

    holdings_meta = load_holdings_with_meta()
    monitor = load_monitor_config()

    self.holdings = holdings_meta["holdings"]
    self.watch_symbols = [h["symbol"] for h in self.holdings]
    self.watch_keywords = holdings_meta.get("watch_keywords") or []

    # 重建 T 监控 symbols（按 holdings 顺序，过滤掉 disabled）
    disabled = set(holdings_meta.get("disabled_symbols") or [])
    t_symbols_raw = (monitor.get("t_monitor") or {}).get("symbols") or []
    t_symbols_filtered = [s for s in t_symbols_raw if s.get("symbol") not in disabled]
    self.t_runner.config.symbols = [
        TMonitorItem(
            symbol=str(s["symbol"]).zfill(6),
            name=str(s.get("name", "")),
            cost_price=float(s.get("cost_price", 0.0)),
            quantity=int(s.get("quantity", 0)),
            note=str(s.get("note", "")),
        )
        for s in t_symbols_filtered
    ]

    # 重建 report_gen 持有的引用
    if hasattr(self, "report_gen") and self.report_gen is not None:
        self.report_gen.holdings = self.holdings
        self.report_gen.watch_symbols = self.watch_symbols
        self.report_gen.watch_keywords = self.watch_keywords

    logger.info(
        f"🔁 配置已重载: holdings={len(self.holdings)} "
        f"t_symbols={len(self.t_runner.config.symbols)} "
        f"disabled={len(disabled)}"
    )
    return {
        "holdings": len(self.holdings),
        "t_symbols": len(self.t_runner.config.symbols),
        "disabled": len(disabled),
    }
```

- [ ] **Step 4: Run test, verify pass**

Run: `python3 -m pytest tests/test_scheduler_reload.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add atrade/scheduler/runner.py tests/test_scheduler_reload.py
git commit -m "feat(scheduler): add reload_from_disk() for hot config reload"
```

---

### Task 3: Add Unix socket reload server to DailyScheduler

**Files:**
- Modify: `atrade/scheduler/runner.py` (add `_start_reload_socket`, call from `start()`)
- Test: `tests/test_scheduler_reload_socket.py`

**Interfaces:**
- Consumes: `reload_from_disk()` from Task 2
- Produces: Unix socket server listening at `/var/run/a-trade-reload.sock`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scheduler_reload_socket.py
import socket
import tempfile
import time
from pathlib import Path

import pytest

from atrade.scheduler.runner import DailyScheduler


def test_socket_server_responds_to_reload(tmp_path, monkeypatch):
    sock_path = tmp_path / "test.sock"
    monkeypatch.setattr("atrade.scheduler.runner._RELOAD_SOCK_PATH", str(sock_path))

    sched = DailyScheduler.__new__(DailyScheduler)
    sched.reload_from_disk = lambda: {"holdings": 1, "t_symbols": 2}

    sched._start_reload_socket()

    # connect and send reload command
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(sock_path))
        s.sendall(b"reload\n")
        resp = b""
        deadline = time.time() + 2
        while time.time() < deadline:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b"\n" in resp or len(resp) > 10:
                break
        assert b"OK" in resp
        assert b"holdings" in resp or b"1" in resp
    finally:
        s.close()


def test_socket_rejects_unknown_command(tmp_path, monkeypatch):
    sock_path = tmp_path / "test.sock"
    monkeypatch.setattr("atrade.scheduler.runner._RELOAD_SOCK_PATH", str(sock_path))

    sched = DailyScheduler.__new__(DailyScheduler)
    sched.reload_from_disk = lambda: {"holdings": 1, "t_symbols": 2}
    sched._start_reload_socket()

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(str(sock_path))
        s.sendall(b"foo\n")
        time.sleep(0.2)
        resp = s.recv(4096)
        assert b"ERR" in resp
    finally:
        s.close()
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python3 -m pytest tests/test_scheduler_reload_socket.py -v`
Expected: AttributeError on `_start_reload_socket` / `_RELOAD_SOCK_PATH`

- [ ] **Step 3: Implement socket server**

In `atrade/scheduler/runner.py`, add at module level:

```python
_RELOAD_SOCK_PATH = os.getenv(
    "A_TRADE_RELOAD_SOCK", "/var/run/a-trade-reload.sock"
)
```

Add method to `DailyScheduler`:

```python
def _start_reload_socket(self) -> None:
    """后台启动 Unix socket 服务，接收 reload 命令。"""
    import socketserver
    import threading

    sock_path = _RELOAD_SOCK_PATH
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
        except OSError:
            pass

    outer = self  # capture

    class _ReloadHandler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                line = self.rfile.readline()
                cmd = line.strip().decode("utf-8", errors="ignore") if line else ""
                if cmd == "reload":
                    try:
                        result = outer.reload_from_disk()
                        self.wfile.write(f"OK {result}\n".encode())
                    except Exception as e:
                        self.wfile.write(f"ERR reload failed: {e}\n".encode())
                else:
                    self.wfile.write(b"ERR unknown command\n")
            except Exception as e:
                try:
                    self.wfile.write(f"ERR handler: {e}\n".encode())
                except Exception:
                    pass

    class _ThreadedUnixServer(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    server = _ThreadedUnixServer(sock_path, _ReloadHandler)
    try:
        os.chmod(sock_path, 0o660)
    except OSError:
        pass
    t = threading.Thread(target=server.serve_forever, daemon=True, name="reload-socket")
    t.start()
    logger.info(f"🔌 reload socket listening at {sock_path}")
```

- [ ] **Step 4: Hook into `start()`**

In `DailyScheduler.start()`, after `self.scheduler.start()` and before recovered log, add:

```python
self._start_reload_socket()
```

- [ ] **Step 5: Run tests, verify pass**

Run: `python3 -m pytest tests/test_scheduler_reload_socket.py -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add atrade/scheduler/runner.py tests/test_scheduler_reload_socket.py
git commit -m "feat(scheduler): Unix socket reload server for hot config updates"
```

---

### Task 4: Web storage module (atomic write + load)

**Files:**
- Create: `atrade/web/__init__.py` (empty)
- Create: `atrade/web/storage.py`
- Test: `tests/test_web_storage.py`

**Interfaces:**
- `read_holdings() -> dict`  (returns full meta dict)
- `write_holdings(meta: dict) -> None`  (atomic, file lock)
- `update_holding(symbol: str, patch: dict) -> dict`  (read-modify-write)
- `validate_patch(patch: dict) -> dict`  (raises ValueError on bad input)

- [ ] **Step 1: Write failing test**

```python
# tests/test_web_storage.py
import json
from pathlib import Path

import pytest

from atrade.web.storage import (
    read_holdings,
    write_holdings,
    update_holding,
    validate_patch,
)


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    target = tmp_path / "holdings.local.json"
    monkeypatch.setattr("atrade.web.storage._HOLDINGS_PATH", target)

    meta = {
        "holdings": [{"symbol": "600522", "name": "中天科技",
                      "cost_price": 62.0, "quantity": 200,
                      "buy_date": "2026-05-01", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": ["白酒"],
    }
    write_holdings(meta)
    result = read_holdings()
    assert result["holdings"][0]["symbol"] == "600522"
    assert result["watch_keywords"] == ["白酒"]


def test_update_holding_partial(tmp_path, monkeypatch):
    target = tmp_path / "holdings.local.json"
    monkeypatch.setattr("atrade.web.storage._HOLDINGS_PATH", target)
    write_holdings({
        "holdings": [{"symbol": "600522", "name": "中天",
                      "cost_price": 62.0, "quantity": 200,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    })
    result = update_holding("600522", {"cost_price": 65.0, "quantity": 250})
    assert result["cost_price"] == 65.0
    assert result["quantity"] == 250


def test_update_holding_missing_symbol(tmp_path, monkeypatch):
    target = tmp_path / "holdings.local.json"
    monkeypatch.setattr("atrade.web.storage._HOLDINGS_PATH", target)
    write_holdings({"holdings": [], "disabled_symbols": [], "watch_keywords": []})
    with pytest.raises(KeyError):
        update_holding("600999", {"cost_price": 10})


def test_validate_patch_rejects_negative_cost():
    with pytest.raises(ValueError):
        validate_patch({"cost_price": -1})


def test_validate_patch_rejects_zero_quantity():
    with pytest.raises(ValueError):
        validate_patch({"quantity": 0})


def test_validate_patch_rejects_long_note():
    with pytest.raises(ValueError):
        validate_patch({"note": "x" * 300})


def test_validate_patch_accepts_valid():
    patch = {"cost_price": 62.0, "quantity": 200, "note": "ok", "buy_date": "2026-05-01"}
    out = validate_patch(patch)
    assert out["cost_price"] == 62.0
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python3 -m pytest tests/test_web_storage.py -v`
Expected: ImportError

- [ ] **Step 3: Implement storage**

Create `atrade/web/__init__.py` (empty file).

Create `atrade/web/storage.py`:

```python
"""holdings.local.json 读/写（原子操作 + 进程内锁）。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_HOLDINGS_PATH: Optional[Path] = None  # 由 init_app() 注入
_lock = threading.Lock()


def init_app(path: Path) -> None:
    """在 FastAPI startup 时注入 holdings.local.json 路径。"""
    global _HOLDINGS_PATH
    _HOLDINGS_PATH = path


def _resolve_path() -> Path:
    if _HOLDINGS_PATH is None:
        # 默认从 atrade.config 取 LOCAL_HOLDINGS
        from atrade.config import LOCAL_HOLDINGS
        return LOCAL_HOLDINGS
    return _HOLDINGS_PATH


def read_holdings() -> dict:
    """读 holdings 文件，返回完整 meta dict。"""
    from atrade.config import load_holdings_with_meta
    try:
        return load_holdings_with_meta()
    except FileNotFoundError:
        return {"holdings": [], "disabled_symbols": [], "watch_keywords": []}


def write_holdings(meta: dict) -> None:
    """原子写入：写 tmp → os.replace。"""
    path = _resolve_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(meta, ensure_ascii=False, indent=2)
    with _lock:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)


def update_holding(symbol: str, patch: dict) -> dict:
    """读 → 改 → 写。返回更新后的 holding。"""
    with _lock:
        meta = read_holdings()
        target_idx = None
        for idx, h in enumerate(meta["holdings"]):
            if str(h.get("symbol", "")).zfill(6) == str(symbol).zfill(6):
                target_idx = idx
                break
        if target_idx is None:
            raise KeyError(f"symbol not in holdings: {symbol}")
        meta["holdings"][target_idx].update(patch)
        # 标记最后更新时间
        meta["holdings"][target_idx]["updated_at"] = (
            datetime.now().isoformat(timespec="seconds")
        )
        write_holdings_unlocked(meta)
        return meta["holdings"][target_idx]


def write_holdings_unlocked(meta: dict) -> None:
    """调用方已持有 _lock 时用。"""
    path = _resolve_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


_ALLOWED_FIELDS = {"cost_price", "quantity", "buy_date", "note", "enabled"}


def validate_patch(patch: dict) -> dict:
    """校验 patch 字段。返回规范化后的 dict；失败抛 ValueError。"""
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是 dict")
    out: dict = {}
    if "cost_price" in patch:
        cp = patch["cost_price"]
        if not isinstance(cp, (int, float)) or cp <= 0:
            raise ValueError(f"cost_price 必须 > 0，实际: {cp}")
        out["cost_price"] = float(cp)
    if "quantity" in patch:
        q = patch["quantity"]
        if not isinstance(q, int) or q <= 0:
            raise ValueError(f"quantity 必须为正整数，实际: {q}")
        out["quantity"] = q
    if "buy_date" in patch:
        bd = str(patch["buy_date"])
        if bd and len(bd) > 10:
            raise ValueError(f"buy_date 格式错误: {bd}")
        out["buy_date"] = bd
    if "note" in patch:
        n = str(patch["note"])
        if len(n) > 200:
            raise ValueError(f"note 不能超过 200 字符（{len(n)}）")
        out["note"] = n
    if "enabled" in patch:
        if not isinstance(patch["enabled"], bool):
            raise ValueError("enabled 必须是 bool")
        out["enabled"] = bool(patch["enabled"])
    if not out:
        raise ValueError("patch 不能为空")
    unknown = set(patch.keys()) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"patch 包含未知字段: {unknown}")
    return out
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_web_storage.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run full suite**

Run: `python3 -m pytest -q`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add atrade/web/__init__.py atrade/web/storage.py tests/test_web_storage.py
git commit -m "feat(web): storage module with atomic write and patch validation"
```

---

### Task 5: Web reload client

**Files:**
- Create: `atrade/web/reload_client.py`
- Test: `tests/test_web_reload_client.py`

**Interfaces:**
- `request_reload() -> dict`  (talks to scheduler via socket)
- `is_socket_available() -> bool`

- [ ] **Step 1: Write failing test**

```python
# tests/test_web_reload_client.py
import json
import socket
import socketserver
import tempfile
import threading
import time
from pathlib import Path

import pytest

from atrade.web.reload_client import request_reload, _socket_path


def _start_mock_server(sock_path, response):
    """启动一个 mock socket server 返回固定响应。"""
    class H(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            self.wfile.write(response)

    class S(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    server = S(sock_path, H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def test_request_reload_parses_ok(tmp_path, monkeypatch):
    sock_path = str(tmp_path / "r.sock")
    monkeypatch.setattr("atrade.web.reload_client._socket_path",
                        lambda: sock_path)
    _start_mock_server(sock_path, b"OK {'holdings': 2}\n")

    result = request_reload()
    assert result["holdings"] == 2


def test_request_reload_returns_none_on_err(tmp_path, monkeypatch):
    sock_path = str(tmp_path / "r.sock")
    monkeypatch.setattr("atrade.web.reload_client._socket_path",
                        lambda: sock_path)
    _start_mock_server(sock_path, b"ERR something broke\n")

    with pytest.raises(RuntimeError):
        request_reload()


def test_request_reload_raises_on_no_socket(tmp_path, monkeypatch):
    sock_path = str(tmp_path / "missing.sock")
    monkeypatch.setattr("atrade.web.reload_client._socket_path",
                        lambda: sock_path)
    with pytest.raises((ConnectionRefusedError, FileNotFoundError, OSError)):
        request_reload()
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python3 -m pytest tests/test_web_reload_client.py -v`
Expected: ImportError

- [ ] **Step 3: Implement reload client**

Create `atrade/web/reload_client.py`:

```python
"""通过 Unix socket 通知 a-trade scheduler 重读配置。"""

from __future__ import annotations

import ast
import os
import socket

_RELOAD_SOCK_ENV = "A_TRADE_RELOAD_SOCK"


def _socket_path() -> str:
    return os.getenv(_RELOAD_SOCK_ENV, "/var/run/a-trade-reload.sock")


def request_reload(timeout: float = 5.0) -> dict:
    """连接 scheduler 的 reload socket，发送 reload 命令，解析响应。"""
    path = _socket_path()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall(b"reload\n")
        chunks = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
        resp = b"".join(chunks).decode("utf-8", errors="ignore").strip()
    if resp.startswith("OK "):
        payload = resp[3:].strip()
        try:
            return ast.literal_eval(payload) if payload.startswith(("{", "[")) else {"raw": payload}
        except (ValueError, SyntaxError):
            return {"raw": payload}
    if resp.startswith("ERR"):
        raise RuntimeError(f"scheduler reload failed: {resp}")
    raise RuntimeError(f"unexpected response: {resp}")
```

- [ ] **Step 4: Run tests, verify pass**

Run: `python3 -m pytest tests/test_web_reload_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add atrade/web/reload_client.py tests/test_web_reload_client.py
git commit -m "feat(web): Unix socket reload client"
```

---

### Task 6: FastAPI app + endpoints

**Files:**
- Create: `atrade/web/app.py`
- Test: `tests/test_web_app.py`

**Interfaces:**
- Routes:
  - `GET /api/health` (公开)
  - `GET /api/holdings` (auth if token set)
  - `PUT /api/holdings/{symbol}` (auth if token set)
  - `POST /api/reload` (auth if token set)
  - `GET /` (serves static HTML)
- Optional Bearer auth via `A_TRADE_WEB_TOKEN` env

- [ ] **Step 1: Write failing test**

```python
# tests/test_web_app.py
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_health_public(monkeypatch):
    monkeypatch.delenv("A_TRADE_WEB_TOKEN", raising=False)
    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_holdings_requires_auth_when_token_set(monkeypatch, tmp_path):
    monkeypatch.setenv("A_TRADE_WEB_TOKEN", "secret123")
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.json")
    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/holdings")
    assert resp.status_code == 401


def test_holdings_ok_with_token(monkeypatch, tmp_path):
    monkeypatch.setenv("A_TRADE_WEB_TOKEN", "secret123")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(
        '{"holdings": [{"symbol": "600522", "name": "中天科技", '
        '"cost_price": 62.0, "quantity": 200, "buy_date": "", "note": ""}], '
        '"disabled_symbols": [], "watch_keywords": []}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/api/holdings", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["symbol"] == "600522"


def test_put_holding_validates(monkeypatch, tmp_path):
    monkeypatch.delenv("A_TRADE_WEB_TOKEN", raising=False)
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(
        '{"holdings": [{"symbol": "600522", "name": "中天科技", '
        '"cost_price": 62.0, "quantity": 200, "buy_date": "", "note": ""}], '
        '"disabled_symbols": [], "watch_keywords": []}'
    )
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    from atrade.web.app import app
    c = TestClient(app)
    resp = c.put("/api/holdings/600522", json={"cost_price": -1})
    assert resp.status_code == 400


def test_root_serves_html(monkeypatch):
    from atrade.web.app import app
    c = TestClient(app)
    resp = c.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<html" in resp.text.lower() or "<!doctype" in resp.text.lower()
```

- [ ] **Step 2: Run tests, verify fail**

Run: `python3 -m pytest tests/test_web_app.py -v`
Expected: ImportError

- [ ] **Step 3: Implement FastAPI app**

Create `atrade/web/app.py`:

```python
"""a-trade 持仓配置 Web 接口。

监听 0.0.0.0:8765，提供：
- GET /api/health
- GET /api/holdings
- PUT /api/holdings/{symbol}
- POST /api/reload
- GET /            单页 HTML UI
- GET /static/*    静态资源

可选 Bearer Token：环境变量 A_TRADE_WEB_TOKEN 非空时启用。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import storage
from .reload_client import request_reload

logger = logging.getLogger("atrade.web")

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_INDEX_HTML = _STATIC_DIR / "index.html"

app = FastAPI(title="a-trade web admin", version="0.1.0")


def _get_token() -> str | None:
    tok = os.getenv("A_TRADE_WEB_TOKEN", "").strip()
    return tok or None


def require_bearer(request: Request) -> None:
    """如果启用了 token，校验 Authorization。"""
    expected = _get_token()
    if expected is None:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer")
    if auth[len("Bearer "):].strip() != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad bearer")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "auth_enabled": _get_token() is not None}


@app.get("/api/holdings", dependencies=[Depends(require_bearer)])
def get_holdings() -> list[dict]:
    meta = storage.read_holdings()
    disabled = set(meta.get("disabled_symbols") or [])
    out = []
    for h in meta.get("holdings", []):
        h2 = dict(h)
        h2["enabled"] = h2.get("symbol") not in disabled
        out.append(h2)
    return out


@app.put("/api/holdings/{symbol}", dependencies=[Depends(require_bearer)])
def put_holding(symbol: str, patch: dict) -> dict:
    try:
        validated = storage.validate_patch(patch)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    sym = symbol.zfill(6)
    if "enabled" in validated:
        # 启停：通过 disabled_symbols 维护
        meta = storage.read_holdings()
        disabled = set(meta.get("disabled_symbols") or [])
        if validated["enabled"]:
            disabled.discard(sym)
        else:
            disabled.add(sym)
        meta["disabled_symbols"] = sorted(disabled)
        storage.write_holdings(meta)
        validated.pop("enabled")

    if validated:
        try:
            updated = storage.update_holding(sym, validated)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"symbol not found: {sym}")
    else:
        # 仅切 enabled
        updated = next(
            (h for h in storage.read_holdings()["holdings"]
             if str(h.get("symbol", "")).zfill(6) == sym),
            None,
        )
        if updated is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"symbol not found: {sym}")

    return updated


@app.post("/api/reload", dependencies=[Depends(require_bearer)])
def post_reload() -> dict:
    try:
        result = request_reload()
    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"scheduler socket unavailable: {e}",
        )
    except RuntimeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    return result


@app.get("/")
def root() -> FileResponse:
    if not _INDEX_HTML.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "index.html not built")
    return FileResponse(_INDEX_HTML, media_type="text/html")


# 静态资源（CSS / JS）
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
```

- [ ] **Step 4: Stub index.html so the test for `/` passes**

Create minimal placeholder `atrade/web/static/index.html`:

```html
<!doctype html>
<html lang="zh">
<head><meta charset="utf-8"><title>a-trade</title></head>
<body><h1>a-trade web admin</h1><p>Loading...</p></body>
</html>
```

- [ ] **Step 5: Run tests, verify pass**

Run: `python3 -m pytest tests/test_web_app.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Run full suite**

Run: `python3 -m pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add atrade/web/app.py atrade/web/static/index.html tests/test_web_app.py
git commit -m "feat(web): FastAPI app with holdings CRUD and reload endpoints"
```

---

### Task 7: Single-page HTML UI (real version)

**Files:**
- Modify: `atrade/web/static/index.html`
- Create: `atrade/web/static/app.js`
- Create: `atrade/web/static/app.css`
- Test: manual via curl or browser

- [ ] **Step 1: Write CSS**

Create `atrade/web/static/app.css`:

```css
:root {
  --bg: #0e1116;
  --fg: #e6edf3;
  --muted: #7d8590;
  --accent: #58a6ff;
  --buy: #3fb950;
  --sell: #f85149;
  --disabled: #6e7681;
  --card: #161b22;
  --border: #30363d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.5;
}
header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  position: sticky; top: 0;
  background: var(--bg);
  z-index: 10;
}
header h1 { margin: 0; font-size: 18px; }
.toolbar {
  display: flex; gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}
input, button, select, textarea {
  background: #0d1117;
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 14px;
  font-family: inherit;
}
input:focus, button:focus { outline: 1px solid var(--accent); }
button { cursor: pointer; }
button.primary { background: var(--accent); color: #0d1117; border-color: var(--accent); font-weight: 600; }
button.danger { color: var(--sell); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
main { padding: 16px; max-width: 720px; margin: 0 auto; }
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.card.disabled { opacity: 0.5; }
.card-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px;
}
.card-title { font-weight: 600; font-size: 16px; }
.row { display: grid; grid-template-columns: 80px 1fr; gap: 8px; margin: 6px 0; align-items: center; }
.row label { color: var(--muted); font-size: 13px; }
.row input { width: 100%; }
.actions { display: flex; gap: 8px; margin-top: 8px; }
.status {
  position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
  background: var(--card);
  border: 1px solid var(--border);
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  display: none;
  z-index: 20;
}
.status.show { display: block; }
.status.ok { border-color: var(--buy); }
.status.err { border-color: var(--sell); }
.muted { color: var(--muted); font-size: 12px; }
```

- [ ] **Step 2: Write JS**

Create `atrade/web/static/app.js`:

```javascript
// a-trade 持仓配置 Web UI
(function () {
  const TOKEN_KEY = "a_trade_web_token";
  let cached = [];

  function token() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(t) {
    localStorage.setItem(TOKEN_KEY, t);
  }

  function authHeaders() {
    const t = token();
    return t ? { Authorization: "Bearer " + t } : {};
  }

  function toast(msg, kind) {
    const el = document.getElementById("status");
    el.textContent = msg;
    el.className = "status show " + (kind || "");
    setTimeout(() => { el.className = "status"; }, 3000);
  }

  async function fetchJSON(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign({}, authHeaders(), opts.headers || {});
    if (opts.body && typeof opts.body !== "string") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    const text = await resp.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text }; }
    return { ok: resp.ok, status: resp.status, data: data };
  }

  function renderCard(h) {
    const sym = h.symbol;
    const card = document.createElement("div");
    card.className = "card" + (h.enabled === false ? " disabled" : "");
    card.dataset.symbol = sym;
    card.innerHTML = `
      <div class="card-head">
        <div class="card-title">${sym} ${h.name || ""}</div>
        <label class="muted"><input type="checkbox" class="enabled-toggle" ${h.enabled !== false ? "checked" : ""}> 启用</label>
      </div>
      <div class="row"><label>成本价</label><input class="cost" type="number" step="0.01" value="${h.cost_price || 0}"></div>
      <div class="row"><label>数量</label><input class="qty" type="number" value="${h.quantity || 0}"></div>
      <div class="row"><label>买入日</label><input class="date" type="text" placeholder="YYYY-MM-DD" value="${h.buy_date || ""}"></div>
      <div class="row"><label>备注</label><input class="note" type="text" maxlength="200" value="${(h.note || "").replace(/"/g, "&quot;")}"></div>
      <div class="actions">
        <button class="primary save">保存</button>
        <button class="toggle">${h.enabled === false ? "启用" : "停用"}</button>
      </div>
    `;
    card.querySelector(".save").onclick = async () => {
      const patch = {
        cost_price: parseFloat(card.querySelector(".cost").value),
        quantity: parseInt(card.querySelector(".qty").value, 10),
        buy_date: card.querySelector(".date").value,
        note: card.querySelector(".note").value,
      };
      const r = await fetchJSON(`/api/holdings/${sym}`, { method: "PUT", body: patch });
      if (r.ok) {
        toast(`${sym} 已保存`, "ok");
        await refresh();
      } else {
        toast(`保存失败: ${r.status} ${JSON.stringify(r.data)}`, "err");
      }
    };
    card.querySelector(".toggle").onclick = async () => {
      const newEnabled = h.enabled === false;
      const r = await fetchJSON(`/api/holdings/${sym}`, {
        method: "PUT",
        body: { enabled: newEnabled },
      });
      if (r.ok) {
        toast(`${sym} 已${newEnabled ? "启用" : "停用"}`, "ok");
        await refresh();
      } else {
        toast(`切换失败: ${r.status}`, "err");
      }
    };
    card.querySelector(".enabled-toggle").onchange = async (e) => {
      const r = await fetchJSON(`/api/holdings/${sym}`, {
        method: "PUT",
        body: { enabled: e.target.checked },
      });
      if (!r.ok) toast(`切换失败: ${r.status}`, "err");
      await refresh();
    };
    return card;
  }

  async function refresh() {
    const r = await fetchJSON("/api/holdings");
    if (!r.ok) {
      toast(`加载失败: ${r.status}`, "err");
      return;
    }
    cached = r.data;
    const main = document.getElementById("list");
    main.innerHTML = "";
    r.data.forEach((h) => main.appendChild(renderCard(h)));
  }

  async function reloadConfig() {
    const r = await fetchJSON("/api/reload", { method: "POST" });
    if (r.ok) {
      toast(`已重载: ${JSON.stringify(r.data)}`, "ok");
    } else {
      toast(`重载失败: ${r.status} ${JSON.stringify(r.data)}`, "err");
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const tokInput = document.getElementById("token-input");
    tokInput.value = token();
    document.getElementById("save-token").onclick = () => {
      setToken(tokInput.value.trim());
      toast("Token 已保存", "ok");
      refresh();
    };
    document.getElementById("reload-btn").onclick = reloadConfig;
    refresh();
  });
})();
```

- [ ] **Step 3: Write HTML**

Replace `atrade/web/static/index.html`:

```html
<!doctype html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>a-trade 持仓配置</title>
  <link rel="stylesheet" href="/static/app.css">
</head>
<body>
  <header>
    <h1>⚙️ a-trade 持仓配置</h1>
    <div class="toolbar">
      <input id="token-input" type="password" placeholder="Bearer Token (可选)" style="flex:1">
      <button id="save-token">保存 Token</button>
      <button id="reload-btn" class="primary">🔄 重载配置</button>
    </div>
  </header>
  <main>
    <div id="list"></div>
    <p class="muted">修改后点保存；改完点"重载配置"让调度器立即生效</p>
  </main>
  <div id="status" class="status"></div>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Smoke-test the UI renders**

Run: `python3 -c "from fastapi.testclient import TestClient; from atrade.web.app import app; c = TestClient(app); print(c.get('/').status_code, c.get('/static/app.css').status_code, c.get('/static/app.js').status_code)"`
Expected: 200 200 200

- [ ] **Step 5: Commit**

```bash
git add atrade/web/static/
git commit -m "feat(web): single-page HTML UI for holdings editing"
```

---

### Task 8: systemd service + .env.example + deploy script

**Files:**
- Create: `deploy/a-trade-web.service`
- Modify: `.env.example`
- Create: `scripts/install_web_service.sh`
- Test: manual on VPS

- [ ] **Step 1: Write systemd unit**

Create `deploy/a-trade-web.service`:

```ini
[Unit]
Description=a-trade web admin
After=network-online.target a-trade.service
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

- [ ] **Step 2: Update .env.example**

Add at end:

```
# a-trade web admin (可选)
# 留空 = 公开访问；非空 = 启用 Bearer Token 鉴权
A_TRADE_WEB_TOKEN=
```

- [ ] **Step 3: Write install script**

Create `scripts/install_web_service.sh`:

```bash
#!/usr/bin/env bash
# 在 VPS 上安装 a-trade-web systemd 服务。
#
# 用法: bash scripts/install_web_service.sh
set -euo pipefail

SERVICE_FILE="/etc/systemd/system/a-trade-web.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="$SCRIPT_DIR/../deploy/a-trade-web.service"

if [[ ! -f "$SOURCE" ]]; then
  echo "错误：未找到 $SOURCE" >&2
  exit 1
fi

cp "$SOURCE" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable a-trade-web
systemctl restart a-trade-web
sleep 2
systemctl --no-pager status a-trade-web
echo "===" 
echo "Web 服务已启动。健康检查："
curl -sS http://127.0.0.1:8765/api/health || echo "(curl 失败)"
```

`chmod +x scripts/install_web_service.sh` after creating.

- [ ] **Step 4: Commit**

```bash
git add deploy/a-trade-web.service .env.example scripts/install_web_service.sh
git commit -m "feat(deploy): systemd unit + install script for a-trade-web"
```

---

### Task 9: End-to-end local test (mock scheduler)

**Files:**
- Create: `tests/test_web_e2e.py`

- [ ] **Step 1: Write test**

```python
# tests/test_web_e2e.py
"""End-to-end: web PUT → mock scheduler reload → JSON file updated."""
import json
import os
import socket
import socketserver
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def fake_scheduler(monkeypatch, tmp_path):
    """启动一个 fake scheduler socket，响应 reload。"""
    sock_path = tmp_path / "reload.sock"
    monkeypatch.setenv("A_TRADE_RELOAD_SOCK", str(sock_path))
    monkeypatch.setattr("atrade.web.reload_client._socket_path",
                        lambda: str(sock_path))

    class H(socketserver.StreamRequestHandler):
        def handle(self):
            self.rfile.readline()
            self.wfile.write(b"OK {'holdings': 1, 't_symbols': 1}\n")

    class S(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    server = S(str(sock_path), H)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    # 设置 holdings 文件
    h_path = tmp_path / "h.json"
    h_path.write_text(json.dumps({
        "holdings": [{"symbol": "600522", "name": "中天科技",
                      "cost_price": 62.0, "quantity": 200,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", h_path)
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "h.local.json")

    yield sock_path


def test_put_then_reload_updates_file(fake_scheduler):
    from atrade.web.app import app
    c = TestClient(app)

    # 1) PUT 改成本价
    r = c.put("/api/holdings/600522", json={"cost_price": 65.5})
    assert r.status_code == 200
    assert r.json()["cost_price"] == 65.5

    # 2) POST reload
    r = c.post("/api/reload")
    assert r.status_code == 200
    assert r.json()["holdings"] == 1


def test_put_then_get_reflects_change(fake_scheduler):
    from atrade.web.app import app
    c = TestClient(app)

    c.put("/api/holdings/600522", json={"quantity": 300})
    r = c.get("/api/holdings")
    assert r.status_code == 200
    holdings = r.json()
    target = next(h for h in holdings if h["symbol"] == "600522")
    assert target["quantity"] == 300


def test_disable_via_enabled_false(fake_scheduler):
    from atrade.web.app import app
    c = TestClient(app)

    r = c.put("/api/holdings/600522", json={"enabled": False})
    assert r.status_code == 200

    r = c.get("/api/holdings")
    target = next(h for h in r.json() if h["symbol"] == "600522")
    assert target["enabled"] is False
```

- [ ] **Step 2: Run e2e test**

Run: `python3 -m pytest tests/test_web_e2e.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: Run full test suite**

Run: `python3 -m pytest -q && python3 -m ruff check atrade/ tests/`
Expected: all pass, no lint errors

- [ ] **Step 4: Commit**

```bash
git add tests/test_web_e2e.py
git commit -m "test(web): end-to-end PUT + reload flow with fake scheduler socket"
```

---

### Task 10: Deploy to VPS and verify

**Files:** none (deployment only)

- [ ] **Step 1: Push to origin + vps**

```bash
git push origin main
git push vps main
```

- [ ] **Step 2: Install web service on VPS**

```bash
ssh root@96.30.194.21 'cd /opt/a-trade/current && bash scripts/install_web_service.sh'
```

Expected: service starts, `curl http://127.0.0.1:8765/api/health` returns `{"ok": true}`

- [ ] **Step 3: Verify from public IP**

From local machine:

```bash
curl http://96.30.194.21:8765/api/health
```

Expected: `{"ok":true,...}` (no auth)

- [ ] **Step 4: End-to-end smoke test**

```bash
curl -X PUT http://96.30.194.21:8765/api/holdings/600522 \
  -H 'Content-Type: application/json' \
  -d '{"cost_price": 65.0}'
curl http://96.30.194.21:8765/api/holdings
curl -X POST http://96.30.194.21:8765/api/reload
```

Expected: holdings updated, reload returns job counts.

- [ ] **Step 5: Document in STATUS**

Update `docs/progress/2026-07-23-android-holdings-app/STATUS.md` with verification results and final timestamp.

- [ ] **Step 6: Final commit**

```bash
git add docs/progress/2026-07-23-android-holdings-app/STATUS.md
git commit -m "docs: record web admin deployment verification"
```

---

## Spec Coverage Checklist

- [x] VPS FastAPI on port 8765 → Task 6, Task 8
- [x] Bearer Token auth (optional, env-gated) → Task 6
- [x] GET /api/holdings, PUT /api/holdings/{symbol}, POST /api/reload → Task 6
- [x] Single-page HTML UI → Task 7
- [x] Unix socket reload → Task 3, Task 5
- [x] disabled_symbols support → Task 1
- [x] Atomic JSON write → Task 4
- [x] systemd unit → Task 8
- [x] End-to-end test → Task 9
- [x] Deploy + verify → Task 10
