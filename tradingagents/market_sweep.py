"""The Back Test module: a market-wide sweep that resumes instead of restarting.

The first run is expensive — every contract, both short timeframes, every entry
rule, the whole barrier grid. Running it again a day later should not repeat it,
and this module is why it doesn't:

* **candles are cached on disk** and only the bars after the last cached one are
  fetched from MEXC;
* **each combination's backtest is CONTINUED**, not re-run, using the tail state
  the engine hands back (`backtest_strategy(..., resume=state)`), so a refresh
  tests the new bars only.

A day of new 15m bars is 96 candles against 34,600 already tested, so a refresh
is ~360x less work than the first run. Verified exact: continuing a split run
reproduces the single-pass result trade-for-trade, including funding.

Layout under ``~/.tradingagents/backtest/``::

    candles/PI_USDT-15m.json      cached bars, appended
    state/PI-15m.json             per-combination resume state
    rows.jsonl                    the current grid
    manifest.json                 what ran, when, and how far
"""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

HOME = Path(os.path.expanduser("~/.tradingagents/backtest"))
CANDLES = HOME / "candles"
STATES = HOME / "state"
ROWS = HOME / "rows.jsonl"
MANIFEST = HOME / "manifest.json"

MIN_TRADES = 100          # the short-timeframe floor
GATE_BLOCK = 0.50         # cost >= half the target: the trade cannot win
CONTEXT_BARS = 300        # lookback a signal needs before the first new bar


def _paths() -> None:
    for d in (HOME, CANDLES, STATES):
        d.mkdir(parents=True, exist_ok=True)


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        return {}


def save_manifest(m: dict) -> None:
    _paths()
    MANIFEST.write_text(json.dumps(m, indent=2))


# ---------------------------------------------------------------- candles
def cached_candles(symbol: str, tf: str):
    """Whatever bars are on disk for this contract, as a DataFrame or None."""
    import pandas as pd

    f = CANDLES / f"{symbol}-{tf}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    df = pd.DataFrame({"Date": pd.to_datetime(d["t"], unit="ms"),
                       "Open": d["o"], "High": d["h"], "Low": d["l"],
                       "Close": d["c"]})
    return df


def refresh_candles(symbol: str, tf: str, *, days: int = 365):
    """Bring the cache up to date and report what was actually fetched.

    Returns ``(df, added, source)`` where ``source`` is ``"fetch"`` on a first
    run and ``"delta"`` when only the new tail was pulled.
    """
    import pandas as pd

    from tradingagents.dataflows import mexc_futures as fx
    from tradingagents import backtest_report as br
    import tradingagents.auto_trader as at

    _paths()
    iv, bs, cap = br.TFS[tf]
    have = cached_candles(symbol, tf)
    if have is None or len(have) < 100:
        raw = at._closed_bars(fx.klines(symbol, iv, cap), bs)
        df, added, source = raw, len(raw), "fetch"
    else:
        last = have["Date"].iloc[-1]
        # how many bars could have printed since the last cached one, plus a
        # small overlap so a partially-formed bar is replaced rather than
        # duplicated
        gap = int((pd.Timestamp.utcnow().tz_localize(None) - last)
                  .total_seconds() // bs) + 5
        if gap <= 1:
            return have, 0, "cache"
        fresh = at._closed_bars(fx.klines(symbol, iv, min(cap, max(300, gap))),
                                bs)
        df = (pd.concat([have, fresh])
              .drop_duplicates(subset="Date", keep="last")
              .sort_values("Date").reset_index(drop=True))
        added = len(df) - len(have)
        source = "delta"
    cut = pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=days + 30)
    df = df[df["Date"] >= cut].reset_index(drop=True)
    (CANDLES / f"{symbol}-{tf}.json").write_text(json.dumps({
        "t": [int(x) for x in df["Date"].to_numpy()
              .astype("datetime64[ms]").astype("int64")],
        "o": [float(x) for x in df["Open"]],
        "h": [float(x) for x in df["High"]],
        "l": [float(x) for x in df["Low"]],
        "c": [float(x) for x in df["Close"]]}, separators=(",", ":")))
    return df, added, source


# ------------------------------------------------------------------ state
def _state_file(coin: str, tf: str) -> Path:
    return STATES / f"{coin}-{tf}.json"


def load_states(coin: str, tf: str) -> dict:
    f = _state_file(coin, tf)
    try:
        return json.loads(f.read_text())
    except (OSError, ValueError):
        return {}


