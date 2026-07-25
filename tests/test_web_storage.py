"""web/storage.py 测试。"""
import json


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    from atrade.web import storage
    target = tmp_path / "holdings.local.json"
    monkeypatch.setattr(storage, "_HOLDINGS_PATH", target)

    meta = {
        "holdings": [{"symbol": "600522", "name": "中天科技",
                      "cost_price": 62.0, "quantity": 200,
                      "buy_date": "2026-05-01", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": ["白酒"],
    }
    storage.write_holdings(meta)
    # file actually exists on disk
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["holdings"][0]["symbol"] == "600522"


def test_update_holding_partial(tmp_path, monkeypatch):
    from atrade.web import storage
    target = tmp_path / "h.json"
    monkeypatch.setattr(storage, "_HOLDINGS_PATH", target)
    storage.write_holdings({
        "holdings": [{"symbol": "600522", "name": "中天",
                      "cost_price": 62.0, "quantity": 200,
                      "buy_date": "", "note": ""}],
        "disabled_symbols": [],
        "watch_keywords": [],
    })
    # Mock load_holdings_with_meta to read from target

    def fake_loader():
        return json.loads(target.read_text(encoding="utf-8"))
    monkeypatch.setattr("atrade.config.load_holdings_with_meta", fake_loader)

    result = storage.update_holding("600522", {"cost_price": 65.0, "quantity": 250})
    assert result["cost_price"] == 65.0
    assert result["quantity"] == 250


def test_update_holding_missing_symbol(tmp_path, monkeypatch):
    from atrade.web import storage
    target = tmp_path / "h.json"
    monkeypatch.setattr(storage, "_HOLDINGS_PATH", target)
    storage.write_holdings({"holdings": [], "disabled_symbols": [], "watch_keywords": []})
    monkeypatch.setattr(
        "atrade.config.load_holdings_with_meta",
        lambda: {"holdings": [], "disabled_symbols": [], "watch_keywords": []},
    )
    import pytest
    with pytest.raises(KeyError):
        storage.update_holding("600999", {"cost_price": 10})


def test_validate_patch_rejects_negative_cost():
    import pytest

    from atrade.web.storage import validate_patch
    with pytest.raises(ValueError):
        validate_patch({"cost_price": -1})


def test_validate_patch_rejects_zero_quantity():
    import pytest

    from atrade.web.storage import validate_patch
    with pytest.raises(ValueError):
        validate_patch({"quantity": 0})


def test_validate_patch_rejects_long_note():
    import pytest

    from atrade.web.storage import validate_patch
    with pytest.raises(ValueError):
        validate_patch({"note": "x" * 300})


def test_validate_patch_accepts_valid():
    from atrade.web.storage import validate_patch
    patch = {"cost_price": 62.0, "quantity": 200, "note": "ok", "buy_date": "2026-05-01"}
    out = validate_patch(patch)
    assert out["cost_price"] == 62.0
    assert out["quantity"] == 200


def test_validate_patch_rejects_unknown_field():
    import pytest

    from atrade.web.storage import validate_patch
    with pytest.raises(ValueError, match="未知字段"):
        validate_patch({"symbol": "600522"})


def test_validate_patch_empty():
    import pytest

    from atrade.web.storage import validate_patch
    with pytest.raises(ValueError, match="不能为空"):
        validate_patch({})


def test_update_t_settings_writes_only_current_holdings(tmp_path, monkeypatch):
    from atrade.web import storage

    monitor_path = tmp_path / "monitor.local.json"
    monitor_path.write_text(json.dumps({
        "news": {"enabled": True},
        "t_monitor": {
            "symbols": [
                {"symbol": "600519", "name": "旧茅台", "cost_price": 1500, "quantity": 100},
            ],
        },
    }))
    monkeypatch.setattr(storage, "_MONITOR_PATH", monitor_path)
    monkeypatch.setattr(
        storage,
        "read_holdings",
        lambda: {
            "holdings": [{"symbol": "600522", "name": "中天科技"}],
            "disabled_symbols": [],
            "watch_keywords": [],
        },
    )

    result = storage.update_t_settings(
        "600522",
        {"take_profit_pct": 0.04, "stop_loss_pct": 0.015},
    )

    payload = json.loads(monitor_path.read_text(encoding="utf-8"))
    assert result["effective"] == {"take_profit_pct": 0.04, "stop_loss_pct": 0.015}
    assert payload["t_monitor"]["symbols"] == [
        {
            "symbol": "600522",
            "trailing": {"take_profit_pct": 0.04, "stop_loss_pct": 0.015},
        },
    ]


def test_clear_t_settings_falls_back_to_defaults(tmp_path, monkeypatch):
    from atrade.web import storage

    monitor_path = tmp_path / "monitor.local.json"
    monitor_path.write_text(json.dumps({
        "t_monitor": {
            "trailing_defaults": {"take_profit_pct": 0.05, "stop_loss_pct": 0.025},
            "symbols": [
                {"symbol": "600522", "trailing": {"take_profit_pct": 0.04}},
            ],
        },
    }))
    monkeypatch.setattr(storage, "_MONITOR_PATH", monitor_path)
    monkeypatch.setattr(
        storage,
        "read_holdings",
        lambda: {"holdings": [{"symbol": "600522"}]},
    )

    result = storage.update_t_settings(
        "600522",
        {"take_profit_pct": None, "stop_loss_pct": None},
    )

    assert result["override"] == {}
    assert result["effective"] == {"take_profit_pct": 0.05, "stop_loss_pct": 0.025}
    payload = json.loads(monitor_path.read_text(encoding="utf-8"))
    assert payload["t_monitor"]["symbols"] == []


def test_update_t_settings_rejects_non_holding(tmp_path, monkeypatch):
    import pytest

    from atrade.web import storage

    monkeypatch.setattr(storage, "_MONITOR_PATH", tmp_path / "monitor.local.json")
    monkeypatch.setattr(storage, "read_holdings", lambda: {"holdings": []})

    with pytest.raises(KeyError, match="holdings"):
        storage.update_t_settings("600519", {"take_profit_pct": 0.04})


def test_validate_t_settings_patch_rejects_out_of_range():
    import pytest

    from atrade.web.storage import validate_t_settings_patch

    with pytest.raises(ValueError, match="stop_loss_pct"):
        validate_t_settings_patch({"stop_loss_pct": 1.0})
