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
import re
import shutil
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
# Cheap coins only (Nov 13, 2026): a strategy whose round trip costs more than this many dollars per $100
# traded ($100 x (2 x fee + 2 x its coin's gap), the store row's own numbers) is left out; 0 = no cap. A
# fee or gap the store does not know is never cheap. Bought by the Backtest v4 check: unseen trades made
# +$0.08 a trade before costs and -$1.06 after; coins at $0.25 or less -$0.22 (older days -$0.07).
COST_CAPS = (0.0, 0.25)
TFS = ("", "15m", "30m", "1h", "4h", "1d")        # "" = any timeframe
SKILLS = ("", "technical-analysis", "backtesting-frameworks", "backtesting-trading-strategies")
CHOSEN_SKILL = "backtesting-trading-strategies"   # its rows were chosen on their older days
WALK_MONTHS = 3                       # whole months walked before the store's last month
STREAK_MIN = 3                        # the shortest current run kept
FOLLOW_CAP = 15                       # "after a run this long" pools runs of 15 or more
FOLLOW_ENOUGH = 30                    # fewer past cases than this is "not enough to tell"
PER_PAGE = 10                         # ten a page, as every Forecast list (forecast_v2_api.PER_PAGE)
LUCK_Z = 1.645                        # one-sided 95%
RULE_SORTS = ("rank", "predicted", "profit", "per_trade", "beat", "winrate", "trades", "worst_run",
              # AT REAL PRICES (Nov 13, 2026): over the trades whose two fills both paid the app's own
              # recorded order book of their minute - the figure the estimate cannot flatter
              "real_profit", "real_per_trade")


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
            tf: str, skill: str, money: str = "", cost_cap: float = 0.0) -> str:
    """Hashed from the rule set itself (CLAUDE.md kit H), never a position on a page. A rule with no
    money rule and no cost cap hashes exactly as before either existed, so the rooms' ids never change."""
    from tradingagents import backtest_report as br

    m = _money(money)
    return br._code(f"forecast_v4|w={window}|wr={float(win_rate):g}|n={min_trades}|tp={tp_rule}"
                    f"|sl={float(sl_cap):g}|tf={tf or 'any'}|skill={skill or 'any'}"
                    + (f"|money={m}" if m else "")
                    + (f"|cost={float(cost_cap):g}" if float(cost_cap or 0) else ""))


def rule_words(window: int, win_rate: float, min_trades: int, tp_rule: str, sl_cap: float,
               tf: str, skill: str, money: str = "", cost_cap: float = 0.0) -> str:
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
    if float(cost_cap or 0):
        s += f", only on coins costing ${float(cost_cap):.2f} or less per $100 traded"
    return s


# ------------------------------------------------------------------ reading the store
END_CODE = v4_store.WHYS.index("END")      # a trade still open when the run ended: its dollars are made up


