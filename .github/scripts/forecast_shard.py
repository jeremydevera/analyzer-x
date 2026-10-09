"""One machine's share of the FORECAST v2 research (Oct 01, 2026).

The operator: *"then predict what combination of room will be effective, for
example: 90% winrate with 40trade, tp is greater than SL will have profit of x
this month"* and *"you are seeing a coin is winning 9 streak then inform me
that specific coin"* (docs/FORECAST-V2.md).

A replay shard (.github/workflows/replay.yml) holds WHOLE coins, and a raw rule
set links strategies only through the runner's per-coin limit, so each machine
replays its own coins for every rule set and hands back its CLOSED TRADES; the
PC adds the machines together and scores the sum (forecast_v2_merge.py).

Every replay is `watcher_research.raw_fast` — the one walk the research and the
rooms' raw rules use — on the strategies the rule set's shape and row options
allow (forecast_rules.row_mask), then the trade options, the runner's own
open trades per coin (`watcher_replay.cap_per_coin`) and the daily loss limit,
in that order (forecast_rules).

STAGES (env STAGE):
  base     the 576 base rule sets + the rooms' own rules, the STREAKS of every
           strategy at the data's end with what followed past streaks, and the
           rooms' rules split every way the old "where the money goes" asked
           (the page dropped that section on Oct 08, 2026; each room's record
           still carries its rule set's id, which the merge and the month
           tracker's bells read)
  options  every option, one at a time, on BASES (the best base sets and the
           rooms' rules, chosen by the PC from the base stage)
  custom   one rule set (CUSTOM, JSON) — the what-if box's stage; nothing
           starts it since the box went on Oct 08, 2026

Out: out/forecast-<SHARD>.npz — per rule set j: j_e / j_x entry and exit
     (int32 minutes from Jan 01, 2026 UTC), j_p profit (float32), j_r / j_rn the
     random draws' profit and trades (BEAT RANDOM); for the base stage also the streaks
     (st_*) and the follow-through table (ft).
     out/forecast-<SHARD>.json — the rule sets in order (id, cfg, slots),
     the streak rows' text fields, the rooms' breakdowns, counts.
"""
# ruff: noqa: E402  (the project imports must follow the sys.path line)
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tradingagents import (
    forecast_rules as fr,
    forecast_v2 as f2,
    room_stats as rs_,
    watcher_policy as wp,
    watcher_replay as wr,
    watcher_research as rs,
)

T0_MIN = 1_767_225_600 // 60          # Jan 01, 2026 00:00 UTC, in minutes
DRAWS = 100                           # random picks per rule set (BEAT RANDOM)
STREAK_FLOOR = 5                      # streaks this long or longer are written
FOLLOW_K = 30                         # what followed streaks of 1..30
RECENT_MS = 30 * wr.DAY_MS            # the rooms' breakdowns cover the last 30 days
SHIFT = 42                            # book index << SHIFT | entry ms, for one sort
# THE BREAKDOWN'S OWN BUCKETS (Oct 08, 2026). They were forecast_v2.HOURS and
# .HELD, kept there for the page's "Where the money goes"; that section went
# with them, and this file was the one reader left — every machine of every
# base run would have died on the first room trade it split, all 40 of them,
# every day (found by the code review before it was pushed). When a trade
# OPENED, New York time; how long a losing trade was held, in seconds.
HOURS = ((0, 6, "12am to 6am"), (6, 9, "6am to 9am"), (9, 12, "9am to noon"),
         (12, 16, "noon to 4pm"), (16, 20, "4pm to 8pm"), (20, 24, "8pm to midnight"))
HELD = ((0, 900, "within 15 minutes"), (900, 3600, "15 to 60 minutes"),
        (3600, float("inf"), "after an hour"))


def ms(s: str) -> int:
    return int(dt.datetime(*map(int, s.split("-"))).timestamp() * 1000)


def log(msg: str) -> None:
    print(f"[forecast {os.environ.get('SHARD', '?')}] {msg}", flush=True)


