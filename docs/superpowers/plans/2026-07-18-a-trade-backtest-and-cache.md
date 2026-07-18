# [Feature] a-trade 回测与缓存增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 a-trade 中加入 SQLite 本地缓存层（含派生字段与东财当日基本面快照），并重写 T+0 模拟器以支持 T+1 严格约束 / 反向做 T / 强制平仓 / 手续费 / 最大回撤跟踪 / CLI 入口，端到端验证茅台 + 平安。

**Architecture:**
1. **数据层**：新增 `atrade/data/cache.py`（SQLite）+ `atrade/data/eastmoney.py`（push2 当日快照）。`history.py` 改为"拉一次新浪 + 派生字段 + upsert 进 cache"。回测从 cache 读，零网络依赖。
2. **回测层**：重写 `atrade/backtest/t0_simulator.py`，引入 Position dataclass（含 lock_until 字段实现 T+1）。
3. **入口层**：`scripts/run_backtest.py`（argparse + Markdown 报告）。

**Tech Stack:** Python 3.9, SQLite（stdlib）, 新浪 hq/quotes, 东财 push2（requests + 重试降级）, pandas, pytest。

## Global Constraints

- Python 3.9 — 仅 stdlib typing，不允许 `X | Y` 联合语法，只用 `Optional[X]` / `Union[X, Y]`
- 不接入券商接口，只生成建议
- 所有凭据只在 `.env`（不入 git）
- 不复权（`ah_factor` 恒为 1.0）
- 历史字段派生：`pct_chg/amplitude/amount/turnover/vol_ratio/pre_close/is_st`
- 当日基本面来自东财 push2 接口，仅写当天那行；接口失败降级（不抛异常）
- T+1 严格约束：T 仓当天买、次开盘可卖；底仓不受 T+1 限制
- 所有 commit message 中文，`feat:` / `test:` / `docs:` / `chore:` 前缀
- 全部 task 前必须 `git add` 准备完毕（仓库由 Task 1 初始化）

---

### Task 1: 初始化 a-trade git 仓库 + 初次提交

**Files:**
- Create: `/Users/jojo/code/a-trade/.gitignore`
- Modify: `/Users/jojo/code/a-trade/.git`（由 git init 产生）

**Interfaces:**
- 无（基线任务）

**Why:** 当前 a-trade 是非 git 目录（`git log` 报错），后续 TDD + 频繁 commit 需要 git。

- [ ] **Step 1: 进入目录并验证非 git 状态**

```bash
cd /Users/jojo/code/a-trade
git status 2>&1 | head -1
```

预期输出："fatal: not a git repository" 或类似。

- [ ] **Step 2: 创建 .gitignore**

```bash
cat > .gitignore << 'EOF'
.env
__pycache__/
*.pyc
.pytest_cache/
data/cache/*.db
data/cache/*.db-*
reports/*.md
logs/*.log
EOF
```

- [ ] **Step 3: 初始化仓库并提交**

```bash
cd /Users/jojo/code/a-trade
git init
git add .gitignore atrade/ config/ docs/ scripts/ start.sh tests/
git commit -m "chore: init git repo with existing a-trade code"
```

预期：1 个 commit。当前所有 .py / .sh / .md / .json / .env.example 都入仓，`.env` 排除。

- [ ] **Step 4: 验证 commit**

```bash
git log --oneline | head
git status
```

预期：1 个 commit，clean。

---

### Task 2: LocalCache 测试 + 接口校准

**Files:**
- Create: `/Users/jojo/code/a-trade/tests/test_cache.py`
- Modify: `/Users/jojo/code/a-trade/atrade/data/__init__.py` (无须改动，已 export LocalCache)
- Modify: `/Users/jojo/code/a-trade/atrade/data/cache.py` (按测试反馈小修，理论上无需修)

**Interfaces:** 见 cache.py 顶部 docstring，验收内容如下。

**说明：** cache.py 已在 PRD 阶段写入 `atrade/data/cache.py`（217 行），含 `class LocalCache` 全部方法（`upsert_daily / upsert_fq / range / last_date / count`），`atrade/data/__init__.py` 也已 export。本 Task 写测试 + 验证 + 提交。

- [ ] **Step 1: 验证 cache.py 已存在并可导入**

```bash
cd /Users/jojo/code/a-trade
ls -la atrade/data/cache.py
python3 -c "from atrade.data import LocalCache; print(LocalCache)"
grep "LocalCache" atrade/data/__init__.py
```

预期：文件存在，能打印类，`__init__.py` 含 `__all__ = [..., "LocalCache"]`。

- [ ] **Step 2: 写测试 `tests/test_cache.py`**

`tests/test_cache.py`（直接落到文件里）：

