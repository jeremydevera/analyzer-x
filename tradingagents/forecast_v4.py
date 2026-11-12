"""Forecast v4 - Forecast v2's two questions asked of Backtest v4's stored trades.

The operator, Nov 10, 2026: *"in auto trade can you create forecast v4 but this time use my backtest
v4 data"*. Forecast v2 (docs/FORECAST-V2.md) answers "which coins are on a streak" and "which room
rules will make the most this month" from the rooms' replays. This asks both of the Claude skills'
strategies in Backtest v4 (tradingagents/v4_store.py, ~/.tradingagents/v4/rows.db), every trade.

WALKED FORWARD, NEVER LOOKING AHEAD. Every day at 12:00am UTC, from the 1st of the month three
months before the store's last candle to that candle, a rule set switches on every strategy of its
kind (timeframe, skill, TP rule, stop ceiling) whose trades that CLOSED in the W days before that
midnight are at least N and at least X% won; every trade a switched-on strategy OPENED that day
counts, at its stored profit ($5 margin x 20x = $100 of coin; Gate's 0.075% fee each way and the
coin's usual gap are already paid in it). A day's pick reads only trades that closed before the day
began. A month's figure is the trades that OPENED in it.

THE LUCK BAR. "Random picks" are the same number of trades on the same days, each worth the average
trade every strategy of the same kind opened that day whatever its record. "Beat random on A of B
days" counts the days the rule set's own trades made more than that; "could be luck" when that is
not clearly more than half the days (one-sided 95%), or the whole walk did not beat it.

LEFT OUT, and said on the page: the backtesting-trading-strategies skill's rows are its best 3
settings of each coin-timeframe, CHOSEN on their older days (acs, Nov 05, 2026), so their trades
opened before their split are the trades they were chosen on - left out of everything here. The
other skills' rows are every setting, chosen by nobody, so every trade of theirs is used.

NOT A ROOM. No runner can trade a skill strategy (the practice runner trades Backtest v2 rows), so
nothing here switches anything on, and there is no reality check against practice: no practice
account has traded these. Backtest v4 is filed once from finished runs and never updated by itself;
`python -m tradingagents.v4_store build` refreshes the store and then this.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tradingagents import stores, v4_store

DAY_S = 86_400
VERSION = 1
WINDOWS = (7, 15, 30)                 # days judged before each day
WIN_RATES = (0, 50, 60, 70, 80, 90)   # switch on at this win rate or better (percent); 0 = any win rate,
                                      # which only a money rule may use (it then decides alone)
# MONEY RULES (operator, Nov 11, 2026: "currently you are basing the room strategy according to winrate,
# can you create room strategy on your own? like profitable after x trades, or winrate = x && profitable
# after x trades ... dont based on winrate, you can use multiple criteria", then "Just start"). Judged on the
# SAME trades as the win rate - those that closed in the W days before the midnight, at least N of them -
# in whole ten-thousandths of a dollar, so the walk and `switched_on`'s SQL add up the same integers:
#   ""      no money rule (every rule set before Nov 11, 2026: their ids are unchanged)
#   "made"  those trades made money in total, after every fee
#   "pf15"  their wins paid at least $1.50 for every $1 their losses cost (and something was won)
MONEY_RULES = ("", "made", "pf15")
MONEY_WORDS = {"made": "made money over them", "pf15": "won at least $1.50 for every $1 it lost over them"}
MIN_TRADES = (3, 5, 10, 20)           # ... over at least this many trades in those days
TP_RULES = ("any", ">")               # any target (or none) / TP wider than SL
SL_CAPS = (0.0, 1.5)                  # any stop / a stop of 1.5% or tighter (0 = no ceiling)
TFS = ("", "15m", "30m", "1h", "4h", "1d")        # "" = any timeframe
SKILLS = ("", "technical-analysis", "backtesting-frameworks", "backtesting-trading-strategies")
CHOSEN_SKILL = "backtesting-trading-strategies"   # its rows were chosen on their older days
WALK_MONTHS = 3                       # whole months walked before the store's last month
STREAK_MIN = 3                        # the shortest current run kept
FOLLOW_CAP = 15                       # "after a run this long" pools runs of 15 or more
FOLLOW_ENOUGH = 30                    # fewer past cases than this is "not enough to tell"
PER_PAGE = 10                         # ten a page, as every Forecast list (forecast_v2_api.PER_PAGE)
LUCK_Z = 1.645                        # one-sided 95%
RULE_SORTS = ("rank", "predicted", "profit", "per_trade", "beat", "winrate", "trades", "worst_run")


def out_path() -> Path:
    return Path(stores.V4.home) / "forecast.json"


def days_dir() -> Path:
    return Path(stores.V4.home) / "forecast-days"


def dated_copy_path(data_end_s: int) -> Path:
    """One kept copy per UTC day of the store's last candle: `forecast-2026-11-06.json.gz`."""
    day = datetime.fromtimestamp(int(data_end_s), tz=timezone.utc).strftime("%Y-%m-%d")
    return days_dir() / f"forecast-{day}.json.gz"


def keep_dated_copy(text: str, data_end_s: int) -> Path:
    """Write the day's forecast gzipped through a temp file and swap it in. The daily refresh REPLACES
    the store, so the short timeframes' older months cannot be made again later; these copies are what
    keeps them. Nothing here ever deletes one."""
    dst = dated_copy_path(data_end_s)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(text.encode("utf-8"))
    os.replace(tmp, dst)
    return dst


