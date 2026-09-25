"""THE RESEARCH LOOP that finds each coin's own formulas ("Sep 25 Strat").

The operator, Sep 25, 2026: *"make sure the confluence is not limited to the
confluence list you mentioned, i need you to research and loop on whats the
best confluence for each coin per timeframe"*.

For ONE coin and timeframe:

1. SPLIT the frame. The UNSEEN period is the last `UNSEEN_DAYS` (30 — the
   Backtest v2 window, the only span with 1-minute candles under it, so the
   grade settles every exit minute by minute). The LEARN period is the
   `LEARN_DAYS` before it. Nothing is learned from the unseen period's
   candles; a change is kept only if it improves the unseen result.
2. INGREDIENTS: every signal in `backtest_report.SIGNALS`, plus the confirm
   filters in `signals_learned.FILTERS` (trend side, the slow average's
   direction, session hours, volatility band, volume spike, stretch).
3. ROUND 1: every signal alone, scored on the learn period at its best
   TP > SL pair; the best become the first candidates, together with the
   timeframe's SEED menu (the store's own market-wide winners) — a seed is a
   first guess, never a limit.
4. EVERY ROUND: refine the current best — add a confirm, drop one, swap the
   trigger, join two into a cascade, or let the leading signals vote —
   score the refinements on the learn period, GRADE the best on the unseen
   period with the real engine (minute-exact exits, fee + slippage +
   funding), and keep the round only if the unseen result improved.
5. STOP after `DRY_ROUNDS` rounds in a row with nothing better on the unseen
   period (or `MAX_ROUNDS`).
6. KEEP up to `KEEP` formulas that pass: TP strictly above SL, SL under 80% of
   the liquidation distance, profitable on the unseen period with at least
   `market_sweep.min_trades(tf, 30)` trades, a win rate above the break-even
   win rate of its own TP/SL and cost, and profitable in every nested window
   the history covers (last 3 months, 6 months, full) with enough trades in
   each. Nothing is forced through: a pair where nothing passes says so.

The learn-period scoring uses a fast bar walk with the same entry and exit
rules as the engine (signal at the close, entry at the next open, SL before
TP inside one bar) and the round-trip cost, without funding; every number
that is REPORTED comes from `auto_trader.backtest_strategy` itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field

import numpy as np

from tradingagents import signals_learned as sl_

UNSEEN_DAYS = 30
LEARN_DAYS = 180
# the least history the loop may learn from: as long as the unseen period,
# or the unseen period ends up choosing everything (KKRSTOCK on this PC had
# 1 day before its last 30 and still "learned" three formulas)
MIN_LEARN_DAYS = 30
WARM_BARS = 300               # market_sweep.CONTEXT_BARS: rules read this far back
MAX_ROUNDS = 8
DRY_ROUNDS = 2
KEEP = 3
TOP_TRIGGERS = 10             # signals the refinements may draw on
BEAM = 6                      # candidates carried from round to round
GRADE_PER_ROUND = 12          # refinements graded on the unseen period
SEARCH_PAIRS = 12             # TP/SL pairs tried per candidate on the learn period
STOP_LIQ_SHARE = 0.8          # SL under 80% of the liquidation distance
NESTED_DAYS = (90, 180)       # plus the full span

# The store's own market-wide winners per timeframe (coins out of 1,002 with
# a row at TP > SL, 20+ trades, 60%+ win and profit in Backtest v2, Sep 25,
# 2026). Round 1's first guesses — the loop is free to leave every one.
SEEDS = {
    "15m": ("cf_obretest", "doji", "ultosc", "crsi", "rsidiv", "macddiv"),
    "30m": ("vwaprev", "crsi", "zscore20", "macddiv", "orderblock"),
    "1h": ("vwaprev", "zscore20", "crsi", "fvg", "rsi2", "bb20", "ote"),
    "4h": ("ibs", "orb", "willr14", "killzone", "mom6"),
    "1d": (),
}


@dataclass
class Frame:
    """One coin+timeframe, everything the loop needs, already fetched."""
    coin: str
    tf: str
    df: object                        # pandas frame of the timeframe's own candles
    fee: float
    slip: float                       # backtest_report.charged_slippage
    liq: float | None                 # liquidation distance in percent
    funding: list = field(default_factory=list)
    fine: tuple | None = None         # (ms, high, low) 1-minute arrays
    base: float = 5.0

    def arrays(self):
        d = self.df
        o = np.asarray(d["Open"], dtype=float)
        h = np.asarray(d["High"], dtype=float)
        lo = np.asarray(d["Low"], dtype=float)
        c = np.asarray(d["Close"], dtype=float)
        v = (np.asarray(d["Volume"], dtype=float) if "Volume" in d.columns
             else np.zeros(len(c)))
        ts = d["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
        return o, h, lo, c, v, ts


def barrier_pairs(tf: str, fee: float, slip: float, liq: float | None) -> list:
    """Every (sl, tp) a learned formula may use: TP strictly greater than SL,
    the stop inside 80% of liquidation, and a cost the target can carry."""
    from tradingagents import backtest_report as br

    rt = br.round_trip_cost(fee, {"slippage": slip})
    out = []
    for s, t in br.pairs_for(tf):
        if t <= s:
            continue
        if liq is not None and s * 100 >= STOP_LIQ_SHARE * abs(liq):
            continue
        if rt / t >= br.GATE_BLOCK:
            continue
        out.append((s, t))
    return out


def breakeven_winrate(tp: float, sl: float, rt: float) -> float:
    """The win rate at which this TP/SL and cost make nothing: the cost is
    paid on wins AND losses (CLAUDE.md rule 11)."""
    win, loss = tp - rt, sl + rt
    return 100.0 * loss / (win + loss) if win > 0 else 100.0


def _search_subset(pairs: list) -> list:
    """Up to SEARCH_PAIRS pairs spread over the grid, favouring a target 1.2x
    to 3x the stop — the shapes TP > SL is for."""
    good = [p for p in pairs if 1.2 <= p[1] / p[0] <= 3.0] or pairs
    if len(good) <= SEARCH_PAIRS:
        return good
    step = len(good) / SEARCH_PAIRS
    return [good[int(i * step)] for i in range(SEARCH_PAIRS)]


class Sim:
    """The fast learn-period walk: the engine's entry/exit rules, the round
    trip cost, no funding. Directions in, per-trade fractions out."""

    def __init__(self, o, h, lo, c):
        self.o, self.h, self.lo, self.c = o, h, lo, c

    def run(self, d: np.ndarray, a: int, b: int, tp: float, sl: float) -> np.ndarray:
        o, h, lo, c = self.o, self.h, self.lo, self.c
        idx = np.flatnonzero(d[a:b - 1]) + a
        outs = []
        nxt = a
        for i in idx:
            if i < nxt:
                continue
            s = int(d[i])
            e = o[i + 1]
            tp_px = e * (1 + s * tp)
            sl_px = e * (1 - s * sl)
            j0 = i + 1
            exit_j, out = None, None
            span = 64
            while j0 < b:
                j1 = min(b, j0 + span)
                if s > 0:
                    hs = np.flatnonzero(lo[j0:j1] <= sl_px)
                    ht = np.flatnonzero(h[j0:j1] >= tp_px)
                else:
                    hs = np.flatnonzero(h[j0:j1] >= sl_px)
                    ht = np.flatnonzero(lo[j0:j1] <= tp_px)
                js = hs[0] if len(hs) else None
                jt = ht[0] if len(ht) else None
                if js is not None and (jt is None or js <= jt):
                    exit_j, out = j0 + js, -sl          # SL first inside a bar
                    break
                if jt is not None:
                    exit_j, out = j0 + jt, tp
                    break
                j0 = j1
                span *= 4
            if exit_j is None:
                exit_j, out = b - 1, s * (c[b - 1] / e - 1)
            outs.append(out)
            nxt = exit_j + 1
        return np.asarray(outs, dtype=float)


def size(spec: dict) -> int:
    """How many conditions a spec reads — the tie-breaker toward simple."""
    if spec.get("join") == "vote":
        vt = spec.get("vote") or {}
        return len(vt.get("sigs") or []) + len(vt.get("confirm") or [])
    return sum(1 + len(lg.get("confirm") or []) for lg in spec.get("legs") or [])


def is_confluence(spec: dict) -> bool:
    """A NEW formula: more than one ingredient. A signal alone is one of the
    existing 130 — a starting point for the loop, never a result of it."""
    if spec.get("join") in ("cascade", "vote"):
        return True
    legs = spec.get("legs") or []
    return bool(legs and legs[0].get("confirm"))


def _key(spec: dict) -> str:
    return json.dumps({k: spec[k] for k in ("join", "legs", "vote") if k in spec},
                      sort_keys=True)


def _filter_confirms() -> list:
    out = []
    F = sl_.FILTERS
    for n in F["trend"]["n"]:
        for side in F["trend"]["side"]:
            out.append({"k": "trend", "n": n, "side": side})
    for n in F["htf"]["n"]:
        for side in F["htf"]["side"]:
            out.append({"k": "htf", "n": n, "side": side})
    for h0 in F["session"]["h0"]:
        for ln in F["session"]["len"]:
            out.append({"k": "session", "h0": h0, "len": ln})
    for lo, hi in F["atr"]["band"]:
        out.append({"k": "atr", "lo": lo, "hi": hi})
    for x in F["volx"]["x"]:
        out.append({"k": "volx", "x": x})
    for x in F["stretch"]["x"]:
        out.append({"k": "stretch", "x": x})
    return out


class Learner:
    def __init__(self, frame: Frame, *, now_ms: int | None = None, log=None,
                 signals=None, max_rounds: int = MAX_ROUNDS):
        from tradingagents import backtest_report as br, market_sweep as msw

        self.f = frame
        self.tf = frame.tf
        self.log = log or (lambda m: None)
        self.max_rounds = max_rounds
        o, h, lo, c, v, ts = frame.arrays()
        end_ms = int(ts[-1]) if len(ts) else 0
        cut_ms = (now_ms or end_ms) - UNSEEN_DAYS * 86_400_000
        # ONLY THE SPAN THAT IS USED: the learn period, the unseen period and
        # WARM_BARS of lead-in. A 15m year is 36,632 bars and every signal
        # computed over all of it took BTC 15m 125 s for nothing.
        a = max(0, int(np.searchsorted(ts, cut_ms - LEARN_DAYS * 86_400_000,
                                       side="left")) - WARM_BARS)
        if a:
            self.f = frame = Frame(**{**frame.__dict__,
                                      "df": frame.df.iloc[a:].reset_index(drop=True)})
            o, h, lo, c, v, ts = frame.arrays()
        self.o, self.h, self.lo, self.c, self.v, self.ts = o, h, lo, c, v, ts
        n = len(self.c)
        self.u0 = int(np.searchsorted(self.ts, cut_ms, side="left"))
        self.l0 = max(WARM_BARS, int(np.searchsorted(
            self.ts, cut_ms - LEARN_DAYS * 86_400_000, side="left")))
        self.n = n
        self.rt = br.round_trip_cost(frame.fee, {"slippage": frame.slip})
        self.pairs = barrier_pairs(self.tf, frame.fee, frame.slip, frame.liq)
        self.search_pairs = _search_subset(self.pairs)
        self.min_unseen = msw.min_trades(self.tf, UNSEEN_DAYS)
        learn_days = max(1.0, (self.ts[self.u0 - 1] - self.ts[self.l0]) / 86_400_000) \
            if self.u0 - 1 > self.l0 else 0.0
        self.learn_days = learn_days
        self.min_learn = msw.min_trades(self.tf, learn_days) if learn_days else 10**9
        self.sim = Sim(self.o, self.h, self.lo, self.c)
        self.feats = sl_.Features(self.o, self.h, self.lo, self.c, self.v, self.ts, self.tf)
        self.signals = list(signals if signals is not None else br.SIGNALS)
        self.sig_dirs: dict = {}
        self.learn_cache: dict = {}
        self.grade_cache: dict = {}
        self.tried = 0
        self.rounds: list = []

    # ------------------------------------------------------------- scoring
    def _dirs(self, spec: dict) -> np.ndarray:
        for s in sl_.ingredients(spec):
            if s not in self.sig_dirs:
                self.sig_dirs[s] = sl_.ingredient_dirs(
                    s, self.tf, self.o, self.h, self.lo, self.c, self.v,
                    self.ts, self.f.funding)
        return sl_.compose(spec, self.sig_dirs, self.feats)

    def behaviour(self, spec: dict) -> str:
        """A fingerprint of the trades a spec would signal: its directions."""
        return hashlib.md5(self._dirs(spec).tobytes()).hexdigest()

    def _sub_dirs(self, spec: dict, w0: int) -> np.ndarray:
        """A spec's directions computed on the frame from bar `w0` on — the
        stored row's own cut — with its own ingredient and feature caches."""
        if getattr(self, "_sub_w0", None) != w0:
            self._sub_w0 = w0
            self._sub_sig: dict = {}
            self._sub_arr = (self.o[w0:], self.h[w0:], self.lo[w0:], self.c[w0:],
                             self.v[w0:], self.ts[w0:])
            self._sub_feats = sl_.Features(*self._sub_arr, self.tf)
        o, h, lo, c, v, ts = self._sub_arr
        for s in sl_.ingredients(spec):
            if s not in self._sub_sig:
                self._sub_sig[s] = sl_.ingredient_dirs(s, self.tf, o, h, lo, c, v,
                                                       ts, self.f.funding)
        return sl_.compose(spec, self._sub_sig, self._sub_feats)

    def learn_score(self, spec: dict, pairs=None) -> dict | None:
        """Best TP > SL pair on the LEARN period: total $ after costs."""
        # BY BEHAVIOUR, not by wording: two specs that take the same trades
        # are one formula (willr14 and stoch14 are the same line upside down,
        # so "willr14 + stoch14 agrees" changed nothing — found on BTC 1h)
        k = self.behaviour(spec) + ("|all" if pairs else "")
        if k in self.learn_cache:
            return self.learn_cache[k]
        self.tried += 1
        d = self._dirs(spec)
        notional = self.f.base * 20
        best = None
        for (s, t) in (pairs or self.search_pairs):
            outs = self.sim.run(d, self.l0, self.u0, t, s)
            if len(outs) < self.min_learn:
                continue
            pnl = float(notional * (outs.sum() - self.rt * len(outs)))
            wins = int((outs - self.rt > 0).sum())
            if best is None or pnl > best["pnl"]:
                best = {"pnl": pnl, "trades": len(outs), "wins": wins, "sl": s, "tp": t}
        self.learn_cache[k] = best
        return best

    def grade(self, spec: dict, s: float, t: float) -> dict | None:
        """The UNSEEN period through the real engine: minute-exact exits,
        fee + slippage + funding. What is reported is this."""
        import tradingagents.auto_trader as at

        k = f"{_key(spec)}|{s}|{t}"
        if k in self.grade_cache:
            return self.grade_cache[k]
        from tradingagents import backtest_report as br

        # THE SAME CUT THE STORED ROW WILL BE MEASURED ON: the unseen window
        # plus WARM_BARS of lead-in (sweep_shard.window), directions computed
        # on that cut alone. Averages computed over the whole history drift
        # from the same averages over 300 bars, so grading on the full frame
        # would report a number the saved row does not repeat.
        w0 = max(0, self.u0 - WARM_BARS)
        sub = self.f.df.iloc[w0:].reset_index(drop=True)
        d = [int(x) for x in self._sub_dirs(spec, w0)]
        iv, bs, _ = br.TFS[self.tf]
        key = f"lx_grade_{self.tf}"
        at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": t,
                                  "sl": s, "threshold": .003}
        try:
            r = at.backtest_strategy(key, sub, self.f.base, fee=self.f.fee,
                                     sizing="flat", slippage=self.f.slip, dirs=d,
                                     tp=t, sl=s, liq_move_pct=self.f.liq,
                                     funding=self.f.funding, keep_log=False,
                                     start_at=self.u0 - w0, fine=self.f.fine)
        except Exception as exc:                               # noqa: BLE001
            self.log(f"grade failed ({type(exc).__name__}: {exc})")
            r = None
        finally:
            at.STRATEGY_SPECS.pop(key, None)
        out = None
        if r is not None:
            out = {"profit": float(r["profit"]), "trades": int(r["trades"]),
                   "wins": int(r["wins"]), "losses": int(r["losses"]),
                   "streak": float(r.get("worst_streak", 0.0)),
                   "streak_len": int(r.get("worst_streak_len", 0))}
        self.grade_cache[k] = out
        return out

    def unseen_value(self, g: dict | None, s: float, t: float) -> float:
        """How good an unseen grade is: its profit, or minus infinity if it
        does not clear the floors (enough trades, above break-even)."""
        if not g or g["trades"] < self.min_unseen:
            return float("-inf")
        wr = 100.0 * g["wins"] / g["trades"]
        if wr <= breakeven_winrate(t, s, self.rt):
            return float("-inf")
        return g["profit"]

    # ---------------------------------------------------------- neighbours
    def _neighbours(self, spec: dict, top: list) -> list:
        out = []
        confirms_pool = _filter_confirms()
        confirms_pool += [{"k": "agree", "sig": s, "within": w} for s in top for w in (1, 3)]
        confirms_pool += [{"k": "veto", "sig": s} for s in top]
        join = spec.get("join", "and")
        if join in ("and", "cascade"):
            legs = spec["legs"]
            first = legs[0]
            # one confirm per (kind, signal): "stoch14 agrees" within 1 bar
            # and again within 3 bars is the same idea twice
            used = {(c.get("k"), c.get("sig")) if c.get("sig") else
                    json.dumps(c, sort_keys=True) for c in first.get("confirm", [])}
            for cf in confirms_pool:
                if ((cf.get("k"), cf.get("sig")) if cf.get("sig") else
                        json.dumps(cf, sort_keys=True)) in used:
                    continue
                if cf.get("sig") == first["trigger"]:
                    continue
                nl = {**first, "confirm": [*first.get("confirm", []), cf]}
                out.append({**spec, "legs": [nl, *legs[1:]]})
            for i in range(len(first.get("confirm", []))):
                cs = [c for j, c in enumerate(first["confirm"]) if j != i]
                out.append({**spec, "legs": [{**first, "confirm": cs}, *legs[1:]]})
            for s in top:
                if s != first["trigger"]:
                    out.append({**spec, "legs": [{**first, "trigger": s}, *legs[1:]]})
        else:
            vt = spec["vote"]
            for cf in confirms_pool:
                if cf.get("sig") in vt["sigs"]:
                    continue
                out.append({**spec, "vote": {**vt, "confirm": [*vt.get("confirm", []), cf]}})
        return out

    def _joins(self, beam: list, top: list) -> list:
        out = []
        firsts = [b for b in beam if b.get("join") in ("and", "cascade")]
        for i, a in enumerate(firsts):
            for b in firsts[i + 1:]:
                out.append({"join": "cascade", "legs": [a["legs"][0], b["legs"][0]]})
                out.append({"join": "cascade", "legs": [b["legs"][0], a["legs"][0]]})
        for m, need in ((3, 2), (4, 2), (5, 3)):
            if len(top) >= m:
                out.append({"join": "vote", "vote": {"sigs": top[:m], "need": need}})
        return out

    # --------------------------------------------------------------- loop
    def run(self) -> dict:
        t0 = time.time()
        rep = {"coin": self.f.coin, "tf": self.tf, "bars": self.n,
               "learn_days": round(self.learn_days, 1), "unseen_days": UNSEEN_DAYS,
               "min_unseen_trades": self.min_unseen, "min_learn_trades": self.min_learn,
               "pairs": len(self.pairs)}
        if not self.pairs:
            return {**rep, "formulas": [], "why": "no TP > SL pair clears the cost gate"}
        if self.u0 >= self.n - 2 or self.learn_days < MIN_LEARN_DAYS:
            return {**rep, "formulas": [],
                    "why": (f"not enough history: {self.learn_days:.0f} day(s) before "
                            f"the last {UNSEEN_DAYS}, and learning needs "
                            f"{MIN_LEARN_DAYS}")}
        # ROUND 1 — every signal alone, plus the seed menu
        singles = []
        for s in self.signals:
            spec = {"join": "and", "legs": [{"trigger": s, "confirm": []}]}
            sc = self.learn_score(spec)
            if sc:
                singles.append((sc["pnl"], s, spec, sc))
        singles.sort(key=lambda x: (-x[0], x[1]))
        top = [s for _p, s, _sp, _sc in singles[:TOP_TRIGGERS]]
        for s in SEEDS.get(self.tf, ()):
            if s in self.signals and s not in top:
                top.append(s)
        beam = [{"join": "and", "legs": [{"trigger": s, "confirm": []}]} for s in top[:BEAM]]
        graded: dict = {}

        def grade_all(specs):
            for sp in specs:
                sc = self.learn_score(sp)
                if not sc:
                    continue
                g = self.grade(sp, sc["sl"], sc["tp"])
                graded[_key(sp)] = (self.unseen_value(g, sc["sl"], sc["tp"]), sp, sc, g)

        grade_all(beam)

        def best_value():
            # progress is judged among COMBINATIONS only: a single signal is
            # an existing formula, so beating one is not what is being asked
            return max([v for v, sp, *_ in graded.values() if is_confluence(sp)]
                       or [float("-inf")])

        best = best_value()
        self.rounds.append({"round": 1, "tried": self.tried, "best_unseen": _num(best),
                            "leaders": top[:TOP_TRIGGERS]})
        dry = 0
        rnd = 1
        while rnd < self.max_rounds and dry < DRY_ROUNDS:
            rnd += 1
            cands = []
            for sp in beam:
                cands += self._neighbours(sp, top)
            cands += self._joins(beam, top)
            scored = []
            # a refinement that signals exactly what its parent did (or any
            # candidate already tried) is not a new idea and takes no slot
            seen = {self.behaviour(x[1]) for x in graded.values()}
            for sp in cands:
                k = self.behaviour(sp)
                if k in seen:
                    continue
                seen.add(k)
                sc = self.learn_score(sp)
                if sc:
                    scored.append((sc["pnl"], k, sp))
            scored.sort(key=lambda x: (-x[0], x[1]))
            grade_all([sp for _p, _k, sp in scored[:GRADE_PER_ROUND]])
            now_best = best_value()
            improved = now_best > best + 1e-9
            if improved:
                best, dry = now_best, 0
            else:
                dry += 1
            # the next round refines the best COMBINATIONS; while fewer than
            # BEAM exist, the best learn-scored refinements fill the beam so
            # the search keeps moving instead of re-expanding the singles
            ranked = sorted((x for x in graded.values() if is_confluence(x[1])),
                            key=lambda x: (-x[0], _key(x[1])))
            nxt = [sp for v, sp, *_ in ranked if v > float("-inf")][:BEAM]
            for _p, _k, sp in scored:
                if len(nxt) >= BEAM:
                    break
                if all(_key(sp) != _key(b) for b in nxt):
                    nxt.append(sp)
            beam = nxt or beam
            self.rounds.append({"round": rnd, "tried": self.tried,
                                "best_unseen": _num(best), "improved": improved})
        kept = self._keep(graded)
        rep.update(rounds=len(self.rounds), tried=self.tried, round_log=self.rounds,
                   seconds=round(time.time() - t0, 1), formulas=kept)
        if not kept:
            rep["why"] = "nothing passed the unseen-period and nested-window checks"
        return rep

    def _nested_ok(self, spec: dict, s: float, t: float) -> tuple[bool, dict]:
        from tradingagents import market_sweep as msw

        d = self._dirs(spec)
        notional = self.f.base * 20
        out = {}
        end = self.n
        spans = [(f"{nd}d", int(np.searchsorted(self.ts, int(self.ts[-1]) - nd * 86_400_000)), nd)
                 for nd in NESTED_DAYS]
        spans.append(("full", WARM_BARS, (self.ts[-1] - self.ts[WARM_BARS]) / 86_400_000))
        for name, a, days in spans:
            a = max(a, WARM_BARS)
            covered = (self.ts[-1] - self.ts[a]) / 86_400_000 >= 0.9 * days
            if name != "full" and not covered:
                out[name] = "not enough history"
                continue
            outs = self.sim.run(d, a, end, t, s)
            pnl = float(notional * (outs.sum() - self.rt * len(outs)))
            need = msw.min_trades(self.tf, days)
            out[name] = {"trades": len(outs), "pnl": round(pnl, 2)}
            if len(outs) < need or pnl <= 0:
                return False, out
        return True, out

    def _keep(self, graded: dict) -> list:
        # WHEN TWO ARE CLOSE, THE SIMPLER ONE: unseen profits within the same
        # whole dollar rank by how many conditions the formula reads
        def rank(x):
            v = x[0]
            whole = math.floor(v) if v != float("-inf") else -10**12
            return (-whole, size(x[1]), _key(x[1]))

        ranked = sorted((x for x in graded.values() if is_confluence(x[1])), key=rank)
        kept, triggers, kept_b, kept_o = [], set(), set(), set()
        for v, sp, sc, g in ranked:
            if v == float("-inf") or len(kept) >= KEEP:
                break
            # THE SAME TRADES WHERE IT IS STORED is the same formula. Two
            # specs that differed only in the learn period and signal alike in
            # the unseen window are one row set twice (GitHub run 36140580272:
            # lx_ETH_30m_1 and _2 were both 28 trades, 71.43%, +$43.41) — so
            # identity is judged on the stored row's own cut, and on the grade
            b = hashlib.md5(self._sub_dirs(sp, max(0, self.u0 - WARM_BARS))
                            .tobytes()).hexdigest()
            outcome = (g["trades"], g["wins"], round(g["profit"], 2))
            if b in kept_b or outcome in kept_o:
                continue                      # the same trades as one kept
            ok, nested = self._nested_ok(sp, sc["sl"], sc["tp"])
            if not ok:
                continue
            lead = (sp.get("legs") or [{}])[0].get("trigger") or "vote"
            if lead in triggers and len(ranked) > KEEP:
                continue                      # prefer different ideas
            triggers.add(lead)
            kept_b.add(b)
            kept_o.add(outcome)
            n = len(kept) + 1
            name = f"{sl_.PREFIX}{self.f.coin}_{self.tf}_{n}"
            kept.append({
                "name": name, "coin": self.f.coin, "tf": self.tf,
                **{k: sp[k] for k in ("join", "legs", "vote") if k in sp},
                "tp": sc["tp"], "sl": sc["sl"],
                "learned": {
                    "unseen": {**g, "winrate": round(100.0 * g["wins"] / g["trades"], 2)},
                    # money rounded, the barriers NOT: round(0.025, 2) is
                    # 0.03, which printed a 2.5% stop as the 3% target
                    "learn": {k: (round(x, 2) if k == "pnl" else x)
                              for k, x in sc.items()},
                    "nested": nested,
                    "breakeven_winrate": round(breakeven_winrate(sc["tp"], sc["sl"], self.rt), 2),
                    "cost_of_tp": round(self.rt / sc["tp"] * 100, 1),
                    "describe": sl_.describe(sp),
                },
            })
        return kept


def _num(x: float):
    return None if x == float("-inf") else round(x, 2)


def learn_pair(frame: Frame, **kw) -> dict:
    return Learner(frame, **kw).run()