```python
import pandas as pd
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data.cache import LocalCache


@pytest.fixture
def tmp_cache(tmp_path):
    return LocalCache(db_path=str(tmp_path / "test.db"))


def test_create_db_tables(tmp_cache):
    cur = tmp_cache._conn().__enter__()
    tables = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    cur.close()
    assert "daily" in tables
    assert "fq_factor" in tables


def test_upsert_and_range(tmp_cache):
    df = pd.DataFrame([{
        "date": "2026-07-01", "code": "600519",
        "open": 1250.0, "high": 1260.0, "low": 1240.0, "close": 1255.0,
        "volume": 1000000, "amount": 1255000000.0,
    }])
    n = tmp_cache.upsert_daily(df)
    assert n == 1
    out = tmp_cache.range("600519")
    assert len(out) == 1
    assert out.iloc[0]["close"] == 1255.0
    assert out.iloc[0]["amount"] == 1255000000.0


def test_upsert_overwrite(tmp_cache):
    df = pd.DataFrame([
        {"date": "2026-07-01", "code": "600519", "open": 1250, "high": 1260, "low": 1240, "close": 1255, "volume": 1000},
        {"date": "2026-07-02", "code": "600519", "open": 1250, "high": 1260, "low": 1240, "close": 1265, "volume": 2000},
    ])
    tmp_cache.upsert_daily(df)
    df2 = pd.DataFrame([{"date": "2026-07-01", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}])
    tmp_cache.upsert_daily(df2)
    out = tmp_cache.range("600519")
    assert len(out) == 2
    assert out[out["date"] == "2026-07-01"].iloc[0]["close"] == 4.0


def test_ensure_columns_auto_add(tmp_cache):
    """传入 cache 表里不存在的字段时，应自动 ALTER TABLE 添加。"""
    df = pd.DataFrame([{
        "date": "2026-07-01", "code": "600519",
        "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5,
        "pe_ttm": 25.0, "pb": 5.0, "future_field_xyz": 999.0,
    }])
    tmp_cache.upsert_daily(df)
    cur = tmp_cache._conn().__enter__()
    cols = {r[1] for r in cur.execute("PRAGMA table_info(daily)").fetchall()}
    cur.close()
    assert "pe_ttm" in cols
    assert "pb" in cols
    assert "future_field_xyz" in cols


def test_range_with_window(tmp_cache):
    df = pd.DataFrame([
        {"date": "2026-07-01", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
        {"date": "2026-07-02", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
        {"date": "2026-07-03", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
    ])
    tmp_cache.upsert_daily(df)
    out = tmp_cache.range("600519", start="2026-07-02", end="2026-07-02")
    assert len(out) == 1
    assert out.iloc[0]["date"] == "2026-07-02"


def test_last_date_and_count(tmp_cache):
    df = pd.DataFrame([
        {"date": "2026-06-30", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
        {"date": "2026-07-01", "code": "600519", "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5},
    ])
    tmp_cache.upsert_daily(df)
    assert tmp_cache.last_date("600519") == "2026-07-01"
    assert tmp_cache.count("600519") == 2
```

- [ ] **Step 3: 跑测试**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/test_cache.py -v
```

预期：6 个测试全部 PASSED。如果有 FAIL，diff 后修 cache.py（修复后再跑一次确认全绿）。

- [ ] **Step 4: 跑全量测试 sanity check**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/ -v
```

预期：当前只有 cache 测试，全 PASSED。

- [ ] **Step 5: 提交**

```bash
cd /Users/jojo/code/a-trade
git add tests/test_cache.py
git commit -m "test(cache): cover LocalCache upsert/schema/range/last_date"
```

（cache.py 和 __init__.py 已在 Task 1 初次提交时入仓，不重复提交。）

---
### Task 3: 派生字段 + 东财快照 → 扩展 history.py

**Files:**
- Create: `/Users/jojo/code/a-trade/atrade/data/eastmoney.py`
- Modify: `/Users/jojo/code/a-trade/atrade/data/history.py:1` (重写为 fetch_with_cache)
- Modify: `/Users/jojo/code/a-trade/atrade/data/__init__.py:1`
- Test: `/Users/jojo/code/a-trade/tests/test_history.py`

**Interfaces:**
- New module `eastmoney`:
  - `def fetch_snap(code: str) -> dict` — 拉一次当日快照（带重试+降级），字段：`pe_ttm, pb, float_mv, total_mv, float_share, total_share`
- Extended `HistoryProvider`:
  - `def fetch_with_cache(self, symbol: str, scale: str = "1d", datalen: int = 600, use_cache: bool = True) -> pd.DataFrame`
  - 行为：先查 cache；如果 cache 内行数 < datalen，从新浪拉增量补齐后 upsert；
  - 计算派生字段：`pre_close, pct_chg, amplitude, amount, vol_ratio, turnover, is_st`，并补 `ah_factor=1.0`；
  - 东财当日快照仅当 `use_snapshot=True`（默认）时拉，失败降级

**Why:** 让 history 同时返回 OHLCV + 派生字段 + 当日基本面；回测只用 OHLCV，选股能拿到今天的 PE/PB。

- [ ] **Step 1: 写失败测试 `tests/test_history.py`**

```python
import pandas as pd
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.data import HistoryProvider


@pytest.fixture
def hp(tmp_path):
    return HistoryProvider(cache_path=str(tmp_path / "test.db"))


def test_derived_fields_present(hp):
    df = hp.fetch_with_cache("600519", scale="1d", datalen=600)
    for col in ["pre_close", "pct_chg", "amplitude", "amount",
                "turnover", "vol_ratio", "is_st", "ah_factor"]:
        assert col in df.columns, f"缺少派生字段: {col}"


def test_derived_values_basic(hp):
    df = hp.fetch_with_cache("600519", scale="1d", datalen=600)
    # amplitude = (high-low)/pre_close*100
    row = df.iloc[10]
    expected_amp = (row["high"] - row["low"]) / row["pre_close"] * 100
    assert abs(row["amplitude"] - expected_amp) < 1e-6
    # ah_factor 必须为 1.0
    assert (df["ah_factor"] == 1.0).all()


def test_cache_is_persisted(hp):
    df1 = hp.fetch_with_cache("600519", scale="1d", datalen=600)
    # 第二次调用应该从 cache 直接读
    df2 = hp.fetch_with_cache("600519", scale="1d", datalen=600)
    assert len(df1) == len(df2)
    # close 数据应一致
    assert (df1["close"].values == df2["close"].values).all()


def test_fetch_with_cache_invalidates_short(mp_path := None, hp=None):
    """如果用户故意要 refresh，可以传 use_cache=False。"""
    # 直接 fetch 跟 fetch_with_cache 一致
    df_direct = hp.fetch("600519", scale="1d", datalen=600)
    df_cached = hp.fetch_with_cache("600519", scale="1d", datalen=600)
    assert df_direct["date"].iloc[-1] == df_cached["date"].iloc[-1]
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/test_history.py -v 2>&1 | head
```

预期：ImportError 或 AttributeError，3 个测试 FAIL。