def walk_from(end_s: int) -> int:
    """12:00am UTC on the 1st of the month WALK_MONTHS before the month of the last candle."""
    d = datetime.fromtimestamp(end_s, tz=timezone.utc)
    y, m = d.year, d.month - WALK_MONTHS
    while m < 1:
        y, m = y - 1, m + 12
    return int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())


def month_starts(from_s: int, end_s: int) -> list[int]:
    out, d = [], datetime.fromtimestamp(from_s, tz=timezone.utc)
    y, m = d.year, d.month
    while True:
        s = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())
        if s > end_s:
            return out
        out.append(s)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _money(money) -> str:
    m = money or ""
    if m not in MONEY_RULES:
        raise ValueError(f"unknown money rule {money!r}: one of {', '.join(repr(x) for x in MONEY_RULES)}")
    return m


def grid() -> list[tuple[int, int, str, float]]:
    """Every (window, min trades, money rule, win rate) a kind of strategy is walked with. A win rate of 0
    with no money rule would switch on everything that traded: it is not a rule, so it is not walked."""
    return [(W, N, m, X) for W in WINDOWS for N in MIN_TRADES for m in MONEY_RULES for X in WIN_RATES
            if X or m]


def rule_id(window: int, win_rate: float, min_trades: int, tp_rule: str, sl_cap: float,
            tf: str, skill: str, money: str = "") -> str:
    """Hashed from the rule set itself (CLAUDE.md kit H), never a position on a page. A rule with no
    money rule hashes exactly as before money rules existed, so the rooms' ids never change."""
    from tradingagents import backtest_report as br

    m = _money(money)
    return br._code(f"forecast_v4|w={window}|wr={float(win_rate):g}|n={min_trades}|tp={tp_rule}"
                    f"|sl={float(sl_cap):g}|tf={tf or 'any'}|skill={skill or 'any'}"
                    + (f"|money={m}" if m else ""))


def rule_words(window: int, win_rate: float, min_trades: int, tp_rule: str, sl_cap: float,
               tf: str, skill: str, money: str = "") -> str:
    m = _money(money)
    kind = f"{tf} " if tf else "any-timeframe "
    who = f"Every day, switch on each {kind}strategy{f' from {skill}' if skill else ''} that "
    if not m:
        s = f"{who}won {float(win_rate):g}% or more of at least {min_trades} trades in its last {window} days"
    elif not win_rate:
        s = (f"{who}{MONEY_WORDS[m].replace(' them', '')} at least {min_trades} trades in its last "
             f"{window} days")
    else:
        s = (f"{who}won {float(win_rate):g}% or more of at least {min_trades} trades in its last {window} "
             f"days and {MONEY_WORDS[m]}")
    if tp_rule == ">":
        s += ", TP wider than SL"
    if sl_cap:
        s += f", stop {float(sl_cap):g}% or tighter"
    return s


# ------------------------------------------------------------------ reading the store
END_CODE = v4_store.WHYS.index("END")      # a trade still open when the run ended: its dollars are made up


def _load(db: Path, log) -> dict:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = {k: v for k, v in con.execute("SELECT k, v FROM meta")}
        st = con.execute("SELECT sid, id, coin, tf, label, skill, tp, sl, split_s FROM strat "
                         "ORDER BY sid").fetchall()
        n = (st[-1][0] + 1) if st else 1
        tfc = np.full(n, -1, np.int8)
        skc = np.full(n, -1, np.int8)
        tp = np.full(n, np.nan)
        sl = np.zeros(n)
        split = np.zeros(n, np.int64)
        info: dict[int, tuple] = {}
        for sid, id_, coin, tf, label, skill, tp_, sl_, split_s in st:
            tfc[sid] = TFS.index(tf) - 1 if tf in TFS[1:] else -1
            skc[sid] = SKILLS.index(skill) - 1 if skill in SKILLS[1:] else -1
            tp[sid] = np.nan if tp_ is None else float(tp_)
            sl[sid] = float(sl_)
            split[sid] = int(split_s)
            info[sid] = (id_, coin, tf, label, skill, tp_, float(sl_))
        exists = np.zeros(n, bool)
        exists[[r[0] for r in st]] = True
        chosen = skc == SKILLS.index(CHOSEN_SKILL) - 1
        parts = []
        cur = con.execute("SELECT sid, ex, en, pnl, why FROM trade ORDER BY sid, ex, en")
        got = 0
        while True:
            rows = cur.fetchmany(500_000)
            if not rows:
                break
            parts.append(np.array(rows, dtype=np.float64))
            got += len(rows)
            if got % 2_000_000 < 500_000:
                log(f"forecast v4: read {got:,} trades")
    finally:
        con.close()
    a = np.concatenate(parts) if parts else np.zeros((0, 4))
    sid = a[:, 0].astype(np.int64)
    ex = a[:, 1].astype(np.int64)
    en = a[:, 2].astype(np.int64)
    pnl = a[:, 3].astype(np.float64)
    # A trade still open at the end of a run (why END) is not a finished trade: it never counts towards a
    # window and its made-up dollars are in no month (Nov 10, 2026: 44,174 of 7,145,966 were END)
    open_ = a[:, 4].astype(np.int64) == END_CODE
    keep = (~chosen[sid] | (en >= split[sid])) & ~open_
    left_out = int((~(~chosen[sid] | (en >= split[sid]))).sum())
    left_open = int(open_.sum())
    return {"meta": meta, "info": info, "exists": exists, "tfc": tfc, "skc": skc, "tp": tp, "sl": sl,
            "sid": sid[keep], "ex": ex[keep], "en": en[keep], "pnl": pnl[keep],
            "all_trades": int(len(sid)), "left_out": left_out, "left_open": left_open}


