"""Backtest a room over a date range, beside what its practice account did.

Operator, Oct 02, 2026: "i want ability to backtest room in forecast v1, i want
option to filter date range to backtest so i can see if the deployed tabs
attached matches the backtest".

For every strategy switched on in the room NOW, two records over the chosen
days:

* BACKTEST — the strategy's own backtest trades, rebuilt by rolling30 from the
  stored candles with every exit settled by the minute (the same trades the
  DEMO column counts). They reach the backtest's last candle — the last daily
  update — and no further; the answer says where that is.
* PRACTICE — the room's own trade record: every practice trade of that
  strategy on that coin that CLOSED in the range.

A practice trade and a backtest trade are THE SAME TRADE when they entered on
the same bar: practice records the signal candle (`entry_ts`), the backtest
the bar after it. Each pair either ended the same way or did not; a practice
trade with no backtest twin is usually one the backtest did not take because
it was still holding an earlier trade (RCA-2026-09-30, the B52662ED check).

Read where the data is: the server filters by date and room, sorts and pages;
the screen never receives every strategy of a 2,594-row room.
"""
from __future__ import annotations

import bisect
import json
import time
from pathlib import Path

from tradingagents import profiles

PER_PAGE = 25
SORTS = ("gap", "practice", "backtest", "different")


def _worst_run(pnls: list) -> tuple[float, int]:
    """The worst unbroken run of losses: its dollars and how many trades."""
    run = worst = 0.0
    n = worst_n = 0
    for p in pnls:
        if p > 0:
            run, n = 0.0, 0
        else:
            run += p
            n += 1
            if run < worst:
                worst, worst_n = run, n
    return round(worst, 2), worst_n


def _side(pnls: list) -> dict:
    wins = sum(1 for p in pnls if p > 0)
    n = len(pnls)
    w, wn = _worst_run(pnls)
    return {"trades": n, "wins": wins, "losses": n - wins,
            "winrate": round(100 * wins / n, 2) if n else None,
            "profit": round(sum(pnls), 2), "worst_run": w, "worst_run_trades": wn}


_LEDGER: dict = {}          # path -> (size, exits, refusals, refused candles; by slot)

# WHY THE PRACTICE ACCOUNT DID NOT TAKE A BACKTEST TRADE: the refusal it wrote
# into its trade record while that trade's entry bar was open
REASONS = {"gate_blocked": "fees too high for the target (cost check)",
           "coin_busy": "the coin already had its 4 trades open",
           "chase_skip": "the price had already run away",
           "stale_skip": "the signal was too old when seen",
           "capital_blocked": "not enough money in the account",
           "blocked": "the coin was taken by another strategy"}


def _practice_exits(pid: str) -> tuple:
    """({slot: [(exit_s, entry_s, pnl, why)]}, {slot: [(ts, refusal)]},
    {slot: {signal candle open}}) - every closed PRACTICE trade, every refusal
    in the room's trade record and every candle the cost check is recorded as
    refusing, read again only when the file has grown."""
    from tradingagents import auto_trader as at

    with profiles.using(pid):
        path = Path(at._pp(at.LEDGER_PATH))
    try:
        size = path.stat().st_size
    except OSError:
        return {}, {}, {}
    hit = _LEDGER.get(str(path))
    if hit and hit[0] == size:
        return hit[1], hit[2], hit[3]
    out: dict = {}
    refused: dict = {}
    candles: dict = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            act = r.get("action")
            slot = f"{r.get('strategy')}|{r.get('symbol')}"
            if act == "exit" and r.get("dry_run"):
                out.setdefault(slot, []).append((float(r.get("ts") or 0), float(r.get("entry_ts") or 0),
                                                 float(r.get("pnl_est") or 0.0), str(r.get("why") or "")))
            elif act in REASONS and r.get("dry_run", True):
                # EVERY CANDLE THE COST CHECK REFUSED is in a row's `bars`
                # since Oct 02, 2026 (RCA-2026-10-02-C) - the exact answer. A
                # `late` row is written two hours after its last candle, so
                # its own time is no moment of refusal
                if act == "gate_blocked":
                    candles.setdefault(slot, set()).update(int(b) for b in r.get("bars") or [])
                if not r.get("late"):
                    refused.setdefault(slot, []).append((float(r.get("ts") or 0), act))
    for v in refused.values():
        v.sort()
    _LEDGER[str(path)] = (size, out, refused, candles)
    return out, refused, candles


