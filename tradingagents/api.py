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

JOB_KINDS = ("download", "backtest", "btupdate", "stratbt")


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
@app.get("/api/reports/file/{name}")
def report_file(name: str):
    """Serve one generated grid page. The name is checked against the folder's
    own listing, so a traversal ('../../etc/passwd') cannot reach anything."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    d = Path(__file__).resolve().parent.parent / "static" / "bt"
    target = (d / name).resolve()
    if target.parent != d.resolve() or not target.is_file() \
            or target.suffix != ".html":
        raise HTTPException(404, f"no such report: {name}")
    return FileResponse(target, media_type="text/html")


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


# ------------------------------------------------------------------- trading
@app.get("/api/trade/summary")
def trade_summary() -> dict:
    """The status ribbon: process, modes, wallet, today, all-time, open."""
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.dataflows import mexc_futures as fx

    cred.load_into_env()
    pid = at.runner_pid()
    books = at.active_modes()
    equity = None
    open_rows: list[dict] = []
    # assets() returns a DICT keyed by currency, not a list — iterating it as
    # a list yields the key strings and .get() dies, which read as "no wallet"
    # instead of an error. usdt_equity() is the one reader both screens use.
    try:
        equity = round(fx.usdt_equity(), 2) if fx.has_credentials() else None
    except Exception:
        equity = None
    try:
        for p in fx.open_positions():
            open_rows.append({
                "symbol": p.get("symbol"),
                "unrealized": round(float(p.get("unRealizedPnl") or 0.0), 2),
                "margin": round(float(p.get("im") or 0.0), 2),
                "side": "LONG" if int(p.get("positionType") or 1) == 1 else "SHORT",
                "entry": float(p.get("holdAvgPrice") or 0.0),
            })
    except Exception:
        pass
    paper_rows: list[dict] = []
    for skey, sst in (at.load_state() or {}).items():
        pos = sst.get("position") if isinstance(sst, dict) else None
        if pos and pos.get("dry"):
            paper_rows.append({
                # the book key is "SYMBOL#paper" (auto_trader.state_key), so
                # the separator is '#'. Splitting on ':' left "PI#paper" on
                # screen where the coin name belongs.
                "symbol": skey.split("#", 1)[0],
                "side": "LONG" if int(pos.get("side") or 1) == 1 else "SHORT",
                "entry": pos.get("entry"),
                "margin": pos.get("margin"),
                "strategy": pos.get("strategy"),
            })
    life = at.coin_stats(dry=False)
    life_total = round(sum(v["pnl"] for v in life.values()), 2)
    open_real = round(sum(r["unrealized"] for r in open_rows), 2)
    return {
        "pid": pid,
        "mode": ("LIVE+PAPER" if (False in books and True in books) else
                 "LIVE" if False in books else
                 "PAPER" if True in books else "OFF") if pid else "STOPPED",
        "halted": at.halted(),
        "equity": equity,
        "today_real": at.pnl_today(dry=False),
        "today_paper": at.pnl_today(dry=True),
        "all_time_closed": life_total,
        "open_unrealized": open_real,
        "all_time": round(life_total + open_real, 2),
        "open_positions": open_rows,
        "paper_positions": paper_rows,
    }


@app.get("/api/trade/positions")
def trade_positions() -> dict:
    """Open positions on both books, with every column the operator reads.

    Fourteen columns, not five: the set is a standing operator decision
    (app.py's _TM_POS comment records restoring them on 2026-08-20), and
    `bracket` is the one that says whether real money is protected.
    """
    import tradingagents.auto_trader as at
    from tradingagents import positions_view as pv
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.dataflows import mexc_futures as fx

    cred.load_into_env()

    def last_price(symbol: str):
        # fx.last_price is the mark-price reader. klines() returns a DataFrame,
        # so indexing it like a list silently yielded nothing and the "to TP"
        # progress column rendered empty on every row.
        try:
            return float(fx.last_price(symbol))
        except Exception:
            return None

    def contract_size(symbol: str) -> float:
        try:
            return float(fx.contract_spec(symbol).get("contractSize") or 1.0)
        except Exception:
            return 1.0

    state = at.load_state()
    try:
        live = fx.open_positions()
    except Exception:
        live = []
    kw = {"last_price": last_price, "contract_size": contract_size,
          "taker_fee": at.taker_fee, "leverage": at.LEVERAGE}
    real = pv.build_rows(state=state, exchange_positions=live,
                         stats=at.coin_stats(dry=False), dry=False, **kw)
    paper = pv.build_rows(state=state, exchange_positions=[],
                          stats=at.coin_stats(dry=True), dry=True, **kw)
    unprotected = [r["coin"] for r in real if r["bracket"]]
    return {"real": real, "paper": paper, "leverage": at.LEVERAGE,
            "unprotected": unprotected}


@app.post("/api/trade/positions/close")
def trade_close_one(body: dict) -> dict:
    """Close ONE position at market. Irreversible; the caller confirms."""
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()
    symbol = str(body.get("symbol") or "").strip()
    if not symbol:
        raise HTTPException(400, "a symbol is required")
    return at.close_one(symbol)


@app.post("/api/trade/panic")
def trade_panic(body: dict) -> dict:
    """PANIC: halt entries and close every position at market.

    Requires an explicit {"confirm": true} — a mis-click must not be able to
    flatten the account.
    """
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred

    if body.get("confirm") is not True:
        raise HTTPException(400, "panic requires confirm=true")
    cred.load_into_env()
    return at.panic_stop(close_positions=bool(body.get("close_positions", True)))


@app.get("/api/trade/strategies")
def trade_strategies(catalog: bool = False) -> dict:
    """The DEPLOYED strategies by default — the ones with a book or a coin.

    `catalog=true` adds every other key in STRATEGY_ORDER so a new one can be
    armed. It is not the default on purpose: showing all 27 made four armed
    strategies read as twenty-seven running ones (2026-08-21), and the
    Streamlit screen it replaced had made the same call in the other
    direction ("an unticked tile is clutter the operator has to read past").
    """
    import tradingagents.auto_trader as at

    settings = at.load_settings()
    books = settings.get("strategy_books") or {}
    coins = settings.get("strategy_coins") or {}
    margins = settings.get("strategy_margins") or {}
    stats = at.strategy_stats(dry=False)
    state = at.load_state()
    limits = settings.get("strategy_loss_limits") or {}
    tripped = at.tripped_strategies(settings)
    today_by = at.pnl_today_by_strategy(dry=False)
    deployed = [k for k in at.STRATEGY_ORDER
                if (books.get(k) or coins.get(k))]
    keys = at.STRATEGY_ORDER if catalog else deployed
    rows = []
    for key in keys:
        spec = at.STRATEGY_SPECS.get(key) or {}
        st_row = stats.get(key) or {}
        # book keys are "SYMBOL" (real) and "SYMBOL#paper" (simulated), so the
        # coin name is what precedes '#' and the book is which side it came from
        open_real_on, open_paper_on = [], []
        for bkey, v in state.items():
            pos = v.get("position") if isinstance(v, dict) else None
            if not pos or pos.get("strategy") != key:
                continue
            coin = bkey.split("#", 1)[0]
            (open_paper_on if pos.get("dry") else open_real_on).append(coin)
        rows.append({
            "key": key,
            "interval": spec.get("interval"),
            "tp": spec.get("tp"), "sl": spec.get("sl"),
            "threshold": spec.get("threshold"),
            "books": books.get(key) or [],
            "coins": coins.get(key) or [],
            "base_margin": margins.get(key),
            "loss_cap": limits.get(key),
            "tripped": key in tripped,
            "today": round(float(today_by.get(key) or 0.0), 2),
            "pnl": round(float(st_row.get("pnl") or 0.0), 2),
            "trades": int(st_row.get("trades") or 0),
            "wins": int(st_row.get("wins") or 0),
            "losses": int(st_row.get("losses") or 0),
            "open_on": open_real_on,
            "open_on_paper": open_paper_on,
        })
    return {
        "rows": rows,
        "sizing": at.sizing_for(settings),
        "conflicts": at.timeframe_conflicts(settings),
        # counted here so the screen's caption cannot invent its own number
        "real_count": sum(1 for k in deployed if "real" in (books.get(k) or [])),
        "paper_count": sum(1 for k in deployed
                           if (books.get(k) or []) and "real" not in books[k]),
        "idle_count": sum(1 for k in deployed if not (books.get(k) or [])),
        "deployed_count": len(deployed),
        "catalog_count": len(at.STRATEGY_ORDER),
        "showing_catalog": catalog,
        # the account-wide breaker, and whether it has already fired today
        "account_loss_cap": float(settings.get("loss_limit") or 0.0),
        "account_cap_hit": at.loss_limit_hit(settings),
        "tripped": sorted(tripped),
    }


@app.post("/api/trade/strategies/backtest")
def strategy_backtest(body: dict) -> dict:
    """The '1 YEAR' button: replay one deployed strategy over a year.

    Detached, because the grid takes minutes — the caller polls
    /api/jobs/stratbt and opens the page when it lands.
    """
    import tradingagents.auto_trader as at
    from tradingagents import db_jobs

    key = str(body.get("key") or "")
    if key not in at.STRATEGY_SPECS:
        raise HTTPException(404, f"unknown strategy: {key}")
    settings = at.load_settings()
    coins = (body.get("coins")
             or (settings.get("strategy_coins") or {}).get(key) or [])
    if not coins:
        raise HTTPException(400, "this strategy has no contract selected")
    margin = float(body.get("base_margin")
                   or (settings.get("strategy_margins") or {}).get(key) or 5.0)
    return {"pid": db_jobs.start("stratbt", {
        "key": key, "label": body.get("label") or key, "coins": coins,
        "base_margin": margin, "days": int(body.get("days") or 365)})}


@app.get("/api/trade/settings")
def trade_settings_get() -> dict:
    import tradingagents.auto_trader as at

    return {"settings": at.load_settings()}


@app.post("/api/trade/settings")
def trade_settings_post(payload: dict) -> dict:
    """Save auto_trade.json. The deploy history records every change."""
    import tradingagents.auto_trader as at

    changes = at.save_settings(payload)
    return {"ok": True, "changes_recorded": len(changes)}


@app.post("/api/trade/runner/start")
def runner_start() -> dict:
    import tradingagents.auto_trader as at

    return {"pid": at.start_runner()}


@app.post("/api/trade/runner/stop")
def runner_stop() -> dict:
    import tradingagents.auto_trader as at

    return {"stopped": at.stop_runner()}


@app.get("/api/trade/pnl/daily")
def trade_pnl_daily(dry: bool = False) -> dict:
    """Realized PnL per calendar day — the calendar view's data."""
    import tradingagents.auto_trader as at

    return {"days": at.daily_pnl(dry=dry)}


@app.get("/api/trade/pnl/by-coin")
def trade_pnl_by_coin(dry: bool = False) -> dict:
    import tradingagents.auto_trader as at

    return {"coins": at.coin_stats(dry=dry)}


@app.get("/api/trade/edge")
def trade_edge(key: str, symbol: str) -> dict:
    """The liquidity gate for one strategy/coin — block is block."""
    import tradingagents.auto_trader as at
    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()
    return at.edge_check(key, symbol)


@app.get("/api/trade/log")
def trade_log(n: int = 200) -> dict:
    import tradingagents.auto_trader as at

    return {"lines": at.log_tail(max(1, min(n, 2000)))}


# ------------------------------------------------------------------- models
def _model_specs() -> dict:
    """Built-in models merged with the operator's own, from one place."""
    import model_registry

    from tradingagents.default_config import DEFAULT_CONFIG  # noqa: F401

    import app_models  # thin, import-safe catalog (no Streamlit)

    return model_registry.merged_models(app_models.MODELS)


@app.get("/api/models")
def models_list() -> dict:
    """The catalog: which are built in, which the operator added, and whether
    each one's key is present. The key VALUE never leaves this process."""
    import model_registry

    from tradingagents import model_health as mh

    custom = model_registry.load_custom()
    specs = _model_specs()
    rows = []
    for mid, spec in specs.items():
        rows.append({
            "id": mid,
            "label": spec.get("label"),
            "provider": spec.get("provider"),
            "base_url": spec.get("base_url"),
            "key_env": spec.get("key_env"),
            "key_present": mh.key_present(spec),
            "custom": mid in custom,
        })
    return {"rows": rows, "presets": list(model_registry.PROVIDER_PRESETS)}


class ModelAdd(BaseModel):
    model_id: str
    preset: str
    base_url: str = ""
    key_env: str = ""


@app.post("/api/models/add")
def models_add(body: ModelAdd) -> dict:
    import model_registry

    ok, msg = model_registry.add_model(body.model_id, body.preset,
                                      base_url=body.base_url,
                                      key_env=body.key_env)
    return {"ok": ok, "message": msg}


@app.post("/api/models/remove")
def models_remove(body: dict) -> dict:
    import model_registry

    mid = str(body.get("model_id") or "")
    return {"ok": model_registry.remove_model(mid)}


@app.post("/api/models/ping")
def models_ping(body: dict) -> dict:
    """Live-test one model against its own provider."""
    from tradingagents import model_health as mh

    mid = str(body.get("model_id") or "")
    spec = _model_specs().get(mid)
    if not spec:
        raise HTTPException(404, f"unknown model: {mid}")
    return {"model_id": mid, **mh.ping(mid, spec)}


# ------------------------------------------------------------- new listings
@app.get("/api/crypto/new")
def crypto_new(min_volume: float = 0.0, include_all: bool = False,
               min_age_hours: float = 0.0, max_age_hours: float | None = None,
               refresh: bool = False) -> dict:
    """Newly listed MEXC spot coins. Says what it could NOT resolve, and
    whether the answer came from cache — an empty table must never be
    mistaken for "no new coins" when the truth is "could not check"."""
    from tradingagents.dataflows import mexc

    r = mexc.screen_new_listings(min_quote_volume=min_volume,
                                 include_all=include_all,
                                 min_age_hours=min_age_hours,
                                 max_age_hours=max_age_hours,
                                 force_refresh=refresh)
    return {
        "rows": [{
            "symbol": c.symbol, "base": c.base, "name": c.name,
            "contract": c.contract, "listed_date": c.listed_date,
            "age_hours": round(c.age_hours, 2), "age_days": c.age_days,
            "price": c.price, "change_pct": round(c.change_pct, 2),
            "quote_volume": round(c.quote_volume, 2),
        } for c in r.coins],
        "scanned": r.scanned, "unresolved": r.unresolved,
        "hidden_by_volume": r.hidden_by_volume,
        "hidden_by_age": r.hidden_by_age,
        "fetched_at": r.fetched_at, "from_cache": r.from_cache,
        "stale": r.stale, "window_days": mexc.WINDOW_DAYS,
    }


@app.get("/api/crypto/upcoming")
def crypto_upcoming() -> dict:
    """Announced-but-not-trading listings, soonest first."""
    from tradingagents.dataflows import mexc

    try:
        rows = mexc.upcoming_listings()
    except Exception as exc:                                   # noqa: BLE001
        return {"rows": [], "why": f"{type(exc).__name__}: {exc}"}
    return {"rows": [{
        "symbol": r.get("symbol"), "base": r.get("base"),
        "name": r.get("name"), "open_ms": r.get("open_ms"),
        "hours_until": (round(r["hours_until"], 2)
                        if r.get("hours_until") is not None else None),
    } for r in rows]}


# ---------------------------------------------------------------- analysis
@app.get("/api/analysis/runs")
def analysis_runs(limit: int = 25) -> dict:
    from tradingagents import analysis_jobs as aj

    return {"rows": aj.runs(limit)}


@app.post("/api/analysis/start")
def analysis_start(spec: dict) -> dict:
    from tradingagents import analysis_jobs as aj

    if not str(spec.get("ticker") or "").strip():
        raise HTTPException(400, "a ticker is required")
    if not str(spec.get("trade_date") or "").strip():
        raise HTTPException(400, "a trade date is required")
    return {"run_id": aj.start(spec)}


@app.get("/api/analysis/{run_id}")
def analysis_status(run_id: str) -> dict:
    from tradingagents import analysis_jobs as aj

    return aj.status(run_id)


@app.post("/api/analysis/{run_id}/stop")
def analysis_stop(run_id: str) -> dict:
    from tradingagents import analysis_jobs as aj

    return {"stopped": aj.stop(run_id)}


@app.get("/api/analysis/social/sources")
def analysis_social_sources() -> dict:
    """Which social sources the Sentiment Analyst can read, and whether X is
    actually usable — X is metered and needs TWITTERAPI_IO_KEY, so the screen
    must be able to say "you picked X but there is no key" BEFORE a run."""
    import os

    from tradingagents import analysis_jobs as aj

    return {
        "sources": [
            {"id": "stocktwits", "label": "StockTwits only",
             "note": "free, keyless, carries Bullish/Bearish tags"},
            {"id": "twitter", "label": "X / Twitter only",
             "note": "metered — spends TwitterAPI.io credits"},
            {"id": "both", "label": "Both",
             "note": "StockTwits plus X — spends credits"},
        ],
        "default": aj.DEFAULT_SOCIAL,
        "x_key_present": bool(os.environ.get("TWITTERAPI_IO_KEY", "").strip()),
        "x_key_env": "TWITTERAPI_IO_KEY",
    }


@app.post("/api/trade/halt")
def trade_halt(body: dict) -> dict:
    """Halt entries, or clear the halt. The kill file blocks NEW entries; open
    positions keep their exchange-side brackets and their own exits."""
    import tradingagents.auto_trader as at

    if bool(body.get("halt", True)):
        at.KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
        at.KILL_PATH.write_text("halted from the UI", encoding="utf-8")
    else:
        at.KILL_PATH.unlink(missing_ok=True)
    return {"halted": at.halted()}


# ------------------------------------------------------------- credentials
@app.get("/api/trade/credentials")
def credentials_status() -> dict:
    """Where the active MEXC keys came from — masked fingerprints only.

    cred.status() is built to be renderable: it returns no secret material,
    so this route cannot leak one. The canary test proves it.
    """
    from tradingagents.dataflows import mexc_credentials as cred

    cred.load_into_env()
    got = dict(cred.status())
    got["env_conflict"] = cred.env_conflict()
    return got


@app.post("/api/trade/credentials")
def credentials_save(body: dict) -> dict:
    """Store a key pair on this Mac at mode 0600, then reload the env."""
    from tradingagents.dataflows import mexc_credentials as cred

    key = str(body.get("api_key") or "").strip()
    secret = str(body.get("api_secret") or "").strip()
    if not key or not secret:
        raise HTTPException(400, "both an api key and a secret are required")
    cred.save(key, secret)
    cred.load_into_env()
    return {"saved": True, **credentials_status()}


@app.post("/api/trade/credentials/forget")
def credentials_forget() -> dict:
    """Delete the stored pair. A shell-supplied key still applies."""
    from tradingagents.dataflows import mexc_credentials as cred

    return {"cleared": cred.clear(), **credentials_status()}


@app.post("/api/trade/credentials/test")
def credentials_test(body: dict) -> dict:
    """What this key can actually DO — read, order, and rest a stop.

    'The request was sent' is not 'it is in place' (rule 14), so the probe
    checks resting a stop, not just reading a balance.
    """
    from tradingagents.dataflows import mexc_credentials as cred
    from tradingagents.dataflows import mexc_futures as fx

    cred.load_into_env()
    symbol = str(body.get("symbol") or "BTC_USDT").strip()
    return fx.preflight(symbol)
