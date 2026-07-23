"""quote_lookup 测试。"""
from unittest.mock import patch


def test_lookup_quote_returns_dict():
    from atrade.web.quote_lookup import lookup_quote

    class FakeQuote:
        symbol = "002436"
        name = "兴森科技"
        price = 41.5
        change_pct = 2.3

        @property
        def is_valid(self):
            return True

    with patch("atrade.data.quotes.QuoteProvider") as Mock:
        instance = Mock.return_value
        instance.batch.return_value = {"002436": FakeQuote()}

        result = lookup_quote("002436")
        assert result is not None
        assert result["name"] == "兴森科技"
        assert result["price"] == 41.5


def test_lookup_quote_returns_none_when_invalid():
    from atrade.web.quote_lookup import lookup_quote

    class FakeQuote:
        symbol = "002436"
        name = ""
        price = 0.0

        @property
        def is_valid(self):
            return False

    with patch("atrade.data.quotes.QuoteProvider") as Mock:
        instance = Mock.return_value
        instance.batch.return_value = {"002436": FakeQuote()}

        assert lookup_quote("002436") is None


def test_lookup_quote_returns_none_on_exception():
    from atrade.web.quote_lookup import lookup_quote

    with patch("atrade.data.quotes.QuoteProvider") as Mock:
        Mock.return_value.batch.side_effect = RuntimeError("network error")
        assert lookup_quote("002436") is None


def test_backfill_updates_missing_names(tmp_path, monkeypatch):
    from atrade.web.quote_lookup import backfill_names

    holdings_path = tmp_path / "h.local.json"
    holdings_path.write_text('{"holdings": [{"symbol": "002436", "name": "002436"}], "disabled_symbols": []}')
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", holdings_path)

    def fake_lookup(sym):
        if sym == "002436":
            return {"symbol": "002436", "name": "兴森科技", "price": 41.0, "is_valid": True}
        return None

    monkeypatch.setattr("atrade.web.quote_lookup.lookup_quote", fake_lookup)

    meta = {
        "holdings": [
            {"symbol": "002436", "name": "002436", "cost_price": 41, "quantity": 100, "buy_date": "", "note": ""},
            {"symbol": "600519", "name": "贵州茅台", "cost_price": 1500, "quantity": 100, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": [],
        "watch_keywords": [],
    }
    result = backfill_names(meta)
    assert result["holdings"][0]["name"] == "兴森科技"
    assert result["holdings"][1]["name"] == "贵州茅台"  # 不变


def test_backfill_no_change_when_all_named(tmp_path, monkeypatch):
    from atrade.web.quote_lookup import backfill_names
    monkeypatch.setattr("atrade.config.LOCAL_HOLDINGS", tmp_path / "missing.json")

    called = []

    def fake_lookup(sym):
        called.append(sym)
        return None

    monkeypatch.setattr("atrade.web.quote_lookup.lookup_quote", fake_lookup)

    meta = {
        "holdings": [
            {"symbol": "600519", "name": "贵州茅台", "cost_price": 1500, "quantity": 100, "buy_date": "", "note": ""},
        ],
        "disabled_symbols": [],
        "watch_keywords": [],
    }
    result = backfill_names(meta)
    assert result["holdings"][0]["name"] == "贵州茅台"
    assert called == []  # 全部已有名字，不调用 lookup
