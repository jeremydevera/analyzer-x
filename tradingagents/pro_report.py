"""THE PRO TRADER RESEARCH, READ (Oct 20, 2026): pick on older days, judge on
days never seen. Design: docs/superpowers/specs/2026-10-20-pro-trader-research-design.md.

Every measured line (pro_search.read_lines) is one coin x timeframe x setting x
stop/target with its whole deep window and its four test months (the trades
that CLOSED in the last 30, 60, 90, 120 days, and the round trips they paid).
From those numbers alone:

* MONTHS: month 4 is the newest 30 days, month 1 the oldest of the four; the
  choosing days are everything closed before the month being judged.
* GROUPS: coins grouped by what they ARE, measured before the test months
  (pro_shard.coin_stats): asset kind, daily volatility third, trending or
  snapping back. A group too small to judge joins its wider group.
* CANDIDATES before a month: a setting that traded on the choosing days and
  pays at least 2:1 after the fees ITS CHOOSING DAYS paid (never the whole
  window's average, which includes the judged month — code review, Oct 20,
  2026); never the random baseline.
* THE CHOICE for a coin and timeframe: its group's default (the candidate that
  made the most over the group's coins, if that was money), or the coin's own
  best when that made money and beat the default on the coin's own choosing
  days by OWN_MARGIN.
* THE MAIN TEST: one choice from the days before all four months, judged on
  the four months (120 days). THE WALK-FORWARD: the choice made again before
  each month from everything closed before it, each month judged by its own.
* The checks each row must pass live in `pro_checks`.

Nothing here switches anything on.
"""
from __future__ import annotations

import math

import numpy as np

from tradingagents import backtest_report as br

# the shard's FIELDS, in order (.github/scripts/pro_shard.py); `months`
# refuses lines written with any other list
FIELDS = ("trades", "wins", "profit",
          "t30", "w30", "p30", "t60", "w60", "p60",
          "t90", "w90", "p90", "t120", "w120", "p120",
          "rt_paid", "pay2", "streak", "dd",
          "c30", "c60", "c90", "c120",
          "gate_blocked", "cost_unmeasured", "chase_skip", "closed_skipped", "unclear",
          "funding")
F = {k: i for i, k in enumerate(FIELDS)}
MONTHS = 4
WINDOW_OF = {1: 120, 2: 90, 3: 60, 4: 30}   # the window holding months m..4
MIN_GROUP = 8              # coins a group needs to have its own default
GROUP_MIN_TRADES = 30      # a group default needs this many choosing trades...
GROUP_MIN_WINS = 10        # ...and wins, across the group
OWN_MIN_TRADES = 15        # a coin's own pick needs this many on its own...
OWN_MIN_WINS = 5
OWN_MARGIN = 1.0           # ...and must beat the group default by $1 there
MIN_WINS = 20              # wins a row needs on its untouched days to pass
STOP_WORSE = 0.10          # $ a losing trade costs on $100 when its stop fills 0.1% worse
PAY_RATIO = br.PAY_RATIO   # the one 2:1 rule's own numbers, never a copy
PAY_SLACK = br._PAY_SLACK


def _check_fields(lines: dict) -> None:
    got = [str(x) for x in lines.get("fields") or FIELDS]
    if got != list(FIELDS):
        raise ValueError(f"lines carry fields {got[:6]}..., this reader expects {list(FIELDS)[:6]}...")


def months(lines: dict) -> np.ndarray:
    """[line, k, (trades, wins, profit)] for k = 0 (before the four months),
    1..4 (oldest -> newest test month)."""
    _check_fields(lines)
    v = lines["vals"]
    t = [v[:, F["t120"]], v[:, F["t90"]], v[:, F["t60"]], v[:, F["t30"]]]
    w = [v[:, F["w120"]], v[:, F["w90"]], v[:, F["w60"]], v[:, F["w30"]]]
    p = [v[:, F["p120"]], v[:, F["p90"]], v[:, F["p60"]], v[:, F["p30"]]]
    out = np.zeros((len(v), MONTHS + 1, 3))
    out[:, 0] = np.stack([v[:, F["trades"]] - t[0], v[:, F["wins"]] - w[0],
                          v[:, F["profit"]] - p[0]], 1)
    for k in range(MONTHS):
        nxt = (t[k + 1], w[k + 1], p[k + 1]) if k + 1 < MONTHS else (0.0, 0.0, 0.0)
        out[:, k + 1] = np.stack([t[k] - nxt[0], w[k] - nxt[1], p[k] - nxt[2]], 1)
    return out