def save_states(coin: str, tf: str, states: dict) -> None:
    _paths()
    _state_file(coin, tf).write_text(json.dumps(states, separators=(",", ":")))


def combo_key(signal: str, th: float, sl: float, tp: float,
              sizing: str) -> str:
    return f"{signal}|{th:g}|{sl:g}|{tp:g}|{sizing}"


# ------------------------------------------------------------------ rows
ROWDIR = HOME / "rows"


def pair_rows(coin: str, tf: str) -> list:
    try:
        return json.loads((ROWDIR / f"{coin}-{tf}.json").read_text())
    except (OSError, ValueError):
        return []


def save_pair_rows(coin: str, tf: str, rows: list) -> None:
    ROWDIR.mkdir(parents=True, exist_ok=True)
    (ROWDIR / f"{coin}-{tf}.json").write_text(json.dumps(rows,
                                                         separators=(",", ":")))


def all_rows() -> list:
    """Every stored row, across every contract and timeframe."""
    if not ROWDIR.exists():
        return []
    out = []
    for f in sorted(ROWDIR.glob("*.json")):
        try:
            out += json.loads(f.read_text())
        except ValueError:
            continue
    return out


def coverage() -> dict:
    """What the store holds: pairs, rows, and how fresh each timeframe is."""
    import datetime as _dt

    pairs = sorted(p.stem for p in ROWDIR.glob("*.json")) if ROWDIR.exists() \
        else []
    newest = 0
    for f in (STATES.glob("*.json") if STATES.exists() else []):
        try:
            newest = max(newest, int(json.loads(f.read_text())
                                     .get("__last_ms__", 0)))
        except ValueError:
            continue
    return {"pairs": len(pairs), "rows": len(all_rows()),
            "last_bar": (_dt.datetime.fromtimestamp(newest / 1000)
                         .strftime("%Y-%m-%d %H:%M") if newest else None),
            "coins": len({p.split("-")[0] for p in pairs})}


