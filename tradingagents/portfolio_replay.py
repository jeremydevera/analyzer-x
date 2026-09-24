"""Replay EVERY deployed row together, through the runner's own gates.

The operator, `Sep 23, 2026`, after being shown that the same 80 rows read
**97.3%** in Backtest v2, **72.0%** on the demo book and **57.1%** live:
*"okay start fixing the bugs now and apply the recommendation you said, i want
forecast to be 10/10"*.

WHY A BACKTEST ROW CANNOT FORECAST AN ACCOUNT. Every stored row is measured
ALONE: every signal is taken, on a coin nothing else is holding, at a cost read
once when the pair was measured. The runner does none of that. On the
operator's own record (`Sep 04` → `Sep 23, 2026`, demo book) the runner refused
**18,450** signals and took **169** — 17,657 for cost against the target, 420
because the coin was already held, 373 for age or chase. Fifty-four rows on
FASTSTOCK were measured as fifty-four simultaneous positions the account can
never hold; the demo holds at most four.

AND THE COST IS NOT ONE NUMBER. The saved book reading on FASTSTOCK says a
round trip costs **0.16%**; the runner's gate, reading the live book at each
signal, saw a median of **2.49%** across 1,469 refusals and a floor of 0.181%,
and the 10 trades it did take paid **0.34%**. A thin book on a stock contract
is wide most of the day and tight for minutes, so the demo trades a small,
biased slice of the backtest's signals. A replay charging the saved 0.16% at
every signal cannot see that. So this one can read the ledger's own gate
readings (`book_readings`) — the venue's cost at the very moment each signal
fired — and use them wherever they exist.

So this walks the whole deployment forward in time as ONE account:

    for every closed bar, on every row, in STRATEGY_ORDER:
        the cost gate       the book's round trip against the target, the
                            ledger's reading at that minute when there is
                            one, the saved reading otherwise  (>= 50% refuses)
        the formula         on the closed bar, same code the runner calls
        one coin, N slices  max_slices per book; an opposite side is refused
        the entry           at the next bar's open, the engine's own convention
        the exit            minute by minute, first price touched wins; both in
                            one minute is the loss (`unclear`), as Backtest v2
        the cost            the round trip the gate measured, plus the funding
                            settlements inside the hold
        the stake           the book's own sizing — Martingale doubling when
                            the book has it switched on — and a FLAT twin

and hands back what the ACCOUNT would have done: trades, wins, losses, money,
the worst run, and every refusal by name — beside what the demo book actually
did over the same days (`demo_actual`), so the two can be read against each
other.

WHAT IT STILL DOES NOT MODEL, and says so in `assumptions`: the stale-bar and
chase guards (latency refusals — a replay acts at the instant of the close),
fills worse than the book (`fill_slippage`), the live capital ceiling (the
demo book has no wallet), and MEXC closing something by hand. Each is named
rather than silently assumed away.

Read-only. It opens candle, cost and ledger files and writes nothing.
"""
from __future__ import annotations

import bisect
import json
import re
import time
from collections import defaultdict
from pathlib import Path

import tradingagents.auto_trader as at
from tradingagents import local_history, market_sweep as msw, stores as _stores

# a same-bar tie between two rows breaks by STRATEGY_ORDER, as the runner's
# loop over `strategies` does
_ORDER = {k: i for i, k in enumerate(at.STRATEGY_ORDER)}
_TF = {"Min15": "15m", "Min30": "30m", "Min60": "1h", "Hour4": "4h",
       "Day1": "1d"}

# A READING COUNTS FOR A SIGNAL ONLY IF THE RUNNER'S OWN GATE WOULD HAVE
# USED IT: within `_GATE_TTL` (5 minutes) of the bar close. Older, and the
# book at that minute is unknown — the signal is refused as `book_unknown`,
# the way the runner refuses a book it cannot read (rule 12), never charged
# a guessed cost. Measured on the operator's record, Sep 15-22, 2026 — the
# practice book took 135 trades at 69.6% on the rows still switched on —
# against how old a reading may be (flat stake, unknown refused):
#     5 min   -> 124 trades  76.6%   +$6.41
#     15 min  -> 143         75.5%   +$7.64
#     60 min  -> 175         72.0%   -$12.16
#     3 days  -> 211         73.9%   +$6.57  (and 747 at 91.0% over Sep 04-22,
#                                            508 of them on coins whose first
#                                            reading was Sep 16)
# Five minutes is the only ceiling with a reason behind it, and from
# Sep 23, 2026 the runner writes every fresh read (`book_readings.jsonl`), so
# the share refused as unknown shrinks on its own.
READING_TOL_MS = at._GATE_TTL * 1000