# ------------------------------------------------------------------ the walk
def _figures(m, sub, pool_avg, day_month, covered_m, complete, covered_days, lsid_n, D, M) -> dict:
    p = sub["pnl"][m]
    k = int(p.size)
    pd_ = np.zeros(D)
    cd = np.zeros(D)
    pm = np.zeros(M)
    cm = np.zeros(M, np.int64)
    wm = np.zeros(M, np.int64)
    worst = 0.0
    worst_n = 0
    be = None
    top: list[list] = []
    distinct = 0
    wins = int((p > 0).sum())
    if k:
        day = sub["day"][m]
        mon = sub["month"][m]
        pd_ = np.bincount(day, weights=p, minlength=D)
        cd = np.bincount(day, minlength=D).astype(np.float64)
        pm = np.bincount(mon, weights=p, minlength=M)
        cm = np.bincount(mon, minlength=M)
        wm = np.bincount(mon[p > 0], minlength=M)
        loss = p <= 0
        if loss.any():
            g = np.cumsum(~loss)
            s = np.bincount(g[loss], weights=p[loss])
            c = np.bincount(g[loss])
            j = int(np.argmin(np.where(c > 0, s, np.inf)))
            worst, worst_n = float(s[j]), int(c[j])
        if wins and k - wins:
            aw = float(p[p > 0].mean())
            al = -float(p[p <= 0].mean())
            be = 100.0 * al / (aw + al) if aw + al > 0 else None
        ls = sub["lsid"][m]
        tc = np.bincount(ls, minlength=lsid_n)
        tpf = np.bincount(ls, weights=p, minlength=lsid_n)
        distinct = int((tc > 0).sum())
        best = np.argpartition(-tc, min(5, lsid_n - 1))[:5] if lsid_n > 5 else np.arange(lsid_n)
        best = best[np.argsort(-tc[best], kind="stable")]
        top = [[int(sub["lsid_u"][b]), int(tc[b]), round(float(tpf[b]), 4)] for b in best if tc[b] > 0]
    rd = cd * pool_avg
    rm = np.bincount(day_month, weights=rd, minlength=M)
    traded = cd > 0
    beat_days = int(((pd_ > rd + 1e-9) & traded).sum())
    days_traded = int(traded.sum())
    profit = float(p.sum()) if k else 0.0
    random_profit = float(rd.sum())
    luck = (days_traded < 10 or beat_days <= days_traded / 2 + LUCK_Z * math.sqrt(days_traded) / 2
            or profit <= random_profit)
    months = [{"trades": int(cm[i]), "wins": int(wm[i]), "losses": int(cm[i] - wm[i]),
               "profit": round(float(pm[i]), 4), "random": round(float(rm[i]), 4),
               "covered": bool(covered_m[i]), "complete": bool(complete[i])} for i in range(M)]
    judged = [i for i in range(M) if complete[i] and covered_m[i]]
    predicted = None
    rank = None
    if judged:
        vals = [float(pm[i]) for i in judged]
        predicted = {"profit": round(sum(vals) / len(vals), 4), "low": round(min(vals), 4),
                     "high": round(max(vals), 4), "months": len(judged),
                     "trades": round(sum(int(cm[i]) for i in judged) / len(judged), 1),
                     "thin": len(judged) < 3}
        rank = round(min(vals), 4)
    return {"trades": k, "wins": wins, "losses": k - wins, "profit": round(profit, 4),
            "win_rate": round(100.0 * wins / k, 2) if k else None,
            "per_trade": round(profit / k, 4) if k else None,
            "break_even": round(be, 2) if be is not None else None,
            "worst_run": round(worst, 4), "worst_run_n": worst_n,
            "worst_day": round(float(pd_[traded].min()), 4) if days_traded else None,
            "green_days": int((pd_ > 0).sum()), "days_traded": days_traded, "days_covered": int(covered_days),
            "busiest_day": int(cd.max()) if k else 0,
            "random_profit": round(random_profit, 4),
            "random_per_trade": round(random_profit / k, 4) if k else None,
            "beat_days": beat_days, "luck": bool(luck), "strategies": distinct,
            "months": months, "predicted": predicted, "rank": rank, "top": top}


