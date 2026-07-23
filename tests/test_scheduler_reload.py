"""DailyScheduler.reload_from_disk() 测试。"""


def _make_scheduler():
    from atrade.scheduler.runner import DailyScheduler
    return DailyScheduler.__new__(DailyScheduler)


def test_reload_updates_holdings(monkeypatch):
    sched = _make_scheduler()
    sched.holdings = [{"symbol": "600519"}]
    sched.watch_symbols = ["600519"]
    sched.watch_keywords = []
    # mock t_runner + report_gen
    class _Cfg:
        symbols = []
    class _R:
        config = _Cfg()
    sched.t_runner = _R()
    sched.report_gen = type("G", (), {})()

    new_meta = {
        "holdings": [
            {"symbol": "600522", "name": "中天科技",
             "cost_price": 62.0, "quantity": 200,
             "buy_date": "2026-05-01", "note": ""},
            {"symbol": "601318", "name": "中国平安",
             "cost_price": 50.0, "quantity": 100,
             "buy_date": "", "note": ""},
        ],
        "disabled_symbols": ["601318"],
        "watch_keywords": ["白酒"],
    }
    monitor_cfg = {
        "t_monitor": {
            "symbols": [
                {"symbol": "600522", "name": "中天科技",
                 "cost_price": 62.0, "quantity": 200, "note": ""},
                {"symbol": "601318", "name": "中国平安",
                 "cost_price": 50.0, "quantity": 100, "note": ""},
            ],
        },
    }

    monkeypatch.setattr("atrade.config.load_holdings_with_meta", lambda: new_meta)
    monkeypatch.setattr("atrade.config.load_monitor_config", lambda: monitor_cfg)

    result = sched.reload_from_disk()
    assert result["holdings"] == 2
    assert result["t_symbols"] == 1  # 601318 被 disabled 过滤
    assert sched.holdings[0]["symbol"] == "600522"
    assert sched.watch_symbols == ["600522", "601318"]
    assert sched.watch_keywords == ["白酒"]
    # 601318 应被过滤
    syms = [s.symbol for s in sched.t_runner.config.symbols]
    assert "601318" not in syms
    assert "600522" in syms


def test_reload_handles_missing_t_monitor(monkeypatch):
    sched = _make_scheduler()
    sched.holdings = []
    sched.watch_symbols = []
    sched.watch_keywords = []
    sched.t_runner = type("R", (), {"config": type("C", (), {"symbols": []})()})()
    sched.report_gen = type("G", (), {})()

    monkeypatch.setattr("atrade.config.load_holdings_with_meta", lambda: {
        "holdings": [], "disabled_symbols": [], "watch_keywords": [],
    })
    monkeypatch.setattr("atrade.config.load_monitor_config", lambda: {})

    result = sched.reload_from_disk()
    assert result["holdings"] == 0
    assert result["t_symbols"] == 0
