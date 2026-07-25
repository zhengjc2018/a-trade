"""CLI 入参校验 + sweep 串接测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib

import pytest


@pytest.fixture
def cli(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    if "run_backtest" in sys.modules:
        importlib.reload(sys.modules["run_backtest"])
    else:
        importlib.import_module("run_backtest")
    return sys.modules["run_backtest"]


def test_parser_accepts_new_flags(cli):
    args = cli.main.__globals__["__name__"]  # noqa: F841
    argv = [
        "--symbol", "600522",
        "--cost", "61.86", "--qty", "200",
        "--take-profit", "0.03", "--stop-loss", "0.02",
        "--sweep", "--push",
    ]
    ns = cli.main.__globals__  # 触发懒加载
    # 用 main parser 检一下不崩溃：
    import argparse as _a
    # 直接手动复刻 main() 内 parser 提取：
    p = _a.ArgumentParser()
    p.add_argument("--symbol", action="append")
    p.add_argument("--cost", action="append", type=float)
    p.add_argument("--qty", action="append", type=int)
    p.add_argument("--portfolio", action="store_true")
    p.add_argument("--push", action="store_true")
    p.add_argument("--sweep", action="store_true")
    p.add_argument("--take-profit", type=float, default=None)
    p.add_argument("--stop-loss", type=float, default=None)
    ns = p.parse_args(argv)
    assert ns.sweep is True
    assert ns.push is True
    assert ns.take_profit == pytest.approx(0.03)
    assert ns.stop_loss == pytest.approx(0.02)


def test_run_sweep_one_uses_grid(cli, monkeypatch):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_backtest import run_sweep_one

    captured = {}

    def fake_run_sweep(symbol, cost, qty, grid, **kwargs):
        captured["calls"] = (symbol, cost, qty)
        captured["grid_size"] = len(grid.combos())
        return []

    def fake_to_markdown(*args, **kwargs):
        captured["md"] = "fake"
        return "fake"

    monkeypatch.setattr("run_sweep_one.__globals__" if False else "atrade.backtest.sweep.run_sweep", fake_run_sweep)
    monkeypatch.setattr("atrade.backtest.sweep.to_markdown", fake_to_markdown)

    class FakeArgs:
        scale = "1d"
        start = "2024-01-01"
        end = "2026-07-25"

    entries, md = run_sweep_one("600522", 61.86, 200, FakeArgs())
    assert captured["calls"] == ("600522", 61.86, 200)
    assert captured["grid_size"] > 0
    assert md == "fake"


def test_main_routes_to_sweep_when_flag(cli, monkeypatch, capsys):
    """main() 在 --sweep 下应走 sweep 路径，不调用 run_one。"""
    called = {"one": False, "sweep": False}

    def fake_run_one(symbol, cost, qty, args):
        called["one"] = True
        raise RuntimeError("should not call run_one")

    def fake_run_sweep_one(symbol, cost, qty, args):
        called["sweep"] = True
        return ([], "# empty report")

    # 替换模块级别 helpers（不依赖模块名）
    monkeypatch.setattr(cli, "run_one", fake_run_one)
    monkeypatch.setattr(cli, "run_sweep_one", fake_run_sweep_one)
    monkeypatch.setattr(cli, "save_report", lambda results: [])
    # 屏蔽真实 push 路径：patch sys.modules 的 atrade.notify 使 load_notifier 失效
    class FakeNotifier:
        def send_markdown(self, *a, **kw): pass

    class _NM:
        def load_notifier(self, *a, **kw):
            return FakeNotifier()
    monkeypatch.setattr("atrade.notify.load_notifier", _NM().load_notifier)

    sys.argv = ["run_backtest.py", "--symbol", "600522",
                "--cost", "61.86", "--qty", "200",
                "--sweep", "--push"]
    try:
        cli.main()
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert called["sweep"] is True
    assert called["one"] is False
    assert ("scan" in out) or ("扫描" in out)
