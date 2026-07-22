"""统一配置加载与校验。

加载优先级（高 → 低）：
1. 显式环境变量 A_TRADE_HOLDINGS_PATH / A_TRADE_MONITOR_PATH
2. config/holdings.local.json / config/monitor.local.json（本地真实数据，Git 忽略）
3. config/holdings.json / config/monitor.json（向后兼容，可继续放示例/真实数据，但真实数据建议迁移到 .local.json）

校验规则：
- 股票代码必须为 6 位数字
- 成本价 > 0，数量为正整数
- 未知顶层字段 → 拒绝启动（不静默忽略）
- 缺失必需字段 → 明确错误并提示如何复制示例
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from loguru import logger

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_HOLDINGS = _CONFIG_DIR / "holdings.json"
LOCAL_HOLDINGS = _CONFIG_DIR / "holdings.local.json"
DEFAULT_MONITOR = _CONFIG_DIR / "monitor.json"
LOCAL_MONITOR = _CONFIG_DIR / "monitor.local.json"

ENV_HOLDINGS = "A_TRADE_HOLDINGS_PATH"
ENV_MONITOR = "A_TRADE_MONITOR_PATH"

_CODE_RE = re.compile(r"^\d{6}$")


class ConfigError(ValueError):
    """配置校验失败。"""


def _candidate_paths(name: str, default_path: Path, local_path: Path, env: str) -> list[Path]:
    out: list[Path] = []
    env_path = os.getenv(env)
    if env_path:
        out.append(Path(env_path))
    out.append(local_path)  # .local.json 优先
    out.append(default_path)
    return [p for p in out if p is not None]


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}（请先复制 .example.json 或创建 .local.json）")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"配置文件 JSON 解析失败: {path}: {e}") from e


def _validate_holding(item: Any, idx: int) -> dict:
    if not isinstance(item, dict):
        raise ConfigError(f"holdings[{idx}] 必须是对象，实际: {type(item).__name__}")
    code = str(item.get("symbol", "")).zfill(6)
    if not _CODE_RE.match(code):
        raise ConfigError(f"holdings[{idx}].symbol 必须是 6 位数字，实际: {item.get('symbol')!r}")
    cost = item.get("cost_price")
    qty = item.get("quantity")
    if cost is None or not isinstance(cost, (int, float)) or cost <= 0:
        raise ConfigError(f"holdings[{idx}].cost_price 必须 > 0，实际: {cost!r}")
    if qty is None or not isinstance(qty, int) or qty <= 0:
        raise ConfigError(f"holdings[{idx}].quantity 必须为正整数，实际: {qty!r}")
    return {
        "symbol": code,
        "name": str(item.get("name", "")),
        "cost_price": float(cost),
        "quantity": int(qty),
        "buy_date": str(item.get("buy_date", "")),
        "note": str(item.get("note", "")),
    }


def _validate_monitor(cfg: dict) -> dict:
    """校验监控配置并填充默认值。"""
    if not isinstance(cfg, dict):
        raise ConfigError("monitor.json 必须是 JSON 对象")
    news = cfg.get("news", {})
    screen = cfg.get("screen", {})
    tmon = cfg.get("t_monitor", {})

    if not isinstance(news, dict):
        raise ConfigError("news 必须是对象")
    if not isinstance(screen, dict):
        raise ConfigError("screen 必须是对象")
    if not isinstance(tmon, dict):
        raise ConfigError("t_monitor 必须是对象")

    interval = int(screen.get("interval_minutes", 30))
    if interval <= 0:
        raise ConfigError(f"screen.interval_minutes 必须 > 0，实际: {interval}")
    pct_min = screen.get("pct_chg_min")
    pct_max = screen.get("pct_chg_max")
    if pct_min is not None and not isinstance(pct_min, (int, float)):
        raise ConfigError("screen.pct_chg_min 必须为数字或 null")
    if pct_max is not None and not isinstance(pct_max, (int, float)):
        raise ConfigError("screen.pct_chg_max 必须为数字或 null")

    tmon_interval = int(tmon.get("scan_interval_minutes", 2))
    if tmon_interval <= 0:
        raise ConfigError(f"t_monitor.scan_interval_minutes 必须 > 0，实际: {tmon_interval}")
    scale = str(tmon.get("scale", "5m"))
    if scale not in {"1m", "5m", "15m", "30m", "60m", "1d"}:
        raise ConfigError(f"t_monitor.scale 必须是支持的 K 线周期，实际: {scale}")
    datalen = int(tmon.get("datalen", 120))
    if datalen <= 0:
        raise ConfigError(f"t_monitor.datalen 必须 > 0，实际: {datalen}")

    confirm_bars = int(tmon.get("confirm_bars", 2))
    if confirm_bars <= 0:
        raise ConfigError(f"t_monitor.confirm_bars 必须 > 0，实际: {confirm_bars}")
    if confirm_bars > 10:
        raise ConfigError(f"t_monitor.confirm_bars 不能 > 10，实际: {confirm_bars}")

    candidate_ttl = int(tmon.get("candidate_ttl_minutes", 30))
    if candidate_ttl <= 0:
        raise ConfigError(f"t_monitor.candidate_ttl_minutes 必须 > 0，实际: {candidate_ttl}")
    if candidate_ttl > 240:
        raise ConfigError(f"t_monitor.candidate_ttl_minutes 不能 > 240，实际: {candidate_ttl}")

    symbols = []
    for idx, item in enumerate(tmon.get("symbols") or []):
        symbols.append(_validate_holding(item, idx))

    return {
        "news": {"enabled": bool(news.get("enabled", True))},
        "screen": {
            "enabled": bool(screen.get("enabled", True)),
            "interval_minutes": interval,
            "pct_chg_min": pct_min,
            "pct_chg_max": pct_max,
            "amount_min": screen.get("amount_min"),
            "code_in": list(screen.get("code_in") or []),
        },
        "t_monitor": {
            "enabled": bool(tmon.get("enabled", True)),
            "scan_interval_minutes": tmon_interval,
            "scale": scale,
            "datalen": datalen,
            "confirm_bars": confirm_bars,
            "candidate_ttl_minutes": candidate_ttl,
            "symbols": symbols,
        },
    }


def load_holdings() -> list[dict]:
    """加载持仓列表，按优先级查找 *.local.json / 默认 *.json。"""
    for path in _candidate_paths("holdings", DEFAULT_HOLDINGS, LOCAL_HOLDINGS, ENV_HOLDINGS):
        if path.exists():
            cfg = _read_json(path)
            raw = cfg.get("holdings") or []
            validated = [_validate_holding(item, idx) for idx, item in enumerate(raw)]
            logger.info(f"加载持仓: {path} ({len(validated)} 项)")
            return validated
    raise ConfigError(
        "未找到任何持仓配置文件。请执行：\n"
        f"  cp {DEFAULT_HOLDINGS.with_suffix('.example.json')} {LOCAL_HOLDINGS}\n"
        "然后编辑 .local.json 填写真实持仓。"
    )


def load_monitor_config() -> dict:
    """加载监控配置（含 screen / t_monitor / news）。"""
    for path in _candidate_paths("monitor", DEFAULT_MONITOR, LOCAL_MONITOR, ENV_MONITOR):
        if path.exists():
            cfg = _read_json(path)
            validated = _validate_monitor(cfg)
            logger.info(f"加载监控配置: {path}")
            return validated
    logger.warning("未找到 monitor 配置文件，将返回空配置")
    return {"news": {"enabled": False}, "screen": {"enabled": False}, "t_monitor": {"enabled": False, "symbols": []}}


def load_watch_keywords() -> list[str]:
    """加载关注关键词（从 holdings 配置顶层 watch_keywords）。"""
    for path in _candidate_paths("holdings", DEFAULT_HOLDINGS, LOCAL_HOLDINGS, ENV_HOLDINGS):
        if path.exists():
            cfg = _read_json(path)
            kw = cfg.get("watch_keywords") or []
            if isinstance(kw, list):
                return [str(x) for x in kw]
            return []
    return []
