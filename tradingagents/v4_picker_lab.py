"""The picker lab: twenty ways the daily picker could choose its rule sets, each walked forward
day by day over Backtest v4's stored trades, to see which makes the most money and which wins
most often.

Operator, Nov 12, 2026: *"Can you create mo picker rule? As of now this is your only criteria?
Could you give me 20 picker rule then do a backtest to see which of them is most profitable and
highest winrate / Because low winrate does not mean its not profitable"*.

WHAT A PICKER RULE IS. The live picker (`v4_picker`) gives each of the three skill rooms one
Forecast v4 rule set and swaps it when it stops passing. A picker rule is (1) the test a rule set
must pass to be picked, (2) the order the passing ones are taken in, and (3) when a room drops the
one it follows. `RULES` holds twenty of them; the first is the live picker's own test
(`v4_picker.judge`, called here, never copied).

NO LOOKING AHEAD. A pick for a day is made at that day's 12:00am UTC from the trades that had
CLOSED before it - the clock the daily chain itself picks on. What the rooms then make is every
trade their rule set's strategies OPENED that day, at its stored profit: Forecast v4's own
arithmetic, read through `forecast_v4._walk(visit=)`, so which trades a rule set takes is never
written a second time. A room that swaps keeps the trades it already opened (the follower finishes
them); a room with no passing rule set sits empty that day.

THE SAME DAYS FOR EVERY RULE. The walk starts where Forecast v4's does; the first pick is made
`LEAD_DAYS` later, so every picker rule has a month of rule-set history to judge on, and all
twenty trade the same days.

THE LUCK BARS, both printed beside every result:
* "random strategies" - the same number of trades on the same days, each worth the average trade
  every strategy of the same kind opened that day (Forecast v4's own bar);
* "random pickers" - `RANDOM_RUNS` pickers that give each room a rule set drawn blindly, redrawn
  every `RANDOM_HOLD` days, from two shelves (`SHELVES`): any rule set that is trading, and only
  the ones that made money over their last 30 days - the bar a picker rule's ORDER has to beat.

ONE FIRST PICK IS NOT A TEST. A rule that holds what it picked on day one is judged on one
decision, so every rule is also started afresh every `START_EVERY` days (`start_days`) and the
page prints how many of those starts made money.

NOT IN THE TEST, and said on the page: the live picker also drops a rule set whose room is losing
in practice (no practice record exists for the past); several strategies on one coin all count;
each room is its own account, so two rooms that follow overlapping rule sets both take the trade.

    python -m tradingagents.v4_picker_lab run      measure, write lab.json and the page
    python -m tradingagents.v4_picker_lab page     the page again from the last run

PRACTICE ONLY, AND NOTHING IS SWITCHED: this reads the store and writes its own folder
(`<v4 home>/picker-lab`). It never touches the live picker's file.
"""
from __future__ import annotations

import json
import pickle
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tradingagents import forecast_v4 as f4
from tradingagents import stores

DAY_S = 86_400
VERSION = 2               # 2: each row carries its day-by-day switch-ons (`follow`) and wins (`day_wins`)
SLOTS = 3                 # the three skill rooms
LEAD_DAYS = 31            # rule-set history before the first pick
RANDOM_RUNS = 200
RANDOM_HOLD = 7           # a random picker redraws its rule sets every 7 days
RANDOM_SEED = 20261112
# the shelves a random picker draws from: any rule set with 30+ trades closed in its last 30 days, and
# only those of them that made money over those days (the bar a picker rule's ORDER has to beat)
SHELVES = {"any": "n30 >= 30", "in_profit": "(n30 >= 30) & (p30 > 0)"}
START_EVERY = 7           # every rule is also started afresh every 7 days: one lucky first pick, or the rule?
START_MIN_DAYS = 14       # a start needs at least this many days left to say anything
BIG = 1e12                # a ratio with nothing to divide by (no losses yet) sorts as this


def home() -> Path:
    return Path(stores.V4.home) / "picker-lab"


def runs_dir() -> Path:
    return home() / "runs"


def kept_path(data_end_s: int) -> Path:
    """One kept run per UTC day of the store's last candle: `lab-2026-11-13.json`."""
    day = datetime.fromtimestamp(int(data_end_s), tz=timezone.utc).strftime("%Y-%m-%d")
    return runs_dir() / f"lab-{day}.json"