_GATE_RE = re.compile(r"round-trip cost ([\d.]+)% vs take-profit")

# Until this second the demo book charged the exchange fee TWICE on every
# exit (`paper_round_trip`, RCA-2026-09-23-E), so a realised cost read off an
# older `exit` row is `2 * taker_fee` above what the gate measured. Rows
# stamped after it are right as written.
DEMO_FEE_TWICE_UNTIL_S = 1790096642      # Sep 23, 2026, the runner restarted on the fix

ASSUMPTIONS = (
    "the stale-bar and chase guards are not applied — a replay acts at the "
    "instant the bar closes, so nothing is ever too old or already moved",
    "fills land exactly at the next bar's open and exactly at the exit price; "
    "a real fill can be worse than the book (fill_slippage)",
    "the live capital ceiling is not applied — this replays the demo book, "
    "which has no wallet; a live account can also be refused for funds",
    "nobody closes a position by hand at MEXC — the only exits are the two "
    "prices and liquidation",
    "a signal with no recorded book reading within three days is refused as "
    "'book unknown', the way the runner refuses a book it cannot read — it is "
    "never charged a guessed cost; from Sep 23, 2026 every fresh read is "
    "recorded, so this refusal fades as the record grows",
)


def _frame_ms(df) -> list[int]:
    return [int(x) for x in
            df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")]


def _funding_curve(funding: list) -> tuple[list[int], list[float]]:
    """Settlement times and the cumulative rate, so the funding paid across a
    hold is one subtraction — the engine's own `_f_ms` / `_f_cum`."""
    fs = sorted((int(f["settle_ms"]), float(f["rate"])) for f in (funding or [])
                if f and f.get("settle_ms") is not None)
    ms, cum = [], [0.0]
    for t, r in fs:
        ms.append(t)
        cum.append(cum[-1] + r)
    return ms, cum


def _funding_per_day(funding: list) -> float:
    """The worse side's expected funding per day, for the gate — the shape of
    `auto_trader.funding_cost(side=0)`: whichever way the signal fires, one
    side pays, and a credit never pays for a spread."""
    fs = sorted((int(f["settle_ms"]), float(f["rate"])) for f in (funding or [])
                if f and f.get("settle_ms") is not None)
    if len(fs) < 2:
        return 0.0
    tail = fs[-30:]
    rates = [r for _, r in tail]
    gaps = [b[0] - a[0] for a, b in zip(tail, tail[1:], strict=False) if b[0] > a[0]]
    if not gaps:
        return 0.0
    cycle_s = sorted(gaps)[len(gaps) // 2] / 1000.0
    per_settle = abs(sum(rates) / len(rates))
    return per_settle * (86400.0 / cycle_s) if cycle_s else 0.0


def ledger_rows(path=None) -> list[dict]:
    """Every row of the trade record, oldest first. A torn line is skipped,
    never raised — the ledger is appended live while this reads it."""
    p = Path(path) if path else at.LEDGER_PATH
    out: list[dict] = []
    if not p.exists():
        return out
    with open(p, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def book_readings(rows: list[dict], *, dry: bool = True,
                  readings_path=None) -> dict:
    """`{symbol: (sorted ts_ms, round_trip_fraction)}` — every time the runner
    READ THE BOOK, from three places:

    * `book_readings.jsonl` — since `Sep 23, 2026` the gate writes every
      fresh read of a coin's book (`auto_trader._record_book_reading`), one
      line a second at most; this is the complete series going forward;
    * a `gate_blocked` row in the ledger carries the cost it refused, in its
      `why` ("round-trip cost 2.490% vs take-profit 0.40% = 623% of the
      target") — but only once an hour per pair;
    * an `enter`/`exit` pair carries the cost it PAID — the realised round
      trip is `move - pnl_est / notional`, stamped at `opened_at`.

    Refusals alone would read high (only wide books are written down); the
    fills put the tight moments back. Together they are the venue's own cost
    at the moments the replay needs it — the same signals, the same minutes.
    """
    by_sym: dict[str, list[tuple[int, float]]] = defaultdict(list)
    enters: dict[str, dict] = {}
    rp = Path(readings_path) if readings_path else at.BOOK_READINGS_PATH
    if rp.exists():
        with open(rp, encoding="utf-8") as fh:
            for ln in fh:
                try:
                    r = json.loads(ln)
                    by_sym[r["symbol"]].append((int(r["ts"]) * 1000,
                                                float(r["round_trip"])))
                except (ValueError, KeyError, TypeError):
                    continue
    for r in rows:
        if bool(r.get("dry_run")) != bool(dry):
            continue
        act = r.get("action")
        sym = r.get("symbol")
        if act == "gate_blocked":
            m = _GATE_RE.search(str(r.get("why") or ""))
            if m and sym and r.get("ts"):
                by_sym[sym].append((int(r["ts"]) * 1000, float(m.group(1)) / 100))
        elif act == "enter" and r.get("trade_id"):
            enters[r["trade_id"]] = r
        elif act == "exit" and r.get("why") in ("TP", "SL"):
            # a fill is a reading only for the days BEFORE the recorder: from
            # Sep 23, 2026 every fresh read is in `book_readings.jsonl`, and
            # a later fill's realised cost is net of the entry half-spread
            # (`paper_round_trip`), so it no longer equals the gate's number
            if int(r.get("ts") or 0) >= DEMO_FEE_TWICE_UNTIL_S:
                continue
            e = enters.get(r.get("trade_id"))
            if not e or not e.get("margin") or not r.get("entry"):
                continue
            side = 1 if r.get("side") == "LONG" else -1
            move = side * (float(r["exit"]) / float(r["entry"]) - 1)
            notional = float(e["margin"]) * float(e.get("leverage") or at.LEVERAGE)
            cost = move - float(r.get("pnl_est") or 0.0) / notional
            if int(r["ts"]) < DEMO_FEE_TWICE_UNTIL_S:
                cost -= 2 * at.FEE_FALLBACK
            when = int(e.get("opened_at") or e.get("ts") or r["ts"]) * 1000
            if cost > 0:
                by_sym[sym].append((when, cost))
    out = {}
    for sym, pts in by_sym.items():
        pts.sort()
        out[sym] = ([t for t, _ in pts], [c for _, c in pts])
    return out


def _reading_at(readings, t_ms: int):
    """The book reading nearest `t_ms` within READING_TOL_MS, else None."""
    if not readings:
        return None
    ts, cs = readings
    i = bisect.bisect_left(ts, t_ms)
    best = None
    for j in (i - 1, i):
        if 0 <= j < len(ts):
            d = abs(ts[j] - t_ms)
            if d <= READING_TOL_MS and (best is None or d < best[0]):
                best = (d, cs[j])
    return None if best is None else best[1]


def demo_actual(rows: list[dict], *, dry: bool = True, since_ms=None,
                until_ms=None, base: float | None = None) -> dict:
    """What the book ACTUALLY did over the window, from the trade record:
    entries, exits, wins, losses, money and every refusal by name."""
    lo = -1 if since_ms is None else since_ms / 1000
    hi = float("inf") if until_ms is None else until_ms / 1000
    refused = defaultdict(int)
    trades: list[dict] = []
    entries = 0
    for r in rows:
        if bool(r.get("dry_run")) != bool(dry):
            continue
        t = r.get("ts") or 0
        if not (lo <= t <= hi):
            continue
        act = r.get("action")
        if act == "enter":
            entries += 1
        elif act == "exit":
            trades.append(r)
        elif act in ("gate_blocked", "coin_busy", "blocked", "stale_skip",
                     "chase_skip", "capital_blocked", "size_capped"):
            refused[act] += 1
    wins = sum(1 for r in trades if float(r.get("pnl_est") or 0) > 0)
    pnl = round(sum(float(r.get("pnl_est") or 0) for r in trades), 2)
    # the same trades with the fee charged ONCE (an exit written before the
    # `paper_round_trip` fix paid it twice) and restated at a flat `base`
    # stake, so they can be read against a flat replay at today's margin
    enters = {r["trade_id"]: r for r in rows
              if r.get("action") == "enter" and r.get("trade_id")}
    base = float(base or 0) or None
    fee_once = 0.0
    at_base = 0.0
    for r in trades:
        e = enters.get(r.get("trade_id")) or {}
        margin = float(e.get("margin") or 0)
        lev = float(e.get("leverage") or at.LEVERAGE)
        p = float(r.get("pnl_est") or 0)
        if (margin and r.get("why") in ("TP", "SL")
                and int(r.get("ts") or 0) < DEMO_FEE_TWICE_UNTIL_S):
            p += 2 * at.FEE_FALLBACK * margin * lev
        fee_once += p
        if base and margin:
            at_base += p * base / margin
    per_row: dict[str, dict] = {}
    for r in trades:
        k = f"{r.get('strategy')}|{r.get('symbol')}"
        d = per_row.setdefault(k, {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0})
        d["trades"] += 1
        d["wins" if float(r.get("pnl_est") or 0) > 0 else "losses"] += 1
        d["pnl"] = round(d["pnl"] + float(r.get("pnl_est") or 0), 2)
    return {
        "entries": entries, "trades": len(trades), "wins": wins,
        "losses": len(trades) - wins,
        "win_rate": round(100 * wins / len(trades), 1) if trades else 0.0,
        "pnl": pnl, "pnl_fee_once": round(fee_once, 2),
        "pnl_at_base": (round(at_base, 2) if base else None),
        "base_margin": base,
        "refused": dict(refused), "rows": per_row,
        "first_ms": (int(min(r["ts"] for r in trades) * 1000) if trades else None),
        "last_ms": (int(max(r["ts"] for r in trades) * 1000) if trades else None),
    }


class _Coin:
    """Everything one contract's replay needs, loaded once."""

    def __init__(self, symbol: str, store) -> None:
        self.symbol = symbol
        self.why = ""
        self.frames: dict = {}
        m1 = msw.cached_candles(symbol, store.fine_tf or "1m",
                                candles_dir=store.candles)
        if m1 is None or len(m1) < 2:
            self.why = "no 1-minute candles in the v2 store"
            self.m1 = None
            return
        self.m1 = m1.sort_values("Date").reset_index(drop=True)
        self.min_ms = _frame_ms(self.m1)
        self.min_hi = [float(x) for x in self.m1["High"]]
        self.min_lo = [float(x) for x in self.m1["Low"]]
        costs = msw.load_costs(symbol, root=str(store.home)) or {}
        self.fee = float(costs.get("fee") or at.FEE_FALLBACK)
        self.slip = float(costs.get("slippage") or 0.0) or at.PAPER_SLIPPAGE
        self.liq = costs.get("liq")
        self.funding = costs.get("funding") or []
        self.f_ms, self.f_cum = _funding_curve(self.funding)
        self.fund_per_day = _funding_per_day(self.funding)
        self.cost_source = "saved" if costs else "default"

    def frame(self, tf: str):
        if tf not in self.frames:
            try:
                self.frames[tf] = msw.bars_from_1m(self.m1, tf)
            except ValueError as exc:
                self.frames[tf] = str(exc)
        return self.frames[tf]

    def funding_between(self, a_ms: int, b_ms: int) -> float:
        if not self.f_ms:
            return 0.0
        a = bisect.bisect_right(self.f_ms, a_ms)
        b = bisect.bisect_right(self.f_ms, b_ms)
        return self.f_cum[b] - self.f_cum[a]


def _settle(coin: _Coin, side: int, entry_ms: int, tp_px: float, sl_px: float,
            liq_px):
    """Walk the minutes from the entry minute forward. Returns
    (why, exit_ms, exit_px, unclear); why "END" when the data runs out."""
    i = bisect.bisect_left(coin.min_ms, entry_ms)
    hi, lo, ms = coin.min_hi, coin.min_lo, coin.min_ms
    n = len(ms)
    while i < n:
        h, lw = hi[i], lo[i]
        if side == 1:
            t_tp, t_sl = h >= tp_px, lw <= sl_px
            t_liq = liq_px is not None and lw <= liq_px
        else:
            t_tp, t_sl = lw <= tp_px, h >= sl_px
            t_liq = liq_px is not None and h >= liq_px
        if t_liq and not t_sl:
            return "LIQ", ms[i], liq_px, 0
        if t_sl and t_tp:
            return "SL", ms[i], sl_px, 1          # same minute: worst case
        if t_sl:
            return "SL", ms[i], sl_px, 0
        if t_tp:
            return "TP", ms[i], tp_px, 0
        i += 1
    return "END", ms[-1], None, 0


def replay(settings: dict | None = None, *, store=None, dry: bool = True,
           keys: set | None = None, since_ms: int | None = None,
           until_ms: int | None = None, from_deployed: bool = False,
           readings: dict | None = None, sizing: str = "book") -> dict:
    """The whole deployment, as one account, over every minute the v2 store
    holds — or over `since_ms`..`until_ms`, and from each row's own deploy
    date when `from_deployed` is set. `readings` is `book_readings(...)`;
    `sizing` is "book" (the book's own switch) or "flat". See the module
    docstring for what is and is not modelled."""
    t0 = time.time()
    settings = at.load_settings() if settings is None else settings
    store = store or _stores.V2
    readings = readings or {}
    coins_by_key = settings.get("strategy_coins") or {}
    cap_slices = at.max_slices(settings) if at.partial_on(settings, dry) else 1
    martingale = sizing == "book" and at.martingale_on(settings, dry)
    deployed = local_history.deployed_at() if from_deployed else {}

    refused = defaultdict(int)
    refused_rows: dict[str, str] = {}          # row -> why it never traded
    coins: dict[str, _Coin] = {}
    events: list[tuple] = []                   # (t_ms, order, key, sym, dir, i)
    rows_meta: dict[tuple, dict] = {}
    n_rows = 0
    twin_of_fp: dict[tuple, str] = {}         # fingerprint -> first row
    twins: dict[str, str] = {}                # later row -> the row it copies

    for key, syms in coins_by_key.items():
        spec = at.STRATEGY_SPECS.get(key) or {}
        tf = _TF.get(spec.get("interval"))
        if keys is not None and key not in keys:
            continue
        for sym in (syms or []):
            n_rows += 1
            row = f"{key}|{sym}"
            if not tf or not spec.get("tp") or not spec.get("sl"):
                refused_rows[row] = "no spec"
                continue
            c = coins.get(sym)
            if c is None:
                c = coins[sym] = _Coin(sym, store)
            if c.m1 is None:
                refused_rows[row] = c.why
                refused["no_candles"] += 1
                continue
            frame = c.frame(tf)
            if isinstance(frame, str):
                refused_rows[row] = frame
                refused["bad_minutes"] += 1
                continue
            if len(frame) < 3:
                refused_rows[row] = f"only {len(frame)} {tf} bars"
                refused["no_candles"] += 1
                continue
            bar_s = int(spec["bar_seconds"])
            # THE SAVED ROUND TRIP, the runner's rule: spread + fee + funding
            # for one bar's hold; used at a signal the record never read
            rt_saved = 2 * (c.fee + c.slip) + c.fund_per_day * (bar_s / 86400.0)
            start = since_ms or 0
            dep = deployed.get(row) if from_deployed else None
            if dep and dep.get("at"):
                start = max(start, int(dep["at"]) * 1000)
            rows_meta[(key, sym)] = {"tf": tf, "bar_s": bar_s, "rt": rt_saved,
                                     "coin": c, "start": start, "signals": 0,
                                     "cost_refused": 0, "why": defaultdict(int)}
            hi = [float(x) for x in frame["High"]]
            lo = [float(x) for x in frame["Low"]]
            cl = [float(x) for x in frame["Close"]]
            op = [float(x) for x in frame["Open"]]
            vol = ([float(x) for x in frame["Volume"]]
                   if "Volume" in frame.columns else None)
            ts = _frame_ms(frame)
            try:
                dirs = at._dirs_for_backtest(key, hi, lo, cl, opens=op,
                                             volume=vol, ts=ts,
                                             funding=c.funding)
            except Exception as exc:                           # noqa: BLE001
                refused_rows[row] = f"formula raised: {str(exc)[:60]}"
                refused["formula_error"] += 1
                continue
            rows_meta[(key, sym)].update({"ts": ts, "op": op})
            # A TWIN is a second row that can only ever place the same trade:
            # same coin, same bars, same win/lose prices, and a formula that
            # fired on exactly the same bars. `stoch14_*` and `willr14_*` are
            # one formula under two names — 48 of the operator's rows on
            # Sep 22, 2026 — so two rows on PSXSTOCK 15m took 45 identical
            # trades each. The account holds the second as a second slice;
            # the screen must not read it as a second opinion.
            fp = (sym, tf, float(spec["tp"]), float(spec["sl"]),
                  tuple(int(x) for x in dirs))
            if fp in twin_of_fp:
                twins[f"{key}|{sym}"] = twin_of_fp[fp]
            else:
                twin_of_fp[fp] = f"{key}|{sym}"
            for i, d in enumerate(dirs):
                if not d or i + 1 >= len(ts):
                    continue
                # the bar CLOSES at the next bar's open; that is when the
                # runner sees it and when the entry can happen
                t = ts[i + 1]
                if t < start or (until_ms is not None and t > until_ms):
                    continue
                events.append((t, _ORDER.get(key, 10 ** 6), key, sym, int(d), i))
                rows_meta[(key, sym)]["signals"] += 1

    events.sort()
    open_by_coin: dict[str, list[dict]] = defaultdict(list)
    step: dict[tuple, int] = defaultdict(int)  # losing run per row
    trades: list[dict] = []
    gate_source = {"record": 0, "saved": 0}
    refusal_log: list[tuple] = []              # (t_ms, key, sym, why)

    def _release(sym: str, now_ms: int) -> None:
        keep = []
        for pos in open_by_coin[sym]:
            if pos["exit_ms"] is not None and pos["exit_ms"] <= now_ms:
                trades.append(pos)
                k = (pos["key"], sym)
                step[k] = 0 if pos["pnl"] > 0 else step[k] + 1
            else:
                keep.append(pos)
        open_by_coin[sym] = keep

    for t_ms, _o, key, sym, d, i in events:
        _release(sym, t_ms)
        meta = rows_meta[(key, sym)]
        c: _Coin = meta["coin"]
        spec = at.STRATEGY_SPECS[key]
        # THE COST GATE: the venue's reading at this minute when the record
        # has one, else the saved reading; 50% of the target or more refuses
        rd = _reading_at(readings.get(sym), t_ms)
        if rd is None:
            # UNKNOWN IS NOT OK WHEN IT IS MONEY (rule 12): the runner refuses
            # a book it cannot read, and so does this. Charging the saved
            # snapshot here booked 1,350 extra "wins" over Sep 04-15, 2026 at
            # 0.22% on books the gate was reading at 0.6%-2.8%.
            refused["book_unknown"] += 1
            meta["cost_refused"] += 1
            meta["why"]["book unknown"] += 1
            refusal_log.append((t_ms, key, sym, "book_unknown"))
            continue
        rt, src = rd, "record"
        if rt / float(spec["tp"]) >= at.COST_RATIO_BLOCK:
            refused["cost_gate"] += 1
            meta["cost_refused"] += 1
            meta["why"]["cost"] += 1
            refusal_log.append((t_ms, key, sym, "cost_gate"))
            continue
        gate_source[src] += 1
        held = open_by_coin[sym]
        if held:
            if len(held) + 1 > cap_slices:
                refused["coin_busy"] += 1
                meta["why"]["coin busy"] += 1
                refusal_log.append((t_ms, key, sym, "coin_busy"))
                continue
            if any(p["side"] != d for p in held):
                refused["opposite_side"] += 1
                meta["why"]["opposite side"] += 1
                refusal_log.append((t_ms, key, sym, "opposite_side"))
                continue
        entry = meta["op"][i + 1]
        if not entry:
            refused["no_price"] += 1
            continue
        tp_px, sl_px = at._bracket(d, entry, float(spec["tp"]), float(spec["sl"]))
        liq_px = None
        if c.liq:
            lm = abs(float(c.liq)) / 100.0
            liq_px = entry * (1 - lm) if d == 1 else entry * (1 + lm)
        why, exit_ms, exit_px, unc = _settle(c, d, t_ms, tp_px, sl_px, liq_px)
        margin = (at.staked_margin(key, settings, step[(key, sym)], dry)
                  if martingale else at.margin_for(key, settings))
        notional = margin * at.LEVERAGE
        if why == "END":
            pnl = None
        elif why == "LIQ":
            pnl = -margin
        else:
            move = d * (exit_px / entry - 1)
            fund = -d * c.funding_between(t_ms, exit_ms)
            pnl = (move - rt + fund) * notional
        open_by_coin[sym].append({
            "key": key, "coin": sym.replace("_USDT", ""), "symbol": sym,
            "tf": meta["tf"], "side": d, "entry_ms": t_ms, "entry": entry,
            "tp": tp_px, "sl": sl_px, "exit_ms": exit_ms if why != "END" else None,
            "exit": exit_px, "why": why, "unclear": unc, "cost": round(rt, 6),
            "cost_source": src, "margin": margin,
            "pnl": (round(pnl, 4) if pnl is not None else None)})

    for sym in list(open_by_coin):
        _release(sym, 10 ** 18)
    end_left = [p for p in trades if p["why"] == "END"]
    closed = [p for p in trades if p["why"] != "END"]
    closed.sort(key=lambda p: p["exit_ms"])

    traded_rows = {(p["key"], p["symbol"]) for p in closed}
    for (key, sym), meta in rows_meta.items():
        if (key, sym) in traded_rows:
            continue
        if not meta["signals"]:
            refused_rows[f"{key}|{sym}"] = "no signal in the window"
            continue
        parts = ", ".join(f"{n} {why}" for why, n in
                          sorted(meta["why"].items(), key=lambda kv: -kv[1]))
        left = meta["signals"] - sum(meta["why"].values())
        tail = f", {left} still open at the end" if left > 0 else ""
        refused_rows[f"{key}|{sym}"] = (
            f"{meta['signals']} signals, refused: {parts}{tail}")

    wins = sum(1 for p in closed if p["pnl"] > 0)
    losses = len(closed) - wins
    pnl = round(sum(p["pnl"] for p in closed), 2)
    worst, run_n, cur, cur_n = 0.0, 0, 0.0, 0
    for p in closed:
        if p["pnl"] <= 0:
            cur += p["pnl"]
            cur_n += 1
            if cur < worst:
                worst, run_n = cur, cur_n
        else:
            cur, cur_n = 0.0, 0
    per_row: dict[str, dict] = {}
    for p in closed:
        spec = at.STRATEGY_SPECS[p["key"]]
        r = per_row.setdefault(f"{p['key']}|{p['symbol']}",
                               {"row": f"{p['key']}|{p['symbol']}",
                                "key": p["key"], "coin": p["coin"], "tf": p["tf"],
                                "tp": spec["tp"], "sl": spec["sl"],
                                "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
                                "unclear": 0, "worst_run": 0.0, "_cur": 0.0})
        r["trades"] += 1
        r["wins" if p["pnl"] > 0 else "losses"] += 1
        r["pnl"] = round(r["pnl"] + p["pnl"], 2)
        r["unclear"] += p["unclear"]
        r["_cur"] = r["_cur"] + p["pnl"] if p["pnl"] <= 0 else 0.0
        r["worst_run"] = round(min(r["worst_run"], r["_cur"]), 2)
    for r in per_row.values():
        r.pop("_cur", None)
        r["twin_of"] = twins.get(r["row"])
        r["win_rate"] = round(100 * r["wins"] / r["trades"], 1)
        meta = rows_meta.get((r["key"], r["coin"] + "_USDT")) or {}
        r["signals"] = meta.get("signals", 0)
        r["cost_refused"] = meta.get("cost_refused", 0)

    all_min = [c.min_ms for c in coins.values() if c.m1 is not None]
    first = min((m[0] for m in all_min), default=None)
    last = max((m[-1] for m in all_min), default=None)
    if since_ms is not None and first is not None:
        first = max(first, since_ms)
    if until_ms is not None and last is not None:
        last = min(last, until_ms)
    return {
        "book": "demo" if dry else "live",
        "sizing": ("martingale" if martingale else "flat"),
        "rows_deployed": n_rows,
        "rows_replayed": len(rows_meta),
        "rows_traded": len(per_row),
        "rows_refused": dict(refused_rows),
        "signals": len(events),
        "refused": dict(refused),
        "gate_source": gate_source,
        "taken": len(closed) + len(end_left),
        "trades": len(closed), "wins": wins, "losses": losses,
        "win_rate": round(100 * wins / len(closed), 1) if closed else 0.0,
        "pnl": pnl,
        "worst_run": {"pnl": round(worst, 2), "trades": run_n},
        "unclear": sum(p["unclear"] for p in closed),
        "still_open": len(end_left),
        "slices_per_coin": cap_slices,
        "leverage": at.LEVERAGE,
        "base_margin": float(settings.get("margin", 10.0)),
        "window": {"first_ms": first, "last_ms": last},
        "rows": sorted(per_row.values(), key=lambda r: -r["pnl"]),
        "twins": twins,
        "log": closed,
        "refusal_log": refusal_log,
        "assumptions": list(ASSUMPTIONS),
        "cost_sources": {s: sum(1 for c in coins.values()
                                if c.m1 is not None and c.cost_source == s)
                         for s in ("saved", "default")},
        "seconds": round(time.time() - t0, 1),
    }


def forecast(settings: dict | None = None, *, dry: bool = True,
             store=None, ledger=None) -> dict:
    """The one call the screen makes. Three replays and the record:

    * `account`   — every deployed row, the book's own sizing, from the first
                    day the venue's book was recorded to the last minute in
                    the store, charging each signal the book's own reading.
                    This is the forecast.
    * `flat`      — the same with a flat stake, so the sizing's share of the
                    money is visible.
    * `checked`   — the same replay cut to the days the demo book has actually
                    been trading, from each row's own deploy date, at a FLAT
                    base stake, beside `actual`, what the book did on those
                    days restated at the same flat stake. The gap between
                    those two is how far this forecast can be trusted.
    """
    settings = at.load_settings() if settings is None else settings
    rows = ledger_rows(ledger) if ledger is not False else []
    rd = book_readings(rows, dry=dry)
    # the forecast runs over the days the venue's book is KNOWN — from the
    # first recorded reading — never over minutes nobody measured a cost for
    known = min((ts[0] for ts, _ in rd.values() if ts), default=None)
    account = replay(settings, store=store, dry=dry, readings=rd, since_ms=known)
    flat = replay(settings, store=store, dry=dry, readings=rd, sizing="flat",
                  since_ms=known)
    actual = demo_actual(rows, dry=dry, base=float(settings.get("margin", 10.0)))
    since = actual.get("first_ms")
    checked = None
    if since:
        # from the first real trade to the end of the minutes, each row from
        # the day it was switched on
        # FLAT on purpose: the record beside it is restated at a flat base
        # stake (`pnl_at_base`), so the two money figures share one label
        checked = replay(settings, store=store, dry=dry, readings=rd,
                         since_ms=since - 6 * 3600 * 1000, from_deployed=True,
                         sizing="flat")
        actual = demo_actual(rows, dry=dry, since_ms=since - 6 * 3600 * 1000,
                             base=float(settings.get("margin", 10.0)))
    _big = ("log", "refusal_log")
    slim = {k: v for k, v in account.items() if k not in _big}
    return {
        "account": slim,
        "flat": {k: flat[k] for k in ("trades", "wins", "losses", "win_rate",
                                       "pnl", "worst_run", "sizing")},
        "checked": ({k: v for k, v in checked.items() if k not in _big}
                    if checked else None),
        "actual": actual,
        "readings": {s: len(v[0]) for s, v in rd.items()},
        "log": account["log"],
    }