# THE COST CHECK WRITES ONE REFUSAL AN HOUR (auto_trader._GATE_LOG_EVERY):
# it runs BEFORE the signal and refuses silently for the next hour after a
# written refusal, so a refused trade usually has NO line of its own. Found
# Oct 02, 2026 by the other session: 6,254 of #4FC03172's 6,612 backtest
# trades sat within an hour after a written gate_blocked for the same strategy
# and coin; this page had called them "the live program saw no signal".
GATE_QUIET_S = 3600


def _reason(mine: list, ts_list: list, entry_s: float, bar_s: int) -> str:
    """Why practice did not take the backtest trade entering at `entry_s`: a
    refusal written while its entry bar was open, else a cost-check refusal
    written in the hour before it (the check stays quiet that long)."""
    i = bisect.bisect_left(ts_list, entry_s - 120)
    if i < len(mine) and mine[i][0] <= entry_s + bar_s:
        return mine[i][1]
    j = bisect.bisect_right(ts_list, entry_s + bar_s) - 1
    while j >= 0 and ts_list[j] >= entry_s - GATE_QUIET_S - bar_s:
        if mine[j][1] == "gate_blocked":
            return "gate_blocked_quiet"
        j -= 1
    return "none"


def compare(room: str, from_s: float, to_s: float, *, sort: str = "gap",
            page: int = 1, per: int = PER_PAGE, now: float | None = None) -> dict:
    from tradingagents import auto_trader as at
    from tradingagents import rolling30 as r30

    now = time.time() if now is None else now
    if room not in profiles.shown():
        raise ValueError(f"no room {room!r}; the rooms are {profiles.shown()}")
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}")
    with profiles.using(room):
        settings = at.load_settings()
    ws = settings.get("watcher_slots") or {}
    slots = [(k, c) for k, cs in (settings.get("strategy_coins") or {}).items() for c in cs or []]
    exits, refused, refused_candles = _practice_exits(room)
    # WHEN EACH STRATEGY WAS SWITCHED ON: the watcher's own stamp, else the
    # deploy record (rows added by hand). The backtest is counted from then -
    # before it, the room was not trading that strategy at all
    from tradingagents import local_history as lh
    with profiles.using(room):
        deployed = lh.deployed_at()
    reasons: dict = {k: 0 for k in REASONS}
    reasons["gate_blocked_quiet"] = 0
    reasons["none"] = 0
    lo_ms, hi_ms = from_s * 1000, to_s * 1000
    rows = []
    tot_bt, tot_pr = [], []
    match = {"same": 0, "different": 0, "practice_only": 0, "backtest_only": 0,
             "after_backtest": 0}
    no_backtest = 0
    ends = []
    for key, coin in slots:
        slot = f"{key}|{coin}"
        rec = r30._load(slot)
        meta = ws.get(slot) or {}
        on_s = float(meta.get("on_at") or (deployed.get(slot) or {}).get("at") or 0) or None
        start_ms = max(lo_ms, on_s * 1000) if on_s else lo_ms
        pr_all = sorted(e for e in exits.get(slot, []) if from_s <= e[0] <= to_s)
        if rec is None:
            no_backtest += 1
            bt, bar_s, end_ms = [], 0, None
            pr = pr_all
        else:
            bar_s, end_ms = int(rec.get("bar_s") or 0), int(rec.get("end_ms") or 0)
            ends.append(end_ms)
            # ONE WINDOW FOR BOTH SIDES: from the switch-on to the backtest's
            # last candle; a practice trade closed after it is counted apart
            bt = [t for t in rec.get("trades") or []
                  if t[0] >= start_ms and lo_ms <= t[1] <= min(hi_ms, end_ms)]
            pr = [e for e in pr_all if e[0] * 1000 <= end_ms]
        # the same trade: the practice signal candle + one bar = the backtest entry
        by_entry = {int(t[0]): t for t in bt}
        used = set()
        same = diff = only_p = 0
        after = len(pr_all) - len(pr)
        for ex_s, en_s, pnl, _why in pr:
            twin = by_entry.get(int(en_s * 1000 + bar_s * 1000)) if rec else None
            if twin is None:
                only_p += 1
                continue
            used.add(int(twin[0]))
            if (twin[2] > 0) == (pnl > 0):
                same += 1
            else:
                diff += 1
        only_b = 0
        mine = refused.get(slot, [])
        ts_list = [x[0] for x in mine]
        gone = refused_candles.get(slot) or set()
        for t in bt:
            if int(t[0]) in used:
                continue
            only_b += 1
            # the cost check's own record of refusing this trade's signal
            # candle (the backtest entry less one bar) is the exact reason
            reasons["gate_blocked" if int(t[0]) // 1000 - bar_s in gone
                    else _reason(mine, ts_list, t[0] / 1000, bar_s)] += 1
        for k_, v in (("same", same), ("different", diff), ("practice_only", only_p),
                      ("backtest_only", only_b), ("after_backtest", after)):
            match[k_] += v
        b_side = _side([t[2] for t in sorted(bt, key=lambda t: t[1])])
        p_side = _side([e[2] for e in pr])
        tot_bt += [(t[1], t[2]) for t in bt]
        tot_pr += [(e[0] * 1000, e[2]) for e in pr]
        spec = at.STRATEGY_SPECS.get(key) or {}
        rows.append({"slot": slot, "id": meta.get("id") or "", "coin": coin.replace("_USDT", ""),
                     "key": key, "tf": meta.get("tf") or "", "signal": meta.get("signal") or "",
                     "tp": meta.get("tp") if meta else round(float(spec.get("tp") or 0) * 100, 3),
                     "sl": meta.get("sl") if meta else round(float(spec.get("sl") or 0) * 100, 3),
                     "backtest": b_side, "practice": p_side,
                     "same": same, "different": diff, "practice_only": only_p,
                     "backtest_only": only_b, "after_backtest": after,
                     "has_backtest": rec is not None, "on_at": on_s,
                     "gap": round(p_side["profit"] - b_side["profit"], 2)})
    key_of = {"gap": lambda r: abs(r["gap"]), "practice": lambda r: r["practice"]["trades"],
              "backtest": lambda r: r["backtest"]["trades"], "different": lambda r: r["different"]}[sort]
    rows.sort(key=lambda r: (-key_of(r), r["slot"]))
    traded = [r for r in rows if r["practice"]["trades"] or r["backtest"]["trades"]]
    pages = max(1, -(-len(traded) // per))
    page = min(max(1, int(page)), pages)
    bt_end = min(ends) if ends else None
    return {"room": room, "from": from_s, "to": to_s, "now": now,
            "slots": len(slots), "no_backtest": no_backtest, "traded": len(traded),
            "backtest_end_ms": bt_end, "backtest_end_latest_ms": max(ends) if ends else None,
            "backtest": _side([p for _, p in sorted(tot_bt)]),
            "practice": _side([p for _, p in sorted(tot_pr)]),
            "match": match, "reasons": reasons,
            "reason_labels": {**REASONS,
                              "gate_blocked_quiet": "fees too high for the target (cost check, "
                                                    "which writes its refusal once an hour)",
                              "none": "no trade and no refusal recorded"},
            "margin": 5.0, "leverage": at.LEVERAGE,
            "rows": traded[(page - 1) * per: page * per], "page": page, "pages": pages,
            "sort": sort}