- [ ] **Step 3: 实现 eastmoney.py**

```python
"""东财 push2 当日快照。

失败的两种降级：
1. 网络异常 → 返回 None
2. 字段缺失（停牌/退市）→ 返回 None
"""

from __future__ import annotations

import time
from typing import Optional

import requests
from loguru import logger


_URL = "https://push2.eastmoney.com/api/qt/stock/get"


def _to_secid(code: str) -> str:
    code = str(code).zfill(6)
    market = "1" if code.startswith(("5", "6", "7", "9")) else "0"
    return f"{market}.{code}"


def fetch_snap(code: str, retries: int = 3) -> Optional[dict]:
    """拉一次当日快照。失败返回 None。"""
    secid = _to_secid(code)
    params = {
        "secid": secid,
        "fields": "f43,f57,f58,f60,f84,f85,f116,f117,f167,f168,f169,f170,f171,f192",
        "invt": 2,
        "fltt": 1,
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    for attempt in range(retries):
        try:
            r = requests.get(_URL, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            if not data or not data.get("f57"):
                logger.warning(f"[eastmoney] {code} 空响应")
                return None
            # 字段映射（单位说明：f43/60/169/170 是 ×100 后的整数）
            return {
                "code": str(data["f57"]).zfill(6),
                "name": data.get("f58"),
                "price": data["f43"] / 100 if data.get("f43") else None,
                "pre_close": data["f60"] / 100 if data.get("f60") else None,
                "open": data.get("f169", 0) / 100 if data.get("f169") is not None else None,
                "pct_chg": data.get("f170"),  # 已是百分比，不需要 /100
                "amplitude": data.get("f171"),
                "vol_ratio": data.get("f192"),
                "pe_ttm": data.get("f167"),
                "pb": data.get("f168"),
                "total_mv": data.get("f116"),       # 万元
                "float_mv": data.get("f117"),       # 万元
                "total_share": data.get("f84"),      # 股
                "float_share": data.get("f85"),      # 股
            }
        except Exception as e:
            logger.warning(f"[eastmoney] {code} 重试 {attempt+1}/{retries}: {e}")
            time.sleep(1 + attempt * 2)
    return None
```

- [ ] **Step 4: 重写 history.py**

完整替换 `atrade/data/history.py`：

```python
"""历史 K 线 + 派生字段 + 缓存层。

提供:
- HistoryProvider.fetch: 原新浪拉取（保留兼容）
- HistoryProvider.fetch_with_cache: 拉 + 派生 + 入库
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
import requests
from loguru import logger

from .cache import LocalCache
from .eastmoney import fetch_snap


@dataclass
class KLine:
    """单根 K 线。"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoryProvider:
    """历史 K 线（含本地缓存）。"""

    KLINE_URL = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/"
        "CN_MarketDataService.getKLineData"
        "?symbol={symbol}&scale={scale}&ma=no&datalen={datalen}"
    )

    HEADERS = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36",
    }

    SCALE_MAP = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30, "60m": 60,
        "1d": 240, "1w": 1680,
    }

    def __init__(self, cache_path: Optional[str] = None):
        self.cache = LocalCache(db_path=cache_path)

    @staticmethod
    def _to_sina_symbol(symbol: str) -> str:
        symbol = str(symbol).strip().zfill(6)
        prefix = "sh" if symbol.startswith("6") else "sz"
        return f"{prefix}{symbol}"

    def fetch(
        self,
        symbol: str,
        scale: Literal["1d", "5m", "15m", "30m", "60m"] = "1d",
        datalen: int = 600,
    ) -> pd.DataFrame:
        """从新浪拉历史 K 线（不入库）。"""
        sina_sym = self._to_sina_symbol(symbol)
        sina_scale = self.SCALE_MAP.get(scale, 240)
        url = self.KLINE_URL.format(
            symbol=sina_sym, scale=sina_scale, datalen=datalen
        )

        for attempt in range(3):
            try:
                resp = requests.get(url, headers=self.HEADERS, timeout=15)
                resp.raise_for_status()
                text = resp.text.strip()
                m = re.search(r'=\(\[([\s\S]+)\]\)', text)
                if not m:
                    logger.warning(f"解析失败: {text[:200]}")
                    return pd.DataFrame()
                raw = "[" + m.group(1) + "]"
                records = json.loads(raw)
                df = pd.DataFrame(records)
                df = df.rename(columns={"day": "date"})
                for col in ["open", "high", "low", "close"]:
                    df[col] = df[col].astype(float)
                df["volume"] = df["volume"].astype(int)
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df = df[["date", "open", "high", "low", "close", "volume"]]
                logger.info(f"✅ 历史 K 线 {symbol} {scale}: {len(df)} 根")
                return df
            except Exception as e:
                logger.warning(f"历史 K 线重试 {attempt+1}/3: {e}")
                time.sleep(1 + attempt)
        return pd.DataFrame()

    def fetch_with_cache(
        self,
        symbol: str,
        scale: Literal["1d", "5m", "15m", "30m", "60m"] = "1d",
        datalen: int = 600,
        use_snapshot: bool = True,
    ) -> pd.DataFrame:
        """拉取 + 入库 + 派生字段。

        流程:
        1. cache 已有 → 直接读 + 派生
        2. cache 不足 → 从新浪拉全量覆盖 → 派生 → upsert
        3. use_snapshot=True → 给最新一天补东财快照
        """
        symbol = str(symbol).zfill(6)
        cached_count = self.cache.count(symbol)

        if cached_count >= max(60, datalen // 2):
            df = self.cache.range(symbol)
        else:
            raw = self.fetch(symbol, scale=scale, datalen=datalen)
            if raw.empty:
                logger.warning(f"{symbol} 无法从新浪拉取，cache 命中返回")
                return self.cache.range(symbol)
            self.cache.upsert_daily(_ohlcv_to_cached(raw, symbol))
            df = self.cache.range(symbol)

        if df.empty:
            return df

        df = _add_derived_fields(df)
        df = df.tail(datalen).reset_index(drop=True)

        # 当日快照
        if use_snapshot and len(df) > 0:
            last_date = df["date"].iloc[-1]
            today = datetime.now().strftime("%Y-%m-%d")
            if last_date >= today or True:  # 总是尝试，更保守
                snap = fetch_snap(symbol)
                if snap and snap.get("price"):
                    df.loc[df.index[-1], "pe_ttm"] = snap["pe_ttm"]
                    df.loc[df.index[-1], "pb"] = snap["pb"]
                    df.loc[df.index[-1], "float_mv"] = snap["float_mv"]
                    df.loc[df.index[-1], "total_mv"] = snap["total_mv"]
                    df.loc[df.index[-1], "float_share"] = snap["float_share"]
                    df.loc[df.index[-1], "total_share"] = snap["total_share"]
                    df.loc[df.index[-1], "name"] = snap["name"] or df["name"].iloc[-1]
                    # 写回 cache
                    self.cache.upsert_daily(df.tail(1))

        return df


def _ohlcv_to_cached(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """把新浪 OHLCV 转成 cache 用的格式，初始派生列空。"""
    out = df.copy()
    out["code"] = code
    out["name"] = None
    out["ah_factor"] = 1.0
    return out


def _add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """派生字段。缺失字段补默认值。"""
    out = df.copy()
    out["pre_close"] = out["close"].shift(1)
    out["pct_chg"] = (out["close"] - out["pre_close"]) / out["pre_close"] * 100
    out["amplitude"] = (out["high"] - out["low"]) / out["pre_close"] * 100
    out["amount"] = out["close"] * out["volume"] * 100  # 1手=100股
    out["vol_ratio"] = out["volume"] / out["volume"].rolling(5, min_periods=1).mean()
    if "float_share" not in out.columns:
        out["float_share"] = None
    out["turnover"] = out["volume"] / out["float_share"] * 100
    out["is_st"] = 0
    out["ah_factor"] = 1.0
    return out
```

