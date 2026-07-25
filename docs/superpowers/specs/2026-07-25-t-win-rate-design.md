# 2026-07-25 T 胜率优化与每日复盘设计

## 背景

当前 T 信号引擎胜率不高，主要原因（代码已确认）：
1. **无大趋势过滤**：`MA5 上穿 MA10` 在下跌趋势中也会触发（死猫跳）
2. **无大盘环境过滤**：熊市中也照常推送 BUY 信号
3. **无保护机制**：买入后等下一次 SELL 信号才卖，期间已回吐
4. **无复盘数据**：每天的 P&L、胜率、按因子/股票分组的统计全部缺失

用户选择：A（信号更严）+ C（追踪止损）+ 复盘推送。

## 目标

1. 每天 0-1 笔高质量 T 交易（少做但准）
2. 胜率 ≥ 60%（A 方案：信号更严）
3. 锁定部分利润 / 限制单笔亏损（C 方案：追踪止损）
4. 每天 15:35 收盘时给一份完整复盘

## 架构

```
atrade/
  market/
    __init__.py
    index_filter.py        # 大盘环境判断（拉沪深300/上证指数）
  monitor/
    t_state.py              # 持仓状态机（持久化到 data/cache/t_state.json）
    t_trailing.py           # 追踪止损 + 锁利逻辑
    t_replay.py             # 复盘报告（解析 t_trades.json → round-trip P&L）

# 修改
atrade/signals/engine.py    # 新增 _filter_market_trend + 大盘过滤
atrade/monitor/t_monitor.py # 集成 filters + t_state + t_trailing
atrade/monitor/t_executor.py # 追踪信号优先于原 SELL
atrade/scheduler/runner.py  # 15:35 推送复盘
atrade/report/generator.py  # generate_t_replay_report()
atrade/config.py            # 校验新增字段
config/monitor.json         # 新增字段默认
```

## 模块设计

### 1. `atrade/market/index_filter.py`

```python
def get_index_trend(symbol: str = "sh000300") -> dict:
    """拉大盘指数最近 60 个交易日 K 线，返回趋势判断。
    
    Returns:
        {
            "symbol": "sh000300",
            "price": 3850.0,
            "ma20": 3820.0,
            "ma60": 3750.0,
            "ma20_slope": 0.5,        # MA20 最近 5 日斜率
            "trend": "up" | "down" | "sideways",
            "drop_pct_5d": -1.2,      # 5 日累计跌幅
            "fetched_at": "2026-07-25T15:30",
        }
```

`is_market_ok_for_buy(trend_dict) -> bool`:
- `trend == "down"` (MA20 < MA60) → False
- `drop_pct_5d < -3%` → False（不论 trend）
- 其他 → True

5 分钟缓存（`functools.lru_cache` with TTL）。

### 2. `atrade/monitor/t_state.py`

```python
@dataclass
class TState:
    symbol: str
    status: Literal["empty", "holding", "locked"]
    entry_price: float = 0.0
    entry_time: str = ""
    peak_price: float = 0.0
    lots: int = 0
    entry_signal: str = ""

class TStateStore:
    """每只股票独立 T 状态，持久化到 data/cache/t_state.json。"""
    def __init__(self, path: Path = None): ...
    def get(symbol) -> TState: ...
    def set(symbol, state: TState): ...
    def reset_day(): ...  # 每天 9:30 清空前日
```

### 3. `atrade/monitor/t_trailing.py`

```python
@dataclass
class TrailingConfig:
    take_profit_pct: float = 0.03   # 锁利阈值（默认 +3%）
    stop_loss_pct: float = 0.02     # 止损阈值（默认 -2%）
    lock_lots: int = 1              # 锁利时卖多少手（默认 0.5 手向下取整）

def check_trailing(state: TState, current_price: float, cfg: TrailingConfig) -> dict | None:
    """每根 K 线检查，返回要执行的动作（None = 不动）。"""
    if state.status != "holding":
        return None
    
    # 更新峰值
    if current_price > state.peak_price:
        state.peak_price = current_price
    
    # 锁利
    if current_price >= state.entry_price * (1 + cfg.take_profit_pct):
        return {
            "action": "take_profit",
            "price": current_price,
            "lots": cfg.lock_lots,
            "reason": f"已达 +{cfg.take_profit_pct*100:.0f}% 锁利线",
        }
    
    # 止损
    if current_price <= state.entry_price * (1 - cfg.stop_loss_pct):
        return {
            "action": "stop_loss",
            "price": current_price,
            "lots": state.lots,  # 全部
            "reason": f"已达 -{cfg.stop_loss_pct*100:.0f}% 止损线",
        }
    
    return None
```

### 4. `atrade/signals/engine.py` 修改

新增过滤函数（在 `scan()` 开头调用）：

```python
def _filter_individual_trend(self, df, latest, signal_type) -> bool:
    """个股大趋势过滤：BUY 必须 MA20>MA60 且 MA20 上行。"""
    if signal_type != SignalType.BUY:
        return True
    ma20 = latest.get("MA20")
    ma60 = latest.get("MA60")
    if pd.isna(ma20) or pd.isna(ma60):
        return False
    if ma20 <= ma60:
        return False
    # MA20 斜率：最近 5 日 MA20 上升
    if len(df) < 25:
        return False
    ma20_now = df["MA20"].iloc[-1]
    ma20_5d_ago = df["MA20"].iloc[-6]
    if ma20_now <= ma20_5d_ago:
        return False
    return True

def _filter_market_regime(self) -> bool:
    """大盘环境过滤：调用 index_filter.is_market_ok_for_buy()。"""
    try:
        from atrade.market.index_filter import is_market_ok_for_buy, get_index_trend
        trend = get_index_trend("sh000300")
        return is_market_ok_for_buy(trend)
    except Exception:
        return True  # 数据失败 → 默认放行
```