# ------------------------------------------------------------- the sets
def rule_sets(stage: str) -> tuple[list[dict], dict]:
    rooms = fr.decode_rooms(os.environ.get("ROOMS", ""))
    if stage == "custom":
        cfg = json.loads(os.environ["CUSTOM"])          # {"id": ..., the rule set}
        return [fr.cfg_of(**{k: cfg[k] for k in ("window_days", "on_winrate", "min_trades",
                                                 "tp_rule", "max_sl")},
                          **{k: v for k, v in cfg.items()
                             if k in fr.OPTION_KEYS or k == "coin_slices"})], rooms
    if stage == "options":
        bases = [fr.decode(x) for x in os.environ.get("BASES", "").split(";") if x.strip()]
        return fr.with_options(bases), rooms
    sets = fr.base_grid()
    seen = {fr.rule_id(c) for c in sets}
    for c in rooms.values():
        if fr.rule_id(c) not in seen:
            seen.add(fr.rule_id(c))
            sets.append(c)
    return sets, rooms


def normal_moves(coins: set) -> dict:
    """Each coin's normal 15-minute move: the median (high - low) / close of
    its last 30 days of 15-minute bars, in percent. A coin whose candles
    cannot be read is left out, so the option keeps it."""
    from tradingagents.dataflows import mexc_futures as fx

    out = {}
    for coin in sorted(coins):
        try:
            df = fx.klines(f"{coin}_USDT", "Min15", 2880)
            hl = (df["High"].astype(float) - df["Low"].astype(float)) / df["Close"].astype(float)
            hl = hl[np.isfinite(hl)]
            if len(hl):
                out[coin] = round(float(np.median(hl)) * 100, 4)
        except Exception as exc:                               # noqa: BLE001
            log(f"{coin}: no 15-minute candles ({type(exc).__name__})")
    return out


# --------------------------------------------------------- one rule set
def replay(books, meta, grids, checks, cfg, end_ms, ctx):
    """The slots a rule set switches on, after every option, capped."""
    mask = fr.row_mask(meta, cfg, ctx)
    idx = np.nonzero(mask)[0]
    if not len(idx):
        return [], mask
    n_all, w_all = grids[int(cfg["window_days"])]
    sub = [books[i] for i in idx]
    # the shape and the row options are already applied by row_mask
    walk = {**cfg, "tp_rule": "any", "max_sl": 0.0, "coin_slices": 0}
    # a room switched off on another window (the 1-4 day rooms, Oct 07, 2026:
    # off on 30 days) is replayed on that window's grid too
    jd = wp.judge_days(cfg)
    jg = None if jd == int(cfg["window_days"]) else (grids[jd][0][:, idx], grids[jd][1][:, idx])
    res = rs.raw_fast(sub, (n_all[:, idx], w_all[:, idx]), checks, walk, end_ms, judge_grid=jg)
    slots = res["slots"]
    if cfg.get("own_market") or cfg.get("no_ny_morning"):
        for s in slots:
            t = s["trades"]
            if len(t):
                s["trades"] = t[fr.trade_keep(s["coin"], t[:, 0], cfg)]
    cap = int(cfg.get("coin_slices") or fr.COIN_SLICES)
    if cap > 0:
        wr.cap_per_coin(slots, cap)
    if cfg.get("day_loss"):
        fr.day_loss(slots, float(cfg["day_loss"]))
    return slots, mask


def closed_arrays(slots, end_ms):
    e, x, p, b = [], [], [], []
    for s in slots:
        t = s["trades"]
        if not len(t):
            continue
        m = (t[:, 3] > 0) & (t[:, 1] <= end_ms)
        if m.any():
            e.append(t[m, 0])
            x.append(t[m, 1])
            p.append(t[m, 2])
            b.append(np.full(int(m.sum()), s["_b"], dtype=np.int64))
    return _cat(e, np.int64), _cat(x, np.int64), _cat(p, np.float64), _cat(b, np.int64)


def _cat(v: list, dtype) -> np.ndarray:
    return np.concatenate(v).astype(dtype) if v else np.zeros(0, dtype)