# ------------------------------------------------------------------- run
def run_pair(symbol: str, tf: str, *, base_margin: float = 5.0,
             days: int = 365, signals: Sequence[str] | None = None,
             thresholds: int = 1) -> dict:
    """Test (or continue) every combination for one contract and timeframe."""
    from tradingagents.dataflows import mexc_futures as fx
    from tradingagents import backtest_report as br
    import tradingagents.auto_trader as at

    coin = symbol.replace("_USDT", "")
    iv, bs, cap = br.TFS[tf]
    df, added, source = refresh_candles(symbol, tf, days=days)
    if len(df) < 500:
        return {"coin": coin, "tf": tf, "rows": [], "added": added,
                "source": source, "why": f"only {len(df)} bars"}
    try:
        fee = at.taker_fee(symbol, fx=fx)
        liq = fx.liquidation_move_pct(symbol, at.LEVERAGE)
        fund = fx.funding_history(symbol)
        book = fx.book_cost(symbol, base_margin * at.LEVERAGE)
        rt = 2 * (fee + float(book.get("spread") or 0) / 2
                  + float(book.get("slippage") or 0))
    except Exception as exc:
        return {"coin": coin, "tf": tf, "rows": [], "added": added,
                "source": source, "why": f"venue: {str(exc)[:60]}"}

    states = load_states(coin, tf)
    last_ms = int(states.get("__last_ms__", 0))
    # State without rows shows the operator nothing. If the grid for this pair
    # is missing (first build, or a store wiped by hand), ignore the resume
    # point and measure it again rather than reporting "no new bars" forever.
    if last_ms and not pair_rows(coin, tf):
        states, last_ms = {}, 0
    ms = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    # Where does new work start? The first bar after everything already tested.
    start_at = 0
    if last_ms:
        newer = [k for k, v in enumerate(ms) if int(v) > last_ms]
        start_at = newer[0] if newer else len(df)
    incremental = bool(last_ms) and 0 < start_at < len(df)
    if last_ms and start_at >= len(df):
        return {"coin": coin, "tf": tf, "rows": pair_rows(coin, tf),
                "added": added, "source": source, "why": "no new bars",
                "incremental": True, "new_bars": 0}

    # An incremental pass only needs the new bars plus enough lookback for the
    # signal rules to be identical to what a full run would have computed.
    lo = max(0, start_at - CONTEXT_BARS) if incremental else 0
    frame = df.iloc[lo:].reset_index(drop=True)
    off = start_at - lo if incremental else 0
    hi_l = [float(x) for x in frame["High"]]
    lo_l = [float(x) for x in frame["Low"]]
    cl_l = [float(x) for x in frame["Close"]]
    # 17 of the entry rules read the OPEN, the VOLUME or the bar's clock
    # (candlestick shapes, opening-range breaks, volume spikes, kill zones).
    # Calling _dirs_for_backtest with only high/low/close returns an all-zero
    # array for those, so they appear in the signal list and can never produce
    # a row -- a silent hole in the grid.
    op_l = [float(x) for x in frame["Open"]]
    vol_l = ([float(x) for x in frame["Volume"]]
             if "Volume" in frame.columns else None)
    ts_l = list(frame["Date"].to_numpy().astype("datetime64[ms]")
                .astype("int64"))
    days_have = int((df["Date"].iloc[-1] - df["Date"].iloc[0]).days)
    n = len(frame)
    half = n // 2

    sigs = list(signals or br.SIGNALS)
    out_rows = []
    for sig in sigs:
        ths = (br.THRESHOLDS[tf][:thresholds] if thresholds < 3
               else br.THRESHOLDS[tf]) if sig in br.THRESH_SIGNALS else [None]
        for th in ths:
            key = f"{sig}_bt_{tf}"
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                      "tp": .02, "sl": .01,
                                      "threshold": .003 if th is None else th}
            try:
                dk = "rsi14_1h" if sig == "rsi14" else key
                dirs = at._dirs_for_backtest(dk, hi_l, lo_l, cl_l,
                                             opens=op_l, volume=vol_l,
                                             ts=ts_l)
            except Exception:
                at.STRATEGY_SPECS.pop(key, None)
                continue
            thp = 0.0 if th is None else round(th * 100, 3)
            for (sl, tp), sz in itertools.product(br.pairs_for(tf),
                                                  ("flat", "martingale")):
                if liq is not None and sl * 100 >= liq:
                    continue
                if rt is not None and rt / tp >= GATE_BLOCK:
                    continue
                ck = combo_key(sig, thp, sl * 100, tp * 100, sz)
                prev = states.get(ck) if incremental else None
                try:
                    r = at.backtest_strategy(
                        key, frame, base_margin, fee=fee, sizing=sz, dirs=dirs,
                        tp=tp, sl=sl, liq_move_pct=liq, funding=fund,
                        keep_log=False, resume=prev or {}, start_at=off)
                except Exception:
                    continue
                states[ck] = r["state"]
                if r["trades"] < MIN_TRADES or r["profit"] <= 0:
                    continue
                m = r["monthly"]
                mk = sorted(m)
                h1 = sum(m[k2] for k2 in mk[:max(1, len(mk) // 2)])
                h2 = sum(m[k2] for k2 in mk[max(1, len(mk) // 2):])
                out_rows.append({
                    "coin": coin, "tf": tf, "signal": sig, "th": thp,
                    "sl": round(sl * 100, 3), "tp": round(tp * 100, 3),
                    "rr": round(tp / sl, 2), "sizing": sz, "lev": at.LEVERAGE,
                    "base": base_margin, "notional": base_margin * at.LEVERAGE,
                    "trades": r["trades"], "wins": r["wins"],
                    "losses": r["losses"],
                    "winrate": round(100 * r["wins"] / r["trades"], 2),
                    "profit": round(r["profit"], 2),
                    "funding": round(r["funding_total"], 2),
                    "h1": round(h1, 2), "h2": round(h2, 2),
                    "green": sum(1 for v in m.values() if v > 0),
                    "months": len(m), "worst": round(r["worst_trade"], 2),
                    "dd": round(r["max_dd"], 2), "liqs": r["liqs"],
                    "stop_reachable": True, "days": days_have,
                    "bars": len(df),
                    "monthly": {k2: round(v2, 2) for k2, v2 in m.items()},
                    "cost_of_tp": round(rt / tp * 100, 1),
                    "rt": round(rt * 100, 4),
                    "gate": "warn" if rt / tp >= .2 else "ok"})
            at.STRATEGY_SPECS.pop(key, None)
    states["__last_ms__"] = int(ms[-1])
    save_states(coin, tf, states)
    save_pair_rows(coin, tf, out_rows)
    return {"coin": coin, "tf": tf, "rows": out_rows, "added": added,
            "source": source, "incremental": incremental,
            "new_bars": max(0, len(df) - start_at) if incremental else len(df),
            "bars": len(df), "days": days_have}