`scan()` 中调用：
```python
def scan(self, symbol, df):
    signals = [...]  # 现有逻辑
    # 新过滤
    market_ok = self._filter_market_regime()
    out = []
    for sig in signals:
        if not market_ok and sig.signal_type in (SignalType.BUY, SignalType.SELL):
            # 系统性下跌时只放行 STOP_LOSS
            continue
        if not self._filter_individual_trend(df, latest, sig.signal_type):
            continue
        # 计算 confidence
        sig.confidence = self._calc_confidence(sig)
        out.append(sig)
    return out
```

### 5. `atrade/monitor/t_executor.py` 集成

每次 `execute()` 之前：
1. 调用 `t_trailing.check_trailing()` 看是否触发追踪动作
2. 若触发：用追踪的 action/lots 替代默认的 SELL/STOP_LOSS 行为
3. 同时更新 `t_state.json`：
   - 锁利后：status=locked
   - 止损后：status=empty
   - BUY 后：status=holding, entry_price=trigger_price

### 6. `atrade/monitor/t_replay.py`

```python
@dataclass
class RoundTrip:
    symbol: str
    direction: str        # "LONG"（T 买入后卖出）
    entry_price: float
    exit_price: float
    shares: int
    pnl: float            # (exit - entry) * shares
    pnl_pct: float        # (exit - entry) / entry
    entry_time: str
    exit_time: str
    entry_factor: str
    exit_factor: str
    holding_minutes: int

def compute_round_trips(trades: list[dict]) -> list[RoundTrip]:
    """配对 BUY → SELL（同 symbol 同日，按时间顺序）。"""
    ...

def compute_stats(trips: list[RoundTrip]) -> dict:
    """总胜率、平均盈亏、盈亏比、按因子/股票分组。"""
    ...
```

### 7. `atrade/report/generator.py` 新增

```python
def generate_t_replay_report(date: str = None) -> str:
    """15:35 复盘：T 交易胜率 + 按因子/股票统计。"""
    from atrade.monitor.t_replay import compute_round_trips, compute_stats
    
    trades = load_trades()
    trips = compute_round_trips(trades, date=date)
    stats = compute_stats(trips)
    
    # Markdown 渲染（参考 closing report 格式）
    ...
```

## 配置

`config/monitor.json` 的 `t_monitor.symbols[].trailing` 字段：

```json
{
  "symbol": "002436",
  "name": "兴森科技",
  "cost_price": 41.0,
  "quantity": 100,
  "trailing": {
    "take_profit_pct": 0.03,    // 不填默认 3%
    "stop_loss_pct": 0.02        // 不填默认 2%
  }
}
```

也可在 `t_monitor.trailing_defaults` 设全局默认（所有未配 trailing 的 symbol 用此值）：

```json
{
  "t_monitor": {
    "trailing_defaults": {
      "take_profit_pct": 0.03,
      "stop_loss_pct": 0.02
    }
  }
}
```

## 调度

- **09:30**：`_job_t_state_reset()` 清空前日 t_state（确保新一天干净）
- **盘中每 2 分钟**：T 扫描，原有逻辑（不重发）
- **15:35 推送合并**：在原 15:35 closing_report guard 之前，加一个 `_job_t_replay()` 推送复盘

## 错误处理

- 大盘数据拉取失败 → `_filter_market_regime` 返回 True（不阻塞）
- t_state.json 损坏 → 启动时重置为初始
- 追踪触发但 executor 失败 → 状态回滚 + 日志

## 风险

| 风险 | 缓解 |
|---|---|
| 大盘过滤过严导致错失反弹 | 大盘 down + 个股 up → 仍可通过（仅大盘 single-side 跌超 3% 才全屏蔽） |
| 追踪止损频繁触发噪音 | 阈值用 % 不是绝对值，配 5m K 线避免过度敏感 |
| 复盘 BUY→SELL 配对错位 | 同 symbol 同日按时间顺序 + 跳过"已锁利"重复卖出 |
| 状态文件跨日污染 | 09:30 显式 reset |

## 测试

- `test_index_filter.py`：拉取失败 / MA20<MA60 屏蔽 / 跌幅超 3% 屏蔽 / 缓存生效
- `test_t_state.py`：状态读写 / reset_day / 损坏恢复
- `test_t_trailing.py`：持仓中触发锁利 / 触发止损 / 已锁利不再触发 / peak 更新
- `test_t_replay.py`：BUY→SELL 配对 / 跨日处理 / 胜率计算 / 因子分组
- `test_signals_filter.py`：MA20<MA60 时 BUY 被过滤 / 大盘下跌时全屏蔽

## 部署

1. 推送代码到 origin + vps
2. VPS 重启 a-trade
3. 监控 15:35 第一份复盘

## 非目标

- 不做回测（已有 `atrade/backtest/` 单独体系）
- 不做账户层面 P&L（只算单笔 round-trip）
- 不做跨日持仓追踪（隔夜 T 不在范围）
