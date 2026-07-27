"""回测 Web API：把 BacktestRunner 暴露到 FastAPI。

endpoints:
    POST /api/backtest/run            单股回测
    POST /api/backtest/portfolio      持仓组合回测
    GET  /api/backtest/jobs/{job_id}  job 状态
    GET  /api/backtest/jobs           列表（symbol / status 过滤）
    GET  /api/backtest/report/{job_id}  最终报告 Markdown
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status

from .jobs import (
    BacktestJob,
    BacktestRunner,
    SweepRequest,
    T0JobRequest,
    make_job_id,
)
from .sweep import SweepGrid, run_sweep
from .sweep import to_markdown as sweep_to_markdown
from .t0_simulator import T0Simulator

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_RUNNER: Optional[BacktestRunner] = None
_RUNNER_LOCK = threading.Lock()


def get_runner() -> BacktestRunner:
    global _RUNNER
    if _RUNNER is not None:
        return _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = BacktestRunner()
        return _RUNNER


def set_runner(runner: BacktestRunner) -> None:
    """注入自定义 runner（用于单测）。"""
    global _RUNNER
    with _RUNNER_LOCK:
        _RUNNER = runner


# ---- executor：把 BacktestJob 转成 {summary, report_path} ----
def _build_executor(
    notifier: Optional[Callable[[str], None]] = None,
) -> Callable[[BacktestJob], dict]:
    def executor(job: BacktestJob) -> dict:
        request = job.request
        report_store = get_runner().reports

        if job.type == "t0":
            req = T0JobRequest.from_dict(request)
            sim = T0Simulator(scale=req.scale)
            result = sim.run(
                req.symbol, req.cost_price, req.quantity,
                start_date=req.start_date.replace("-", ""),
                end_date=req.end_date.replace("-", ""),
            )
            summary = _summary_from_t0(result)
            if req.sweep:
                grid = SweepGrid()
                entries = run_sweep(
                    req.symbol, req.cost_price, req.quantity, grid,
                    start_date=req.start_date, end_date=req.end_date, scale=req.scale,
                )
                md = sweep_to_markdown(req.symbol, entries, req.cost_price, req.quantity)
                md = f"{result.summary()}\n\n---\n\n{md}"
            else:
                md = result.summary()
            path = report_store.write(job.job_id, md)
            if req.push and notifier:
                try:
                    notifier(md)
                except Exception:
                    pass
            return {"summary": summary, "report_path": path}

        if job.type == "sweep":
            req = SweepRequest.from_dict(request)
            grid = SweepGrid(
                take_profits=req.take_profits,
                stop_losses=req.stop_losses,
            )
            entries = run_sweep(
                req.symbol, req.cost_price, req.quantity, grid,
                start_date=req.start_date, end_date=req.end_date, scale=req.scale,
            )
            summary = _summary_from_sweep(req.symbol, entries)
            md = sweep_to_markdown(req.symbol, entries, req.cost_price, req.quantity)
            path = report_store.write(job.job_id, md)
            if req.push and notifier:
                try:
                    notifier(md)
                except Exception:
                    pass
            return {"summary": summary, "report_path": path}

        if job.type == "portfolio":
            # portfolio：依次走 sweep 路径，每只股一个报告
            from atrade.config import load_holdings
            all_holdings = load_holdings()
            active_holdings = [h for h in all_holdings if int(h.get("quantity", 0)) > 0]
            skipped = [h for h in all_holdings if int(h.get("quantity", 0)) <= 0]
            if not active_holdings:
                raise ValueError(
                    f"当前 {len(all_holdings)} 个持仓全部为 0 股（已平仓），无可回测标的"
                )
            pieces = []
            summaries = []
            for h in active_holdings:
                grid = SweepGrid()
                entries = run_sweep(
                    h["symbol"], h["cost_price"], h["quantity"], grid,
                    start_date=request.get("start_date", "2024-01-01"),
                    end_date=request.get("end_date", datetime.now().strftime("%Y-%m-%d")),
                    scale=request.get("scale", "1d"),
                )
                pieces.append(
                    f"## {h['name'] or h['symbol']} ({h['symbol']})\n\n"
                    + sweep_to_markdown(h["symbol"], entries, h["cost_price"], h["quantity"])
                )
                summaries.append(_summary_from_sweep(h["symbol"], entries))
            skipped_note = ""
            if skipped:
                skipped_lines = [
                    f"- {h['name'] or h['symbol']} ({h['symbol']}): 持仓 0 股，已跳过"
                    for h in skipped
                ]
                skipped_note = (
                    "## ⚠️ 已跳过（持仓 0 股）\n\n" + "\n".join(skipped_lines) + "\n\n---\n\n"
                )
            summary = {
                "portfolio_count": len(active_holdings),
                "skipped_count": len(skipped),
                "items": summaries,
            }
            md = (
                "# 📊 持仓组合扫描\n\n"
                f"_扫描 {len(active_holdings)} 个持仓，跳过 {len(skipped)} 个已平仓标的_\n\n"
                f"{skipped_note}"
                + "\n\n---\n\n".join(pieces)
            )
            path = report_store.write(job.job_id, md)
            if request.get("push") and notifier:
                try:
                    notifier(md)
                except Exception:
                    pass
            return {"summary": summary, "report_path": path}

        raise ValueError(f"未知 job.type: {job.type}")

    return executor


def _summary_from_t0(r) -> dict:
    return {
        "net_t_profit": round(r.net_t_profit, 2),
        "t_win_rate": round(r.t_win_rate, 4),
        "trades": r.t_win_count + r.t_loss_count,
        "cost_change": round(r.cost_change, 4),
    }


def _summary_from_sweep(symbol: str, entries) -> dict:
    if not entries:
        return {"symbol": symbol, "best": None}
    qualified = sorted(entries, key=lambda e: e.score, reverse=True)
    best = qualified[0]
    return {
        "symbol": symbol,
        "best": {
            "take_profit_pct": best.take_profit_pct,
            "stop_loss_pct": best.stop_loss_pct,
            "win_rate": round(best.win_rate, 4),
            "net_pnl": round(best.net_pnl, 2),
            "trades": best.trades,
        },
        "combos": len(entries),
    }


def _make_job(type_: str, symbol: str, request: dict, push: bool = True) -> BacktestJob:
    if not push:
        request = {**request, "push": False}
    return BacktestJob(
        job_id=make_job_id(),
        type=type_,
        symbol=symbol,
        request=request,
    )


# ---- routes ----
@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_backtest(payload: dict, request: Request) -> dict:
    try:
        req = T0JobRequest.from_dict(payload)
    except (ValueError, KeyError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    if req.sweep:
        job = _make_job(
            "sweep",
            req.symbol,
            SweepRequest(
                symbol=req.symbol,
                cost_price=req.cost_price,
                quantity=req.quantity,
                start_date=req.start_date,
                end_date=req.end_date,
                scale=req.scale,
                push=req.push,
            ).__dict__,
            push=req.push,
        )
    else:
        job = _make_job("t0", req.symbol, req.__dict__)

    runner = get_runner()
    runner.set_executor(_build_executor(notifier=_maybe_notify(request)))
    runner.submit(job)
    return {"job_id": job.job_id, "status": job.status.value, "symbol": job.symbol}


@router.post("/portfolio", status_code=status.HTTP_202_ACCEPTED)
def run_portfolio_backtest(payload: dict, request: Request) -> dict:
    body = dict(payload or {})
    body.setdefault("start_date", "2024-01-01")
    body.setdefault("end_date", datetime.now().strftime("%Y-%m-%d"))
    body.setdefault("scale", "1d")
    body.setdefault("push", True)
    job = BacktestJob(
        job_id=make_job_id(),
        type="portfolio",
        symbol="",
        request=body,
    )
    runner = get_runner()
    runner.set_executor(_build_executor(notifier=_maybe_notify(request)))
    runner.submit(job)
    return {"job_id": job.job_id, "status": job.status.value, "type": "portfolio"}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    entry = get_runner().status(job_id)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job not found: {job_id}")
    return entry


@router.get("/jobs")
def list_jobs(
    symbol: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(20),
) -> list[dict]:
    jobs = get_runner().jobs.list(
        symbol=symbol, status=status_filter, limit=limit,
    )
    # 加 summary 缩略
    out = []
    for e in jobs:
        item = {
            "job_id": e["job_id"],
            "symbol": e.get("symbol", ""),
            "type": e.get("type", "t0"),
            "status": e.get("status"),
            "created_at": e.get("created_at"),
            "finished_at": e.get("finished_at"),
        }
        if e.get("summary"):
            item["summary"] = e["summary"]
        out.append(item)
    return out


@router.get("/report/{job_id}")
def get_report(job_id: str) -> dict:
    runner = get_runner()
    entry = runner.status(job_id)
    if not entry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"job not found: {job_id}")
    path = entry.get("report_path")
    if path:
        try:
            from pathlib import Path
            text = Path(path).read_text(encoding="utf-8")
            return {"job_id": job_id, "markdown": text, "path": path}
        except OSError as e:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e
    raise HTTPException(status.HTTP_404_NOT_FOUND, "report not ready")


def _maybe_notify(request: Request) -> Optional[Callable[[str], None]]:
    """从 request.app.state 取 notifier；测试时为 None。"""
    try:
        notifier = getattr(request.app.state, "notifier", None)
    except Exception:
        notifier = None
    if notifier is None:
        return None

    def _fn(md: str) -> None:
        try:
            for chunk in _split_by_bytes(md, 3800):
                notifier.send_markdown(chunk)
        except Exception:
            pass

    return _fn


def _split_by_bytes(text: str, max_bytes: int) -> list[str]:
    """粗略按字节切 markdown。"""
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]
    out = []
    cur = []
    cur_bytes = 0
    for line in text.splitlines(keepends=True):
        lb = len(line.encode("utf-8"))
        if cur_bytes + lb > max_bytes:
            out.append("".join(cur))
            cur = [line]
            cur_bytes = lb
        else:
            cur.append(line)
            cur_bytes += lb
    if cur:
        out.append("".join(cur))
    return out
