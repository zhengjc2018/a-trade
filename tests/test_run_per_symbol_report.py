import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import run_per_symbol_report


class FakeProvider:
    def __init__(self, daily, intraday):
        self.daily = daily
        self.intraday = intraday

    def fetch_with_cache(self, symbol, scale, datalen, use_snapshot=False):
        return self.daily if scale == "1d" else self.intraday


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    daily = pd.DataFrame({
        "date": pd.date_range("2025-06-01", periods=120, freq="B").strftime("%Y-%m-%d"),
        "open": [10 + i * 0.01 for i in range(120)],
        "high": [10 + i * 0.01 + 0.1 for i in range(120)],
        "low": [10 + i * 0.01 - 0.1 for i in range(120)],
        "close": [10 + i * 0.01 for i in range(120)],
        "volume": [100000] * 120,
    })
    intraday = pd.DataFrame({
        "date": pd.date_range("2026-07-01 09:30", periods=240, freq="5min").strftime("%Y-%m-%d %H:%M:%S"),
        "open": [10] * 240,
        "high": [10.05] * 240,
        "low": [9.95] * 240,
        "close": [10] * 240,
        "volume": [1000] * 240,
    })
    monkeypatch.setattr(run_per_symbol_report, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(run_per_symbol_report, "HistoryProvider", lambda: FakeProvider(daily, intraday))
    monkeypatch.setattr(run_per_symbol_report, "SignalEngine", lambda: None)
    monkeypatch.setattr(
        run_per_symbol_report,
        "load_holdings",
        lambda: [{"symbol": "600522", "name": "中天科技", "cost_price": 12.5, "quantity": 2000}],
    )
    return tmp_path


def test_cli_portfolio_creates_report(fake_env):
    rc = run_per_symbol_report.main(["--portfolio"])
    assert rc == 0
    files = list(fake_env.glob("per_symbol_*.md"))
    assert files
    text = files[0].read_text()
    assert "中天科技" in text
    assert "## 5. 自然语言总结" in text
