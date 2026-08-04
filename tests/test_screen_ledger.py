"""荐股推送台账测试。"""

from __future__ import annotations

from atrade.monitor.screen_ledger import RecommendationLedger


def test_add_and_get(tmp_path):
    ledger = RecommendationLedger(tmp_path / "recommendations.json")
    ledger.add(
        "2026-08-03",
        "600519",
        "贵州茅台",
        1253.0,
        "2026-08-03T09:26:05",
        source="pre_market",
    )
    records = ledger.get("2026-08-03")
    assert len(records) == 1
    assert records[0].symbol == "600519"
    assert records[0].price == 1253.0
    assert records[0].source == "pre_market"
    assert ledger.get("2026-08-02") == []


def test_first_picks_uses_earliest_push(tmp_path):
    ledger = RecommendationLedger(tmp_path / "recommendations.json")
    ledger.add(
        "2026-08-03",
        "600519",
        "贵州茅台",
        1260.0,
        "2026-08-03T10:00:00",
        source="intraday",
    )
    ledger.add(
        "2026-08-03",
        "600519",
        "贵州茅台",
        1253.0,
        "2026-08-03T09:26:05",
        source="pre_market",
    )
    picks = ledger.first_picks("2026-08-03")
    assert len(picks) == 1
    assert picks[0].price == 1253.0
    assert picks[0].pushed_at == "2026-08-03T09:26:05"


def test_missing_file_returns_empty(tmp_path):
    ledger = RecommendationLedger(tmp_path / "missing.json")
    assert ledger.get("2026-08-03") == []
    assert ledger.first_picks("2026-08-03") == []
