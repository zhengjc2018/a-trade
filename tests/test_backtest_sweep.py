"""Sweep 网格 + Pareto 排名单测。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))



from atrade.backtest.sweep import (
    SweepEntry,
    SweepGrid,
    _score,
    rank,
    run_sweep,
    to_markdown,
)
from atrade.backtest.t0_simulator import T0BacktestResult


def _entry(tp, sl, wins, losses, net=100.0):
    total = wins + losses
    return SweepEntry(
        take_profit_pct=tp,
        stop_loss_pct=sl,
        result=T0BacktestResult(
            symbol="000001",
            start_date="-", end_date="-",
            initial_cost=0.0, final_cost=0.0, cost_change=0.0,
            total_t_profit=net, net_t_profit=net,
            t_win_count=wins, t_loss_count=losses,
            t_win_rate=wins / total if total else 0.0,
            max_drawdown_pct=0.0, fee_total=0.0,
            buy_hold_profit=0.0, annualized_return=0.0,
            t_position_max=0, t1_locks_held=0,
            quantity=0, final_total_quantity=0, peak_cash_usage=0.0,
        ),
    )


def test_default_grid_size():
    g = SweepGrid()
    combos = g.combos()
    assert combos == [
        (0.01, 0.01), (0.01, 0.02), (0.01, 0.03), (0.01, 0.05),
        (0.02, 0.01), (0.02, 0.02), (0.02, 0.03), (0.02, 0.05),
        (0.03, 0.01), (0.03, 0.02), (0.03, 0.03), (0.03, 0.05),
        (0.05, 0.01), (0.05, 0.02), (0.05, 0.03), (0.05, 0.05),
        (0.07, 0.01), (0.07, 0.02), (0.07, 0.03), (0.07, 0.05),
        (0.10, 0.01), (0.10, 0.02), (0.10, 0.03), (0.10, 0.05),
    ]


def test_grid_max_combos_trim_diagonal():
    g = SweepGrid(
        take_profits=[0.01, 0.05, 0.10, 0.20],
        stop_losses=[0.01, 0.05, 0.10, 0.20],
        max_combos=8,
    )
    combos = g.combos()
    assert len(combos) <= 8


def test_score_penalizes_low_trade_count():
    e_none = _entry(0.03, 0.02, 0, 0, net=0)
    e_few = _entry(0.03, 0.02, 1, 0, net=50.0)
    e_many = _entry(0.03, 0.02, 7, 3, net=200.0)
    # Few trades 的分数应低于 many（净收益低）
    assert _score(e_many) > _score(e_few)
    # 笔数太少 (<2) 直接扣 50 元
    assert _score(e_none) < -49


def test_score_prefers_high_win_rate_when_net_equal():
    # 同等净额下，高胜率应胜出
    a = _entry(0.03, 0.02, 7, 1, net=200.0)  # 87.5%
    b = _entry(0.03, 0.02, 4, 4, net=200.0)  # 50%
    assert _score(a) > _score(b)

    # 净额上远超但胜率低：现实中由用户决定，强健测试只覆盖明显场景
    big_net = _entry(0.03, 0.02, 5, 5, net=10000.0)
    # 这里允许任一者赢 — score 公式设计是可调的：胜率门槛由 rank() 把控
    assert isinstance(_score(big_net), float)


def test_rank_filters_low_win_rate():
    good = _entry(0.03, 0.02, 8, 2, net=100.0)
    bad = _entry(0.03, 0.02, 3, 7, net=200.0)
    tiny = _entry(0.03, 0.02, 1, 0, net=10.0)
    ranked = rank([bad, good, tiny], min_win_rate=0.6)
    assert ranked[0] is good
    assert bad not in ranked
    assert tiny not in ranked  # trades < 2


def test_to_markdown_includes_top3_and_recommendation():
    entries = [
        _entry(0.03, 0.02, 8, 2, net=200.0),
        _entry(0.05, 0.03, 7, 3, net=150.0),
        _entry(0.07, 0.05, 6, 4, net=120.0),
    ]
    md = to_markdown("600522", entries, 10.0, 100)
    assert "# 🧪 600522 锁利/止损参数扫描" in md
    assert "PUT /api/t-settings/600522" in md
    assert "+3.0%" in md
    assert "胜率 ≥ 60%" in md


def test_run_sweep_uses_take_profit_and_stop_loss(monkeypatch):
    """run_sweep 应正确把每个组合的 take_profit/stop_loss 注入到 T0Simulator.__init__。"""
    seen = []

    def fake_init(self, **kwargs):
        seen.append((kwargs.get("take_profit_pct"), kwargs.get("stop_loss_pct")))
        # 跳过真实初始化（避免 history/engine 副作用）
        self.history = None
        self.engine = None
        self.scale = kwargs.get("scale", "1d")
        self.datalen = kwargs.get("datalen", 600)

    def fake_run(self, symbol, cost, qty, **kwargs):
        return _entry(0.03, 0.02, 5, 1).result

    monkeypatch.setattr("atrade.backtest.sweep.T0Simulator.__init__", fake_init)
    monkeypatch.setattr("atrade.backtest.sweep.T0Simulator.run", fake_run)
    run_sweep("000001", 10.0, 100, SweepGrid())
    combos = SweepGrid().combos()
    assert len(seen) == len(combos)
    for (tp, sl), (exp_tp, exp_sl) in zip(seen, combos):
        assert tp == exp_tp
        assert sl == exp_sl


def test_run_sweep_progress_callback(monkeypatch):
    monkeypatch.setattr(
        "atrade.backtest.sweep.T0Simulator.run",
        lambda self, *a, **kw: _entry(0.03, 0.02, 5, 1).result,
    )
    progress = []
    run_sweep(
        "000001", 10.0, 100, SweepGrid(),
        progress_cb=lambda d, t: progress.append((d, t)),
    )
    assert progress, "no progress callback"
    assert progress[-1][0] == progress[-1][1]  # done == total