# ------------------------------------------------------------ BEAT RANDOM
class Flat:
    """Every book's closed trades in one sorted array, for interval sums:
    the profit of book j's trades that OPENED in [a, z) is cum[hi] - cum[lo]."""

    def __init__(self, books, end_ms, cfg_filter=None):
        # ONE allocation each, filled book by book — the book index is the
        # high bits, so the books' runs are already in order. A list of
        # per-book arrays plus a concatenate needed twice the memory and
        # failed on the PC at 257 MB with 5.6 GB free (Oct 01, 2026).
        total = sum(len(b.exits) for b in books)
        self.keys = np.empty(total, np.int64)
        self.cum = np.zeros(total + 1, np.float64)
        n = 0
        for j, b in enumerate(books):
            t = b.c["trades"]
            if not len(t):
                continue
            t = t[(t[:, 3] > 0) & (t[:, 1] <= end_ms)]
            if cfg_filter is not None and len(t):
                t = t[fr.trade_keep(b.c["coin"], t[:, 0], cfg_filter)]
            if not len(t):
                continue
            o = np.argsort(t[:, 0], kind="stable")
            k = len(t)
            self.keys[n:n + k] = (np.int64(j) << SHIFT) | t[o, 0].astype(np.int64)
            self.cum[n + 1:n + k + 1] = t[o, 2]
            n += k
        self.keys = self.keys[:n]
        self.cum = self.cum[:n + 1]
        np.cumsum(self.cum, out=self.cum)

    def sums(self, j, a, z):
        """(profit, trades) of each book j's trades opened in [a, z)."""
        lo = np.searchsorted(self.keys, (j << SHIFT) | a, "left")
        hi = np.searchsorted(self.keys, (j << SHIFT) | z, "left")
        return self.cum[hi] - self.cum[lo], hi - lo


def beat_random(slots, mask, n_grid, checks, flat, rng, end_ms):
    """DRAWS (profit, trades): every slot's book swapped for a random
    strategy of the same shape that was trading at the same check (a row
    existed in the window), over the same on/off stretch.

    COMPARED PER TRADE, never in total (found before the first run, Oct 01,
    2026): the random picks are not held to the runner's trades per coin or
    the loss limit, so they make more trades, and against a losing market
    more trades is a bigger total loss — a total would let a rule set "beat"
    random by the cap alone. Those limits remove trades first come, first
    served, not by quality, so profit per trade is a fair yardstick."""
    if not slots:
        return np.zeros(DRAWS, np.float32), np.zeros(DRAWS, np.int64)
    k_of = {c: k for k, c in enumerate(checks)}
    ks = np.array([k_of[int(s["on_ms"])] for s in slots], dtype=np.int64)
    a = np.array([int(s["on_ms"]) for s in slots], dtype=np.int64)
    z = np.array([int(s["off_ms"]) if s["off_ms"] is not None else end_ms + 1 for s in slots],
                 dtype=np.int64)
    pools = {}
    for k in np.unique(ks):
        pools[int(k)] = np.nonzero(mask & (n_grid[int(k)] >= 1))[0]
    out = np.zeros(DRAWS, np.float64)
    cnt = np.zeros(DRAWS, np.int64)
    for d in range(DRAWS):
        j = np.empty(len(slots), np.int64)
        ok = np.ones(len(slots), bool)
        for k, pool in pools.items():
            sel = ks == k
            if not len(pool):
                ok[sel] = False
                continue
            j[sel] = pool[rng.integers(0, len(pool), int(sel.sum()))]
        if ok.any():
            prof, n = flat.sums(j[ok], a[ok], z[ok])
            out[d], cnt[d] = float(prof.sum()), int(n.sum())
    return out.astype(np.float32), cnt


