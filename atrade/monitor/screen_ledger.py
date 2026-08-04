"""荐股推送台账。

记录每天早盘/盘中选股推送的股票与推送价，供 15:00 的胜率复盘使用。
同一个股票当天多次推送时，以第一次推送价作为默认买入价。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

DEFAULT_RECOMMENDATION_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "cache" / "recommendations.json"
)
_FILE_LOCK = threading.RLock()


@dataclass
class Recommendation:
    symbol: str
    name: str
    price: float
    pushed_at: str
    source: str = "screen"


class RecommendationLedger:
    """按日期追加荐股记录，并提供"每只股票当日首次推送"查询。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else DEFAULT_RECOMMENDATION_FILE
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(
        self,
        trade_date: str,
        symbol: str,
        name: str,
        price: float,
        pushed_at: str,
        source: str = "screen",
    ) -> None:
        """追加一条荐股记录。"""
        with _FILE_LOCK:
            data = self._load()
            picks = data.setdefault(trade_date, [])
            picks.append({
                "symbol": str(symbol).zfill(6),
                "name": str(name),
                "price": round(float(price), 4),
                "pushed_at": pushed_at,
                "source": source,
            })
            self._save(data)

    def add_many(
        self,
        trade_date: str,
        picks: list[dict],
        source: str = "screen",
    ) -> None:
        """批量追加，供一次选股推送使用。"""
        now = datetime.now().isoformat(timespec="seconds")
        for pick in picks:
            self.add(
                trade_date,
                pick["symbol"],
                pick.get("name", ""),
                pick.get("price", 0.0),
                pick.get("pushed_at", now),
                pick.get("source", source),
            )

    def get(self, trade_date: str) -> list[Recommendation]:
        """返回指定日期的全部荐股记录（按写入顺序）。"""
        with _FILE_LOCK:
            data = self._load()
            rows = data.get(trade_date, [])
        return [
            Recommendation(
                symbol=str(row.get("symbol", "")).zfill(6),
                name=str(row.get("name", "")),
                price=float(row.get("price", 0.0)),
                pushed_at=str(row.get("pushed_at", "")),
                source=str(row.get("source", "screen")),
            )
            for row in rows
            if row.get("symbol")
        ]

    def first_picks(self, trade_date: str) -> list[Recommendation]:
        """每个股票取当日第一次推送，作为默认买入价。"""
        first: dict[str, Recommendation] = {}
        for rec in self.get(trade_date):
            current = first.get(rec.symbol)
            if current is None or rec.pushed_at < current.pushed_at:
                first[rec.symbol] = rec
        return sorted(first.values(), key=lambda r: r.pushed_at)
