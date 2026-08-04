"""CLI 端到端冒烟测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_cli_writes_report(tmp_path, monkeypatch):
    import scripts.run_gap_study as cli

    monkeypatch.setattr(cli, "MAIN_BOARD_PREFIXES", ("600",))

    def fake_codes():
        return pd.DataFrame({
            "code": ["600001", "600002"],
            "name": ["测试A", "测试B"],
        })

    monkeypatch.setattr(cli.ak, "stock_info_a_code_name", fake_codes)

    class FakeHistory:
        def fetch_with_cache(self, code, scale="1d", datalen=515, use_snapshot=False):
            import numpy as np
            n = 100
            closes = np.linspace(10.0, 15.0, n)
            closes[-3] = 10.0
            closes[-2] = 11.2
            closes[-1] = 11.5
            return pd.DataFrame({
                "date": pd.date_range("2025-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
                "open": closes * 0.99,
                "high": closes * 1.03,
                "low": closes * 0.98,
                "close": closes,
                "volume": np.full(n, 100_000),
            })

    monkeypatch.setattr(cli, "HistoryProvider", lambda: FakeHistory())
    monkeypatch.setattr(cli, "industry_of", lambda code: "半导体")
    monkeypatch.setattr(cli, "_allowed_codes", lambda: {"600001", "600002"})
    out = tmp_path / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_gap_study.py",
            "--min-samples", "2",
            "--lookback-bars", "100",
            "--out", str(out),
        ],
    )
    cli.main()
    assert out.exists()
    assert "# 次日高开研究（今日未涨停）" in out.read_text(encoding="utf-8")
