"""THE PRO TRADER RESEARCH, READ (Oct 20, 2026): pick on older days, judge on
days never seen. Design: docs/superpowers/specs/2026-10-20-pro-trader-research-design.md.

Every measured line (pro_search.read_lines) is one coin x timeframe x setting x
stop/target with its whole deep window and its four test months (the trades
that CLOSED in the last 30, 60, 90, 120 days). From those numbers alone:

* MONTHS: month 4 is the newest 30 days, month 1 the oldest of the four; the
  choosing days are everything closed before the month being judged.
* GROUPS: coins grouped by what they ARE, measured before the test months
  (pro_shard.coin_stats): asset kind, daily volatility third, trending or
  snapping back. A group too small to judge joins its wider group.
* THE CHOICE for a coin and timeframe, from choosing days only: its group's
  default (the setting + stop/target that made the most over the group's
  coins), or the coin's own best when that beat the default on the coin's own
  choosing days. Only settings that pay at least 2:1 after the coin's fees.
* THE MAIN TEST: one choice from the days before all four months, judged on
  the four months (120 days). THE WALK-FORWARD: the choice made again before
  each month from everything closed before it, each month judged by its own.
* THE CHECKS each row must pass (`checks`), on its untouched days.

Nothing here switches anything on.
"""
from __future__ import annotations

import math

import numpy as np

F = {k: i for i, k in enumerate((
    "trades", "wins", "profit", "t30", "w30", "p30", "t60", "w60", "p60",
    "t90", "w90", "p90", "t120", "w120", "p120", "rt_paid", "pay2", "streak", "dd"))}
MONTHS = 4
MIN_GROUP = 8              # coins a group needs to have its own default
GROUP_MIN_TRADES = 30      # a group default needs this many choosing trades...
GROUP_MIN_WINS = 10        # ...and wins, across the group
OWN_MIN_TRADES = 15        # a coin's own pick needs this many on its own...
OWN_MIN_WINS = 5
OWN_MARGIN = 1.0           # ...and must beat the group default by $1 there
MIN_WINS = 20              # wins a row needs on its untouched days to pass
STOP_WORSE = 0.10          # $ a losing trade costs when its stop fills 0.1% worse


def months(lines: dict) -> np.ndarray:
    """[line, k, (trades, wins, profit)] for k = 0 (before the four months),
    1..4 (oldest -> newest test month)."""
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


def groups(stats: dict) -> dict:
    """coin -> its group name. kind (crypto / stocks / other) x volatility
    third within the kind x trending (variance ratio >= 1) or snapping back;
    a group under MIN_GROUP coins drops its trend half, then its volatility
    third."""
    kinds = {}
    for coin, s in stats.items():
        if not isinstance(s, dict) or s.get("vol") is None or s.get("error") or s.get("why"):
            continue
        k = s.get("kind") or "crypto"
        kinds.setdefault("crypto" if k == "crypto" else "stocks" if k == "stocks" else "other",
                         []).append(coin)
    full: dict = {}
    for kind, coins in kinds.items():
        vols = sorted(float(stats[c]["vol"]) for c in coins)
        cuts = (vols[len(vols) // 3], vols[(2 * len(vols)) // 3]) if len(vols) >= 3 else (math.inf, math.inf)
        for c in coins:
            vol = float(stats[c]["vol"])
            third = "quiet" if vol < cuts[0] else "middle" if vol < cuts[1] else "wild"
            vr = stats[c].get("vr")
            trend = "trending" if vr is not None and not math.isnan(float(vr)) and float(vr) >= 1 else "snapping-back"
            full[c] = (kind, third, trend)
    size3 = {}
    for g in full.values():
        size3[g] = size3.get(g, 0) + 1
    size2 = {}
    for g in full.values():
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


def choose(lines: dict, mon: np.ndarray, grp: dict, upto: int) -> dict:
    """(coin index, tf index) -> (line index, how) from the choosing days
    before month `upto` (1 = before all four months ... 4 = before the newest).
    `how` is "group default" or "own pick". Only lines that pay 2:1 after the
    coin's own fees are candidates."""
    hist = mon[:, :upto].sum(axis=1)                    # trades, wins, profit
    cand = lines["vals"][:, F["pay2"]] > 0
    coins = lines["coins"]
    c_ix, tf_ix = lines["coin"], lines["tf"]
    cfg = lines["var"].astype(np.int64) * 64 + lines["bar"].astype(np.int64)
    gname = np.array([grp.get(coins[i], "") for i in range(len(coins))], dtype=object)[c_ix] \
        if len(c_ix) else np.zeros(0, dtype=object)
    out: dict = {}
    # the group defaults, one per (group, timeframe)
    defaults: dict = {}
    sel = np.where(cand & (gname != ""))[0]
    keys: dict = {}
    for i in sel:
        k = (gname[i], int(tf_ix[i]), int(cfg[i]))
        a = keys.setdefault(k, [0.0, 0.0, 0.0])
        a[0] += hist[i, 0]
        a[1] += hist[i, 1]
        a[2] += hist[i, 2]
    for (g, tf, c), (t, w, p) in keys.items():
        if t < GROUP_MIN_TRADES or w < GROUP_MIN_WINS:
            continue
        best = defaults.get((g, tf))
        if best is None or (p, t) > (best[1], best[2]):
            defaults[(g, tf)] = (c, p, t)
    # each coin and timeframe
    by_pair: dict = {}
    for i in np.where(cand)[0]:
        by_pair.setdefault((int(c_ix[i]), int(tf_ix[i])), []).append(i)
    for (ci, tf), idx in by_pair.items():
        g = grp.get(coins[ci], "")
        dflt = defaults.get((g, tf))
        mine = [i for i in idx if hist[i, 0] >= OWN_MIN_TRADES and hist[i, 1] >= OWN_MIN_WINS]
        own = max(mine, key=lambda i: (hist[i, 2], hist[i, 0])) if mine else None
        d_line = None
        if dflt is not None:
            hit = [i for i in idx if cfg[i] == dflt[0]]
            d_line = hit[0] if hit else None
        if own is not None and (d_line is None or hist[own, 2] > hist[d_line, 2] + OWN_MARGIN):
            out[(ci, tf)] = (int(own), "own pick")
        elif d_line is not None:
            out[(ci, tf)] = (int(d_line), "group default")
    return out


def judged(mon: np.ndarray, picks: dict, frm: int, to: int) -> dict:
    """(coin, tf) -> (trades, wins, profit) of each pick over months frm..to."""
    return {k: tuple(float(x) for x in mon[i, frm:to + 1].sum(axis=0)) for k, (i, _how) in picks.items()}


def walk_forward(mon: np.ndarray, lines: dict, grp: dict) -> dict:
    """(coin, tf) -> [(line, how, trades, wins, profit) for months 1..4]: the
    pick made again before each month, judged on that month alone."""
    out: dict = {}
    for m in range(1, MONTHS + 1):
        for k, (i, how) in choose(lines, mon, grp, m).items():
            t, w, p = (float(x) for x in mon[i, m])
            out.setdefault(k, [None] * MONTHS)[m - 1] = (i, how, t, w, p)
    return out