def _load(db: Path, log, extra: bool = False) -> dict:
    """Every trade the forecast may count, in the store's own order. `extra` also keeps each one's exit
    kind, side and exit minute ("why", "side", "at" - the candle's time where the store has no minute):
    the picker lab prints them in its trade logs; nothing in the forecast reads them. Either way each
    trade carries its mark (`real`: how many of its two fills paid a recorded order book; 0 for every
    trade of a store built before Nov 13, 2026)."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        meta = {k: v for k, v in con.execute("SELECT k, v FROM meta")}
        st = con.execute("SELECT sid, id, coin, tf, label, skill, tp, sl, split_s, fee, slip FROM strat "
                         "ORDER BY sid").fetchall()
        n = (st[-1][0] + 1) if st else 1
        tfc = np.full(n, -1, np.int8)
        skc = np.full(n, -1, np.int8)
        tp = np.full(n, np.nan)
        sl = np.zeros(n)
        split = np.zeros(n, np.int64)
        cost = np.full(n, np.inf)          # dollars a round trip per $100; unknown = never cheap
        info: dict[int, tuple] = {}
        for sid, id_, coin, tf, label, skill, tp_, sl_, split_s, fee_, slip_ in st:
            if fee_ is not None and slip_ is not None:
                cost[sid] = 100.0 * (2 * float(fee_) + 2 * float(slip_))
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
        have = {r[1] for r in con.execute("PRAGMA table_info(trade)")}
        # each trade's mark: how many of its two fills paid a recorded order book (a store built before
        # Nov 13, 2026 has none: every trade an estimate)
        more = ", real" if "real" in have else ", 0"
        if extra:
            more += ", side, " + ("COALESCE(at, ex)" if "at" in have else "ex")
        cur = con.execute("SELECT sid, ex, en, pnl, why" + more + " FROM trade ORDER BY sid, ex, en")
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
    a = np.concatenate(parts) if parts else np.zeros((0, 8 if extra else 6))
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
    out = {"meta": meta, "info": info, "exists": exists, "tfc": tfc, "skc": skc, "tp": tp, "sl": sl,
           "cost": cost,
           "sid": sid[keep], "ex": ex[keep], "en": en[keep], "pnl": pnl[keep],
           "real": a[:, 5].astype(np.int8)[keep],
           "all_trades": int(len(sid)), "left_out": left_out, "left_open": left_open}
    if extra:
        out.update(why=a[:, 4].astype(np.int8)[keep], side=a[:, 6].astype(np.int8)[keep],
                   at=a[:, 7].astype(np.int64)[keep])
    return out


# ------------------------------------------------------------------ the walk
def could_be_luck(days_traded, beat_days, profit, random_profit):
    """THE LUCK BAR in one place: "could be luck" when it traded on fewer than 10 days, did not beat
    random picks on clearly more than half of them (one-sided 95%), or did not beat them over the whole
    walk. Works on plain numbers and on numpy arrays alike (the picker lab asks it of every rule set
    at once)."""
    return ((days_traded < 10) | (beat_days <= days_traded / 2 + LUCK_Z * np.sqrt(days_traded) / 2)
            | (profit <= random_profit))


def _figures(m, sub, pool_avg, day_month, covered_m, complete, covered_days, lsid_n, D, M) -> dict:
    p = sub["pnl"][m]
    k = int(p.size)
    pd_ = np.zeros(D)
    cd = np.zeros(D)
    wd = np.zeros(D, np.int64)
    pm = np.zeros(M)
    cm = np.zeros(M, np.int64)
    wm = np.zeros(M, np.int64)
    worst = 0.0
    worst_n = 0
    be = None
    top: list[list] = []
    distinct = 0
    wins = int((p > 0).sum())
    real_n = real_w = 0
    real_p = 0.0
    if k:
        rp = p[sub["real"][m]]          # the trades whose two fills both paid a recorded order book
        real_n, real_w, real_p = int(rp.size), int((rp > 0).sum()), float(rp.sum())
        day = sub["day"][m]
        mon = sub["month"][m]
        pd_ = np.bincount(day, weights=p, minlength=D)
        cd = np.bincount(day, minlength=D).astype(np.float64)
        wd = np.bincount(day[p > 0], minlength=D)
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
    luck = bool(could_be_luck(days_traded, beat_days, profit, random_profit))
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
            "months": months, "predicted": predicted, "rank": rank, "top": top,
            # AT REAL PRICES: its result over the real-priced trades alone. Blank (None), never $0.00,
            # when it has none - everything before Oct 17, 2026 and every fill with no reading
            "real_trades": real_n, "real_wins": real_w,
            "real_profit": round(real_p, 4) if real_n else None,
            "real_per_trade": round(real_p / real_n, 4) if real_n else None,
            # the calendar's boxes (taken out by `_walk` before the rule is kept): trades, wins and
            # profit on each walked day, the same trades the months add
            "_days": (cd, wd, pd_)}


def _walk(d: dict, end_s: int, log, visit=None, keep: bool = False) -> dict:
    """`visit(rule, m, sub, km)`, when given, is called once for every rule set walked, with the very mask
    `m` of the trades it took (over `sub`, the walked trades of its kind; `sub["row"]` is each one's place
    in `d`'s arrays) and `km`, every trade of its kind - so the picker lab (`v4_picker_lab`) reads the
    same trades this walk counts, never a second copy of the rules. It changes nothing written here.

    The answer carries every rule set's figures DAY BY DAY ("days": trades, wins, profit, one row per
    rule in `rules`' order) for the calendar; `keep` also hands back the walked trades themselves ("t"),
    which `build` files so a clicked day can list its trades (`rule_day`)."""
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
    t = {"sid": j_sid, "pnl": pnl[sel], "day": j_day, "row": sel,
         "month": np.searchsorted(np.array(ms), en[sel], side="right") - 1,
         "tfc": d["tfc"][j_sid], "skc": d["skc"][j_sid],
         "tpf": ~np.isnan(d["tp"][j_sid]) & (np.nan_to_num(d["tp"][j_sid]) > d["sl"][j_sid]),
         "slc": d["sl"][j_sid] <= 1.5 + 1e-9, "cost": d["cost"][j_sid],
         # real-priced: both of the trade's fills paid the recorded order book of their minute
         "real": (d["real"][sel] == 2) if d.get("real") is not None else np.zeros(len(sel), bool)}
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
    s_cost = d["cost"]
    rules, seen, dupes, same_as = [], {}, 0, {}
    coverage = {}
    day_c, day_w, day_p = [], [], []
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
                for cap, cc in [(c, k) for c in SL_CAPS for k in COST_CAPS]:
                    kst = (stm & (s_tpf if tp_rule == ">" else True) & ((s_sl <= cap + 1e-9) if cap else True)
                           & ((s_cost <= cc + 1e-9) if cc else True))
                    if not kst.any():
                        continue
                    sig = np.packbits(kst).tobytes()
                    if sig in seen:            # the same strategies as a kind already walked
                        kept = seen[sig]
                        for W, N, mr, X in grid():
                            same_as[rule_id(W, X, N, tp_rule, cap, tf, sk, mr, cc)] = rule_id(
                                W, X, N, kept[0], kept[1], kept[2], kept[3], mr, kept[4])
                        dupes += len(grid())
                        continue
                    seen[sig] = (tp_rule, cap, tf, sk, cc)
                    km = np.ones(len(idx), bool)
                    if tp_rule == ">":
                        km &= sub["tpf"]
                    if cap:
                        km &= sub["slc"]
                    if cc:
                        km &= sub["cost"] <= cc + 1e-9
                    pool_c = np.bincount(sub["day"][km], minlength=D).astype(np.float64)
                    pool_p = np.bincount(sub["day"][km], weights=sub["pnl"][km], minlength=D)
                    pool_avg = np.where(pool_c > 0, pool_p / np.maximum(pool_c, 1), 0.0)
                    covered_m = np.bincount(sub["month"][km], minlength=M) > 0
                    covered_days = int((pool_c > 0).sum())
                    no_target = bool((kst & ~s_tpf).any())
                    kind = {"tf": tf, "skill": sk, "tp_rule": tp_rule, "sl_cap": cap, "cost_cap": cc,
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
                                    c_, w_, p_ = f.pop("_days")
                                    day_c.append(c_)
                                    day_w.append(w_)
                                    day_p.append(p_)
                                    rules.append({"id": rule_id(W, X, N, tp_rule, cap, tf, sk, mr, cc),
                                                  "window": W, "min_win_rate": X, "min_trades": N,
                                                  "money": mr,
                                                  "words": rule_words(W, X, N, tp_rule, cap, tf, sk, mr, cc),
                                                  **kind, **f})
                                    if visit is not None:
                                        visit(rules[-1], m, sub, km)
            log(f"forecast v4: {tf or 'any timeframe'} / {sk or 'any skill'} walked, {len(rules):,} rule sets")
    info = d["info"]
    for r in rules:
        r["top"] = [{"id": info[s][0], "coin": info[s][1], "tf": info[s][2], "label": info[s][3],
                     "trades": n_, "profit": pr} for s, n_, pr in r["top"]]
    months = [{"key": datetime.fromtimestamp(s, tz=timezone.utc).strftime("%Y-%m"), "from_s": s,
               "to_s": min(n_, end_s), "complete": c} for s, n_, c in zip(ms, nxt, complete)]
    days = {"trades": np.array(day_c, dtype=np.int32).reshape(len(rules), D),
            "wins": np.array(day_w, dtype=np.int32).reshape(len(rules), D),
            "profit": np.array(day_p, dtype=np.float64).reshape(len(rules), D)}
    from tradingagents import skill_bt as _sb

    marks = d["real"][sel] if d.get("real") is not None else np.zeros(len(sel), np.int8)
    out = {"rules": rules, "dupes": dupes, "same_as": same_as, "coverage": coverage, "days": days,
           "walk": {"from_s": start, "to_s": int(end_s), "days": int(D), "months": months,
                    "trades": int(len(sel)),
                    # of the walked trades: both fills at the recorded order book (`real`), one (`part`);
                    # the rest paid the coin's usual gap. The record begins `from_s`
                    "real": {"from_s": _sb.REAL_FROM_S, "trades": int(len(sel)),
                             "real": int((marks == 2).sum()), "part": int((marks == 1).sum())}}}
    if keep:
        out["t"] = t
    return out


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
    d = _load(db, log, extra=True)        # each trade's side, exit kind and exit minute: the day lists
    meta = d["meta"]
    end_s = int(meta.get("data_end_s") or (int(d["ex"].max()) if len(d["ex"]) else 0))
    if not len(d["sid"]) or not end_s:
        raise RuntimeError("Backtest v4 holds no trades: nothing to forecast")
    walk = _walk(d, end_s, log, keep=True)
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
                 "tp_rules": list(TP_RULES), "sl_caps": list(SL_CAPS), "cost_caps": list(COST_CAPS), "tfs": list(TFS),
                 "skills": list(SKILLS), "tested": len(rules), "same_as_another": walk["dupes"]},
        "rules": rules, "same_as": walk["same_as"],
        "streaks": {"cols": ["id", "coin", "tf", "label", "skill", "tp", "sl", *STREAK_COLS[1:]],
                    "rows": srows, "min": STREAK_MIN},
        "follow": streak["follow"],
    }
    from tradingagents.forecast_v2 import publish

    # the calendar's files first, whole, then the forecast that names them: a reader holding the old
    # forecast keeps reading the old folder, which is removed only by the build AFTER this one
    before = _named_walk_dir(out)
    doc["walk_dir"] = _file_walk(out.parent, doc["built_s"], int(float(meta.get("built_s", 0) or 0)),
                                 walk, d, log)
    doc["seconds"] = round(time.time() - t0, 1)
    text = json.dumps(doc, separators=(",", ":"))
    publish(out, text)
    _prune_walk_dirs(out.parent, {doc["walk_dir"], before}, log)
    kept = keep_dated_copy(text, end_s) if out == out_path() else None
    log(f"forecast v4: {len(rules):,} rule sets and {len(srows):,} streaks written to {out} "
        f"in {doc['seconds']:.0f} s" + (f"; dated copy {kept}" if kept else ""))
    return {k: doc[k] for k in ("built_s", "seconds", "store", "used", "walk", "grid")}


# ------------------------------------------------------------------ the calendar's files
WALK_FORMAT = 2          # 2: each strategy's cost (`s_cost`), for the cheap-coins rule sets
WINDOW_FLAGS = tuple(f"{mr}{W}" for mr in MONEY_RULES if mr for W in WINDOWS)   # one bit each


def _named_walk_dir(out: Path) -> str:
    """The calendar folder the forecast now on disk names ("" when none does)."""
    try:
        with open(out, encoding="utf-8") as fh:
            head = fh.read()
        return str(json.loads(head).get("walk_dir") or "")
    except (OSError, ValueError):
        return ""


def _file_walk(home: Path, built_s: int, store_built_s: int, walk: dict, d: dict, log) -> str:
    """File what the calendar reads, into a folder of its own named by the build (`walk-<built_s>`):
    every rule set's trades, wins and profit on each walked day (`days_*.bin`, one row per rule in the
    forecast's order), and every walked trade - sorted by the day it OPENED, closing order inside a
    day - with what the walk judged it by (`n7`..`w30`, the money flags), so `rule_day` asks a day the
    walk's own question of its own numbers. Raw arrays, one file each, written to a temp folder and
    renamed whole; `index.json` says each one's type and where each day starts."""
    t = walk["t"]
    start = int(walk["walk"]["from_s"])
    D = int(walk["walk"]["days"])
    order = np.argsort(t["day"], kind="stable")
    day = t["day"][order]
    rows = t["row"][order]
    offsets = np.searchsorted(day, np.arange(D + 1), side="left")
    flags = np.zeros(len(order), np.uint8)
    for b, k in enumerate(WINDOW_FLAGS):
        flags |= (t[k][order].astype(np.uint8) << b)
    counts = {}
    for W in WINDOWS:
        for k in (f"n{W}", f"w{W}"):
            v = t[k][order]
            counts[k] = v.astype(np.int16 if (len(v) == 0 or int(v.max()) < 32_767) else np.int32)
    n_sid = len(d["tfc"])
    tpf = ~np.isnan(d["tp"]) & (np.nan_to_num(d["tp"]) > d["sl"])
    cols = {
        "sid": t["sid"][order].astype(np.int32),
        "en": (d["en"][rows] - start).astype(np.int32),
        "ex": (d["ex"][rows] - start).astype(np.int32),
        "at": (d["at"][rows] - start).astype(np.int32),
        "p4": np.rint(d["pnl"][rows] * 10_000).astype(np.int32),
        "side": d["side"][rows].astype(np.int8),
        "why": d["why"][rows].astype(np.int8),
        "flags": flags, **counts,
        # per strategy (indexed by sid): its kind, the walk's own tests of it
        "s_tfc": d["tfc"].astype(np.int8), "s_skc": d["skc"].astype(np.int8),
        "s_tpf": tpf.astype(np.uint8), "s_slc": (d["sl"] <= 1.5 + 1e-9).astype(np.uint8),
        "s_cost": d["cost"].astype(np.float64),
        # per rule set, per day: the calendar's boxes
        "days_trades": walk["days"]["trades"], "days_wins": walk["days"]["wins"],
        "days_profit": walk["days"]["profit"],
    }
    name = f"walk-{int(built_s)}"
    final = home / name
    tmp = home / f"{name}.tmp-{os.getpid()}"
    home.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    for k, v in cols.items():
        np.ascontiguousarray(v).tofile(tmp / f"{k}.bin")
    index = {"format": WALK_FORMAT, "built_s": int(built_s), "store_built_s": int(store_built_s),
             "start": start, "D": D, "rows": int(len(order)), "n_sid": int(n_sid),
             "offsets": [int(x) for x in offsets], "flags": list(WINDOW_FLAGS),
             "cols": {k: np.asarray(v).dtype.str for k, v in cols.items()},
             "rule_ids": [r["id"] for r in walk["rules"]]}
    (tmp / "index.json").write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    shutil.rmtree(final, ignore_errors=True)
    os.replace(tmp, final)
    size = sum(p.stat().st_size for p in final.iterdir())
    log(f"forecast v4: the calendar's files, {len(order):,} walked trades, {size / 1e6:,.0f} MB in {final}")
    return name


def _prune_walk_dirs(home: Path, keep: set, log) -> None:
    """Remove calendar folders no forecast names any more: every `walk-*` folder but the new one and the
    one the forecast before it named (a reader may still hold that forecast). A folder Windows will not
    let go (a reader has a file open) is left for the next build."""
    for p in home.glob("walk-*"):
        if not p.is_dir() or p.name in keep:
            continue
        if ".tmp-" in p.name and time.time() - p.stat().st_mtime < 6 * 3600:
            continue                       # another build may be writing it
        try:
            shutil.rmtree(p)
        except OSError as e:
            log(f"forecast v4: could not remove the old calendar folder {p} ({e}); the next build tries again")


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
    cc = float(rule.get("cost_cap") or 0)
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
    if cc:          # a fee or gap the store does not know (NULL) fails this, as the walk's `inf` does
        where.append("100.0 * (2 * s.fee + 2 * s.slip) <= ?")
        args.append(cc + 1e-9)
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


MONEY = ("profit", "per_trade", "worst_run", "worst_day", "random_profit", "random_per_trade", "rank",
         "real_profit", "real_per_trade")


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
        cq = str(q.get("cost") or "")
        if cq == "cheap":
            got = [r for r in got if r.get("cost_cap")]
            named.append(f"only coins costing ${COST_CAPS[-1]:.2f} or less per $100 traded")
        elif cq == "none":
            got = [r for r in got if not r.get("cost_cap")]
            named.append("any coin, whatever it costs")
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
        if _truthy(q.get("real_made")):
            got = [r for r in got if (r.get("real_trades") or 0) > 0 and (r.get("real_profit") or 0) > 0]
            named.append("made money at real prices")
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
        if "made money at real prices" in named and rules and "real_trades" not in rules[0]:
            why = ("this forecast was worked out before trades were priced at the recorded order book, so "
                   "no rule set has a real-priced figure yet - the next nightly build fills it in")
    return {"ready": True, "rows": rows, "total": total, "of": len(rules), "page": page, "pages": pages,
            "per_page": PER_PAGE, "filters": named, "sort": sort, "desc": desc, "why": why,
            "base_margin": round(k * v4_store.MEASURED_MARGIN, 4)}


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------------ a rule set's calendar
# Operator, Nov 13, 2026: "when i click and id in Best switch-on rules this month currently you are
# showing months only i want a calendar, when i click a day in calendar, show me the trades it made in
# that day". A day is the walk's own day: 12:00am to 12:00am UTC, its trades the ones OPENED that day.
class BadAsk(ValueError):
    """A question the calendar cannot answer as asked (a malformed day): the route answers 400."""


WHY_WORDS = {"SL": "stop (SL)", "TP": "target (TP)", "SIGNAL": "opposite signal", "END": "run ended",
             "OTHER": "other"}
_WALK_IDX: dict = {"key": None, "index": None, "pos": None}


def _day_key(s: int) -> str:
    return datetime.fromtimestamp(int(s), tz=timezone.utc).strftime("%Y-%m-%d")


def _walk_files(doc: dict):
    """(folder, index, rule position by id) of the calendar files the forecast `doc` names, or None
    when it names none (a forecast built before the calendar) or they cannot be read."""
    name = str(doc.get("walk_dir") or "")
    if not name:
        return None
    folder = out_path().parent / name
    p = folder / "index.json"
    try:
        st = p.stat()
    except OSError:
        return None
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _WALK_IDX["key"] != key:
            try:
                index = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if index.get("format") != WALK_FORMAT:
                return None
            _WALK_IDX.update(key=key, index=index, pos={r: i for i, r in enumerate(index["rule_ids"])})
        return folder, _WALK_IDX["index"], _WALK_IDX["pos"]


def _read(folder: Path, index: dict, col: str, a: int = 0, count: int = -1) -> np.ndarray:
    """Rows [a, a + count) of one column, read and closed at once (no file is held open across asks,
    so the next build can remove an old folder)."""
    dt = np.dtype(index["cols"][col])
    return np.fromfile(folder / f"{col}.bin", dtype=dt, count=count, offset=a * dt.itemsize)


def _find_rule(doc: dict, rule_id: str):
    """The listed rule set for an id (a twin's id finds the rule set it is listed as), or None."""
    want = str(rule_id or "").strip().lstrip("#").upper()
    want = doc.get("same_as", {}).get(want, want)
    for r in doc["rules"]:
        if r["id"] == want:
            return r
    return None


def _takes(t: dict, rule: dict) -> np.ndarray:
    """THE SWITCH-ON TEST, asked of filed trades: which of them `rule` takes. The walk's own arithmetic
    (`_walk`: its kind, at least min_trades closed in its window before the day, its money rule, and
    wins x 100 >= win rate x trades) over the numbers the walk itself filed for each trade - held equal
    to the walk's day figures for every rule set by tests/test_forecast_v4_calendar.py."""
    W = int(rule["window"])
    N = int(rule["min_trades"])
    X = int(rule["min_win_rate"])
    n_ = t[f"n{W}"].astype(np.int64)
    m = n_ >= N
    if rule.get("tf"):
        m &= t["tfc"] == TFS.index(rule["tf"]) - 1
    if rule.get("skill"):
        m &= t["skc"] == SKILLS.index(rule["skill"]) - 1
    if rule.get("tp_rule") == ">":
        m &= t["tpf"]
    if float(rule.get("sl_cap") or 0):
        m &= t["slc"]
    cc = float(rule.get("cost_cap") or 0)
    if cc:
        m &= t["cost"] <= cc + 1e-9
    mr = _money(rule.get("money"))
    if mr:
        m &= t[f"{mr}{W}"]
    if X:
        m &= t[f"w{W}"].astype(np.int64) * 100 >= X * n_
    return m


def _filed(folder: Path, index: dict, a: int, b: int) -> dict:
    """Walked trades [a, b) as `_takes` reads them: each one's strategy (`sid`), its kind (from the
    strategy), the counts the walk judged it by and the money flags."""
    sid = _read(folder, index, "sid", a, b - a).astype(np.int64)
    t = {"sid": sid, "tfc": _read(folder, index, "s_tfc")[sid], "skc": _read(folder, index, "s_skc")[sid],
         "tpf": _read(folder, index, "s_tpf")[sid].astype(bool),
         "slc": _read(folder, index, "s_slc")[sid].astype(bool), "cost": _read(folder, index, "s_cost")[sid]}
    for W in WINDOWS:
        t[f"n{W}"] = _read(folder, index, f"n{W}", a, b - a)
        t[f"w{W}"] = _read(folder, index, f"w{W}", a, b - a)
    flags = _read(folder, index, "flags", a, b - a)
    for bit, name in enumerate(index["flags"]):
        t[name] = (flags >> bit) & 1 == 1
    return t


def rule_days(rule_id: str, base_margin: float = 5.0) -> dict:
    """Every walked day of one rule set, for the calendar: {"YYYY-MM-DD" (UTC): pnl, wins, losses,
    trades} on each day it opened a trade, the dollars at `base_margin`. The boxes add up to the
    rule set's months and total: they are the same trades, filed by the walk that counted those."""
    doc = load()
    if doc is None:
        return {**_not_ready(), "days": {}}
    r = _find_rule(doc, rule_id)
    if r is None:
        return {"ready": True, "found": False, "days": {},
                "why": f"no rule set #{str(rule_id).strip().lstrip('#').upper()} in this forecast"}
    w = doc["walk"]
    k = max(_num(base_margin, 5.0), 0.01) / v4_store.MEASURED_MARGIN
    span = {"from": _day_key(w["from_s"]), "to": _day_key(max(w["from_s"], w["to_s"] - 1))}
    files = _walk_files(doc)
    if files is None:
        return {"ready": True, "found": True, "id": r["id"], "days": {}, **span,
                "why": ("this forecast's calendar files are from an older build: the day-by-day "
                        "figures come with the next build (python -m tradingagents.forecast_v4 build)")}
    folder, index, pos = files
    i = pos.get(r["id"])
    if i is None:
        return {"ready": True, "found": True, "id": r["id"], "days": {}, **span,
                "why": "the calendar files do not hold this rule set: they belong to another build"}
    D = int(index["D"])
    c = _read(folder, index, "days_trades", i * D, D)
    wn = _read(folder, index, "days_wins", i * D, D)
    p = _read(folder, index, "days_profit", i * D, D)
    days = {}
    for j in np.nonzero(c > 0)[0]:
        days[_day_key(int(index["start"]) + int(j) * DAY_S)] = {
            "pnl": round(float(p[j]) * k, 4), "trades": int(c[j]), "wins": int(wn[j]),
            "losses": int(c[j] - wn[j]), "coins": []}
    return {"ready": True, "found": True, "id": r["id"], "words": r["words"], "days": days, **span,
            "trades": int(c.sum()), "profit": round(float(p.sum()) * k, 4),
            "base_margin": round(k * v4_store.MEASURED_MARGIN, 4)}


DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def rule_day(rule_id: str, day: str, page: int = 1, base_margin: float = 5.0) -> dict:
    """The trades one rule set OPENED on one walked day (12:00am to 12:00am UTC), oldest first, ten a
    page, with the day's totals over ALL of them (never the page's). Each trade: the strategy (id, coin,
    timeframe, setting, skill), long or short, opened, closed (the exit minute), what closed it, its
    stop and target and its profit at `base_margin`. `box` is the calendar's own figure for the day, so
    a list that ever disagrees with its box says so."""
    if not DAY_RE.match(str(day or "")):
        raise BadAsk(f"day must be YYYY-MM-DD, not {day!r}")
    try:
        day_s = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    except ValueError as e:
        raise BadAsk(f"no such day {day!r}") from e
    doc = load()
    if doc is None:
        return {**_not_ready(), "rows": [], "total": 0, "page": 1, "pages": 1}
    r = _find_rule(doc, rule_id)
    if r is None:
        return {"ready": True, "found": False, "rows": [], "total": 0, "page": 1, "pages": 1,
                "why": f"no rule set #{str(rule_id).strip().lstrip('#').upper()} in this forecast"}
    files = _walk_files(doc)
    base = {"ready": True, "found": True, "id": r["id"], "words": r["words"], "day": day, "day_s": day_s,
            "rows": [], "total": 0, "page": 1, "pages": 1, "per_page": PER_PAGE}
    if files is None:
        return {**base, "why": ("this forecast's calendar files are from an older build: the trades "
                                "come with the next build (python -m tradingagents.forecast_v4 build)")}
    folder, index, pos = files
    start, D = int(index["start"]), int(index["D"])
    j = (day_s - start) // DAY_S
    if day_s < start or j >= D:
        return {**base, "why": (f"{day} is outside the days walked ({_day_key(start)} to "
                                f"{_day_key(start + (D - 1) * DAY_S)})")}
    ri = pos.get(r["id"])
    if ri is None:
        return {**base, "why": "the calendar files do not hold this rule set: they belong to another build"}
    k = max(_num(base_margin, 5.0), 0.01) / v4_store.MEASURED_MARGIN
    a, b = int(index["offsets"][j]), int(index["offsets"][j + 1])
    t = _filed(folder, index, a, b)
    sid = t["sid"]
    m = _takes(t, r)
    idx = np.nonzero(m)[0]
    p4 = _read(folder, index, "p4", a, b - a)[idx].astype(np.int64)
    en = _read(folder, index, "en", a, b - a)[idx].astype(np.int64) + start
    at = _read(folder, index, "at", a, b - a)[idx].astype(np.int64) + start
    side = _read(folder, index, "side", a, b - a)[idx]
    why = _read(folder, index, "why", a, b - a)[idx]
    s_sel = sid[idx]
    box_n = int(_read(folder, index, "days_trades", ri * D + j, 1)[0])
    box_p = float(_read(folder, index, "days_profit", ri * D + j, 1)[0])
    order = np.lexsort((s_sel, at, en))                 # opened, then closed, then strategy
    total = int(len(idx))
    wins = int((p4 > 0).sum())
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, int(_num(page, 1))), pages)
    shown = order[(page - 1) * PER_PAGE: page * PER_PAGE]
    names, names_why = _strategy_names([int(s_sel[x]) for x in shown], int(index["store_built_s"]))
    rows = []
    for x in shown:
        s = int(s_sel[x])
        nm = names.get(s, {})
        rows.append({"id": nm.get("id"), "coin": nm.get("coin"), "tf": nm.get("tf"), "label": nm.get("label"),
                     "skill": nm.get("skill"), "tp": nm.get("tp"), "sl": nm.get("sl"),
                     "side": "long" if int(side[x]) > 0 else "short",
                     "opened_s": int(en[x]), "closed_s": int(at[x]),
                     "closed_by": WHY_WORDS.get(v4_store.WHYS[int(why[x])], "other")
                     if 0 <= int(why[x]) < len(v4_store.WHYS) else "other",
                     "profit": round(int(p4[x]) / 10_000 * k, 4)})
    profit = int(p4.sum()) / 10_000
    return {**base, "rows": rows, "total": total, "page": page, "pages": pages,
            "trades": total, "wins": wins, "losses": total - wins,
            "win_rate": round(100.0 * wins / total, 2) if total else None,
            "profit": round(profit * k, 4), "strategies": int(len(np.unique(s_sel))),
            "box": {"trades": box_n, "profit": round(box_p * k, 4)},
            "agrees": box_n == total and abs(box_p - profit) < 0.00005 * max(1, total),
            "names_why": names_why, "base_margin": round(k * v4_store.MEASURED_MARGIN, 4)}