def stops_targets(lines: dict) -> tuple[np.ndarray, np.ndarray]:
    """Each line's stop and target, in percent."""
    tfs = list(lines["tfs"])
    sl = np.zeros(len(lines["vals"]))
    tp = np.zeros(len(lines["vals"]))
    for k, tf in enumerate(tfs):
        bars = np.asarray(lines["barriers"][f"barriers_{tf}"], dtype=float).reshape(-1, 2) * 100
        m = lines["tf"] == k
        if m.any():
            sl[m] = bars[lines["bar"][m], 0]
            tp[m] = bars[lines["bar"][m], 1]
    return sl, tp


def baseline_mask(lines: dict) -> np.ndarray:
    """Lines of the luck baseline (signals_pro `baseline` families)."""
    from tradingagents import signals_pro as sp

    base = np.array([sp.is_baseline(n) for n in lines["names"]], dtype=bool)
    return base[lines["var"]] if len(lines["var"]) else np.zeros(0, dtype=bool)


def choosing_paid(lines: dict, upto: int) -> tuple[np.ndarray, np.ndarray]:
    """(trades, round trips paid summed, % of the position) of each line on
    the choosing days before month `upto`: the whole window less the trades
    that closed in the months judged after."""
    v = lines["vals"]
    w = WINDOW_OF[upto]
    t_all = v[:, F["trades"]]
    return t_all - v[:, F[f"t{w}"]], v[:, F["rt_paid"]] * t_all - v[:, F[f"c{w}"]]


def candidates(lines: dict, upto: int, cost_mult: float = 1.0,
               baseline: bool = False) -> np.ndarray:
    """Lines that may be chosen before month `upto`: traded on the choosing
    days, pay 2:1 after the fees THOSE days paid (x `cost_mult`, the
    sensitivity run), not the baseline — or, with `baseline`, ONLY the
    baseline: random entries chosen exactly as a strategy would be, which
    shows how often luck alone gets through the choice and the checks."""
    th, paid = choosing_paid(lines, upto)
    with np.errstate(invalid="ignore", divide="ignore"):
        c = cost_mult * np.where(th > 0, paid / np.maximum(th, 1), np.nan)
    sl, tp = stops_targets(lines)
    win, loss = tp - c, sl + c
    ok = (th > 0) & np.isfinite(c) & (win > 0) & (win + PAY_SLACK >= PAY_RATIO * loss)
    base = baseline_mask(lines)
    return ok & (base if baseline else ~base)


