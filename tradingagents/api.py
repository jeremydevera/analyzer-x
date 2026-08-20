"""The HTTP layer the React frontend talks to. Thin on purpose.

Every route is a typed window onto a module the test suite already trusts —
no business logic lives here, so a bug here can only be a wiring bug, and
every route is pinned by tests/test_api.py before any frontend uses it.

Serves localhost by default. No response ever carries a secret: the tests
plant a canary MEXC key and sweep every GET for it.

Run:  .venv/bin/uvicorn tradingagents.api:app --port 8787
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="TradingAgents API", version="1.0")

# The Next.js dev server runs on :3000; the API on :8787. Same machine, two
# ports — the browser calls this CORS and blocks it without consent.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

JOB_KINDS = ("download", "backtest", "btupdate")


# ------------------------------------------------------------------ health
@app.get("/api/health")
def health() -> dict:
    from tradingagents import parquet_store as pqs

    return {"ok": True, "storage": pqs.sizes()}


# -------------------------------------------------------------- strategies
@app.get("/api/strategies")
def strategies(coin: str | None = None, tf: str | None = None,
               signal: str | None = None, profitable: bool = False,
               limit: int = 500, offset: int = 0) -> dict:
    """Every stored strategy, filtered. Rows carry their stable id."""
    from tradingagents import backtest_report as br
    from tradingagents import market_sweep as msw

    rows = msw.all_rows()
    sel = [r for r in rows
           if (not coin or r.get("coin") == coin)
           and (not tf or r.get("tf") == tf)
           and (not signal or r.get("signal") == signal)
           and (not profitable or (r.get("profit") or 0) > 0)]
    sel.sort(key=lambda r: -(r.get("profit") or 0))
    for r in sel:
        r.setdefault("id", br.row_code(r["coin"], r["tf"], r["signal"],
                                       r.get("th") or 0.0, r["sl"], r["tp"],
                                       r["sizing"]))
    return {"rows": sel[offset:offset + max(0, min(limit, 2000))],
            "total": len(sel)}


@app.get("/api/strategies/facets")
def strategy_facets() -> dict:
    """Distinct coins/timeframes/signals, for the filter dropdowns."""
    from tradingagents import market_sweep as msw

    rows = msw.all_rows()
    return {"coins": sorted({r["coin"] for r in rows}),
            "tfs": sorted({r["tf"] for r in rows}),
            "signals": sorted({r["signal"] for r in rows})}


class TradesQuery(BaseModel):
    coin: str
    tf: str
    signal: str
    th: float = 0.0
    sl: float
    tp: float
    sizing: str
    base_margin: float = 5.0


@app.post("/api/strategies/trades")
def strategy_trades(q: TradesQuery) -> dict:
    """Every trade one stored strategy made, rebuilt from local candles."""
    from tradingagents import market_sweep as msw

    got = msw.trades_for(q.coin, q.tf, signal=q.signal, th=q.th, sl=q.sl,
                         tp=q.tp, sizing=q.sizing, base_margin=q.base_margin)
    return got


# ----------------------------------------------------------------- storage
@app.get("/api/storage/by-coin")
def storage_by_coin() -> dict:
    from tradingagents import market_sweep as msw

    return {"rows": msw.storage_by_coin()}


@app.get("/api/storage/coverage")
def storage_coverage() -> dict:
    from tradingagents import market_sweep as msw

    return {"rows": msw.candle_coverage()}


@app.get("/api/storage/sizes")
def storage_sizes() -> dict:
    from tradingagents import parquet_store as pqs

    return pqs.sizes()


# -------------------------------------------------------------------- jobs
def _check_kind(kind: str) -> None:
    if kind not in JOB_KINDS:
        raise HTTPException(404, f"unknown job kind: {kind}")


@app.get("/api/jobs/{kind}")
def job_status(kind: str) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs

    return db_jobs.status(kind)


@app.post("/api/jobs/{kind}/start")
def job_start(kind: str, spec: dict) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs

    return {"pid": db_jobs.start(kind, spec)}


@app.post("/api/jobs/{kind}/stop")
def job_stop(kind: str) -> dict:
    _check_kind(kind)
    from tradingagents import db_jobs

    db_jobs.request_stop(kind)
    return {"ok": True}


# ----------------------------------------------------------------- history
@app.get("/api/ledger")
def ledger(limit: int = 500) -> dict:
    import tradingagents.auto_trader as at

    rows = at.ledger_tail(100000)
    return {"rows": rows[:max(0, min(limit, 5000))], "total": len(rows)}


@app.get("/api/deployments")
def deployments(symbol: str | None = None, limit: int = 200) -> dict:
    from tradingagents import local_history as lh

    return {"rows": lh.deployments(symbol=symbol, limit=limit)}


# ----------------------------------------------------------------- reports
@app.get("/api/reports")
def reports() -> dict:
    """Generated grid pages, newest first, so the frontend can link them."""
    from pathlib import Path

    d = Path(__file__).resolve().parent.parent / "static" / "bt"
    if not d.exists():
        return {"rows": []}
    files = sorted(d.glob("*.html"), key=lambda f: -f.stat().st_mtime)
    return {"rows": [{"name": f.name, "bytes": f.stat().st_size,
                      "mtime": int(f.stat().st_mtime)} for f in files[:50]]}