# ---------------------------------------------------------------- STREAKS
def streaks(books, end_ms):
    """Every strategy's run of wins or losses at the data's end, and across
    all of them what followed a run of k (k = 1..FOLLOW_K): how many times,
    how often the next trade won, and the next 10 trades' profit."""
    seqs_w, seqs_p, seqs_b = [], [], []
    rows = []
    recent = end_ms - RECENT_MS
    for j, b in enumerate(books):
        t = b.c["trades"]
        if not len(t):
            continue
        t = t[(t[:, 3] > 0) & (t[:, 1] <= end_ms)]
        if not len(t):
            continue
        t = t[np.argsort(t[:, 1], kind="stable")]
        w = t[:, 2] > 0
        seqs_w.append(w)
        seqs_p.append(t[:, 2])
        seqs_b.append(np.full(len(t), j, np.int64))
        last = bool(w[-1])
        flips = np.flatnonzero(w != last)
        n = len(w) - (int(flips[-1]) + 1 if len(flips) else 0)
        if n >= STREAK_FLOOR:
            run = t[-n:]
            r30 = t[t[:, 1] >= recent]
            c = b.c
            rows.append({"b": j, "id": c["id"], "coin": c["coin"], "tf": c["tf"],
                         "signal": c["signal"], "th": float(c.get("th", 0.0)),
                         "tp": float(c["tp"]), "sl": float(c["sl"]),
                         "cost_of_tp": float(c.get("cost_of_tp") or 0.0),
                         "kind": "win" if last else "loss", "length": int(n),
                         "started_ms": int(run[0, 0]), "last_ms": int(run[-1, 1]),
                         "profit": round(float(run[:, 2].sum()), 2),
                         "trades": int(len(r30)), "wins": int((r30[:, 2] > 0).sum())})
    if not seqs_w:
        return rows, np.zeros((2, FOLLOW_K, 4))
    W = np.concatenate(seqs_w)
    P = np.concatenate(seqs_p)
    B = np.concatenate(seqs_b)
    n = len(W)
    new = np.ones(n, bool)
    new[1:] = (W[1:] != W[:-1]) | (B[1:] != B[:-1])
    rid = np.cumsum(new) - 1
    start = np.flatnonzero(new)
    r = np.arange(n) - start[rid] + 1                    # length of the run ending here
    nxt = np.zeros(n, bool)
    nxt[:-1] = B[1:] == B[:-1]
    w_next = np.zeros(n, bool)
    w_next[:-1] = W[1:]
    has10 = np.zeros(n, bool)
    if n > 10:
        has10[:-10] = B[10:] == B[:-10]
    C = np.concatenate([[0.0], np.cumsum(P)])
    i = np.arange(n)
    p10 = np.zeros(n)
    ok = i + 11 <= n
    p10[ok] = C[i[ok] + 11] - C[i[ok] + 1]
    ft = np.zeros((2, FOLLOW_K, 4))                      # kind x k x (cases, next win, cases10, pnl10)
    for kind, sel in ((0, W), (1, ~W)):
        for k in range(1, FOLLOW_K + 1):
            m = sel & (r >= k) & nxt
            m10 = m & has10
            ft[kind, k - 1] = (m.sum(), (m & w_next).sum(), m10.sum(), p10[m10].sum())
    return rows, ft


# ---------------------------------------------------- WHERE THE MONEY GOES
def breakdown(slots, meta_by_id, end_ms):
    """A room's rules replayed, its trades of the last 30 days split every
    way section C splits practice: timeframe, signal family, stocks or
    crypto, the New York hour it opened, how fast a loss closed; with the
    win and loss sizes and the costs (each strategy's cost x its target)."""
    out = {"tf": {}, "family": {}, "kind": {}, "hour": {}, "stops": {},
           "sizes": [0, 0.0, 0, 0.0], "costs": 0.0, "trades": 0, "profit": 0.0}
    lo = end_ms - RECENT_MS
    for s in slots:
        t = s["trades"]
        if not len(t):
            continue
        t = t[(t[:, 3] > 0) & (t[:, 1] <= end_ms) & (t[:, 0] >= lo)]
        if not len(t):
            continue
        c = meta_by_id[s["id"]]
        keys = {"tf": c["tf"], "family": f2.family(c["signal"]),
                "kind": "stocks" if rs_.is_stock(c["coin"]) else "crypto"}
        cost = float(c.get("cost_of_tp") or 0.0) / 100.0 * float(c["tp"])     # $ on $100
        minutes, _wd = fr.local_minutes(t[:, 0].astype(np.int64), "America/New_York")
        for (entry, exit_, pnl, _cl), minute in zip(t, minutes, strict=True):
            win = pnl > 0
            for g, k in keys.items():
                cell = out[g].setdefault(k, [0, 0, 0.0])
                cell[0] += 1
                cell[1] += int(win)
                cell[2] += float(pnl)
            h = next(label for a, b, label in HOURS if a * 60 <= minute < b * 60)
            cell = out["hour"].setdefault(h, [0, 0, 0.0])
            cell[0] += 1
            cell[1] += int(win)
            cell[2] += float(pnl)
            if not win:
                held = (exit_ - entry) / 1000.0
                lab = next(label for a, b, label in HELD if a <= held < b)
                cell = out["stops"].setdefault(lab, [0, 0, 0.0])
                cell[0] += 1
                cell[2] += float(pnl)
                out["sizes"][2] += 1
                out["sizes"][3] += float(pnl)
            else:
                out["sizes"][0] += 1
                out["sizes"][1] += float(pnl)
            out["costs"] += cost
            out["trades"] += 1
            out["profit"] += float(pnl)
    return out