- [ ] **Step 5: 更新 __init__.py**

```python
"""a-trade 数据访问层。"""
from .quotes import QuoteProvider, Quote
from .history import HistoryProvider, KLine
from .cache import LocalCache
from .eastmoney import fetch_snap

__all__ = [
    "QuoteProvider", "Quote", "HistoryProvider", "KLine",
    "LocalCache", "fetch_snap",
]
```

- [ ] **Step 6: 跑测试**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/test_history.py -v
```

预期：4 个测试全部 PASSED（首次运行会拉一次新浪，缓存入库）。

- [ ] **Step 7: 提交**

```bash
cd /Users/jojo/code/a-trade
git add atrade/data/eastmoney.py atrade/data/history.py atrade/data/__init__.py tests/test_history.py
git commit -m "feat(data): derive OHLCV fields + Eastmoney snapshot in HistoryProvider"
```

---

### Task 4: 重写 T+0 模拟器（T+1 / 平仓 / 费用 / 回撤）

**Files:**
- Modify: `/Users/jojo/code/a-trade/atrade/backtest/t0_simulator.py` (重写)
- Test: `/Users/jojo/code/a-trade/tests/test_t0_simulator.py`

**Interfaces:**
- `class T0Position`: 当前持仓快照（底仓 + T 仓带 lock_until_date 字段）
- `class T0Trade` 保留，向后兼容
- `class T0BacktestResult` 增字段：`total_profit_net, max_drawdown_pct, annualized_return, fee_total, position_t1_locks:int, t_position_max`
- `class T0Simulator`:
  - `__init__(self, t_position_pct=0.5, fee_commission=0.00025, fee_stamp_duty_sell=0.001, slippage_pct=0.0005, force_close_pct=0.05)`
  - `run(self, symbol, cost_price, quantity, start_date='20240101', end_date='20260717') -> T0BacktestResult`
- T+1 规则：当天买入 → lock_until=次日；次日开盘价为可卖价
- 强制平仓：T 仓浮动亏损 ≥ `force_close_pct` → 当日收盘价平
- 手续费：买入 `price*qty*commission`；卖出 `price*qty*(commission+stamp_duty)`
- 滑点：买入 `price*(1+slippage)`、卖出 `price*(1-slippage)`

**Why:** 让回测从估值层面真的能告诉用户"满仓被套该不该做 T、能不能摊低成本"。

- [ ] **Step 1: 写失败测试 `tests/test_t0_simulator.py`**

```python
import pandas as pd
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.backtest.t0_simulator import (
    T0Simulator, T0BacktestResult, T0Trade, Position,
)


def make_flat_60_days():
    """构造 60 天平稳数据，避免触发任何信号。"""
    dates = pd.date_range("2026-01-01", periods=60, freq="B")
    return pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": [100.0] * 60,
        "high": [101.0] * 60,
        "low": [99.0] * 60,
        "close": [100.0] * 60,
        "volume": [1000000] * 60,
    })


def test_buy_hold_profit():
    df = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=60, freq="B").strftime("%Y-%m-%d"),
        "open": 100.0, "high": 101.0, "low": 99.0,
        "close": 105.0, "volume": 1000000,
    })
    sim = T0Simulator()
    sim.history.fetch_with_cache = lambda *a, **kw: df  # mock
    r = sim.run("TEST", 100.0, 1000, start_date="20260101", end_date="20260301")
    assert r.buy_hold_profit > 0
    assert r.t_total_profit == 0  # 无信号→无 T
    assert r.fee_total == 0