def _strategy_names(sids: list[int], store_built_s: int) -> tuple[dict, str]:
    """Each strategy's id, coin, timeframe, setting and skill from the Backtest v4 store - only while
    the store is the one this forecast was built from (a strategy's number, `sid`, is given by each
    store build). Otherwise none, and why."""
    if not sids:
        return {}, ""
    db = v4_store.db_path()
    try:
        con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error as e:
        return {}, f"the Backtest v4 store could not be opened ({e})"
    try:
        got = {k: v for k, v in con.execute("SELECT k, v FROM meta WHERE k = 'built_s'")}
        if int(float(got.get("built_s", 0) or 0)) != int(store_built_s):
            return {}, ("Backtest v4 was rebuilt after this forecast: each trade's strategy is named again "
                        "once the forecast is worked out from it (it follows the store within minutes)")
        q = ",".join("?" * len(sids))
        rows = con.execute(f"SELECT sid, id, coin, tf, label, skill, tp, sl FROM strat WHERE sid IN ({q})",
                           sids).fetchall()
    except sqlite3.Error as e:
        return {}, f"the Backtest v4 store could not be read ({e})"
    finally:
        con.close()
    return {int(s): {"id": i, "coin": c, "tf": tf, "label": lb, "skill": sk, "tp": tp, "sl": sl}
            for s, i, c, tf, lb, sk, tp, sl in rows}, ""


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
