"""THE OLD-DATA TEST of a learned formula set: candles it never met.

The operator, Sep 26, 2026, on the Sep 25 Strat review: *"Yes do 2 and 3"* —
2 being *"keep only the ones that pass the never-seen test"*.

Why a test is needed at all: the Sep 25 run CHOSE on its last 30 days (see
`formula_learner`'s docstring), so the "unseen" win rate on the screen was
the best of several peeks, not a measurement. The only candles that took no
part in learning OR choosing are the ones BEFORE the learner's window:

    ... | OLD 90 days | learn 180 days | chosen-on 30 days |  Sep 25, 2026
         ^ this file measures here

A formula PASSES when, over those 90 old days, through the real engine with
fee + slippage + funding:

* it took at least `market_sweep.min_trades(tf, 90)` trades,
* its win rate beat its OWN break-even (the TP/SL and the cost it was learned
  with — `learned.breakeven_winrate`, never 50%, CLAUDE.md rule 11),
* and it made money.

A formula whose coin has no 90 days (plus the 300-bar lead-in) before the
window is NOT verified — it is counted as "too young to test", never passed
and never failed. The result is written to `VERIFIED_FILE`, and the store's
"Sep 25 Strat · passed old-data test" group reads it (rows_index).
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

OLD_DAYS = 90
WINDOW_DAYS = 210                   # formula_learner: LEARN_DAYS + UNSEEN_DAYS
WARM = 300                          # market_sweep.CONTEXT_BARS
FEE = 0.0002
# the Sep 25 run measured back from Sep 25, 2026 (UTC midnight, as the
# review's first 300-formula test did)
RUN_END_MS = 1_790_294_400_000
VERIFIED_FILE = Path(__file__).resolve().parent / "learned" / "sep25_verified.json"


def _cost(f: dict) -> float:
    """The round trip the formula was LEARNED with, recovered exactly from
    its stored break-even: be = (sl + rt) / (tp + sl)."""
    be = float(f["learned"]["breakeven_winrate"]) / 100.0
    return max(0.0, be * (f["tp"] + f["sl"]) - f["sl"])


def _old_candles(symbol: str, tf: str, old0, learn0):
    """The old window plus WARM bars of lead-in, straight from the venue.

    Not the disk cache: this PC's cache is a TAIL (ETH 15m held Aug 04 to
    Sep 15, 2026 — none of the old window), and a test that could only read
    the tail would call almost every coin "too young". Pages backwards from
    the learner's first bar, never writing any cache."""
    import pandas as pd

    from tradingagents import backtest_report as br
    from tradingagents.dataflows import exchange as fx

    iv, bs, _ = br.TFS[tf]
    end = int(learn0.timestamp()) - 1
    stop = int(old0.timestamp()) - (WARM + 5) * bs
    parts = []
    while end > stop:
        part = fx.klines_page(symbol, iv, 2000, end)
        if part is None or part.empty:
            break
        parts.append(part)
        first = int(part["Date"].iloc[0].timestamp())
        if first >= end:
            break
        end = first - 1
    if not parts:
        return None
    return (pd.concat(parts, ignore_index=True).sort_values("Date")
            .drop_duplicates(subset="Date").reset_index(drop=True))