def previous(doc: dict) -> dict | None:
    """The newest kept run on an EARLIER store than `doc`'s - the same rules, another night's prices.
    The store is replaced every night, so a run cannot be made again later: the kept copy is the only
    way to see whether two nights agree (RCA-2026-11-12-B: they did not)."""
    best = None
    for f in sorted(runs_dir().glob("lab-*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if int(d["store"]["data_end_s"]) < int(doc["store"]["data_end_s"]) and (
                best is None or d["store"]["data_end_s"] > best["store"]["data_end_s"]):
            best = d
    return best


# ------------------------------------------------------------------ the twenty picker rules
def _rule(key, name, promote, demote, gate, rank, keep, hold=True, spread=False) -> dict:
    return {"key": key, "name": name, "promote": promote, "demote": demote, "gate": gate, "rank": rank,
            "keep": keep, "hold": hold, "spread": spread}


# gate / rank / keep are read over one day's figures for every rule set (`Stats`):
#   n30 w30 p30    trades, wins and dollars of the trades that CLOSED in its last 30 days (7, 14, 28 too;
#                  "A" = every day so far)
#   wr30 ppt30     win rate (percent) and dollars a trade        pf30   dollars won for every $1 lost
#   pay30          average win / average loss                    edge30 dollars a trade above the average
#   green30        share of its trading days that made money            strategy of its kind, same days
#   traded30       days with a closed trade                      calm30 dollars made / worst dip (at least $1)
#   wkmin          the worst of its last four weeks, dollars     tfi    its timeframe (-1 = any)
#   live3 liverank3   the live picker's own test and its worst whole month (live1: without the 3-month wait)
RULES = [
    _rule("live", "Today's picker",
          "100+ trades so far, beat random picks by more than luck, 3 or more whole months and every one "
          "in profit, profit in total, and the month so far not losing (once it has 20 trades). "
          "Best worst month first.",
          "Dropped the day it fails any of those.", "live3", "liverank3", "live3"),
    _rule("live_early", "Today's picker without the 3-month wait",
          "The same test, but one whole month in profit is enough to start.",
          "Dropped the day it fails any of those.", "live1", "liverank1", "live1"),
    _rule("money30", "Most money, last 30 days",
          "30+ trades closed in its last 30 days and they made money. Most money first.",
          "Dropped when its last 30 days stop making money.", "(n30 >= 30) & (p30 > 0)", "p30", "p30 > 0"),
    _rule("money14", "Most money, last 14 days",
          "20+ trades closed in its last 14 days and they made money. Most money first.",
          "Dropped when its last 14 days stop making money.", "(n14 >= 20) & (p14 > 0)", "p14", "p14 > 0"),
    _rule("money7", "Most money, last 7 days",
          "10+ trades closed in its last 7 days and they made money. Most money first.",
          "Dropped when its last 7 days stop making money.", "(n7 >= 10) & (p7 > 0)", "p7", "p7 > 0"),
    _rule("money_all", "Most money since the start",
          "100+ trades closed since the test began and they made money. Most money first.",
          "Dropped when its total turns negative.", "(nA >= 100) & (pA > 0)", "pA", "pA > 0"),
    _rule("per_trade30", "Most money a trade",
          "50+ trades closed in its last 30 days, in profit. Most dollars a trade first.",
          "Dropped when its last 30 days stop making money.", "(n30 >= 50) & (p30 > 0)", "ppt30", "p30 > 0"),
    _rule("pf30", "Wins biggest against losses",
          "50+ trades closed in its last 30 days, in profit. Most dollars won for every $1 lost first.",
          "Dropped when its wins no longer cover its losses.", "(n30 >= 50) & (p30 > 0)", "pf30", "pf30 >= 1"),
    _rule("pf15_money", "Wins $1.50 for every $1 lost, then most money",
          "50+ trades closed in its last 30 days that won at least $1.50 for every $1 lost. Most money first.",
          "Dropped when it wins less than $1.20 for every $1 lost.",
          "(n30 >= 50) & (pf30 >= 1.5)", "p30", "pf30 >= 1.2"),
    _rule("big_wins", "Big wins: average win 2x the average loss",
          "30+ trades closed in its last 30 days, in profit, its average win at least twice its average "
          "loss - any win rate. Most money first.",
          "Dropped when its last 30 days stop making money.",
          "(n30 >= 30) & (p30 > 0) & (pay30 >= 2)", "p30", "p30 > 0"),
    _rule("low_wr", "Wins under half its trades, still makes money",
          "30+ trades closed in its last 30 days, a win rate UNDER 50%, and in profit. Most money first.",
          "Dropped when its last 30 days stop making money.",
          "(n30 >= 30) & (p30 > 0) & (wr30 < 50)", "p30", "p30 > 0"),
    _rule("top_wr", "Highest win rate",
          "50+ trades closed in its last 30 days, in profit. Highest win rate first.",
          "Dropped when its last 30 days stop making money.", "(n30 >= 50) & (p30 > 0)", "wr30", "p30 > 0"),
    _rule("wr70_money", "Wins 70%+ and makes money",
          "30+ trades closed in its last 30 days, 70% or more won, in profit. Most money first.",
          "Dropped when it wins under 60% or its last 30 days stop making money.",
          "(n30 >= 30) & (p30 > 0) & (wr30 >= 70)", "p30", "(p30 > 0) & (wr30 >= 60)"),
    _rule("green_days", "Most days in profit",
          "Closed trades on 15+ of its last 30 days, in profit. The biggest share of winning days first.",
          "Dropped when its last 30 days stop making money.",
          "(traded30 >= 15) & (p30 > 0)", "green30", "p30 > 0"),
    _rule("smooth", "Smoothest: money against its worst dip",
          "30+ trades closed in its last 30 days, in profit. Most money for every $1 of its worst dip first.",
          "Dropped when its last 30 days stop making money.", "(n30 >= 30) & (p30 > 0)", "calm30", "p30 > 0"),
    _rule("four_weeks", "Four winning weeks in a row",
          "Each of its last four weeks made money (30+ trades closed in them). Best worst week first.",
          "Dropped when its last four weeks together stop making money.",
          "(wkmin > 0) & (n28 >= 30)", "wkmin", "p28 > 0"),
    _rule("beats_kind", "Beats its own kind by the most",
          "50+ trades closed in its last 30 days, in profit, and making more a trade than the average "
          "strategy of its kind. Biggest gap first.",
          "Dropped when it stops beating its kind or stops making money.",
          "(n30 >= 50) & (p30 > 0) & (edge30 > 0)", "edge30", "(p30 > 0) & (edge30 > 0)"),
    _rule("quick_exit", "Hot now, dropped fast",
          "30+ trades closed in its last 30 days, in profit, and its last 7 days in profit too. Most money first.",
          "Dropped the day its last 7 days lose money (once 5 trades closed in them) or its last 30 do.",
          "(n30 >= 30) & (p30 > 0) & (p7 > 0)", "p30", "((p7 >= 0) | (n7 < 5)) & (p30 > 0)"),
    _rule("top3_daily", "The top 3 every day, no holding",
          "Every day the rooms follow the three rule sets with the most money in their last 30 days "
          "(30+ trades closed, in profit).",
          "Nothing is held: a rule set is dropped the day it leaves the top three.",
          "(n30 >= 30) & (p30 > 0)", "p30", None, hold=False),
    _rule("spread", "One room on each of three timeframes",
          "30+ trades closed in its last 30 days, in profit, and built on one timeframe; no two rooms "
          "share a timeframe. Most money first.",
          "Dropped when its last 30 days stop making money.",
          "(n30 >= 30) & (p30 > 0) & (tfi >= 0)", "p30", "p30 > 0", spread=True),
]


def rule_id(spec: dict) -> str:
    """Hashed from the picker rule itself (CLAUDE.md kit H): change its test and its id changes."""
    from tradingagents import backtest_report as br

    return br._code(f"picker_lab|{spec['key']}|gate={spec['gate']}|rank={spec['rank']}|keep={spec['keep']}"
                    f"|hold={int(spec['hold'])}|spread={int(spec['spread'])}|slots={SLOTS}|lead={LEAD_DAYS}")


# ------------------------------------------------------------------ every rule set, day by day
def matrices(d: dict, end_s: int, log=print) -> dict:
    """Forecast v4's walk, with every rule set's trades added up two ways: by the day they OPENED (what
    a room following it makes that day) and by the first midnight after they CLOSED (what a picker
    knows that morning). Dollars are whole ten-thousandths, as the walk's money rules add them."""
    start = f4.walk_from(end_s)
    D = int((end_s - start) // DAY_S + 1)
    K = D + 1                                     # column k: known at the start of day k
    ms = f4.month_starts(start, end_s)
    Mn = len(ms)
    p4_all = np.rint(d["pnl"] * 10_000).astype(np.int64)
    kd_all = np.clip((d["ex"] - start) // DAY_S + 1, 0, D)
    names = ("o_n", "o_w", "o_p", "k_n", "k_w", "k_gw", "k_gl", "km_n", "km_p")
    cols: dict[str, list] = {k: [] for k in names}
    pool: dict[str, list] = {k: [] for k in ("o_n", "o_p", "k_n", "k_p", "km_n")}
    kinds: dict[tuple, int] = {}
    rules: list[dict] = []

    def count(x, n, w=None):
        b = np.bincount(x, weights=w, minlength=n)
        return np.rint(b).astype(np.int64) if w is not None else b.astype(np.int64)

    def visit(rule, m, sub, km):
        key = (rule["tf"], rule["skill"], rule["tp_rule"], float(rule["sl_cap"]), float(rule.get("cost_cap") or 0.0))
        if key not in kinds:
            kinds[key] = len(kinds)
            ii = np.flatnonzero(km)
            row = sub["row"][ii]
            p, kd = p4_all[row], kd_all[row]
            pool["o_n"].append(count(sub["day"][ii], D))
            pool["o_p"].append(count(sub["day"][ii], D, p))
            pool["k_n"].append(count(kd, K))
            pool["k_p"].append(count(kd, K, p))
            pool["km_n"].append(count(sub["month"][ii] * K + kd, Mn * K).reshape(Mn, K))
        ii = np.flatnonzero(m)
        row = sub["row"][ii]
        day = sub["day"][ii]
        p, kd = p4_all[row], kd_all[row]
        win = p > 0
        mk = sub["month"][ii] * K + kd
        got = {"o_n": count(day, D), "o_w": count(day[win], D), "o_p": count(day, D, p),
               "k_n": count(kd, K), "k_w": count(kd[win], K), "k_gw": count(kd[win], K, p[win]),
               "k_gl": count(kd[~win], K, -p[~win]),
               "km_n": count(mk, Mn * K).reshape(Mn, K), "km_p": count(mk, Mn * K, p).reshape(Mn, K)}
        # the lab reads what the forecast counted, or it stops: never a second answer
        if int(got["o_n"].sum()) != int(rule["trades"]) or abs(got["o_p"].sum() / 1e4 - rule["profit"]) > 0.001:
            raise RuntimeError(f"#{rule['id']}: the lab added up {int(got['o_n'].sum())} trades "
                               f"{got['o_p'].sum() / 1e4:+.4f}, Forecast v4 {rule['trades']} {rule['profit']:+.4f}")
        for k in names:
            cols[k].append(got[k])
        rules.append({"id": rule["id"], "words": rule["words"], "tf": rule["tf"], "skill": rule["skill"],
                      "tp_rule": rule["tp_rule"], "sl_cap": float(rule["sl_cap"]),
                      "cost_cap": float(rule.get("cost_cap") or 0.0), "window": rule["window"],
                      "min_win_rate": rule["min_win_rate"], "min_trades": rule["min_trades"],
                      "money": rule["money"], "kind": kinds[key]})

    walk = f4._walk(d, end_s, log, visit=visit)
    small = {"o_n", "o_w", "k_n", "k_w", "km_n"}
    out = {k: np.array(cols[k], dtype=np.int32 if k in small else np.int64) for k in names}
    out.update({f"pool_{k}": np.array(v, dtype=np.int64) for k, v in pool.items()})
    out.update({"rules": rules, "start": int(start), "end_s": int(end_s), "D": D, "ms": [int(x) for x in ms],
                "same_as": walk["same_as"], "walk": walk["walk"], "coverage": walk["coverage"]})
    return out


class Prepared:
    """The running totals a day's figures are read from, worked out once."""

    def __init__(self, M: dict):
        self.M = M
        self.R = len(M["rules"])
        self.D = int(M["D"])
        self.K = self.D + 1
        self.start = int(M["start"])
        # the days a picker can trade: when the store ends on the stroke of midnight, the walk's last
        # day has no time in it and is no pick day
        self.Dp = min(self.D, int((int(M["end_s"]) - 1 - self.start) // DAY_S + 1))
        self.ms = list(M["ms"])
        nxt = f4.month_starts(self.ms[-1], self.ms[-1] + 32 * DAY_S)[-1]
        self.month_end = self.ms[1:] + [nxt]
        self.C = {k: np.cumsum(M[k], axis=1, dtype=np.int64) for k in ("k_n", "k_w", "k_gw", "k_gl")}
        self.kp = M["k_gw"] - M["k_gl"]
        self.Cp = self.C["k_gw"] - self.C["k_gl"]
        self.CM_n = np.cumsum(M["km_n"], axis=2, dtype=np.int64)
        self.CM_p = np.cumsum(M["km_p"], axis=2, dtype=np.int64)
        self.kind = np.array([r["kind"] for r in M["rules"]], dtype=np.int64)
        self.CP_n = np.cumsum(M["pool_k_n"], axis=1, dtype=np.int64)
        self.CP_p = np.cumsum(M["pool_k_p"], axis=1, dtype=np.int64)
        self.CPM_n = np.cumsum(M["pool_km_n"], axis=2, dtype=np.int64)
        # the luck bar on the closing clock: each day's closed trades against the same number of
        # average trades of its kind that closed that day
        pavg = np.where(M["pool_k_n"] > 0, M["pool_k_p"] / np.maximum(M["pool_k_n"], 1), 0.0)
        rand = M["k_n"] * pavg[self.kind]
        traded = M["k_n"] > 0
        self.C_traded = np.cumsum(traded, axis=1, dtype=np.int64)
        self.C_beat = np.cumsum((self.kp > rand + 1e-5) & traded, axis=1, dtype=np.int64)
        self.C_rand = np.cumsum(rand, axis=1)
        # what a room following it makes: the forecast's own bar, by the day a trade opened
        self.pool_avg = np.where(M["pool_o_n"] > 0, M["pool_o_p"] / np.maximum(M["pool_o_n"], 1), 0.0)
        self.tfi = np.array([f4.TFS.index(r["tf"]) - 1 if r["tf"] else -1 for r in M["rules"]], dtype=np.int64)
        self.filters = np.array([bool(r["skill"]) + bool(r["tf"]) for r in M["rules"]], dtype=np.int64)
        ids = [r["id"] for r in M["rules"]]
        self.id_rank = np.argsort(np.argsort(np.array(ids)))
        self.ix = {i: n for n, i in enumerate(ids)}

    def index_of(self, rule_id: str) -> int | None:
        rid = rule_id if rule_id in self.ix else (self.M.get("same_as") or {}).get(rule_id)
        return self.ix.get(rid) if rid else None


class Stats:
    """Every rule set's figures at the start of walk day `g`, from trades that closed before it."""

    _INT = {"n": "k_n", "w": "k_w", "gw": "k_gw", "gl": "k_gl"}

    def __init__(self, P: Prepared, g: int):
        self.P, self.g, self.c = P, int(g), {}

    def __getitem__(self, key: str):
        if key not in self.c:
            self.c[key] = self._make(key)
        return self.c[key]

    def eval(self, expr: str):
        return eval(expr, {"__builtins__": {}}, self)        # names are looked up through __getitem__

    def _span(self, C, L):
        """The sum over the L known days ending at g (None = every day so far)."""
        hi = C[..., self.g]
        if L is None or self.g - L < 0:
            return hi.copy()
        return hi - C[..., self.g - L]

    def _make(self, key: str):
        P, g = self.P, self.g
        if key == "tfi":
            return P.tfi
        if key in ("live3", "liverank3"):
            self.c["live3"], self.c["liverank3"] = self._live(3)
            return self.c[key]
        if key in ("live1", "liverank1"):
            self.c["live1"], self.c["liverank1"] = self._live(1)
            return self.c[key]
        if key == "wkmin":
            weeks = [P.Cp[:, g - 7 * j] - P.Cp[:, g - 7 * (j + 1)] for j in range(4)]
            return np.min(weeks, axis=0) / 1e4
        name = key.rstrip("0123456789A")
        tail = key[len(name):]
        if not tail or name not in ("n", "w", "gw", "gl", "p", "wr", "ppt", "pf", "pay", "green", "traded",
                                    "dd", "calm", "edge"):
            raise KeyError(f"the picker lab has no figure called {key!r}")
        L = None if tail == "A" else int(tail)
        if name in self._INT:
            return self._span(P.C[self._INT[name]], L)
        n, w, gw, gl = (self[f"{x}{tail}"] for x in ("n", "w", "gw", "gl"))
        if name == "p":
            return (gw - gl) / 1e4
        if name == "wr":
            return np.where(n > 0, 100.0 * w / np.maximum(n, 1), 0.0)
        if name == "ppt":
            return np.where(n > 0, (gw - gl) / 1e4 / np.maximum(n, 1), 0.0)
        if name == "pf":
            return np.where(gl > 0, gw / np.maximum(gl, 1), np.where(gw > 0, BIG, 0.0))
        if name == "pay":
            lost = n - w
            both = (w > 0) & (lost > 0) & (gl > 0)
            return np.where(both, (gw / np.maximum(w, 1)) / (gl / np.maximum(lost, 1) + 1e-12),
                            np.where((w > 0) & (gl == 0), BIG, 0.0))
        if name == "edge":
            pn = self._span(P.CP_n, L)[P.kind]
            pp = self._span(P.CP_p, L)[P.kind]
            return self[f"ppt{tail}"] - np.where(pn > 0, pp / 1e4 / np.maximum(pn, 1), 0.0)
        lo = 0 if L is None else max(0, g - L + 1)
        day_p = P.kp[:, lo:g + 1]
        if name == "traded":
            return (P.M["k_n"][:, lo:g + 1] > 0).sum(axis=1)
        if name == "green":
            return (day_p > 0).sum(axis=1) / np.maximum(self[f"traded{tail}"], 1)
        cum = np.cumsum(day_p, axis=1)
        peak = np.maximum.accumulate(np.maximum(cum, 0), axis=1)
        dd = (peak - cum).max(axis=1) / 1e4
        if name == "dd":
            return dd
        return self[f"p{tail}"] / np.maximum(dd, 1.0)          # calm

    def _live(self, need: int):
        """The live picker's own test (`v4_picker.judge`) asked of each rule set's record as it stood
        this morning; `need` whole months before a rule set is not "thin" (the live picker: 3)."""
        from tradingagents import v4_picker as vp

        P, g = self.P, self.g
        now = P.start + g * DAY_S
        Mn = len(P.ms)
        complete = [P.month_end[i] <= now for i in range(Mn)]
        cur = max(i for i in range(Mn) if P.ms[i] <= now)
        covered = P.CPM_n[:, :, g] > 0
        nA, pA = self["nA"], self["pA"]
        luck = f4.could_be_luck(P.C_traded[:, g], P.C_beat[:, g], self["gwA"] - self["glA"], P.C_rand[:, g])
        ok = np.zeros(P.R, bool)
        rank = np.full(P.R, -BIG)
        for r in np.flatnonzero((nA >= vp.MIN_TRADES) & (pA > 0)):      # both are needed to pass `judge`
            judged = [i for i in range(Mn) if complete[i] and covered[P.kind[r], i]]
            vals = [P.CM_p[r, i, g] / 1e4 for i in judged]
            rec = {"trades": int(nA[r]), "luck": bool(luck[r]), "predicted": {"thin": len(judged) < need},
                   "rank": min(vals) if vals else None, "profit": float(pA[r]),
                   "months": [{"trades": int(P.CM_n[r, cur, g]), "profit": P.CM_p[r, cur, g] / 1e4}]}
            ok[r] = vp.judge(rec)[0]
            if vals:
                rank[r] = min(vals)
        return ok, rank

    def sig(self, r: int) -> tuple:
        """Rule sets with the very same record so far are ONE bet (the live picker's `_same_results`)."""
        return int(self["nA"][r]), int(self["wA"][r]), int(self["gwA"][r] - self["glA"][r])


# ------------------------------------------------------------------ one day's pick
def decide(spec: dict, S: Stats, held: list[int]) -> list[int]:
    """The rule set each room follows today (-1 = empty), given what it followed yesterday. As the live
    picker does it: a room keeps its rule set while it passes `keep`; a room whose rule set failed takes
    the best passing one no room follows (never its own back the same day, never a twin); with none
    left it sits empty."""
    P = S.P
    elig = np.asarray(S.eval(spec["gate"]), bool)
    score = np.asarray(S.eval(spec["rank"]), float)
    idx = np.flatnonzero(elig)
    order = idx[np.lexsort((P.id_rank[idx], P.filters[idx], -S["pA"][idx], -score[idx]))]
    out = [-1] * SLOTS
    if spec["hold"]:
        keep = np.asarray(S.eval(spec["keep"]), bool)
        kept = {s: r for s, r in enumerate(held) if r >= 0 and keep[r]}
        failed = [s for s in range(SLOTS) if s not in kept]
        taken = {S.sig(r) for r in kept.values()} | {S.sig(held[s]) for s in failed if held[s] >= 0}
        for s, r in kept.items():
            out[s] = r
    else:
        kept, failed, taken = {}, list(range(SLOTS)), set()
    used_tf = {int(P.tfi[r]) for r in kept.values()} if spec["spread"] else set()
    picks = []
    for r in order:
        if len(picks) == len(failed):
            break
        sg = S.sig(int(r))
        if sg in taken or (spec["spread"] and int(P.tfi[r]) in used_tf):
            continue
        taken.add(sg)
        used_tf.add(int(P.tfi[r]))
        picks.append(int(r))
    if not spec["hold"]:                      # a rule set still in the top three stays in its room
        stay = {s: r for s, r in enumerate(held) if r in picks}
        for s, r in stay.items():
            out[s] = r
        picks = [r for r in picks if r not in stay.values()]
        failed = [s for s in range(SLOTS) if s not in stay]
    for s, r in zip(failed, picks):
        out[s] = r
    return out


def start_days(P: Prepared) -> list[int]:
    """The walk days a rule is started on: the first pick day, then every `START_EVERY` days while at
    least `START_MIN_DAYS` are left."""
    return [g for g in range(LEAD_DAYS, P.Dp, START_EVERY) if P.Dp - g >= START_MIN_DAYS or g == LEAD_DAYS]


def simulate(P: Prepared, specs: list[dict] | None = None, log=print, starts: list[int] | None = None) -> dict:
    """Every picker rule walked from day `LEAD_DAYS` to the last day, one pick a day - and, for each
    later day in `starts`, the same rule started afresh that day with empty rooms. `follow[key]` is the
    walk from the first day; `started[key][g]` the walk begun on day g (-1 before it)."""
    specs = RULES if specs is None else specs
    days = list(range(LEAD_DAYS, P.Dp))
    starts = sorted(set([LEAD_DAYS] + list(starts or [])))
    started = {s["key"]: {g0: np.full((len(days), SLOTS), -1, np.int32) for g0 in starts} for s in specs}
    held = {s["key"]: {g0: [-1] * SLOTS for g0 in starts} for s in specs}
    shelf = {name: [] for name in SHELVES}
    for gi, g in enumerate(days):
        S = Stats(P, g)
        for s in specs:
            for g0 in starts:
                if g >= g0:
                    held[s["key"]][g0] = decide(s, S, held[s["key"]][g0])
                    started[s["key"]][g0][gi] = held[s["key"]][g0]
        for name, expr in SHELVES.items():
            shelf[name].append(np.flatnonzero(np.asarray(S.eval(expr), bool)))
        if gi % 10 == 0:
            log(f"picker lab: day {gi + 1} of {len(days)} picked")
    return {"days": days, "follow": {k: v[LEAD_DAYS] for k, v in started.items()}, "started": started,
            "starts": starts, "shelf": shelf}


def hold_fixed(P: Prepared, days: list[int], rule_ids: list[str]) -> np.ndarray:
    """No picker: the rooms follow these rule sets every day (the rooms' own starting rules)."""
    idx = [P.index_of(i) for i in rule_ids]
    row = [(-1 if i is None else i) for i in idx] + [-1] * (SLOTS - len(idx))
    return np.tile(np.array(row[:SLOTS], np.int32), (len(days), 1))


def day_totals(P: Prepared, days: list[int], follow: np.ndarray) -> dict:
    """What the rooms made each day: the trades their rule sets' strategies opened that day."""
    M = P.M
    g = np.array(days)
    n = np.zeros(len(days), np.int64)
    w = np.zeros(len(days), np.int64)
    p = np.zeros(len(days), np.int64)
    rnd = np.zeros(len(days))
    for s in range(follow.shape[1]):
        r = follow[:, s]
        ok = r >= 0
        n[ok] += M["o_n"][r[ok], g[ok]]
        w[ok] += M["o_w"][r[ok], g[ok]]
        p[ok] += M["o_p"][r[ok], g[ok]]
        rnd[ok] += M["o_n"][r[ok], g[ok]] * P.pool_avg[P.kind[r[ok]], g[ok]]
    return {"n": n, "w": w, "p": p, "random": rnd}


def random_pickers(P: Prepared, sim: dict, runs: int = RANDOM_RUNS, seed: int = RANDOM_SEED,
                   shelf: str = "any") -> dict:
    """Pickers with no skill: each room follows a rule set drawn blindly from a shelf (`SHELVES`),
    redrawn every `RANDOM_HOLD` days. Their trades and dollars, one figure a run."""
    rng = np.random.default_rng(seed)
    days = sim["days"]
    n = np.zeros(runs, np.int64)
    w = np.zeros(runs, np.int64)
    p = np.zeros(runs, np.int64)
    for k in range(runs):
        follow = np.full((len(days), SLOTS), -1, np.int32)
        held = [-1] * SLOTS
        for gi in range(len(days)):
            if gi % RANDOM_HOLD == 0:
                pool = sim["shelf"][shelf][gi]
                take = rng.choice(pool, size=min(SLOTS, len(pool)), replace=False) if len(pool) else []
                held = [int(x) for x in take] + [-1] * (SLOTS - len(take))
            follow[gi] = held
        t = day_totals(P, days, follow)
        n[k], w[k], p[k] = t["n"].sum(), t["w"].sum(), t["p"].sum()
    return {"n": n, "w": w, "p": p}


# ------------------------------------------------------------------ the trades themselves
def rows_followed(d: dict, end_s: int, need: dict[int, np.ndarray], log=print) -> dict[int, np.ndarray]:
    """The walk once more, keeping - for the rule sets a picker followed - the trades they opened on
    the days they were followed: each trade's place in `d`'s arrays. The same masks as the first walk."""
    out: dict[int, np.ndarray] = {}
    seen = [0]

    def visit(rule, m, sub, km):
        r = seen[0]
        seen[0] += 1
        if r in need:
            ii = np.flatnonzero(m)
            ii = ii[need[r][sub["day"][ii]]]
            out[r] = sub["row"][ii].astype(np.int64)

    f4._walk(d, end_s, log, visit=visit)
    return out


def figures(p4: np.ndarray, en: np.ndarray, month_starts: list[int]) -> dict:
    """One picker rule's trades (in closing order) as the page prints them, dollars at $5 margin."""
    k = int(len(p4))
    p = p4 / 1e4
    wins = int((p4 > 0).sum())
    worst, worst_n, dip, be, aw, al = 0.0, 0, 0.0, None, None, None
    if k:
        loss = p4 <= 0
        if loss.any():
            g = np.cumsum(~loss)
            s = np.bincount(g[loss], weights=p[loss])
            c = np.bincount(g[loss])
            j = int(np.argmin(np.where(c > 0, s, np.inf)))
            worst, worst_n = float(s[j]), int(c[j])
            if worst >= 0:                 # a run of trades that made exactly $0.00 is no losing run
                worst, worst_n = 0.0, 0
        cum = np.cumsum(p)
        dip = float((np.maximum.accumulate(np.maximum(cum, 0)) - cum).max())
        if wins and k - wins:
            aw, al = float(p[p4 > 0].mean()), -float(p[p4 <= 0].mean())
            be = 100.0 * al / (aw + al) if aw + al > 0 else None
    mon = np.searchsorted(np.array(month_starts), en, side="right") - 1 if k else np.zeros(0, np.int64)
    months = []
    for i in range(len(month_starts)):
        m = mon == i
        if m.any():
            months.append({"key": datetime.fromtimestamp(month_starts[i], tz=timezone.utc).strftime("%Y-%m"),
                           "trades": int(m.sum()), "wins": int((p4[m] > 0).sum()),
                           "profit": round(float(p[m].sum()), 4)})
    profit = float(p.sum()) if k else 0.0
    return {"trades": k, "wins": wins, "losses": k - wins, "profit": round(profit, 4),
            "win_rate": round(100.0 * wins / k, 2) if k else None,
            "per_trade": round(profit / k, 4) if k else None,
            "break_even": round(be, 2) if be is not None else None,
            "avg_win": round(aw, 4) if aw is not None else None,
            "avg_loss": round(al, 4) if al is not None else None,
            "worst_run": round(worst, 4), "worst_run_n": worst_n, "worst_dip": round(dip, 4),
            "months": months, "green_months": sum(m["profit"] > 0 for m in months)}


# ------------------------------------------------------------------ the whole run
def _cache_dir() -> Path:
    p = home() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


SWAPPING = ("collect", "build", "unreadable")      # v4_daily phases that end in (or may hide) the store's swap


def refresh_in_the_way() -> str | None:
    """Why the live store must not be copied right now, or None. The daily refresh swaps the store in
    whole at the end of its build; on Windows a copy still reading the old file makes that swap fail,
    and the refresh then builds the whole store again (about 35 minutes) - on the night the rooms wait
    for it. A state that cannot be read is not a go-ahead."""
    from tradingagents import v4_daily

    st = v4_daily.status()
    if st.get("phase") in SWAPPING:
        return (f"the daily refresh is about to swap the store in (it is at: {st.get('phase')}"
                + (f" - {st['why']}" if st.get("why") else "") + "); run the lab once the day's list has landed")
    return None


def load_store(db: Path | None = None, log=print, fresh: bool = False) -> dict:
    """The store's trades as Forecast v4 reads them (`forecast_v4._load`, with each trade's side, exit
    kind and exit minute), from ONE private copy of the file: the daily chain swaps the live file in
    whole, and a reader holding it open would refuse that swap on Windows. The copy sits beside the
    lab's results (the store's own drive) and is replaced by the next run - never one copy a run."""
    from tradingagents import v4_store

    src = Path(db) if db else v4_store.db_path()
    if not src.exists():
        raise RuntimeError(f"no Backtest v4 store at {src}: run python -m tradingagents.v4_store build first")
    copy = _cache_dir() / "rows-copy.db"
    stamp = _cache_dir() / "rows-copy.json"
    want = {"src": str(src), "size": src.stat().st_size, "mtime": int(src.stat().st_mtime)}
    have = json.loads(stamp.read_text(encoding="utf-8")) if stamp.exists() else None
    if fresh or have != want or not copy.exists():
        live = src.resolve() == v4_store.db_path().resolve()     # any other file is nobody's to swap
        busy = refresh_in_the_way() if live else None
        if busy:
            raise RuntimeError(f"picker lab: not copying the store - {busy}")
        log(f"picker lab: copying the store ({want['size'] / 1e6:,.0f} MB) to {copy}")
        tmp = copy.with_name(copy.name + ".tmp")
        shutil.copyfile(src, tmp)
        tmp.replace(copy)
        stamp.write_text(json.dumps(want), encoding="utf-8")
    pk = _cache_dir() / f"loaded-{want['mtime']}-{want['size']}.pkl"
    for f in _cache_dir().glob("loaded-*.pkl"):
        if f != pk:
            f.unlink()                      # one read of the store kept, the current one
    if pk.exists():
        with open(pk, "rb") as fh:
            return pickle.load(fh)
    d = f4._load(copy, log, extra=True)
    with open(pk, "wb") as fh:
        pickle.dump(d, fh, protocol=4)
    return d


def run(db: Path | None = None, log=print, fresh: bool = False) -> dict:
    """Measure every picker rule and write `lab.json` and the trades of each (`trades.pkl`)."""
    return measure(load_store(db, log, fresh), log)


def _started(P: Prepared, days: list[int], follow_of: dict[int, np.ndarray]) -> list[dict]:
    """One line a start day: what the rule made from that day to the end, begun with empty rooms."""
    out = []
    for g0, f in sorted(follow_of.items()):
        t = day_totals(P, days, f)
        n, w = int(t["n"].sum()), int(t["w"].sum())
        out.append({"start_s": P.start + g0 * DAY_S, "days": P.Dp - g0, "trades": n, "wins": w,
                    "profit": round(float(t["p"].sum() / 1e4), 4)})
    return out


def measure(d: dict, log=print) -> dict:
    """Everything after the store is read: `d` as `forecast_v4._load(extra=True)` returns it."""
    from tradingagents import backtest_report as br
    from tradingagents import profiles, v4_store

    t0 = time.time()
    meta = d["meta"]
    end_s = int(meta.get("data_end_s") or int(d["ex"].max()))
    M = matrices(d, end_s, log)
    P = Prepared(M)
    if P.Dp <= LEAD_DAYS + 1:
        raise RuntimeError(f"the walk has {P.Dp} days: too few to pick on (needs more than {LEAD_DAYS + 1})")
    starts = start_days(P)
    sim = simulate(P, RULES, log, starts)
    days = sim["days"]
    rooms = [f4.rule_id(**p["v4_rule"]) for p in profiles.BUILTIN if p.get("follows") == "v4" and p.get("v4_rule")]
    rows = [{"spec": s, "id": rule_id(s), "follow": sim["follow"][s["key"]], "baseline": False,
             "started": sim["started"][s["key"]]} for s in RULES]
    fixed = hold_fixed(P, days, rooms)
    rows.append({"spec": {"key": "no_picker", "name": "No picker: the rooms keep the rules they started with",
                          "promote": "The three rooms follow " + ", ".join(f"#{r}" for r in rooms)
                                     + " every day, never swapped.",
                          "demote": "Nothing is ever dropped.", "gate": "", "rank": "", "keep": "",
                          "hold": True, "spread": False},
                 "id": br._code("picker_lab|no_picker|" + "|".join(rooms)), "follow": fixed, "baseline": True,
                 "started": {g0: np.where((np.array(days) >= g0)[:, None], fixed, -1) for g0 in starts}})
    rnd = {name: random_pickers(P, sim, shelf=name) for name in SHELVES}
    rnd_ppt = {name: np.where(v["n"] > 0, v["p"] / 1e4 / np.maximum(v["n"], 1), 0.0) for name, v in rnd.items()}

    need: dict[int, np.ndarray] = {}
    for x in rows:
        for gi, g in enumerate(days):
            for r in x["follow"][gi]:
                if r >= 0:
                    need.setdefault(int(r), np.zeros(P.D, bool))[g] = True
    log(f"picker lab: reading the trades of {len(need):,} rule sets the pickers followed")
    got = rows_followed(d, end_s, need, log)
    start = P.start
    out_rows, trades = [], {}
    for x in rows:
        f = x["follow"]
        tot = day_totals(P, days, f)
        tr, slot, rset = [], [], []
        for s in range(SLOTS):
            for gi, g in enumerate(days):
                r = int(f[gi, s])
                if r < 0:
                    continue
                mine = got[r]
                mine = mine[(d["en"][mine] - start) // DAY_S == g]
                tr.append(mine)
                slot.append(np.full(len(mine), s, np.int8))
                rset.append(np.full(len(mine), r, np.int32))
        tr = np.concatenate(tr) if tr else np.zeros(0, np.int64)
        slot = np.concatenate(slot) if slot else np.zeros(0, np.int8)
        rset = np.concatenate(rset) if rset else np.zeros(0, np.int32)
        at = d["at"][tr]
        order = np.lexsort((d["sid"][tr], d["en"][tr], at))          # closing order
        tr, slot, rset, at = tr[order], slot[order], rset[order], at[order]
        p4 = np.rint(d["pnl"][tr] * 10_000).astype(np.int64)
        # the trades must be the ones the day-by-day totals counted: two walks, one answer
        if len(tr) != int(tot["n"].sum()) or int(p4.sum()) != int(tot["p"].sum()):
            raise RuntimeError(f"{x['spec']['key']}: {len(tr)} trades {p4.sum() / 1e4:+.4f} read back, "
                               f"{int(tot['n'].sum())} {tot['p'].sum() / 1e4:+.4f} in the day-by-day totals")
        fig = figures(p4, d["en"][tr], P.ms)
        ppt = fig["per_trade"]
        changed = (f[1:] != f[:-1]) & (f[:-1] >= 0)
        sets = []
        for r in np.unique(rset):
            m = rset == r
            sets.append({"id": M["rules"][int(r)]["id"], "words": M["rules"][int(r)]["words"],
                         "room_days": int((f == r).sum()), "trades": int(m.sum()),
                         "wins": int((p4[m] > 0).sum()), "profit": round(float(p4[m].sum() / 1e4), 4)})
        sets.sort(key=lambda z: -z["room_days"])
        trades[x["id"]] = {"sid": d["sid"][tr], "en": d["en"][tr], "slot": slot, "rset": rset, "at": at, "p4": p4,
                           "side": d["side"][tr], "why": d["why"][tr]}
        begun = _started(P, days, x["started"])
        if (begun[0]["trades"], begun[0]["profit"]) != (fig["trades"], fig["profit"]):
            raise RuntimeError(f"{x['spec']['key']}: its first start {begun[0]} is not its own row "
                               f"{fig['trades']} {fig['profit']:+.4f}")
        out_rows.append({
            "id": x["id"], "key": x["spec"]["key"], "name": x["spec"]["name"], "baseline": x["baseline"],
            "promote": x["spec"]["promote"], "demote": x["spec"]["demote"], **fig,
            "days": len(days), "per_day": round(fig["trades"] / len(days), 2),
            "swaps": int(changed.sum()), "empty_room_days": int((f < 0).sum()),
            "first_pick_s": next((start + int(days[gi]) * DAY_S for gi in range(len(days)) if (f[gi] >= 0).any()), None),
            "rule_sets": sets, "worst_day": round(float(tot["p"].min() / 1e4), 4),
            "random_strategies": round(float(tot["random"].sum() / 1e4), 4),
            "beat_random": {name: ([int((rnd[name]["p"] < p4.sum()).sum()), int((rnd_ppt[name] < ppt).sum())]
                                   if fig["trades"] else None) for name in SHELVES},
            "starts": begun, "starts_green": sum(b["profit"] > 0 for b in begun),
            "day_profit": [round(float(v) / 1e4, 4) for v in tot["p"]],
            "day_trades": [int(v) for v in tot["n"]],
            "day_wins": [int(v) for v in tot["w"]],
            "day_random": [round(float(v) / 1e4, 4) for v in tot["random"]],
            # the switch-on each of its rooms followed, day by day (None = the room sat empty): what the
            # Forecast v4 "Rooms" section turns into "deployed" and "undeployed" (v4_picker_rooms)
            "follow": [[(M["rules"][int(r)]["id"] if r >= 0 else None) for r in day] for day in f],
        })
    followed = sorted({int(r) for x in rows for r in np.unique(x["follow"]) if r >= 0})
    q = lambda a: [round(float(np.percentile(a, x)), 4) for x in (5, 50, 95)]     # noqa: E731
    doc = {
        "version": VERSION, "built_s": int(time.time()), "seconds": round(time.time() - t0, 1),
        "store": {"data_end_s": end_s, "built_s": int(meta.get("built_s", 0) or 0),
                  "strategies": int(meta.get("strategies", 0) or 0), "trades": int(meta.get("trades", 0) or 0),
                  "margin": v4_store.MEASURED_MARGIN, "leverage": v4_store.LEVERAGE,
                  # how the store priced each coin's buy-sell gap: {"minutes": coins, "one reading": coins},
                  # or None for a store built before the usual gap (one reading a coin, a night)
                  "gaps": json.loads(meta["gaps"]) if meta.get("gaps") else None,
                  # of the store's finished trades: priced from the recorded order book on both sides
                  # (`real`) or one (`part`) - the page's cost sentence is derived from it
                  "real": json.loads(meta["real"]) if meta.get("real") else None},
        "walk": M["walk"], "coverage": M["coverage"], "rule_sets": P.R, "slots": SLOTS,
        "lead_days": LEAD_DAYS, "first_day_s": start + days[0] * DAY_S, "last_day_s": start + days[-1] * DAY_S,
        "days": len(days), "months": [int(x) for x in P.ms], "rooms": rooms,
        "starts": [start + g0 * DAY_S for g0 in starts],
        "random": {"runs": RANDOM_RUNS, "hold": RANDOM_HOLD,
                   "shelves": {name: {"test": SHELVES[name], "profit": q(v["p"] / 1e4),
                                      "per_trade": q(rnd_ppt[name]), "trades": q(v["n"]),
                                      "in_profit": int((v["p"] > 0).sum())} for name, v in rnd.items()}},
        "switch_ons": {M["rules"][r]["id"]: M["rules"][r]["words"] for r in followed},
        "rules": out_rows,
    }
    home().mkdir(parents=True, exist_ok=True)
    from tradingagents.forecast_v2 import publish

    # the trades first, swapped in whole, then the run that names them (`built_s` pairs the two): a
    # reader between the two swaps sees files of two runs and keeps the pair it already holds
    tmp = home() / "trades.pkl.writing"
    with open(tmp, "wb") as fh:
        used = np.unique(np.concatenate([t["sid"] for t in trades.values()] or [np.zeros(0, np.int64)]))
        pickle.dump({"end_s": end_s, "built_s": doc["built_s"], "trades": trades, "rules": M["rules"],
                     "info": {int(s): d["info"][int(s)] for s in used}}, fh, protocol=4)
    tmp.replace(home() / "trades.pkl")
    publish(home() / "lab.json", json.dumps(doc, separators=(",", ":")))
    runs_dir().mkdir(parents=True, exist_ok=True)
    publish(kept_path(end_s), json.dumps(doc, separators=(",", ":")))       # nothing here deletes one
    log(f"picker lab: {len(out_rows)} rows written to {home() / 'lab.json'} in {doc['seconds']:.0f} s")
    return doc


def table(doc: dict) -> str:
    """The run as plain lines, most money first (what `run` prints)."""
    from tradingagents.positions_view import fmt_when

    sh = doc["random"]["shelves"]
    lines = [f"{fmt_when(doc['first_day_s'])} to {fmt_when(doc['store']['data_end_s'])} "
             f"({doc['days']} days), {doc['rule_sets']:,} rule sets, {doc['slots']} rooms, "
             f"${doc['store']['margin']:g} x {doc['store']['leverage']}x; random pickers: "
             + "; ".join(f"{name} median {v['profit'][1]:+.2f} ({v['in_profit']} of {doc['random']['runs']} "
                         f"in profit, {v['per_trade'][1]:+.3f} a trade)" for name, v in sh.items())]
    for r in sorted(doc["rules"], key=lambda r: -r["profit"]):
        mon = " ".join(f"{m['key'][5:]}:{m['profit']:+.0f}" for m in r["months"])
        beat = r["beat_random"]["in_profit"]
        lines.append(f"#{r['id']} {r['name'][:44]:44} {r['profit']:+10.2f} {r['trades']:7d} "
                     f"{(r['win_rate'] or 0):5.1f}% run {r['worst_run']:+.0f}/{r['worst_run_n']} "
                     f"dip {r['worst_dip']:.0f} swaps {r['swaps']:3d} empty {r['empty_room_days']:3d} "
                     f"starts {r['starts_green']}/{len(r['starts'])} "
                     f"beat {beat[1] if beat else '-'}/{doc['random']['runs']} [{mon}]")
    return "\n".join(lines)


# ------------------------------------------------------------------ once a night, by itself
# The Forecast v4 "Rooms" section reads the newest run (operator, Nov 12, 2026: "create a section 'room'
# where you will list all the room that is earning this month"), so the lab measures again whenever the
# daily refresh has landed a newer store. In its OWN process (it holds a 1 GB read and two walks), started
# by the site's 30-second tick; what it is doing, and why it could not, is kept where the page reads it.
RETRY_S = 3600            # a run that failed is tried again an hour later, never every tick


def status_path() -> Path:
    return home() / "status.json"


def _status() -> dict:
    try:
        return json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(st: dict) -> None:
    from tradingagents.forecast_v2 import publish

    home().mkdir(parents=True, exist_ok=True)
    publish(status_path(), json.dumps(st))


def running() -> bool:
    """A run is going when something HOLDS the run lock - never a pid (CLAUDE.md, RCA-2026-10-19-A)."""
    from tradingagents import portable

    try:
        fh = open(home() / "run.lock", "a+", encoding="utf-8")   # noqa: SIM115
    except OSError:
        return False
    try:
        portable.lock_exclusive(fh, blocking=False)
    except OSError:
        return True
    else:
        portable.unlock(fh)
        return False
    finally:
        fh.close()


def newest_run_end() -> int:
    """The last candle of the store the newest run was measured on (0 = never measured)."""
    try:
        return int(json.loads((home() / "lab.json").read_text(encoding="utf-8"))["store"]["data_end_s"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def store_end() -> int:
    """The live store's last candle (0 = no store, or one that cannot be read this second): one small
    read of its own stamp, cheap enough for a 30-second tick."""
    from tradingagents import v4_store

    try:
        con = v4_store._con()
        if con is None:
            return 0
        try:
            row = con.execute("SELECT v FROM meta WHERE k = 'data_end_s'").fetchone()
            return int(json.loads(row[0])) if row else 0
        finally:
            con.close()
    except Exception:                                          # noqa: BLE001 - a store mid-swap: next tick
        return 0


def due(now_s: float | None = None) -> str | None:
    """Why a run should start now, or None. Due when the live store is newer than the newest run, the
    daily refresh has finished with it (its list landed), no run is going, and the last try on THIS
    store did not fail within the hour."""
    from tradingagents import v4_daily

    now_s = time.time() if now_s is None else now_s
    if running():
        return None
    end_s = store_end()
    if not end_s or end_s <= newest_run_end():
        return None
    phase = v4_daily.status().get("phase")
    if phase not in v4_daily.IDLE:
        return None                       # still measuring, building or writing the day's list
    st = _status()
    if st.get("tried_end_s") == end_s:
        # the last try on THIS store failed, or started and never ended (killed, or died before it
        # could say why): the next try waits RETRY_S, counted from when that one stopped or started
        failed = st.get("ok") is False
        died = bool(st.get("started_s")) and not st.get("ended_s")
        since = float(st.get("ended_s") or st.get("started_s") or 0)
        if (failed or died) and now_s - since < RETRY_S:
            return None
    from tradingagents.positions_view import fmt_when

    return f"the store now ends {fmt_when(end_s)}, the newest run was measured on {fmt_when(newest_run_end()) if newest_run_end() else 'nothing'}"


def nightly(log=print) -> int:
    """`python -m tradingagents.v4_picker_lab nightly`: one run under the run lock. Its start, its end and
    any failure are written to status.json - a job that could not run SAYS SO, where the page reads it."""
    from tradingagents import portable, v4_picker_lab_page as page

    home().mkdir(parents=True, exist_ok=True)
    fh = open(home() / "run.lock", "a+", encoding="utf-8")   # noqa: SIM115
    try:
        portable.lock_exclusive(fh, blocking=False)
    except OSError:
        fh.close()
        log("picker lab: a run is already going")
        return 0
    tried = store_end()
    st = {"started_s": int(time.time()), "ended_s": None, "ok": None, "error": "", "tried_end_s": tried}
    try:
        _write_status(st)
        doc = run(log=log)
        page.write()
        st.update(ok=True, store_end_s=doc["store"]["data_end_s"], rows=len(doc["rules"]))
        log(table(doc))
    except Exception as exc:                                   # noqa: BLE001 - the reason is the product
        st.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:500])
        log(f"picker lab: the run FAILED - {st['error']}")
    finally:
        st["ended_s"] = int(time.time())
        _write_status(st)
        portable.unlock(fh)
        fh.close()
    return 0 if st["ok"] else 1


def start_run() -> int:
    """Start `nightly` as a background program with no window; its output goes to run.log."""
    import os
    import subprocess
    import sys

    from tradingagents import portable

    home().mkdir(parents=True, exist_ok=True)
    with (home() / "run.log").open("a", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tradingagents.v4_picker_lab", "nightly"],
            stdout=logf, stderr=subprocess.STDOUT, **portable.DETACHED,
            cwd=str(Path(__file__).resolve().parent.parent),
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    return proc.pid


def tick(now_s: float | None = None) -> dict:
    """The site's tick: start a run when one is due. Never from a test."""
    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return {"started": False, "why": "never from a test"}
    why = due(now_s)
    if not why:
        return {"started": False}
    pid = start_run()
    print(f"[picker lab] measuring again (pid {pid}): {why}", flush=True)
    return {"started": True, "why": why}


def status() -> dict:
    """What the Rooms section says about its own freshness: the run it shows, a run going now, and a
    run that failed or died (started, never ended, and nothing holds the lock)."""
    st = _status()
    going = running()
    died = bool(st.get("started_s") and not st.get("ended_s") and not going)
    return {"running": going, "started_s": st.get("started_s"), "ended_s": st.get("ended_s"),
            "ok": st.get("ok"), "error": st.get("error") or ("the run that started never finished" if died else ""),
            "measured_end_s": newest_run_end() or None}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m tradingagents.v4_picker_lab")
    ap.add_argument("what", choices=("run", "page", "show", "nightly", "status"))
    ap.add_argument("--db", default=None)
    ap.add_argument("--fresh", action="store_true", help="copy the store again even if it has not changed")
    a = ap.parse_args(argv)
    if a.what == "nightly":
        return nightly()
    if a.what == "status":
        print(json.dumps({**status(), "due": due()}, indent=1))
        return 0
    if a.what == "run":
        print(table(run(Path(a.db) if a.db else None, fresh=a.fresh)))
    if a.what == "show":
        print(table(json.loads((home() / "lab.json").read_text(encoding="utf-8"))))
    if a.what in ("run", "page"):
        from tradingagents import v4_picker_lab_page as page

        out = page.write()
        print(f"{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