def groups(stats: dict) -> dict:
    """coin -> its group name. kind (crypto / stocks / other) x volatility
    third within the kind x trending (variance ratio >= 1) or snapping back;
    a group under MIN_GROUP coins drops its trend half, then its volatility
    third."""
    kinds: dict = {}
    for coin, s in stats.items():
        if not isinstance(s, dict) or s.get("vol") is None or s.get("error") or s.get("why"):
            continue
        k = s.get("kind") or "crypto"
        kinds.setdefault("crypto" if k == "crypto" else "stocks" if k == "stocks" else "other",
                         []).append(coin)
    full: dict = {}
    for kind, coins in kinds.items():
        vols = sorted(float(stats[c]["vol"]) for c in coins)
        cuts = ((vols[len(vols) // 3], vols[(2 * len(vols)) // 3]) if len(vols) >= 3
                else (math.inf, math.inf))
        for c in coins:
            vol = float(stats[c]["vol"])
            third = "quiet" if vol < cuts[0] else "middle" if vol < cuts[1] else "wild"
            vr = stats[c].get("vr")
            trend = ("trending" if vr is not None and not math.isnan(float(vr)) and float(vr) >= 1
                     else "snapping-back")
            full[c] = (kind, third, trend)
    size3: dict = {}
    size2: dict = {}
    for g in full.values():
        size3[g] = size3.get(g, 0) + 1
        size2[g[:2]] = size2.get(g[:2], 0) + 1
    out = {}
    for c, g in full.items():
        if size3[g] >= MIN_GROUP:
            out[c] = "-".join(g)
        elif size2[g[:2]] >= MIN_GROUP:
            out[c] = "-".join(g[:2])
        else:
            out[c] = g[0]
    return out


def _first_per(keys: np.ndarray, order: np.ndarray) -> np.ndarray:
    """Positions in `order` where a new key starts (keys already sorted by
    `order` so equal keys sit together)."""
    if not len(order):
        return order
    k = keys[order]
    new = np.ones(len(order), dtype=bool)
    new[1:] = np.any(k[1:] != k[:-1], axis=1)
    return order[new]


def choose(lines: dict, mon: np.ndarray, grp: dict, upto: int, cost_mult: float = 1.0,
           notional: float = 100.0, baseline: bool = False) -> dict:
    """(coin index, tf index) -> (line index, how) from the choosing days
    before month `upto` (1 = before all four months ... 4 = before the
    newest). `how` is "group default" or "own pick".

    `cost_mult` re-makes the choice as if every choosing-day trade had paid
    that many times its round trip (profit and the 2:1 rule both): trades
    older than the recorded order books pay each coin's usual cost, which is
    measured on the newest ~45 days, so the main test's choice reads a cost
    level from the days it is judged on (code review, Oct 20, 2026) — this
    shows how much the choice leans on it."""
    if not len(lines["vals"]):
        return {}
    hist = mon[:, :upto].sum(axis=1)                    # trades, wins, profit
    if cost_mult != 1.0:
        _th, paid = choosing_paid(lines, upto)
        hist[:, 2] -= (cost_mult - 1.0) * np.nan_to_num(paid) * notional / 100.0
    cand = candidates(lines, upto, cost_mult, baseline)
    coins = list(lines["coins"])
    gnames = sorted(set(grp.values()))
    g_of_coin = np.array([gnames.index(grp[c]) if c in grp else -1 for c in coins], dtype=np.int64)
    c_ix = lines["coin"].astype(np.int64)
    tf_ix = lines["tf"].astype(np.int64)
    cfg = lines["var"].astype(np.int64) * 64 + lines["bar"].astype(np.int64)
    g_line = g_of_coin[c_ix]
    # ---- the group defaults: one per (group, timeframe)
    idx = np.where(cand & (g_line >= 0))[0]
    defaults: dict = {}
    if len(idx):
        key = np.stack([g_line[idx], tf_ix[idx], cfg[idx]], 1)
        uk, inv = np.unique(key, axis=0, return_inverse=True)
        inv = inv.ravel()
        T = np.bincount(inv, weights=hist[idx, 0], minlength=len(uk))
        W = np.bincount(inv, weights=hist[idx, 1], minlength=len(uk))
        P = np.bincount(inv, weights=hist[idx, 2], minlength=len(uk))
        ok = np.where((T >= GROUP_MIN_TRADES) & (W >= GROUP_MIN_WINS) & (P > 0))[0]
        if len(ok):
            order = ok[np.lexsort((-T[ok], -P[ok], uk[ok, 1], uk[ok, 0]))]
            for j in _first_per(uk[:, :2], order):
                defaults[(int(uk[j, 0]), int(uk[j, 1]))] = int(uk[j, 2])
    # ---- each coin's own best that made money on its choosing days
    own_ok = np.where(cand & (hist[:, 0] >= OWN_MIN_TRADES) & (hist[:, 1] >= OWN_MIN_WINS)
                      & (hist[:, 2] > 0))[0]
    own: dict = {}
    if len(own_ok):
        pk = np.stack([c_ix[own_ok], tf_ix[own_ok]], 1)
        order = own_ok[np.lexsort((-hist[own_ok, 0], -hist[own_ok, 2], pk[:, 1], pk[:, 0]))]
        keys = np.stack([c_ix, tf_ix], 1)
        for i in _first_per(keys, order):
            own[(int(c_ix[i]), int(tf_ix[i]))] = int(i)
    # ---- each coin's line of its group's default
    d_line: dict = {}
    for i in np.where(cand & (g_line >= 0))[0]:
        d = defaults.get((int(g_line[i]), int(tf_ix[i])))
        if d is not None and int(cfg[i]) == d:
            d_line[(int(c_ix[i]), int(tf_ix[i]))] = int(i)
    out: dict = {}
    for pair in set(own) | set(d_line):
        o, d = own.get(pair), d_line.get(pair)
        if o is not None and (d is None or hist[o, 2] > hist[d, 2] + OWN_MARGIN):
            out[pair] = (o, "own pick")
        elif d is not None:
            out[pair] = (d, "group default")
    return out


def judged(mon: np.ndarray, picks: dict, frm: int, to: int) -> dict:
    """(coin, tf) -> (trades, wins, profit) of each pick over months frm..to."""
    return {k: tuple(float(x) for x in mon[i, frm:to + 1].sum(axis=0))
            for k, (i, _how) in picks.items()}


def walk_forward(mon: np.ndarray, lines: dict, grp: dict) -> dict:
    """(coin, tf) -> [(line, how, trades, wins, profit) or None for months
    1..4]: the pick made again before each month, judged on that month alone."""
    out: dict = {}
    for m in range(1, MONTHS + 1):
        for k, (i, how) in choose(lines, mon, grp, m).items():
            t, w, p = (float(x) for x in mon[i, m])
            out.setdefault(k, [None] * MONTHS)[m - 1] = (i, how, t, w, p)
    return out