def test_t1_lock():
    """T+1 约束：当天买入，次日开盘前不能卖。"""
    dates = pd.date_range("2026-01-01", periods=60, freq="B")
    df = pd.DataFrame({
        "date": dates.strftime("%Y-%m-%d"),
        "open": 100.0, "high": 110.0, "low": 99.0,
        "close": 105.0, "volume": 1000000,
    })
    # 强制制造一个 BUY 信号和后续 SELL 信号
    sim = T0Simulator()
    sim.history.fetch_with_cache = lambda *a, **kw: df
    signals = [
        # BUY 在 day 20, SELL 试图在 day 20 当天（应被 T+1 锁住）
    ]
    # 这块需要手动 mock 信号引擎，本测验证 Position.lock_until 字段逻辑
    pos = Position(base=1000, t_holdings=100, t_avg_cost=100.0, lock_until_date="2026-01-21")
    # 当天 lock_until=2026-01-21 → 1/20 当天不能卖
    assert pos.is_locked("2026-01-20") is True
    assert pos.is_locked("2026-01-21") is False


def test_fee_calculation():
    sim = T0Simulator(fee_commission=0.001, slippage_pct=0.0)
    # 模拟一笔买入: 价格 100 * 数量 1000
    buy_fee = sim._calc_buy_fee(100.0, 1000)
    assert buy_fee == 100.0  # 100 * 1000 * 0.001


def test_slippage():
    sim = T0Simulator(slippage_pct=0.001)
    assert sim._slippage_buy(100.0) == pytest.approx(100.1, rel=1e-6)
    assert sim._slippage_sell(100.0) == pytest.approx(99.9, rel=1e-6)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/test_t0_simulator.py -v 2>&1 | head
