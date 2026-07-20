# A-Trade 个股做 T 策略报告（CLI 按需）设计

## 1. 目标

为 `config/holdings.json` 中的每只股票生成一份本地 Markdown 报告，输出以下内容：

- 波动性特征：日内振幅、ATR、跳空分布、成交量变化、连续涨跌天数。
- 做 T 适配度：最佳单笔持仓时长、建议仓位比例、最适合的因子（波段反弹、趋势确认、放量突破、超卖反弹）。
- 风险指标：单笔最大回撤、年化波动、月度最大回撤、连亏天数。
- 风格归类（震荡 / 趋势 / 高波动 / 低波动）与一段自然语言总结。

调用方式：

```
.venv/bin/python scripts/run_per_symbol_report.py --portfolio
.venv/bin/python scripts/run_per_symbol_report.py --symbol 600522 --cost 12.50 --qty 2000
```

报告落到 `reports/per_symbol_<symbol>_<timestamp>.md`，不推送 QQ 群，不修改任何业务信号逻辑。

## 2. 范围与约束

- 仅使用现有 `HistoryProvider.fetch_with_cache` 拉取日线和分钟线，不引入新的数据源。
- 分钟线仅用最近 30 个交易日，最少需要 5/15/30/60 四个周期，以避免单分钟周期抖动。
- 报告纯离线运行，不联网写消息、不修改 `data/cache/stock.db` 中既有字段。
- 输出指标与单位明确（如百分比、振幅倍数、绝对价位）。
- 单只股票报告生成失败不阻塞其余股票，整体返回非零状态码并打印失败原因。
- 所有计算基于复权后的收盘价序列；如果 `ah_factor` 全部为 1.0，则等价不复权，并在报告中标注。
- 报告模块不依赖 `botpy`、`openclaw`、QQ 凭据；本地环境即可运行。

## 3. 不在范围内

- 实时推送、盘中决策、自动化执行。
- 个股预测、新闻/政策情绪、强化学习模型。
- 跨股票相关性、组合配置、行业因子。
- 自动调参、参数搜索、黑箱模型。
- 修改现有 `SignalEngine`、`T0Simulator`、`Scheduler`、`DailyScheduler`、`BotpyNotifier` 等模块的对外行为。

## 4. 数据契约

报告模块统一消费下列派生数据：

```python
from dataclasses import dataclass

@dataclass
class SymbolReport:
    symbol: str
    name: str
    cost_price: float
    quantity: int
    lookback_days: int          # 默认 252
    intraday_days: int          # 默认 30
    generated_at: str           # ISO 时间
    volatility: dict
    adaptive: dict
    risk: dict
    style: str                  # 'range' / 'trend' / 'high_vol' / 'low_vol'
    summary: str                # 自然语言总结
```

| 模块 | 指标 | 输入 | 输出 |
| --- | --- | --- | --- |
| 波动性 | `daily_amp_p50/p90/max` | 日线 high-low | 振幅 % |
| 波动性 | `atr_14_pct` | 日线 OHLC | 14 日 ATR 占收盘价百分比 |
| 波动性 | `gap_dist` | 日线 open vs prev_close | 跳空分布（均值、绝对均值、>2% 概率） |
| 波动性 | `vol_zscore_60` | 日线 volume | 当日量相对 60 日均量 z-score |
| 波动性 | `streak_max` | 日线 pct_chg | 最大连续涨/跌天数 |
| 适配度 | `intra_amp_p50/p90` | 5/15/30/60 分钟线 | 日内振幅分布 |
| 适配度 | `hold_minutes_p90` | 5/15/30/60 分钟线 | 振幅恢复 90% 所需时间 |
| 适配度 | `factor_score` | 4 因子扫描 | 波段反弹/趋势确认/放量突破/超卖反弹的命中次数 |
| 适配度 | `position_pct` | 自定义规则 | 推荐仓位（0.1-0.5 区间） |
| 适配度 | `preferred_factors` | `factor_score` | 命中次数 Top-2 因子 |
| 风险 | `max_drawdown_1y` | 日线 close | 最大回撤 |
| 风险 | `annual_vol` | 日线 pct_chg | 年化波动 |
| 风险 | `monthly_max_dd` | 月度净值 | 月度最大回撤 |
| 风险 | `loss_streak_max` | 日线 pct_chg | 最大连续亏损天数 |
| 风格 | `style` | 聚合规则 | 见 §6 |

## 5. 因子命中统计

复用现有 `SignalEngine.scan` 但只统计因子命中，不生成交易信号。复用前必须：

- 因子代码仅使用 `df.iloc[-1]` 与 `df.iloc[:-1]` 的派生指标；不引入未来函数。
- 5 分钟 K 线为唯一执行粒度，因为这是最细的盘中粒度，与 `TMonitorRunner` 一致。
- 对每只股票取最近 30 个交易日内每个 5m 收盘点运行 `scan`，统计 4 个因子命中次数；不取最后 1 个点的值，避免“今天”的样本偏差。
- 输出 `factor_score` 字典，例如 `{'波段反弹': 7, '趋势确认': 3, '放量突破': 2, '超卖反弹': 5}`。

