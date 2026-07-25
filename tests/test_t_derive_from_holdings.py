"""T 监控 symbols 派生自 holdings 的测试。"""


def test_reload_derives_t_symbols_from_holdings_when_monitor_empty(tmp_path, monkeypatch):
    from atrade.scheduler.runner import DailyScheduler
    sched = DailyScheduler.__new__(DailyScheduler)
    sched.holdings = [{"symbol": "002436", "name": "兴森科技",
                       "cost_price": 41.0, "quantity": 100,
                       "buy_date": "", "note": ""}]
    sched.watch_symbols = ["002436"]
    sched.watch_keywords = []
    sched.t_runner = type("R", (), {"config": type("C", (), {"symbols": []})()})()
    sched.report_gen = type("G", (), {})()

    new_meta = {
        "holdings": [
            {"symbol": "002436", "name": "兴森科技",
             "cost_price": 41.0, "quantity": 100, "buy_date": "", "note": ""},
            {"symbol": "600522", "name": "中天科技",
             "cost_price": 61.0, "quantity": 200, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": ["600522"],  # 中天被停用
        "watch_keywords": [],
    }
    # monitor 留空 → 应从 holdings 派生
    monitor_cfg = {"t_monitor": {"scan_interval_minutes": 2}}
    monkeypatch.setattr("atrade.config.load_holdings_with_meta", lambda: new_meta)
    monkeypatch.setattr("atrade.config.load_monitor_config", lambda: monitor_cfg)

    sched.reload_from_disk()
    syms = [s.symbol for s in sched.t_runner.config.symbols]
    assert "002436" in syms
    assert "600522" not in syms  # 被 disabled 过滤
    assert sched.t_runner.config.symbols[0].name == "兴森科技"


def test_reload_uses_holdings_and_only_overlays_monitor_trailing(tmp_path, monkeypatch):
    """monitor symbols 仅是阈值覆盖，不能替换真实 holdings。"""
    from atrade.scheduler.runner import DailyScheduler
    sched = DailyScheduler.__new__(DailyScheduler)
    sched.holdings = []
    sched.watch_symbols = []
    sched.watch_keywords = []
    sched.t_runner = type("R", (), {"config": type("C", (), {"symbols": []})()})()
    sched.report_gen = type("G", (), {})()

    new_meta = {
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 0,
                      "quantity": 100, "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    }
    monitor_cfg = {
        "t_monitor": {
            "symbols": [{"symbol": "600519", "name": "茅台",
                         "cost_price": 1500, "quantity": 100, "note": "",
                         "trailing": {"take_profit_pct": 0.04}}],
            "trailing_defaults": {"take_profit_pct": 0.03, "stop_loss_pct": 0.02},
        },
    }
    monkeypatch.setattr("atrade.config.load_holdings_with_meta", lambda: new_meta)
    monkeypatch.setattr("atrade.config.load_monitor_config", lambda: monitor_cfg)

    sched.reload_from_disk()
    syms = [s.symbol for s in sched.t_runner.config.symbols]
    assert syms == ["002436"]
    assert sched.t_runner.config.symbols[0].trailing.take_profit_pct == 0.03


def test_reload_filters_disabled_in_derived(monkeypatch):
    """派生时应过滤掉 disabled_symbols。"""
    from atrade.scheduler.runner import DailyScheduler
    sched = DailyScheduler.__new__(DailyScheduler)
    sched.holdings = []
    sched.watch_symbols = []
    sched.watch_keywords = []
    sched.t_runner = type("R", (), {"config": type("C", (), {"symbols": []})()})()
    sched.report_gen = type("G", (), {})()

    new_meta = {
        "holdings": [
            {"symbol": "600519", "name": "a", "cost_price": 1500,
             "quantity": 100, "buy_date": "", "note": ""},
            {"symbol": "000001", "name": "b", "cost_price": 12,
             "quantity": 5000, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": ["000001"],
        "watch_keywords": [],
    }
    monitor_cfg = {"t_monitor": {}}
    monkeypatch.setattr("atrade.config.load_holdings_with_meta", lambda: new_meta)
    monkeypatch.setattr("atrade.config.load_monitor_config", lambda: monitor_cfg)

    sched.reload_from_disk()
    syms = [s.symbol for s in sched.t_runner.config.symbols]
    assert syms == ["600519"]