def _coin_job(coin: str, specs: list, run_end_ms: int) -> list:
    import pandas as pd

    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, market_sweep as msw, signals_learned as sl
    from tradingagents.dataflows import exchange as fx

    day = 86_400_000
    learn0 = pd.Timestamp(run_end_ms - WINDOW_DAYS * day, unit="ms")
    old0 = pd.Timestamp(run_end_ms - (WINDOW_DAYS + OLD_DAYS) * day, unit="ms")
    try:
        fund = fx.funding_history(f"{coin}_USDT")
        fund_ok = True
    except Exception as exc:                                   # noqa: BLE001
        fund, fund_ok = [], f"{type(exc).__name__}: {exc}"
    out, frames = [], {}
    for f in specs:
        tf = f["tf"]
        rec = {"name": f["name"], "coin": coin, "tf": tf}
        if tf not in frames:
            try:
                frames[tf] = _old_candles(f"{coin}_USDT", tf, old0, learn0)
            except Exception as exc:                           # noqa: BLE001
                # a failed READ is not "no candles": named, never a verdict
                frames[tf] = f"{type(exc).__name__}: {exc}"
        df = frames[tf]
        if isinstance(df, str):
            out.append({**rec, "status": "error", "why": df})
            continue
        if df is None or not len(df):
            # the venue has nothing that old: listed after the old window
            # (AALSTOCK's first hour is Jun 18, 2026)
            out.append({**rec, "status": "too young to test", "old_days": 0.0})
            continue
        old = df[(df["Date"] >= old0) & (df["Date"] < learn0)]
        pre = df[df["Date"] < old0].tail(WARM)
        span = ((old["Date"].iloc[-1] - old["Date"].iloc[0]).total_seconds() / 86_400
                if len(old) > 1 else 0.0)
        if len(pre) < WARM or span < 0.9 * OLD_DAYS:
            out.append({**rec, "status": "too young to test",
                        "old_days": round(span, 1)})
            continue
        if fund_ok is not True:
            # funding unread is not zero funding (CLAUDE.md rule 12's shape)
            out.append({**rec, "status": "funding unreadable", "why": fund_ok})
            continue
        frame = pd.concat([pre, old]).reset_index(drop=True)
        o = frame["Open"].astype(float).to_numpy()
        h = frame["High"].astype(float).to_numpy()
        lo = frame["Low"].astype(float).to_numpy()
        c = frame["Close"].astype(float).to_numpy()
        v = (frame["Volume"].astype(float).to_numpy() if "Volume" in frame
             else None)
        ts = frame["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
        rt = _cost(f)
        key = f"{f['name']}__old"
        try:
            dirs = sl.dirs_for(f, o, h, lo, c, v, ts, funding=fund)
            iv, bs, _ = br.TFS[tf]
            at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs,
                                      "tp": f["tp"], "sl": f["sl"], "threshold": .003}
            r = at.backtest_strategy(key, frame, 5.0, fee=FEE, sizing="flat",
                                     slippage=max(0.0, rt / 2 - FEE), dirs=list(dirs),
                                     tp=f["tp"], sl=f["sl"], funding=fund,
                                     keep_log=False, start_at=WARM)
        except Exception as exc:                               # noqa: BLE001
            out.append({**rec, "status": "error",
                        "why": f"{type(exc).__name__}: {exc}"})
            continue
        finally:
            at.STRATEGY_SPECS.pop(key, None)
        n, w = int(r["trades"]), int(r["wins"])
        wr = round(100.0 * w / n, 2) if n else None
        be = float(f["learned"]["breakeven_winrate"])
        need = msw.min_trades(tf, OLD_DAYS)
        why = []
        if n < need:
            why.append(f"{n} trades, needs {need}")
        if wr is None or wr <= be:
            why.append(f"win rate {wr}% not above its break-even {be}%")
        if float(r["profit"]) <= 0:
            why.append(f"lost ${-float(r['profit']):.2f}")
        out.append({**rec, "status": "passed" if not why else "failed",
                    "trades": n, "wins": w, "losses": int(r["losses"]),
                    "winrate": wr, "breakeven_winrate": be,
                    "profit": round(float(r["profit"]), 2),
                    "min_trades": need, "why": "; ".join(why)})
    return out


def verify(learned_file: Path | None = None, *, workers: int = 6,
           run_end_ms: int = RUN_END_MS,
           log=print) -> dict:
    from tradingagents import signals_learned as sl
    from tradingagents.positions_view import fmt_when

    src = Path(learned_file or sl.LEARNED_FILE)
    raw = json.loads(src.read_text(encoding="utf-8"))
    formulas = raw.get("formulas") or {}
    # the run's own end: the newest learn/grade the file can vouch for is the
    # collect stamp's day; the learner measured back from its own "now"
    by_coin: dict = {}
    for f in formulas.values():
        by_coin.setdefault(f["coin"], []).append(f)
    res: dict = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_coin_job, c, fs, run_end_ms): c for c, fs in by_coin.items()}
        for i, fu in enumerate(as_completed(futs), 1):
            coin = futs[fu]
            try:
                for rec in fu.result():
                    res[rec["name"]] = rec
            except Exception as exc:                           # noqa: BLE001
                for f in by_coin[coin]:
                    res[f["name"]] = {"name": f["name"], "coin": coin, "tf": f["tf"],
                                      "status": "error",
                                      "why": f"{type(exc).__name__}: {exc}"}
            if i % 25 == 0 or i == len(futs):
                log(f"{i} of {len(futs)} coins, {time.time() - t0:.0f}s")
    counts: dict = {}
    for r in res.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    day = 86_400
    doc = {
        "about": "Sep 25 Strat formulas measured on the 90 days BEFORE the "
                 "learner's window — candles that took no part in learning or "
                 "choosing (tradingagents/learn_verify.py)",
        "run": raw.get("run"), "checked": fmt_when(time.time()),
        "old_from": fmt_when(run_end_ms / 1000 - (WINDOW_DAYS + OLD_DAYS) * day),
        "old_to": fmt_when(run_end_ms / 1000 - WINDOW_DAYS * day),
        "rule": "at least min_trades(tf, 90) trades, win rate above its own "
                "break-even, and a profit after fee + slippage + funding",
        "counts": counts, "formulas": dict(sorted(res.items()))}
    VERIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VERIFIED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=0), encoding="utf-8")
    tmp.replace(VERIFIED_FILE)
    log(f"done: {counts}")
    return doc


def passed_names() -> set:
    """The formulas that passed the old-data test — empty if never run."""
    try:
        raw = json.loads(VERIFIED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {n for n, r in (raw.get("formulas") or {}).items()
            if r.get("status") == "passed"}


if __name__ == "__main__":
    import calendar
    import sys

    # the day the learner measured back from, UTC: a later run passes its own
    # (`python -m tradingagents.learn_verify 2026-09-28`)
    end = (calendar.timegm(time.strptime(sys.argv[1], "%Y-%m-%d")) * 1000
           if len(sys.argv) > 1 else RUN_END_MS)
    verify(run_end_ms=end)