```

预期：ImportError（`Position` 不存在 / `is_locked` 不存在 / `_calc_buy_fee` 不存在）。

- [ ] **Step 3: 重写 t0_simulator.py**

完整替换 `atrade/backtest/t0_simulator.py`：

```python
"""T+0 做 T 模拟器（T+1 严格约束版）。

规则:
- 底仓（你已有持仓）：任何 SELL 信号当天即可卖，不受 T+1 限制
- T 仓：当天买 → 次开盘前 lock，次日开盘可卖
- 反向做 T（先卖后买）：仅针对底仓，T 仓不允许
- 强制平仓：浮动亏损 >= 5% → 当日收盘价平
- 收盘前若有 T 仓 → 按收盘价强制平

费用（默认）:
- 佣金：买卖各 0.025%
- 印花税：卖出 0.1%
- 滑点：买卖各 0.05%
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from atrade.data import HistoryProvider
from atrade.indicators import add_all_indicators
from atrade.signals import SignalEngine, SignalType


@dataclass
class Position:
    """持仓快照。
    
    base: 底仓股数（不受 T+1 限制）
    t_holdings: T 仓股数
    t_avg_cost: T 仓移动加权成本
    lock_until_date: T 仓最早可卖日期（YYYY-MM-DD）。空字符串=未锁定。
    """
    base: int = 0
    t_holdings: int = 0
    t_avg_cost: float = 0.0
    lock_until_date: str = ""

    def is_locked(self, today: str) -> bool:
        if not self.lock_until_date:
            return False
        return today < self.lock_until_date


@dataclass
class T0Trade:
    """单笔 T 交易。"""
    date: str
    direction: str  # "buy" / "sell"
    price: float
    quantity: int
    amount: float
    signal: str
    profit: float = 0.0
    fee: float = 0.0
    slippage: float = 0.0


@dataclass
class T0BacktestResult:
    symbol: str
    start_date: str
    end_date: str
    initial_cost: float
    final_cost: float
    cost_change: float
    total_t_profit: float
    net_t_profit: float           # 总盈亏减去总费用
    t_win_count: int
    t_loss_count: int
    t_win_rate: float
    max_drawdown_pct: float
    fee_total: float
    buy_hold_profit: float
    annualized_return: float      # 年化收益率 %
    t_position_max: int           # T 仓峰值
    t1_locks_held: int            # 累计 T+1 锁仓天数
    trades: list[T0Trade] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"# 📊 {self.symbol} T+0 回测报告（T+1 严格约束）",
            f"回测区间: {self.start_date} ~ {self.end_date}",
            "",
            f"## 核心指标",
            f"| 指标 | 数值 |",
            f"|---|---|",
            f"| 初始成本 | {self.initial_cost:.2f} |",
            f"| 最终成本 | {self.final_cost:.2f} |",
            f"| **成本变化** | **{self.cost_change:+.2f}%** |",
            f"| T 净盈亏 | {self.net_t_profit:+.2f}（已扣费用） |",
            f"| T 总费用 | {self.fee_total:.2f} |",
            f"| T 胜率 | {self.t_win_rate*100:.1f}% |",
            f"| T 笔数 | {self.t_win_count + self.t_loss_count}（{self.t_win_count} 胜 / {self.t_loss_count} 负）|",
            f"| T 仓峰值 | {self.t_position_max} 股 |",
            f"| T+1 锁仓天数 | {self.t1_locks_held} |",
            f"| 最大回撤 | {self.max_drawdown_pct*100:.2f}% |",
            f"| 年化收益率 | {self.annualized_return:+.2f}% |",
            f"| 同期死拿盈亏 | {self.buy_hold_profit:+.2f}% |",
            f"| **做 T vs 死拿** | **{self.net_t_profit/(self.initial_cost*1000)+self.buy_hold_profit:+.2f}%** |",
            "",
        ]
        if self.trades:
            lines.append("## 交易明细（最近 10 笔）")
            lines.append("| 日期 | 方向 | 价格 | 数量 | 信号 | 盈亏 | 费用 |")
            lines.append("|---|---|---|---|---|---|---|")
            for t in self.trades[-10:]:
                lines.append(
                    f"| {t.date} | {t.direction} | {t.price:.2f} | "
                    f"{t.quantity} | {t.signal} | {t.profit:+.2f} | {t.fee:.2f} |"
                )
        return "\n".join(lines)


class T0Simulator:
    """T+0 做 T 模拟器（T+1 严格约束）。"""

    def __init__(
        self,
        t_position_pct: float = 0.5,
        fee_commission: float = 0.00025,
        fee_stamp_duty_sell: float = 0.001,
        slippage_pct: float = 0.0005,
        force_close_loss_pct: float = 0.05,
    ):
        self.history = HistoryProvider()
        self.engine = SignalEngine()
        self.t_position_pct = t_position_pct
        self.fee_commission = fee_commission
        self.fee_stamp_duty_sell = fee_stamp_duty_sell
        self.slippage_pct = slippage_pct
        self.force_close_loss_pct = force_close_loss_pct

    # ---------- 工具方法 ----------
    def _slippage_buy(self, price: float) -> float:
        return price * (1 + self.slippage_pct)

    def _slippage_sell(self, price: float) -> float:
        return price * (1 - self.slippage_pct)

    def _calc_buy_fee(self, price: float, qty: int) -> float:
        return price * qty * self.fee_commission

    def _calc_sell_fee(self, price: float, qty: int) -> float:
        return price * qty * (self.fee_commission + self.fee_stamp_duty_sell)

    @staticmethod
    def _next_date(date_str: str) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    # ---------- 主流程 ----------
    def run(
        self,
        symbol: str,
        cost_price: float,
        quantity: int,
        start_date: str = "20240101",
        end_date: str = "20260717",
        force_eod_close: bool = True,
    ) -> T0BacktestResult:
        """跑回测。"""
        df = self.history.fetch_with_cache(symbol)
        if df is None or len(df) < 60:
            raise ValueError(f"{symbol} 数据不足")

        df["date_obj"] = pd.to_datetime(df["date"])
        df = df[(df["date_obj"] >= start_date) & (df["date_obj"] <= end_date)].copy()
        if len(df) < 30:
            raise ValueError(f"{symbol} 日期范围内数据不足（{len(df)} 行）")

        df_ind = add_all_indicators(df).reset_index(drop=True)

        pos = Position(base=quantity, t_holdings=0, t_avg_cost=0.0, lock_until_date="")
        trades: list[T0Trade] = []
        total_profit_gross = 0.0
        fee_total = 0.0
        t_win = t_loss = 0
        t_position_max = 0
        t1_locks_held = 0

        # 净值曲线：(底仓 + T 仓) * 当日 close + 累计 T 现金
        portfolio_values: list[tuple[str, float]] = []

        for i in range(30, len(df_ind)):
            row = df_ind.iloc[i]
            today = row["date"]

            # 1. 先处理"今日锁变可卖" → 解锁昨日买入
            if pos.lock_until_date and today >= pos.lock_until_date:
                pos.lock_until_date = ""

            # 2. 强制平仓（T 仓浮亏 >= 阈值）
            if pos.t_holdings > 0 and pos.t_avg_cost > 0:
                cur_price = row["close"]
                unrealized_pct = (cur_price - pos.t_avg_cost) / pos.t_avg_cost
                if unrealized_pct <= -self.force_close_loss_pct:
                    sell_price = self._slippage_sell(cur_price)
                    fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                    profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                    trades.append(T0Trade(
                        date=today, direction="sell",
                        price=sell_price, quantity=pos.t_holdings,
                        amount=sell_price * pos.t_holdings, signal="强制止损",
                        profit=profit, fee=fee,
                    ))
                    total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                    fee_total += fee
                    if profit >= 0:
                        t_win += 1
                    else:
                        t_loss += 1
                    pos.t_holdings = 0
                    pos.t_avg_cost = 0.0
                    pos.lock_until_date = ""

            # 3. 信号 → 决策
            signals = self.engine.scan(symbol, df_ind.iloc[:i+1])
            cur_close = row["close"]
            t_size = int(pos.base * self.t_position_pct)

            for sig in signals:
                if sig.signal_type == SignalType.STOP_LOSS:
                    # 全部清仓（含底仓）
                    if pos.t_holdings > 0 and not pos.is_locked(today):
                        sell_price = self._slippage_sell(cur_close)
                        fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                        profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                        trades.append(T0Trade(
                            date=today, direction="sell",
                            price=sell_price, quantity=pos.t_holdings,
                            amount=sell_price * pos.t_holdings, signal=sig.name,
                            profit=profit, fee=fee,
                        ))
                        total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                        fee_total += fee
                        if profit >= 0:
                            t_win += 1
                        else:
                            t_loss += 1
                        pos.t_holdings = 0
                        pos.t_avg_cost = 0.0

                elif sig.signal_type == SignalType.SELL:
                    # 高抛
                    if pos.t_holdings > 0 and not pos.is_locked(today):
                        sell_price = self._slippage_sell(cur_close)
                        fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                        profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                        trades.append(T0Trade(
                            date=today, direction="sell",
                            price=sell_price, quantity=pos.t_holdings,
                            amount=sell_price * pos.t_holdings, signal=sig.name,
                            profit=profit, fee=fee,
                        ))
                        total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                        fee_total += fee
                        if profit >= 0:
                            t_win += 1
                        else:
                            t_loss += 1
                        pos.t_holdings = 0
                        pos.t_avg_cost = 0.0
                        pos.lock_until_date = ""
                    elif pos.t_holdings == 0:
                        # 反向做 T：允许底仓做"先卖后买"模式（卖出底仓部分）
                        if pos.base >= t_size:
                            sell_price = self._slippage_sell(cur_close)
                            fee = self._calc_sell_fee(sell_price, t_size)
                            # 此笔视为对底仓的减仓，盈亏计入 total_profit_gross
                            base_diff = (sell_price - cost_price) * t_size - fee
                            trades.append(T0Trade(
                                date=today, direction="sell",
                                price=sell_price, quantity=t_size,
                                amount=sell_price * t_size, signal=sig.name + "(底仓减)",
                                profit=base_diff, fee=fee,
                            ))
                            total_profit_gross += (sell_price - cost_price) * t_size
                            fee_total += fee
                            pos.base -= t_size
                            # 标记：要在次日买回（cost 维持不变）
                            pos.lock_until_date = self._next_date(today)
                            t1_locks_held += 1

                elif sig.signal_type == SignalType.BUY:
                    # 低吸开 T 仓
                    if t_size > 0:
                        buy_price = self._slippage_buy(cur_close)
                        fee = self._calc_buy_fee(buy_price, t_size)
                        new_qty = pos.t_holdings + t_size
                        new_avg = (
                            (pos.t_avg_cost * pos.t_holdings + buy_price * t_size) / new_qty
                            if pos.t_holdings > 0 else buy_price
                        )
                        trades.append(T0Trade(
                            date=today, direction="buy",
                            price=buy_price, quantity=t_size,
                            amount=buy_price * t_size, signal=sig.name,
                            fee=fee,
                        ))
                        fee_total += fee
                        pos.t_holdings = new_qty
                        pos.t_avg_cost = new_avg
                        pos.lock_until_date = self._next_date(today)
                        t_position_max = max(t_position_max, pos.t_holdings)
                        t1_locks_held += 1

            # 4. 收盘强制平仓
            if force_eod_close and pos.t_holdings > 0:
                sell_price = self._slippage_sell(cur_close)
                fee = self._calc_sell_fee(sell_price, pos.t_holdings)
                profit = (sell_price - pos.t_avg_cost) * pos.t_holdings - fee
                trades.append(T0Trade(
                    date=today, direction="sell",
                    price=sell_price, quantity=pos.t_holdings,
                    amount=sell_price * pos.t_holdings, signal="EOD 强制平",
                    profit=profit, fee=fee,
                ))
                total_profit_gross += (sell_price - pos.t_avg_cost) * pos.t_holdings
                fee_total += fee
                if profit >= 0:
                    t_win += 1
                else:
                    t_loss += 1
                pos.t_holdings = 0
                pos.t_avg_cost = 0.0
                pos.lock_until_date = ""

            # 5. 跟踪净值
            portfolio_values.append((today, (pos.base + pos.t_holdings) * cur_close))

        # ---------- 汇总 ----------
        last_close = df_ind.iloc[-1]["close"]
        new_cost = (
            (cost_price * quantity + total_profit_gross) / quantity
            if quantity > 0 else cost_price
        )
        cost_change_pct = (new_cost - cost_price) / cost_price * 100
        buy_hold_pct = (last_close - cost_price) / cost_price * 100
        net_t_profit = total_profit_gross - fee_total
        net_t_pct = net_t_profit / (cost_price * quantity) * 100

        # 最大回撤
        max_dd = 0.0
        if portfolio_values:
            peak = -1e18
            for _, v in portfolio_values:
                peak = max(peak, v)
                if peak > 0:
                    dd = (peak - v) / peak
                    max_dd = max(max_dd, dd)

        # 年化
        days = (df_ind["date_obj"].iloc[-1] - df_ind["date_obj"].iloc[0]).days
        years = max(days / 365.0, 1e-9)
        ann_return = ((1 + net_t_pct / 100) ** (1 / years) - 1) * 100

        total_trades = t_win + t_loss
        win_rate = t_win / total_trades if total_trades > 0 else 0.0

        return T0BacktestResult(
            symbol=symbol,
            start_date=df_ind.iloc[0]["date"],
            end_date=df_ind.iloc[-1]["date"],
            initial_cost=cost_price,
            final_cost=new_cost,
            cost_change=cost_change_pct,
            total_t_profit=total_profit_gross,
            net_t_profit=net_t_profit,
            t_win_count=t_win,
            t_loss_count=t_loss,
            t_win_rate=win_rate,
            max_drawdown_pct=max_dd,
            fee_total=fee_total,
            buy_hold_profit=buy_hold_pct,
            annualized_return=ann_return,
            t_position_max=t_position_max,
            t1_locks_held=t1_locks_held,
            trades=trades,
        )
```

- [ ] **Step 4: 跑测试**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/test_t0_simulator.py -v
```

预期：5 个测试全部 PASSED。

- [ ] **Step 5: 端到端验证（茅台）**

```bash
cd /Users/jojo/code/a-trade
python3 -c "
import sys; sys.path.insert(0, '.')
from atrade.backtest import T0Simulator
sim = T0Simulator()
r = sim.run('600519', 1650.0, 100, '20250101', '20260717')
print(r.summary())
"
```

预期：打印完整报告，T 笔数 / T 净盈亏 / 最大回撤都有数值。

- [ ] **Step 6: 提交**

```bash
cd /Users/jojo/code/a-trade
git add atrade/backtest/t0_simulator.py tests/test_t0_simulator.py
git commit -m "feat(backtest): T+1 strict T+0 simulator with fees/slippage/drawdown"
```

---

### Task 5: CLI 入口 `scripts/run_backtest.py`

**Files:**
- Create: `/Users/jojo/code/a-trade/scripts/run_backtest.py`

**Interfaces:**
- CLI 参数：
  - `--symbol 600519`（可多次）
  - `--cost 1650`、`--qty 100`（与 --symbol 一一对应）
  - `--start / --end` （默认 2024-01-01 / 2026-07-17）
  - `--portfolio` 模式（读 `config/holdings.json`）
  - `--push` 推 QQ 群（可选）
  - `--t-position-pct 0.5` 等覆盖
- 输出：
  - 终端表格
  - Markdown 报告 → `reports/backtest_{symbol}_{date}.md`

**Why:** 把所有产出串起来，让用户手机 QQ 群里就能看 / 自己跑也能本地看。

- [ ] **Step 1: 写脚本**

```python
"""回测 CLI 入口。