def _walk(d: dict, end_s: int, log) -> dict:
    sid, ex, en, pnl = d["sid"], d["ex"], d["en"], d["pnl"]
    start = walk_from(end_s)
    D = (end_s - start) // DAY_S + 1
    ms = month_starts(start, end_s)
    M = len(ms)
    nxt = ms[1:] + [month_starts(ms[-1], ms[-1] + 32 * DAY_S)[-1]]
    complete = [n <= end_s for n in nxt]
    key = (sid << 32) | ex
    win = pnl > 0
    cw = np.concatenate(([0], np.cumsum(win, dtype=np.int64)))
    # the money rules add whole ten-thousandths of a dollar (every stored profit has 4 decimals), so a
    # window's sum is exact however large the running total grows - the SQL in `switched_on` adds the same
    p4 = np.rint(pnl * 10_000).astype(np.int64)
    cgw = np.concatenate(([0], np.cumsum(np.where(p4 > 0, p4, 0))))
    cgl = np.concatenate(([0], np.cumsum(np.where(p4 > 0, 0, -p4))))
    del p4
    sel = np.nonzero((en >= start) & (en < start + D * DAY_S))[0]
    sel = sel[np.argsort(ex[sel], kind="stable")]          # closing order, for the losing runs
    j_sid = sid[sel]
    j_day = (en[sel] - start) // DAY_S
    dstart = start + j_day * DAY_S
    t = {"sid": j_sid, "pnl": pnl[sel], "day": j_day,
         "month": np.searchsorted(np.array(ms), en[sel], side="right") - 1,
         "tfc": d["tfc"][j_sid], "skc": d["skc"][j_sid],
         "tpf": ~np.isnan(d["tp"][j_sid]) & (np.nan_to_num(d["tp"][j_sid]) > d["sl"][j_sid]),
         "slc": d["sl"][j_sid] <= 1.5 + 1e-9}
    for W in WINDOWS:
        lo = np.searchsorted(key, (j_sid << 32) | (dstart - W * DAY_S), side="left")
        hi = np.searchsorted(key, (j_sid << 32) | dstart, side="left")      # closed BEFORE the day
        t[f"n{W}"] = (hi - lo).astype(np.int32)
        t[f"w{W}"] = (cw[hi] - cw[lo]).astype(np.int32)
        gw, gl = cgw[hi] - cgw[lo], cgl[hi] - cgl[lo]
        t[f"made{W}"] = gw > gl
        t[f"pf15{W}"] = (2 * gw >= 3 * gl) & (gw > 0)
        del gw, gl
    log(f"forecast v4: {len(sel):,} trades opened from {_fmt(start)} on")
    day_month = np.searchsorted(np.array(ms), start + np.arange(D) * DAY_S, side="right") - 1
    ex_s = d["exists"]
    s_tfc, s_skc, s_tp, s_sl = d["tfc"], d["skc"], d["tp"], d["sl"]
    s_tpf = ~np.isnan(s_tp) & (np.nan_to_num(s_tp) > s_sl)
    rules, seen, dupes, same_as = [], {}, 0, {}
    coverage = {}
    for ti, tf in enumerate(TFS):
        for ki, sk in enumerate(SKILLS):
            sm = np.ones(len(sel), bool)
            stm = ex_s.copy()
            if tf:
                sm &= t["tfc"] == ti - 1
                stm &= s_tfc == ti - 1
            if sk:
                sm &= t["skc"] == ki - 1
                stm &= s_skc == ki - 1
            if not stm.any():
                continue
            idx = np.nonzero(sm)[0]
            sub = t if len(idx) == len(sel) else {k: v[idx] for k, v in t.items()}
            u, inv = np.unique(sub["sid"], return_inverse=True)
            sub = {**sub, "lsid": inv, "lsid_u": u}
            if tf and not sk:
                coverage[tf] = {"strategies": int(stm.sum()), "trades": int(len(idx)),
                                "first_s": int(np.min(en[sel][idx])) if len(idx) else None}
            for tp_rule in TP_RULES:
                for cap in SL_CAPS:
                    kst = stm & (s_tpf if tp_rule == ">" else True) & ((s_sl <= cap + 1e-9) if cap else True)
                    if not kst.any():
                        continue
                    sig = np.packbits(kst).tobytes()
                    if sig in seen:            # the same strategies as a kind already walked
                        kept = seen[sig]
                        for W, N, mr, X in grid():
                            same_as[rule_id(W, X, N, tp_rule, cap, tf, sk, mr)] = rule_id(W, X, N, *kept, mr)
                        dupes += len(grid())
                        continue
                    seen[sig] = (tp_rule, cap, tf, sk)
                    km = np.ones(len(idx), bool)
                    if tp_rule == ">":
                        km &= sub["tpf"]
                    if cap:
                        km &= sub["slc"]
                    pool_c = np.bincount(sub["day"][km], minlength=D).astype(np.float64)
                    pool_p = np.bincount(sub["day"][km], weights=sub["pnl"][km], minlength=D)
                    pool_avg = np.where(pool_c > 0, pool_p / np.maximum(pool_c, 1), 0.0)
                    covered_m = np.bincount(sub["month"][km], minlength=M) > 0
                    covered_days = int((pool_c > 0).sum())
                    no_target = bool((kst & ~s_tpf).any())
                    kind = {"tf": tf, "skill": sk, "tp_rule": tp_rule, "sl_cap": cap,
                            "kind_n": int(kst.sum()),
                            "widest_tp": None if no_target else float(np.nanmax(s_tp[kst])),
                            "widest_sl": float(s_sl[kst].max()),
                            "pool_trades": int(pool_c.sum()),
                            "pool_per_trade": round(float(pool_p.sum() / pool_c.sum()), 4) if pool_c.sum() else None}
                    for W in WINDOWS:
                        n_ = sub[f"n{W}"]
                        w100 = sub[f"w{W}"] * 100
                        for N in MIN_TRADES:
                            base = km & (n_ >= N)
                            for mr in MONEY_RULES:
                                mb = (base & sub[f"{mr}{W}"]) if mr else base
                                for X in WIN_RATES:
                                    if not (X or mr):
                                        continue
                                    m = (mb & (w100 >= X * n_)) if X else mb
                                    f = _figures(m, sub, pool_avg, day_month, covered_m, complete,
                                                 covered_days, len(u), D, M)
                                    rules.append({"id": rule_id(W, X, N, tp_rule, cap, tf, sk, mr),
                                                  "window": W, "min_win_rate": X, "min_trades": N,
                                                  "money": mr,
                                                  "words": rule_words(W, X, N, tp_rule, cap, tf, sk, mr),
                                                  **kind, **f})
            log(f"forecast v4: {tf or 'any timeframe'} / {sk or 'any skill'} walked, {len(rules):,} rule sets")
    info = d["info"]
    for r in rules:
        r["top"] = [{"id": info[s][0], "coin": info[s][1], "tf": info[s][2], "label": info[s][3],
                     "trades": n_, "profit": pr} for s, n_, pr in r["top"]]
    months = [{"key": datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m"), "from_s": s,
               "to_s": min(n_, end_s), "complete": c} for s, n_, c in zip(ms, nxt, complete)]
    return {"rules": rules, "dupes": dupes, "same_as": same_as, "coverage": coverage,
            "walk": {"from_s": start, "to_s": int(end_s), "days": int(D), "months": months,
                     "trades": int(len(sel))}}