## 6. 风格归类规则

| 条件 | 风格 |
| --- | --- |
| `atr_14_pct < 1.5%` 且 `gap_dist.abs_mean < 0.5%` | low_vol |
| `atr_14_pct > 4%` 或 `daily_amp_p90 > 6%` | high_vol |
| 60 日均线斜率绝对值 > 0.5%/日 且 ADX>20 | trend |
| 其它 | range |

`summary` 由 1-2 句中文组成，结合风格、波动性、命中因子、风险等级。例如：

> 中天科技属于 range 风格，14 日 ATR 2.6%，年内振幅中位数 2.3%。建议关注 波段反弹、趋势确认 因子，单笔仓位不超过 25%，最大月度回撤约 9.1%。

## 7. 报告样例

```markdown
# 中天科技 (600522) 做 T 策略报告

- 成本价：12.50 / 数量：2000
- 报告时间：2026-07-20 21:30
- 数据范围：252 个日线 + 30 个交易日的 5/15/30/60 分钟线

## 1. 风格归类

range

## 2. 波动性

| 指标 | 数值 |
|---|---|
| 日内振幅 P50 | 2.30% |
| 日内振幅 P90 | 3.90% |
| 14 日 ATR | 2.60% |
| 跳空绝对均值 | 0.58% |
| 跳空 >2% 概率 | 5.8% |
| 量比 z-score（60 日） | 0.4 |
| 最大连涨天数 | 4 |
| 最大连跌天数 | 5 |

## 3. 做 T 适配度

| 项目 | 建议 |
|---|---|
| 最佳单笔持仓时长 | 15-30 分钟 |
| 建议单笔仓位 | 25% |
| 首选因子 | 波段反弹、趋势确认 |

因子命中（30 个 5m 收盘点）：
- 趋势确认：6
- 超卖反弹：3
- 波段反弹：9
- 放量突破：2

## 4. 风险指标

| 指标 | 数值 |
|---|---|
| 年化波动 | 28.7% |
| 单年最大回撤 | -18.3% |
| 月度最大回撤 | -9.1% |
| 最大连亏天数 | 5 |

## 5. 自然语言总结

中天科技属于 range 风格，14 日 ATR 2.6%，年内振幅中位数 2.3%。建议关注 波段反弹、趋势确认 因子，单笔仓位不超过 25%，最大月度回撤约 9.1%。
```

## 8. 模块结构

新增文件，不修改现有对外 API：

- `atrade/per_symbol/__init__.py`
- `atrade/per_symbol/volatility.py`（波动性指标）
- `atrade/per_symbol/adaptive.py`（适配度与因子统计）
- `atrade/per_symbol/risk.py`（风险指标）
- `atrade/per_symbol/styler.py`（风格归类 + 总结）
- `atrade/per_symbol/report.py`（汇总成 `SymbolReport`）
- `scripts/run_per_symbol_report.py`（CLI 入口）
- `tests/test_per_symbol_report.py`（单元测试）

每个指标函数独立、可测，输入为 `pd.DataFrame`，返回 `dict` 或简单标量。

## 9. 测试策略

1. 用预置的合成日线（趋势、震荡、跳空、连涨跌）和合成 5 分钟线（高/低波动）覆盖所有指标。
2. 因子命中统计用 mock `SignalEngine.scan` 验证计数。
3. 风格归类给出边界用例（ATR 1.4% / 1.6%、gap_abs 0.4% / 0.6%）。
4. CLI 集成测试：调用 `--symbol 600522 --cost 12.50 --qty 2000`，断言报告文件存在并包含必要章节。
5. 不调用真实 QQ 接口、不联网拉取、不依赖 `.env`。

## 10. 与现有工作的关系

- 复用 2026-07-19 全面审查报告 P0-1 / P0-2 / P1-1 / P1-2 / P1-3 计划中的数据契约改进。
- 与 2026-07-19 全量修复设计文档 P3-1 “文档与一致性” 无冲突。
- 报告模块不修改 `SignalEngine` / `T0Simulator`，因此可以独立上线，与“全量修复”并行推进。
- 上线后用户可以选择性触发回测账本重写：回测重写完成后，可以把 `T0Simulator` 输出的 `final_cost` / `max_drawdown_pct` 接入到 `risk.monthly_max_dd`，进一步降低报告与未来实盘之间的偏差。

## 11. 完成标准

- `scripts/run_per_symbol_report.py --portfolio` 能在不联网的前提下为现有持仓生成报告。
- 报告包含 §4 表格、§5 因子命中、§6 风格归类、§7 总结四个必要章节。
- 单元测试覆盖所有指标函数，CI 通过。
- 不修改任何现有模块的对外 API 与现有测试。
- 进度文件 `docs/progress/2026-07-20-per-symbol-t-strategy/` 记录每个阶段的状态和验证命令。
