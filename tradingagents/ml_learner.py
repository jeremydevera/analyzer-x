"""THE SEP 27 ML LEARNER — decision trees per coin and timeframe.

The operator, Sep 27, 2026: "instead of using confluence, can you review past
30 days and create best strategy for each coin and each timeframe use machine
learning on what's best strategy i want tp higher than sl". Chosen with them:
learn from the 6 months before the last 30 days, test on those 30; trees.

For ONE coin and timeframe (the Sep 25 loop's split, and for its reason — a
number used to pick a winner cannot be the evidence it won):

    TRAIN (to 150 days; 1d to 690) | VALIDATE (30 days) | UNSEEN (last 30)

1. CLUES at every candle (ml_features), price only — no existing signal.
2. For each TP > SL pair in the search subset and each side: a LABEL per
   TRAIN candle — did an entry at the next open reach TP before SL (the stop
   when both touch in one bar, the engine's rule)? A label still unresolved
   when TRAIN ends is dropped, so nothing from VALIDATE leaks back (purge).
3. FIT one tree model per side (ml_trees) on TRAIN.
4. CANDIDATES: pair x confidence (the model's own top 2/5/10/20% of TRAIN
   scores) x sides (both / long / short), pre-scored on VALIDATE by the fast
   walk; the best GRADE_TOP go through the real engine on VALIDATE with the
   Sep 25 floors: enough trades, win rate above the pair's own break-even,
   profit > 0 — and the win rate's lower confidence bound (Wilson, 90%
   shared across the 12 validate tries) above that break-even too, so the
   best of many tries on one month cannot pass by luck (on a pure random walk
   the plain floors kept 3 formulas a seed).
5. KEEP up to KEEP with different trades — judged on VALIDATE (the
   directions over it and its outcome) — then GRADE each kept one on UNSEEN,
   minute-exact, on the stored row's own cut. That grade is stored and shown
   as it is and never keeps, drops or ranks anything.
No nested-window check: TRAIN predictions are in-sample.
"""
from __future__ import annotations

import hashlib
import math
import statistics
import time

import numpy as np

from tradingagents import formula_learner as fl
from tradingagents import ml_features as mf
from tradingagents import ml_trees as mt
from tradingagents import positions_view as pv
from tradingagents import signals_ml as sml

UNSEEN_DAYS = fl.UNSEEN_DAYS
VALIDATE_DAYS = fl.VALIDATE_DAYS
LEARN_DAYS = {"15m": 180, "30m": 180, "1h": 180, "4h": 180, "1d": 720}
MIN_TRAIN_ROWS = 400
MIN_TRAIN_DAYS = 30
QUANTILES = (0.98, 0.95, 0.90, 0.80)
SIDES = ("both", "long", "short")
GRADE_TOP = 12
KEEP = 3
# 90% confidence SHARED across the GRADE_TOP validate tries (one-sided,
# 0.10 / 12 per try): the best of 12 on one month must clear break-even by
# more than luck would give any one of them. 1.645 alone (90% for a single
# try) still kept a 7-of-10 formula on two of three pure random walks.
WILSON_Z = statistics.NormalDist().inv_cdf(1 - 0.10 / GRADE_TOP)   # ~2.394


def wilson_lower(wins: int, n: int, z: float = WILSON_Z) -> float:
    """The Wilson score lower bound of a win rate, in percent: how low the
    true rate can plausibly be after `wins` of `n`. 0 when there are no trades."""
    if n <= 0:
        return 0.0
    p = wins / n
    z2 = z * z
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return 100.0 * (centre - margin) / (1 + z2 / n)


def labels(o, h, lo, a: int, b: int, tp: float, sl: float, side: int) -> np.ndarray:
    """1.0 where an entry at o[i+1] reaches TP first, 0.0 where SL comes first
    (or both in one bar), NaN where neither happens before bar b."""
    n = len(o)
    y = np.full(n, np.nan)
    for i in range(a, min(b, n) - 1):
        e = o[i + 1]
        tp_px = e * (1 + side * tp)
        sl_px = e * (1 - side * sl)
        j0, span = i + 1, 32
        while j0 < b:
            j1 = min(b, j0 + span)
            if side > 0:
                hs = np.flatnonzero(lo[j0:j1] <= sl_px)
                ht = np.flatnonzero(h[j0:j1] >= tp_px)
            else:
                hs = np.flatnonzero(h[j0:j1] >= sl_px)
                ht = np.flatnonzero(lo[j0:j1] <= tp_px)
            js = hs[0] if len(hs) else None
            jt = ht[0] if len(ht) else None
            if js is not None and (jt is None or js <= jt):
                y[i] = 0.0
                break
            if jt is not None:
                y[i] = 1.0
                break
            j0, span = j1, span * 4
    return y