def _fmt(s: int) -> str:
    from tradingagents.positions_view import fmt_when

    return fmt_when(s)


# ------------------------------------------------------------------ streaks
STREAK_COLS = ("sid", "win", "length", "started_s", "last_s", "profit", "trades", "wins", "break_even")


def _streaks(d: dict) -> dict:
    sid, ex, en, pnl = d["sid"], d["ex"], d["en"], d["pnl"]
    n = len(sid)
    if not n:
        return {"rows": [], "follow": {}}
    win = pnl > 0
    new_sid = np.r_[True, sid[1:] != sid[:-1]]
    change = new_sid | np.r_[True, win[1:] != win[:-1]]
    run_id = np.cumsum(change) - 1
    run_start = np.nonzero(change)[0]
    pos = np.arange(n) - run_start[run_id] + 1
    first = np.nonzero(new_sid)[0]
    last = np.r_[first[1:] - 1, n - 1]
    grp = np.cumsum(new_sid) - 1
    gend = last[grp]
    cs = np.concatenate(([0.0], np.cumsum(pnl)))
    cw = np.concatenate(([0], np.cumsum(win, dtype=np.int64)))
    csw = np.concatenate(([0.0], np.cumsum(np.where(win, pnl, 0.0))))
    # what happened after past runs this long: the trade after each point a run reached k
    i = np.nonzero(np.arange(n) < gend)[0]
    kk = np.minimum(pos[i], FOLLOW_CAP)
    code = win[i].astype(np.int64) * (FOLLOW_CAP + 1) + kk
    size = 2 * (FOLLOW_CAP + 1)
    cases = np.bincount(code, minlength=size)
    nw = np.bincount(code, weights=win[i + 1].astype(np.float64), minlength=size)
    h10 = i + 10 <= gend[i]
    n10 = np.bincount(code[h10], minlength=size)
    s10 = np.bincount(code[h10], weights=(cs[i[h10] + 11] - cs[i[h10] + 1]), minlength=size)
    follow = {}
    for w in (0, 1):
        for k in range(1, FOLLOW_CAP + 1):
            c = w * (FOLLOW_CAP + 1) + k
            follow[f"{'win' if w else 'loss'}{k}"] = {
                "k": k, "cases": int(cases[c]), "capped": k == FOLLOW_CAP,
                "next_win": round(100.0 * nw[c] / cases[c], 1) if cases[c] else None,
                "next10": round(float(s10[c] / n10[c]), 4) if n10[c] else None,
                "enough": int(cases[c]) >= FOLLOW_ENOUGH}
    L = pos[last]
    keep = L >= STREAK_MIN
    rows = []
    for g in np.nonzero(keep)[0]:
        a, b = first[g], last[g]
        rs = run_start[run_id[b]]
        tr = b - a + 1
        w_ = int(cw[b + 1] - cw[a])
        ws = csw[b + 1] - csw[a]
        ls = (cs[b + 1] - cs[a]) - ws
        be = None
        if w_ and tr - w_:
            aw, al = ws / w_, -ls / (tr - w_)
            be = round(100.0 * al / (aw + al), 2) if aw + al > 0 else None
        rows.append([int(sid[b]), int(win[b]), int(L[g]), int(en[rs]), int(ex[b]),
                     round(float(cs[b + 1] - cs[rs]), 4), int(tr), w_, be])
    return {"rows": rows, "follow": follow}


# ------------------------------------------------------------------ build
def build(db: Path | None = None, out: Path | None = None, log=print) -> dict:
    """Walk every rule set and find every streak, then write the whole answer in one swap."""
    db = Path(db) if db else v4_store.db_path()
    out = Path(out) if out else out_path()
    if not db.exists():
        raise RuntimeError(f"no Backtest v4 store at {db}: run python -m tradingagents.v4_store build first")
    t0 = time.time()
    d = _load(db, log)
    meta = d["meta"]
    end_s = int(meta.get("data_end_s") or (int(d["ex"].max()) if len(d["ex"]) else 0))
    if not len(d["sid"]) or not end_s:
        raise RuntimeError("Backtest v4 holds no trades: nothing to forecast")
    walk = _walk(d, end_s, log)
    streak = _streaks(d)
    info = d["info"]
    srows = [[info[r[0]][0], info[r[0]][1], info[r[0]][2], info[r[0]][3], info[r[0]][4],
              info[r[0]][5], info[r[0]][6], *r[1:]] for r in streak["rows"]]
    rules = walk["rules"]
    doc = {
        "version": VERSION, "built_s": int(time.time()), "seconds": round(time.time() - t0, 1),
        "store": {"built_s": int(meta.get("built_s", 0) or 0), "data_end_s": end_s,
                  "strategies": int(meta.get("strategies", 0) or 0),
                  "trades": int(meta.get("trades", 0) or 0),
                  "sources": json.loads(meta.get("sources", "{}") or "{}"),
                  "margin": v4_store.MEASURED_MARGIN, "leverage": v4_store.LEVERAGE},
        "used": {"trades": int(len(d["sid"])), "left_out": d["left_out"], "left_open": d["left_open"],
                 "left_open_why": "trades still open when their run ended: not finished, so never counted",
                 "left_out_why": (f"the {CHOSEN_SKILL} skill's trades opened before their split: its rows "
                                  "are its best 3 settings, chosen on those trades")},
        "walk": walk["walk"], "coverage": walk["coverage"],
        "grid": {"windows": list(WINDOWS), "win_rates": list(WIN_RATES), "min_trades": list(MIN_TRADES),
                 "money": list(MONEY_RULES), "money_words": MONEY_WORDS,
                 "tp_rules": list(TP_RULES), "sl_caps": list(SL_CAPS), "tfs": list(TFS),
                 "skills": list(SKILLS), "tested": len(rules), "same_as_another": walk["dupes"]},
        "rules": rules, "same_as": walk["same_as"],
        "streaks": {"cols": ["id", "coin", "tf", "label", "skill", "tp", "sl", *STREAK_COLS[1:]],
                    "rows": srows, "min": STREAK_MIN},
        "follow": streak["follow"],
    }
    from tradingagents.forecast_v2 import publish

    text = json.dumps(doc, separators=(",", ":"))
    publish(out, text)
    kept = keep_dated_copy(text, end_s) if out == out_path() else None
    log(f"forecast v4: {len(rules):,} rule sets and {len(srows):,} streaks written to {out} "
        f"in {doc['seconds']:.0f} s" + (f"; dated copy {kept}" if kept else ""))
    return {k: doc[k] for k in ("built_s", "seconds", "store", "used", "walk", "grid")}


