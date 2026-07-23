"""T 信号自动执行器测试。"""
import json


def _alert(symbol="002436", sig="SELL", price=50.0, name="兴森科技"):
    return {
        "symbol": symbol,
        "name": name,
        "signal_type": sig,
        "signal_name": "BUY(2因子共振)" if sig == "BUY" else "放量拉升",
        "reason": "test reason",
        "trigger_price": price,
        "strength": "strong",
    }


def test_sell_decrements_quantity(tmp_path, monkeypatch):
    """SELL 应该扣减持仓并记录 trade。"""
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    # 配置 holdings 文件
    holdings_path = tmp_path / "holdings.local.json"
    holdings_path.write_text(json.dumps({
        "holdings": [
            {"symbol": "002436", "name": "兴森", "cost_price": 41.0,
             "quantity": 300, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": [],
        "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": True, "lots_per_trade": 1.0})
    trade = ex.execute(_alert(sig="SELL", price=50.0))

    assert trade is not None
    assert trade["direction"] == "SELL"
    assert trade["shares"] == 100
    assert trade["holding_qty_after"] == 200

    # holdings 文件已更新
    updated = json.loads(holdings_path.read_text())
    assert updated["holdings"][0]["quantity"] == 200


def test_sell_skipped_when_insufficient_quantity(tmp_path, monkeypatch):
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 10,
                      "quantity": 50, "buy_date": "", "note": ""}],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": True, "lots_per_trade": 1.0})
    trade = ex.execute(_alert(sig="SELL"))
    assert trade is not None
    assert trade["skipped_reason"]  # 非空说明
    assert "持仓不足" in trade["skipped_reason"]


def test_sell_skipped_when_already_traded_today(tmp_path, monkeypatch):
    """同一只股票同一天第二次 SELL 应被跳过。"""
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 10,
                      "quantity": 500, "buy_date": "", "note": ""}],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": True})
    first = ex.execute(_alert(sig="SELL"))
    assert first["holding_qty_after"] == 400

    second = ex.execute(_alert(sig="SELL"))
    assert "今日已执行" in second["skipped_reason"]
    assert second["shares"] == 0


def test_stop_loss_shares_sell_slot(tmp_path, monkeypatch):
    """STOP_LOSS 与 SELL 共用槽位。"""
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 10,
                      "quantity": 500, "buy_date": "", "note": ""}],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": True})
    ex.execute(_alert(sig="SELL"))
    # STOP_LOSS 应被同一槽位跳过
    second = ex.execute(_alert(sig="STOP_LOSS"))
    assert "今日已执行" in second["skipped_reason"]


def test_buy_records_only_no_quantity_change(tmp_path, monkeypatch):
    """BUY 仅记账，不修改持仓数量。"""
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 10,
                      "quantity": 300, "buy_date": "", "note": ""}],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": True})
    trade = ex.execute(_alert(sig="BUY"))

    assert trade["direction"] == "BUY"
    assert "BUY 仅记账" in trade["skipped_reason"]
    assert trade["shares"] == 100  # 记账了 100 股

    # 持仓没变
    updated = json.loads(holdings_path.read_text())
    assert updated["holdings"][0]["quantity"] == 300


def test_auto_execute_disabled_returns_none(tmp_path, monkeypatch):
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 10,
                      "quantity": 300, "buy_date": "", "note": ""}],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": False})
    assert ex.execute(_alert(sig="SELL")) is None


def test_lots_per_trade_configurable(tmp_path, monkeypatch):
    from atrade.monitor import t_executor
    monkeypatch.setattr(t_executor, "_TRADES_FILE", tmp_path / "t_trades.json")
    holdings_path = tmp_path / "h.json"
    holdings_path.write_text(json.dumps({
        "holdings": [{"symbol": "002436", "name": "x", "cost_price": 10,
                      "quantity": 500, "buy_date": "", "note": ""}],
        "disabled_symbols": [], "watch_keywords": [],
    }))
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)
    monkeypatch.setattr("atrade.config.DEFAULT_HOLDINGS", tmp_path / "missing.json")

    ex = t_executor.TTradeExecutor({"auto_execute": True, "lots_per_trade": 2.0})
    trade = ex.execute(_alert(sig="SELL"))
    assert trade["shares"] == 200
    assert trade["holding_qty_after"] == 300