class MLLearner:
    WARM = fl.WARM_BARS

    def __init__(self, frame: fl.Frame, *, now_ms: int | None = None, log=None):
        from tradingagents import backtest_report as br, market_sweep as msw

        self.log = log or (lambda m: None)
        self.tf = frame.tf
        learn_days = LEARN_DAYS.get(self.tf, 180)
        o, h, lo, c, v, ts = frame.arrays()
        end_ms = int(ts[-1]) if len(ts) else 0
        cut_ms = (now_ms or end_ms) - UNSEEN_DAYS * 86_400_000
        a = max(0, int(np.searchsorted(ts, cut_ms - (learn_days + VALIDATE_DAYS)
                                       * 86_400_000, side="left")) - self.WARM)
        if a:
            frame = fl.Frame(**{**frame.__dict__,
                                "df": frame.df.iloc[a:].reset_index(drop=True)})
            o, h, lo, c, v, ts = frame.arrays()
        self.f = frame
        self.o, self.h, self.lo, self.c, self.v, self.ts = o, h, lo, c, v, ts
        self.n = len(c)
        self.u0 = int(np.searchsorted(ts, cut_ms, side="left"))
        self.v0 = min(self.u0, int(np.searchsorted(
            ts, cut_ms - VALIDATE_DAYS * 86_400_000, side="left")))
        # training may start as soon as every clue has its window (the
        # stored cut still carries WARM bars of lead-in)
        self.l0 = max(mf.MAX_WINDOW, int(np.searchsorted(
            ts, cut_ms - (learn_days + VALIDATE_DAYS) * 86_400_000, side="left")))
        self.rt = br.round_trip_cost(frame.fee, {"slippage": frame.slip})
        self.pairs = fl.barrier_pairs(self.tf, frame.fee, frame.slip, frame.liq)
        self.search = fl._search_subset(self.pairs)
        self.min_validate = msw.min_trades(self.tf, VALIDATE_DAYS)
        self.min_unseen = msw.min_trades(self.tf, UNSEEN_DAYS)
        self.train_days = (float(ts[self.v0 - 1] - ts[self.l0]) / 86_400_000
                           if self.v0 - 1 > self.l0 else 0.0)
        self.skipped = {"too few rows": 0, "one outcome only": 0}
        self.most_rows = 0
        u = self.u0
        # WHAT THE CHOOSING CODE MAY READ: the bars before UNSEEN, nothing else
        self.sel = (o[:u], h[:u], lo[:u], c[:u], v[:u], ts[:u])
        self.X = mf.features(*self.sel, frame.funding, self.tf)
        self.ok = np.isfinite(self.X).all(axis=1)
        self.sim = fl.Sim(*self.sel[:4])

    # ----------------------------------------------------------- pieces
    def _frame_desc(self) -> str:
        """Names the frame a "not enough history" answer is about — a short
        fetch (Sep 28, 2026: DOGE/TIA 15m on GitHub, candles that never
        reached before the last 30 days) must be visible in the words, not
        just a crash. No bar means no first-candle time to print."""
        if not self.n:
            return f"the {self.tf} frame holds 0 bars"
        first = pv.fmt_when(float(self.ts[0]) / 1000.0)
        return f"the {self.tf} frame holds {self.n:,} bars from {first}"

    def missing_clues(self) -> list[str]:
        """The clues that are NaN on every TRAIN row (none when TRAIN is empty)."""
        train = self.X[self.l0:max(self.l0, self.v0 - 1)]
        if not len(train):
            return []
        return [mf.FEATURES[j] for j in range(train.shape[1])
                if np.isnan(train[:, j]).all()]

    def _fit_side(self, y: np.ndarray):
        """A model on the TRAIN rows with a clue set and a resolved label, or
        None when there are too few or only one kind of outcome."""
        idx = np.arange(len(y))
        rows = idx[(idx >= self.l0) & (idx < self.v0 - 1)]
        rows = rows[self.ok[rows] & np.isfinite(y[rows])] if len(rows) else rows
        self.most_rows = max(self.most_rows, int(len(rows)))
        if len(rows) < MIN_TRAIN_ROWS:
            self.skipped["too few rows"] += 1
            return None
        if len(np.unique(y[rows])) < 2:
            self.skipped["one outcome only"] += 1
            return None
        m = mt.fit(self.X[rows], y[rows])
        p = np.full(len(self.X), np.nan)
        p[self.ok] = mt.predict(m, self.X[self.ok])
        return m, p, p[rows]

    def _validate(self, d: np.ndarray, s: float, t: float) -> dict | None:
        w0 = max(0, self.v0 - self.WARM)
        sub = self.f.df.iloc[w0:self.u0].reset_index(drop=True)
        return fl.engine_run(self.f, self.tf, sub, [int(x) for x in d[w0:self.u0]],
                             s, t, self.v0 - w0, None, self.log, key_prefix="ml")

    def _value(self, g: dict | None, s: float, t: float) -> float:
        if not g or g["trades"] < self.min_validate:
            return float("-inf")
        be = fl.breakeven_winrate(t, s, self.rt)
        if 100.0 * g["wins"] / g["trades"] <= be:
            return float("-inf")
        # NOT BY LUCK: the best of many tries on one month clears a plain
        # "above break-even" on noise; its lower bound must clear it too
        if wilson_lower(g["wins"], g["trades"]) <= be:
            return float("-inf")
        return g["profit"] if g["profit"] > 0 else float("-inf")

    def _cut_dirs(self, spec: dict) -> list:
        """Directions on the stored row's own cut (UNSEEN + WARM bars) — the
        call the GitHub row measurement makes."""
        w0 = max(0, self.u0 - self.WARM)
        o, h, lo, c, v, ts = self.o, self.h, self.lo, self.c, self.v, self.ts
        return sml.dirs_for(spec, o[w0:], h[w0:], lo[w0:], c[w0:], v[w0:], ts[w0:],
                            self.f.funding)

    def _grade(self, spec: dict) -> dict | None:
        w0 = max(0, self.u0 - self.WARM)
        sub = self.f.df.iloc[w0:].reset_index(drop=True)
        return fl.engine_run(self.f, self.tf, sub, self._cut_dirs(spec), spec["sl"],
                             spec["tp"], self.u0 - w0, self.f.fine, self.log,
                             key_prefix="ml")

    # -------------------------------------------------------------- run
    def run(self) -> dict:
        t0 = time.time()
        frame_desc = self._frame_desc()
        rep = {"coin": self.f.coin, "tf": self.tf, "bars": self.n,
               "train_days": round(self.train_days, 1),
               "validate_days": VALIDATE_DAYS, "unseen_days": UNSEEN_DAYS,
               "min_validate_trades": self.min_validate,
               "min_unseen_trades": self.min_unseen, "pairs": len(self.pairs),
               "first_bar": frame_desc}
        if not self.pairs:
            return {**rep, "formulas": [], "why": "no TP > SL pair clears the cost gate"}
        if (self.u0 >= self.n - 2 or self.v0 >= self.u0 - 2
                or self.train_days < MIN_TRAIN_DAYS):
            return {**rep, "formulas": [],
                    "why": (f"not enough history: {self.train_days:.0f} day(s) to "
                            f"learn from, and the trees need {MIN_TRAIN_DAYS} "
                            f"({frame_desc})")}
        # A CLUE MISSING ON EVERY TRAINING CANDLE is named, never reported as
        # "not enough history" (Sep 28, 2026 review). Dropping the column is
        # not allowed — the model must read the same columns live — so the
        # pair keeps nothing and says which clue was missing.
        missing = self.missing_clues()
        if missing:
            return {**rep, "formulas": [], "missing_clues": missing,
                    "why": "; ".join(
                        f"the {name} clue is missing on every candle"
                        + (" (no volume on this contract?)"
                           if name == "vol_ratio_20" else "")
                        for name in missing)}
        notional = self.f.base * 20
        cands = []
        fitted = 0
        self.skipped = {"too few rows": 0, "one outcome only": 0}
        self.most_rows = 0
        for (s, t) in self.search:
            side_models = {}
            for side, sgn in (("long", 1), ("short", -1)):
                y = labels(self.sel[0], self.sel[1], self.sel[2], self.l0, self.v0,
                           t, s, sgn)
                got = self._fit_side(y)
                if got:
                    side_models[side] = got
                    fitted += 1
            for q in QUANTILES:
                thr = {sd: float(f"{float(np.quantile(m[2], q)):.6g}")
                       for sd, m in side_models.items()}
                for sides in SIDES:
                    need = ("long", "short") if sides == "both" else (sides,)
                    if not all(sd in side_models for sd in need):
                        continue
                    d = sml.compose({sd: side_models[sd][1] for sd in need},
                                    {sd: thr[sd] for sd in need}, sides)
                    outs = self.sim.run(d, self.v0, self.u0, t, s)
                    if len(outs) < self.min_validate:
                        continue
                    pre = float(notional * (outs.sum() - self.rt * len(outs)))
                    cands.append((pre, s, t, q, sides,
                                  {sd: side_models[sd][0] for sd in need},
                                  {sd: thr[sd] for sd in need}, d))
        cands.sort(key=lambda x: (-x[0], x[1], x[2], x[3], x[4]))
        graded = []
        for pre, s, t, q, sides, models, thr, d in cands[:GRADE_TOP]:
            g = self._validate(d, s, t)
            v = self._value(g, s, t)
            if v > float("-inf"):
                graded.append((v, s, t, q, sides, models, thr, g, d))
        graded.sort(key=lambda x: (-x[0], x[1], x[2], x[3], x[4]))
        # DIFFERENT TRADES, JUDGED ON VALIDATE: the directions over it and its
        # outcome. UNSEEN never keeps, drops or ranks anything — it is graded
        # only after a formula is already kept.
        kept, seen_b, seen_o = [], set(), set()
        grade_failed = 0
        for v, s, t, q, sides, models, thr, g, d in graded:
            if len(kept) >= KEEP:
                break
            b = hashlib.md5(np.asarray(d[self.v0:self.u0], np.int8).tobytes()).hexdigest()
            outcome = (g["trades"], g["wins"], round(g["profit"], 2))
            if b in seen_b or outcome in seen_o:
                continue
            seen_b.add(b)
            seen_o.add(outcome)
            name = f"{sml.PREFIX}{self.f.coin}_{self.tf}_{len(kept) + 1}"
            spec = {"name": name, "coin": self.f.coin, "tf": self.tf, "tp": t, "sl": s,
                    "sides": sides, "q": q, "thr": thr, "models": models,
                    "features": mf.VERSION}
            learned = {
                "validate": {**g, "winrate": round(100.0 * g["wins"] / g["trades"], 2),
                             "wilson_lower": round(wilson_lower(g["wins"], g["trades"]), 2)},
                "train": {"days": round(self.train_days, 1)},
                "breakeven_winrate": round(fl.breakeven_winrate(t, s, self.rt), 2),
                "cost_of_tp": round(self.rt / t * 100, 1),
                "describe": sml.describe(spec),
            }
            u = self._grade(spec)
            if u is None:
                grade_failed += 1
                learned["unseen"] = None
                learned["grade_error"] = "engine failed"
            else:
                learned["unseen"] = {
                    **u, "winrate": (round(100.0 * u["wins"] / u["trades"], 2)
                                     if u["trades"] else None),
                    "min_trades": self.min_unseen, "chose": False}
            spec["learned"] = learned
            kept.append(spec)
        rep.update(candidates=len(cands), fitted=fitted, skipped=dict(self.skipped),
                   grade_failed=grade_failed,
                   seconds=round(time.time() - t0, 1), formulas=kept)
        if not fitted:
            rep["why"] = (f"not enough history: {self.most_rows} labelled training "
                          f"candles, the trees need {MIN_TRAIN_ROWS}")
        elif not kept:
            rep["why"] = "nothing passed the validate-period checks"
        return rep


def learn_pair(frame: fl.Frame, **kw) -> dict:
    return MLLearner(frame, **kw).run()