# ------------------------------------------------------------------ what a rule set switches on
def switched_on(rule: dict, at_s: int, db: Path | None = None) -> list[dict]:
    """The strategies `rule` switches on at midnight `at_s` - the walk's own arithmetic (`_walk`), asked
    of one midnight. `rule` carries `rule_id`'s parameter names: window, win_rate, min_trades, tp_rule,
    sl_cap, tf, skill and money (absent = none). A strategy is on when the trades that CLOSED in
    [at_s - window days, at_s) (a
    trade's CLOSE is the window clock; END trades and the chosen skill's trades opened before its split
    are not counted, as in `_load`) number at least min_trades and won (pnl above 0) win_rate percent or
    more, pass its money rule (MONEY_RULES, added in whole ten-thousandths of a dollar as the walk
    adds them), and its kind passes: tf, skill, TP wider than SL (a strategy with no target fails it) and a
    stop of sl_cap percent or tighter (0 = no ceiling). Each row: sid, id, coin, tf, strategy, label,
    skill, params (dict), stop (a fraction), target (a fraction or None), fee, slip, n, wins."""
    db = Path(db) if db else v4_store.db_path()
    window = int(rule["window"])
    tp_rule = rule.get("tp_rule", "any")
    cap = float(rule.get("sl_cap") or 0)
    tf = rule.get("tf") or ""
    skill = rule.get("skill") or ""
    money = _money(rule.get("money"))
    lo, hi = int(at_s) - window * DAY_S, int(at_s)
    where = ["t.ex >= ?", "t.ex < ?", "t.why <> ?", "(s.skill <> ? OR t.en >= s.split_s)"]
    args: list = [lo, hi, END_CODE, CHOSEN_SKILL]
    if tf:
        where.append("s.tf = ?")
        args.append(tf)
    if skill:
        where.append("s.skill = ?")
        args.append(skill)
    if tp_rule == ">":
        where.append("s.tp IS NOT NULL AND s.tp > s.sl")
    if cap:
        where.append("s.sl <= ?")
        args.append(cap + 1e-9)
    p4 = "CAST(ROUND(t.pnl * 10000) AS INTEGER)"
    having = "k_n >= ? AND k_wins * 100 >= ? * k_n"
    if money == "made":
        having += f" AND SUM({p4}) > 0"
    elif money == "pf15":
        having += (f" AND k_wins > 0 AND 2 * SUM(CASE WHEN t.pnl > 0 THEN {p4} ELSE 0 END)"
                   f" >= 3 * SUM(CASE WHEN t.pnl > 0 THEN 0 ELSE -{p4} END)")
    sql = ("SELECT s.sid, s.id, s.coin, s.tf, s.strategy, s.label, s.skill, s.params, s.tp, s.sl, s.fee, "
           "s.slip, COUNT(*) AS k_n, SUM(t.pnl > 0) AS k_wins FROM strat s JOIN trade t ON t.sid = s.sid "
           "WHERE " + " AND ".join(where) + " GROUP BY s.sid HAVING " + having + " "
           "ORDER BY s.sid")      # k_*: never `wins`, which is also a column of strat
    args += [int(rule["min_trades"]), float(rule["win_rate"])]
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        got = con.execute(sql, args).fetchall()
    finally:
        con.close()
    return [{"sid": r[0], "id": r[1], "coin": r[2], "tf": r[3], "strategy": r[4], "label": r[5],
             "skill": r[6], "params": json.loads(r[7]), "stop": r[9] / 100.0,
             "target": None if r[8] is None else r[8] / 100.0, "fee": r[10], "slip": r[11],
             "n": int(r[12]), "wins": int(r[13])} for r in got]


# ------------------------------------------------------------------ reading it back
_CACHE: dict = {"key": None, "doc": None}
_LOCK = threading.Lock()


def load(path: Path | None = None) -> dict | None:
    p = Path(path) if path else out_path()
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _CACHE["key"] != key:
            doc = json.loads(p.read_text(encoding="utf-8"))
            if doc.get("version") != VERSION:
                return None
            _CACHE.update(key=key, doc=doc)
        return _CACHE["doc"]