# --------------------------------------------------------------------- main
def main() -> int:
    src, shard = os.environ["SRC"], os.environ["SHARD"]
    end_ms = int(os.environ["END_MS"])
    stage = (os.environ.get("STAGE") or "base").strip()
    start = os.environ.get("START") or "2026-07-01"
    # no coins to avoid since Oct 07, 2026 (operator: "i dont need its logic")
    ctx = {"families": [f for f in (os.environ.get("FAMILIES") or "").split(",") if f.strip()]}
    out = Path("out")
    out.mkdir(exist_ok=True)
    t0 = time.time()
    L = rs.load_lean([src], end_ms=end_ms)
    books = list(L["books"].values())
    if os.environ.get("MAX_BOOKS"):           # a quick local check, never on the fleet
        books = books[:int(os.environ["MAX_BOOKS"])]
    meta = [b.c for b in books]
    for j, b in enumerate(books):
        b.c["_b"] = j
    log(f"{len(books):,} strategies loaded in {time.time() - t0:.0f}s")
    checks = wr.local_midnights(ms(start), end_ms)
    sets, rooms = rule_sets(stage)
    if os.environ.get("MAX_SETS"):            # a quick local check, never on the fleet
        keep = int(os.environ["MAX_SETS"])
        room_set = {fr.rule_id(c) for c in rooms.values()}
        sets = sets[:keep] + [c for c in sets[keep:] if fr.rule_id(c) in room_set]
    if any(c.get("stop_vs_move") for c in sets):
        ctx["move"] = normal_moves({m["coin"] for m in meta})
    grids = {wd: rs.count_grid(books, checks, wd * wr.DAY_MS)
             for wd in sorted({int(c["window_days"]) for c in sets}
                              | {wp.judge_days(c) for c in sets})}
    log(f"{len(sets)} rule sets, {len(checks)} checks, stage {stage}")
    arrays: dict = {}
    info = {"shard": shard, "stage": stage, "end_ms": end_ms, "start": start,
            "books": len(books), "trades": int(sum(len(b.exits) for b in books)),
            "sets": [], "rooms": {}, "write": L["totals"].get("write")}
    flats: dict = {}
    room_ids = {fr.rule_id(c): rid for rid, c in rooms.items()}
    meta_by_id = {m["id"]: m for m in meta}
    seed = int(os.environ.get("SEED") or 7) * 1000 + int(shard)
    for j, cfg in enumerate(sets):
        slots, mask = replay(books, meta, grids, checks, cfg, end_ms, ctx)
        for s in slots:
            s["_b"] = meta_by_id[s["id"]]["_b"]
        e, x, p, _b = closed_arrays(slots, end_ms)
        arrays[f"{j}_e"] = (e // 60_000 - T0_MIN).astype(np.int32)
        arrays[f"{j}_x"] = (x // 60_000 - T0_MIN).astype(np.int32)
        arrays[f"{j}_p"] = p.astype(np.float32)
        fkey = (bool(cfg.get("own_market")), bool(cfg.get("no_ny_morning")))
        if fkey not in flats:
            flats[fkey] = Flat(books, end_ms, cfg if any(fkey) else None)
        rng = np.random.default_rng(seed * 10_007 + j)
        arrays[f"{j}_r"], arrays[f"{j}_rn"] = beat_random(
            slots, mask, grids[int(cfg["window_days"])][0], checks, flats[fkey], rng, end_ms)
        rid = fr.rule_id(cfg)
        info["sets"].append({"id": rid, "cfg": cfg, "slots": len(slots),
                             "open": int(sum(int((s["trades"][:, 3] == 0).sum())
                                             for s in slots if len(s["trades"])))})
        if rid in room_ids and stage == "base":
            info["rooms"][room_ids[rid]] = {"id": rid, **breakdown(slots, meta_by_id, end_ms)}
        if (j + 1) % 50 == 0:
            log(f"  {j + 1} of {len(sets)} rule sets, {time.time() - t0:.0f}s")
    if stage == "base":
        rows, ft = streaks(books, end_ms)
        arrays["ft"] = ft
        info["streaks"] = [{k: v for k, v in r.items() if k != "b"} for r in rows]
        log(f"{len(rows):,} strategies on a run of {STREAK_FLOOR}+ at the end")
    np.savez_compressed(out / f"forecast-{shard}.npz", **arrays)
    (out / f"forecast-{shard}.json").write_text(json.dumps(info, separators=(",", ":")),
                                                encoding="utf-8")
    log(f"done in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
