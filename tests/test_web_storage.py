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