def _not_ready() -> dict:
    return {"ready": False,
            "why": ("Forecast v4 has not been worked out yet: run python -m tradingagents.forecast_v4 build "
                    "(or python -m tradingagents.v4_store build, which builds Backtest v4 and then this)")}


def summary() -> dict:
    doc = load()
    if doc is None:
        return _not_ready()
    rules = doc["rules"]
    traded = [r for r in rules if r["trades"]]
    rows = doc["streaks"]["rows"]
    wi = doc["streaks"]["cols"].index("win")
    return {"ready": True, "built_s": doc["built_s"], "seconds": doc["seconds"], "store": doc["store"],
            "used": doc["used"], "walk": doc["walk"], "coverage": doc["coverage"], "grid": doc["grid"],
            "counts": {"rules": len(rules), "traded": len(traded),
                       "made_money": sum(1 for r in traded if r["profit"] > 0),
                       "not_luck": sum(1 for r in traded if not r["luck"]),
                       "win_streaks": sum(1 for r in rows if r[wi]),
                       "loss_streaks": sum(1 for r in rows if not r[wi])},
            "defaults": {"win_n": 5, "loss_m": 5, "recent": 7},
            "per_page": PER_PAGE}


def _num(v, default=0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


MONEY = ("profit", "per_trade", "worst_run", "worst_day", "random_profit", "random_per_trade", "rank")


def _scaled(r: dict, k: float) -> dict:
    if k == 1.0:
        return r
    o = dict(r)
    for f in MONEY:
        if o.get(f) is not None:
            o[f] = round(o[f] * k, 4)
    o["months"] = [{**m, "profit": round(m["profit"] * k, 4), "random": round(m["random"] * k, 4)}
                   for m in r["months"]]
    if r.get("predicted"):
        o["predicted"] = {**r["predicted"], **{f: round(r["predicted"][f] * k, 4)
                                               for f in ("profit", "low", "high")}}
    o["top"] = [{**t, "profit": round(t["profit"] * k, 4)} for t in r["top"]]
    if r.get("pool_per_trade") is not None:
        o["pool_per_trade"] = round(r["pool_per_trade"] * k, 4)
    return o


def _sort_value(sort: str):
    def f(r):
        if sort == "rank":           # judged on every whole month first: one good month is no "worst month"
            return None if r["rank"] is None else (0 if (r["predicted"] or {}).get("thin") else 1, r["rank"])
        if sort == "predicted":
            return (r["predicted"] or {}).get("profit")
        if sort == "beat":
            return (r["beat_days"] / r["days_traded"]) if r["days_traded"] else None
        if sort == "winrate":
            return r["win_rate"]
        return r.get(sort)
    return f


def rules_page(q: dict) -> dict:
    """The rule sets, filtered, sorted and paged HERE (never in the browser). Keys, all optional:
    window, tf, skill, tp_rule, money ("none" = win rate alone, or one of MONEY_RULES), max_tp, max_sl
    (ceilings on the widest target / stop the rule set
    can switch on, inclusive; a rule set that can switch on a strategy with no target is left out by
    max_tp), min_winrate (of its trades), min_trades, min_profit (dollars at the base margin),
    profitable, not_luck, traded, q (an id: overrides every other filter), base_margin, sort, desc,
    page."""
    doc = load()
    if doc is None:
        return {**_not_ready(), "rows": [], "total": 0, "page": 1, "pages": 1}
    k = max(_num(q.get("base_margin"), 5.0), 0.01) / v4_store.MEASURED_MARGIN
    rules = doc["rules"]
    named: list[str] = []
    want = str(q.get("q") or "").strip().lstrip("#").upper()
    if want:
        twin = doc.get("same_as", {}).get(want)
        got = [r for r in rules if r["id"] == (twin or want)]
        named.append(f"id #{want}" + (f" - the same rule set as #{twin}: it switches on exactly the same "
                                       "strategies, so it is listed once" if twin else ""))
    else:
        got = rules
        w = int(_num(q.get("window"), 0))
        if w:
            got = [r for r in got if r["window"] == w]
            named.append(f"judged on {w} days")
        if q.get("tf") is not None and str(q.get("tf")) != "":
            tf = "" if q["tf"] == "any" else str(q["tf"])
            got = [r for r in got if r["tf"] == tf]
            named.append(f"{tf or 'any timeframe'} rule sets")
        if q.get("skill") is not None and str(q.get("skill")) != "":
            sk = "" if q["skill"] == "any" else str(q["skill"])
            got = [r for r in got if r["skill"] == sk]
            named.append(f"{sk or 'any skill'} rule sets")
        if q.get("tp_rule") in TP_RULES:
            got = [r for r in got if r["tp_rule"] == q["tp_rule"]]
            named.append("TP wider than SL" if q["tp_rule"] == ">" else "any TP")
        mq = str(q.get("money") or "")
        if mq == "none":
            got = [r for r in got if not r.get("money")]
            named.append("judged on win rate alone")
        elif mq in MONEY_RULES[1:]:
            got = [r for r in got if r.get("money") == mq]
            named.append("money rule: " + MONEY_WORDS[mq].replace(" over them", "") + " in its judged days")
        mtp = _num(q.get("max_tp"), 0)
        if mtp > 0:
            got = [r for r in got if r["widest_tp"] is not None and r["widest_tp"] <= mtp + 1e-9]
            named.append(f"TP {mtp:g}% or smaller")
        msl = _num(q.get("max_sl"), 0)
        if msl > 0:
            got = [r for r in got if r["widest_sl"] <= msl + 1e-9]
            named.append(f"SL {msl:g}% or tighter")
        mwr = _num(q.get("min_winrate"), 0)
        if mwr > 0:
            got = [r for r in got if (r["win_rate"] or 0) >= mwr - 1e-9]
            named.append(f"won {mwr:g}% or more")
        mtr = int(_num(q.get("min_trades"), 0))
        if mtr > 0:
            got = [r for r in got if r["trades"] >= mtr]
            named.append(f"{mtr}+ trades")
        if q.get("min_profit") not in (None, ""):
            mp = _num(q.get("min_profit"), 0)
            got = [r for r in got if r["profit"] * k >= mp - 1e-9]
            named.append(f"made at least ${mp:g}")
        if _truthy(q.get("profitable")):
            got = [r for r in got if r["profit"] > 0]
            named.append("made money")
        if _truthy(q.get("not_luck")):
            got = [r for r in got if r["trades"] and not r["luck"]]
            named.append("beat random by more than luck")
        if _truthy(q.get("traded", True)):
            got = [r for r in got if r["trades"]]
            named.append("traded")
    sort = q.get("sort") if q.get("sort") in RULE_SORTS else "rank"
    desc = True if q.get("desc") in (None, "") else _truthy(q.get("desc"))
    val = _sort_value(sort)
    have = [r for r in got if r["trades"] and val(r) is not None]
    rest = [r for r in got if not (r["trades"] and val(r) is not None)]
    # either way round, a rule set with nothing to sort on (no trade, no whole month) goes last
    got = sorted(have, key=val, reverse=desc) + sorted(rest, key=lambda r: -r["trades"])
    total = len(got)
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, int(_num(q.get("page"), 1))), pages)
    rows = [_scaled(r, k) for r in got[(page - 1) * PER_PAGE: page * PER_PAGE]]
    why = ""
    if not total:
        why = (f"none of the {len(rules):,} rule sets walked matched"
               f"{(' ' + ', '.join(named)) if named else ''} - every rule set was examined")
    return {"ready": True, "rows": rows, "total": total, "of": len(rules), "page": page, "pages": pages,
            "per_page": PER_PAGE, "filters": named, "sort": sort, "desc": desc, "why": why,
            "base_margin": round(k * v4_store.MEASURED_MARGIN, 4)}


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def streaks_page(q: dict) -> dict:
    """The strategies whose newest trades are a run of wins (kind=win) or losses, at least `min` long,
    their last trade within `recent` days of the store's last candle (0 = any), filtered by tf,
    skill and q (a coin or an #id), ten a page, longest first."""
    doc = load()
    if doc is None:
        return {**_not_ready(), "rows": [], "total": 0, "page": 1, "pages": 1}
    k = max(_num(q.get("base_margin"), 5.0), 0.01) / v4_store.MEASURED_MARGIN
    cols = doc["streaks"]["cols"]
    ix = {c: i for i, c in enumerate(cols)}
    kind = 1 if str(q.get("kind") or "win") == "win" else 0
    least = max(int(_num(q.get("min"), 5)), 1)
    recent = int(_num(q.get("recent"), 7))
    end_s = doc["store"]["data_end_s"]
    rows = doc["streaks"]["rows"]
    got = [r for r in rows if r[ix["win"]] == kind and r[ix["length"]] >= least]
    named = [f"{least}+ {'wins' if kind else 'losses'} in a row"]
    if recent > 0:
        got = [r for r in got if r[ix["last_s"]] > end_s - recent * DAY_S]
        named.append(f"last trade in the last {recent} days of the data")
    tf = str(q.get("tf") or "")
    if tf:
        got = [r for r in got if r[ix["tf"]] == tf]
        named.append(tf)
    sk = str(q.get("skill") or "")
    if sk:
        got = [r for r in got if r[ix["skill"]] == sk]
        named.append(sk)
    want = str(q.get("q") or "").strip().upper()
    if want:
        idw = want.lstrip("#")
        got = [r for r in got if r[ix["id"]] == idw or want in str(r[ix["coin"]]).upper()]
        named.append(f"matching {want}")
    got.sort(key=lambda r: (r[ix["length"]], r[ix["last_s"]]), reverse=True)
    total = len(got)
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, int(_num(q.get("page"), 1))), pages)
    follow = doc["follow"]
    out = []
    for r in got[(page - 1) * PER_PAGE: page * PER_PAGE]:
        d = {c: r[i] for c, i in ix.items()}
        d["win"] = bool(d["win"])
        d["profit"] = round(d["profit"] * k, 4)
        d["win_rate"] = round(100.0 * d["wins"] / d["trades"], 2) if d["trades"] else None
        d["follow"] = follow.get(f"{'win' if kind else 'loss'}{min(d['length'], FOLLOW_CAP)}")
        out.append(d)
    of = sum(1 for r in rows if r[ix["win"]] == kind)
    why = "" if total else (f"none of the {of:,} {'winning' if kind else 'losing'} runs of "
                            f"{doc['streaks']['min']}+ matched {', '.join(named)} - every one was examined")
    return {"ready": True, "rows": out, "total": total, "of": of, "page": page, "pages": pages,
            "per_page": PER_PAGE, "filters": named, "why": why, "data_end_s": end_s,
            "base_margin": round(k * v4_store.MEASURED_MARGIN, 4)}


def main(argv: list[str] | None = None) -> int:
    import sys

    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["build"]:
        print(json.dumps(build(), indent=1))
        return 0
    if args[:1] == ["status"]:
        print(json.dumps({k: v for k, v in summary().items() if k != "grid"}, indent=1))
        return 0
    print("usage: python -m tradingagents.forecast_v4 build | status")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