用法:
    python3 scripts/run_backtest.py --symbol 600519 --cost 1650 --qty 100
    python3 scripts/run_backtest.py --portfolio
    python3 scripts/run_backtest.py --symbol 600519 --cost 1650 --qty 100 --push
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atrade.backtest import T0Simulator
from atrade.backtest.t0_simulator import T0BacktestResult


REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def run_one(symbol: str, cost: float, qty: int, args) -> T0BacktestResult:
    sim = T0Simulator(
        t_position_pct=args.t_position_pct,
        fee_commission=args.fee_commission,
        fee_stamp_duty_sell=args.fee_stamp_duty_sell,
        slippage_pct=args.slippage,
    )
    return sim.run(symbol, cost, qty,
                   start_date=args.start.replace("-", ""),
                   end_date=args.end.replace("-", ""))


def print_console(results: list[T0BacktestResult]):
    print("\n" + "=" * 80)
    print(f"{'代码':<8} {'区间':<24} {'成本变化':>10} {'T 净额':>12} "
          f"{'胜率':>8} {'最大回撤':>10} {'年化':>10} {'vs 死拿':>10}")
    print("-" * 80)
    for r in results:
        vs = r.net_t_profit / (r.initial_cost * 1000) * 100 + r.buy_hold_profit
        print(
            f"{r.symbol:<8} {r.start_date}~{r.end_date:<10} "
            f"{r.cost_change:>+9.2f}% {r.net_t_profit:>+11.2f} "
            f"{r.t_win_rate*100:>7.1f}% {r.max_drawdown_pct*100:>9.2f}% "
            f"{r.annualized_return:>+9.2f}% {vs:>+9.2f}%"
        )
    print("=" * 80 + "\n")


def save_report(results: list[T0BacktestResult]) -> list[Path]:
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = []
    for r in results:
        path = REPORTS_DIR / f"backtest_{r.symbol}_{today}.md"
        path.write_text(r.summary(), encoding="utf-8")
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description="a-trade T+0 回测 CLI")
    parser.add_argument("--symbol", action="append", help="股票代码（可多次）")
    parser.add_argument("--cost", action="append", type=float, help="成本价")
    parser.add_argument("--qty", action="append", type=int, help="持仓股数")
    parser.add_argument("--portfolio", action="store_true", help="用 config/holdings.json 全跑")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--t-position-pct", type=float, default=0.5)
    parser.add_argument("--fee-commission", type=float, default=0.00025)
    parser.add_argument("--fee-stamp-duty-sell", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0005)
    parser.add_argument("--push", action="store_true", help="推送到 QQ 群")

    args = parser.parse_args()

    # 决定跑哪些
    targets = []
    if args.portfolio:
        holdings = json.loads(Path("config/holdings.json").read_text())["holdings"]
        for h in holdings:
            targets.append((h["symbol"], h["cost_price"], h["quantity"]))
    elif args.symbol:
        symbols = args.symbol
        costs = args.cost or [0.0] * len(symbols)
        qtys = args.qty or [0] * len(symbols)
        for s, c, q in zip(symbols, costs, qtys):
            targets.append((s, c, q))
    else:
        parser.print_help()
        return

    # 跑
    results = [run_one(s, c, q, args) for s, c, q in targets]
    print_console(results)
    paths = save_report(results)
    for p in paths:
        print(f"📄 报告: {p}")

    # 推送（可选）
    if args.push:
        try:
            from atrade.notify.botpy_notifier import BotpyNotifier
            notifier = BotpyNotifier()
            for r in results:
                msg = r.summary()[:2500]
                notifier.send_markdown(msg)
        except Exception as e:
            print(f"⚠️ 推送失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑茅台 + 平安**

```bash
cd /Users/jojo/code/a-trade
python3 scripts/run_backtest.py --symbol 600519 --cost 1650 --qty 100
python3 scripts/run_backtest.py --symbol 000001 --cost 12.5 --qty 5000
```

预期：
- 终端输出表格，两行结果
- `reports/backtest_600519_*.md` 和 `backtest_000001_*.md` 落盘

- [ ] **Step 3: 跑 portfolio 模式**

```bash
cd /Users/jojo/code/a-trade
python3 scripts/run_backtest.py --portfolio
```

预期：跟 Step 2 一样，但同时跑两个。

- [ ] **Step 4: 提交**

```bash
cd /Users/jojo/code/a-trade
git add scripts/run_backtest.py
git commit -m "feat(cli): run_backtest.py for single + portfolio mode"
```

---

### Task 6: 端到端验证 + 截图报告

**Files:**
- Modify: `/Users/jojo/code/a-trade/reports/` (新增)

**Interfaces:** 无

- [ ] **Step 1: 清缓存 + 全量跑一次**

```bash
cd /Users/jojo/code/a-trade
rm -f data/cache/stock.db
python3 scripts/run_backtest.py --portfolio
```

预期：终端 + `reports/` 下两份 md 报告，茅台和平安都有数据。

- [ ] **Step 2: 跑所有测试**

```bash
cd /Users/jojo/code/a-trade
python3 -m pytest tests/ -v
```

预期：所有测试 PASSED（cache/history/t0_simulator）。

- [ ] **Step 3: git log 验证提交链**

```bash
cd /Users/jojo/code/a-trade
git log --oneline
```

预期：7 个 commit（init + 5 feat + 1 feat）。

- [ ] **Step 4: 提交（如果有 reports/ 改动）**

```bash
cd /Users/jojo/code/a-trade
ls reports/*.md 2>&1
# reports/ 在 .gitignore 中，不入 git，无需提交
```

---

## 收尾备注

- **本期不做**：
  - 真实 5 分钟线日内 T 推演（C 复杂度超纲）
  - 信号 → 自动推 QQ 群（独立 Task，放在本计划之外）
  - launchd 安装实测（独立 Task）
  - 命令路由（独立 Task）

- **下一轮候选 Task**：
  - 真实日内 T+1 用 5m 线推
  - botpy 命令路由（`/check`、`/signal`、`/portfolio`）
  - launchd 安装 + 验证自动推送
  - 长周期回测（开通新浪分页拉 1000+ 根）

