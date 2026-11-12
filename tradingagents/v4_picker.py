"""The daily picker: the three skill rooms follow the best rule sets of the month, and
a room whose rule stopped working is replaced or switched off - by itself.

Operator, Nov 12, 2026: *"can i have a logic to run the best switch-on for this month?
for example logic detected CKVS7G7Z is performing well then what it will do is i will
deploy it automatically in auto trade practice ... then for example in my current
deployed switch on (D7EN8BNV RSS7CUKH 7T3VJU82) it did not performed well, then it will
undeploy it ... the goal for this is that i will not manually search for best switch on
and deploy and undeploy what is not working"*. Asked how it should show in Auto Trade
and what "performing well" means, they took the recommended answers: FIXED ROOMS, RULE
SWAPPED (the three tabs stay, each follows whatever rule set the picker gives it) and
WORST MONTH GREEN + BEATS RANDOM.

One pass a day, inside the daily chain (`v4_daily._lists`), after Forecast v4 is rebuilt
and BEFORE the day's list is written, so the day's list is judged by the rules the picker
has just chosen. It reads Forecast v4's own record (`forecast_v4.load()`), never a second
calculation:

* a rule set is GOOD when it traded at least `MIN_TRADES` times, was never beaten by luck
  (`luck` false - it beat random picks by more than chance), has at least 3 whole months
  (`predicted.thin` false), made money in EVERY whole month (`rank`, its worst whole month,
  above zero), made money in total, and is not losing money in the month so far;
* a slot KEEPS its rule while the rule is still good AND the room's own practice trades
  since it was switched on (at least `PRACTICE_MIN` of them in the last 30 days) are not
  losing money in total - a rule that is still green in the backtest while practice
  loses is not "performing well";
* a slot whose rule is no longer good takes the best good rule set no other slot follows
  (best worst month first, as Forecast v4 sorts them); with none left the slot is OFF: no
  tab, no new trade, and a trade it already holds is finished by the follower;
* a slot that is off takes a rule set again the day one passes, and its tab returns.

Churn is the enemy: a slot whose rule still passes is never swapped for a slightly better
one, so a room is not rebuilt every night from a ranking that moves by cents.

PRACTICE MONEY ONLY. Nothing here can place an order or touch real money: a skill room has
no runner and no real-money path (`profiles.follows`), and the picker only writes which
rule set the follower reads.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

DAY_S = 86400

# What "performing well" needs, in one place.
MIN_TRADES = 100          # trades the rule set made over the walked days, not a handful
MONTH_MIN_TRADES = 20     # trades the month so far needs before a loss in it can fail a rule set
PRACTICE_MIN = 10         # closed practice trades before practice can overrule the backtest
PRACTICE_DAYS = 30
LOG_KEEP = 60             # decisions kept in the file, newest last


def _path() -> Path:
    from tradingagents import profiles

    f = profiles._picker_file()
    if f is None:
        raise RuntimeError("no picker file: a test must set profiles.PICKER_PATH")
    return f


def load() -> dict:
    from tradingagents import profiles

    return dict(profiles.picker_state())


def _save(st: dict) -> None:
    from tradingagents import forecast_v2 as f2

    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    f2.publish(p, json.dumps(st))


def slots() -> list[str]:
    """The fixed rooms the picker fills: every room that follows Backtest v4, retired or not by BUILTIN."""
    from tradingagents import profiles

    return [p["id"] for p in profiles.BUILTIN
            if p.get("follows") == "v4" and not p.get("retired")]


def _rule_of(rec: dict) -> dict:
    """forecast_v4.rule_id's arguments for a Forecast v4 record."""
    return {"window": int(rec["window"]), "win_rate": int(rec["min_win_rate"]),
            "min_trades": int(rec["min_trades"]), "tp_rule": rec.get("tp_rule") or "any",
            "sl_cap": float(rec.get("sl_cap") or 0.0), "tf": rec.get("tf") or "",
            "skill": rec.get("skill") or "", "money": rec.get("money") or ""}


def resolve(doc: dict, rule_id: str) -> dict | None:
    """A rule set's record - through `same_as` when the grid listed it as the twin of another."""
    by_id = {r["id"]: r for r in doc.get("rules") or []}
    rid = rule_id if rule_id in by_id else (doc.get("same_as") or {}).get(rule_id)
    return by_id.get(rid) if rid else None


def judge(rec: dict | None) -> tuple[bool, str]:
    """Is a rule set performing well, by Forecast v4's own numbers? (and in words, why not)"""
    if not rec:
        return False, "Forecast v4 has no record of this rule set"
    n = int(rec.get("trades") or 0)
    if n < MIN_TRADES:
        return False, f"only {n} trades over the days walked (needs {MIN_TRADES})"
    if rec.get("luck"):
        return False, "it did not beat random picks by more than luck"
    if (rec.get("predicted") or {}).get("thin"):
        return False, "fewer than 3 whole months to judge it on"
    rank = rec.get("rank")
    if rank is None or rank <= 0:
        return False, f"a whole month lost money (worst {rank:+.2f})" if rank is not None else "no whole month to judge"
    if float(rec.get("profit") or 0) <= 0:
        return False, f"it lost {float(rec.get('profit') or 0):+.2f} over the days walked"
    months = rec.get("months") or []
    cur = months[-1] if months else None
    # the month so far counts once it holds enough trades to mean something: on the 2nd of a
    # month one losing trade would otherwise switch every room off (the whole months before it
    # are already judged above)
    if cur and int(cur.get("trades") or 0) >= MONTH_MIN_TRADES and float(cur.get("profit") or 0) < 0:
        return False, f"the month so far is losing ({float(cur['profit']):+.2f} over {int(cur['trades'])} trades)"
    return True, ""


def _same_results(rec: dict) -> tuple:
    """Rule sets that switched on strategies with the very same trades have the same numbers
    (Nov 12, 2026: #CKVS7G7Z and its "technical-analysis" twin #5AUSDZ9L both +377.37 over
    1,207 trades) - they are ONE bet, and two slots must never follow one bet."""
    return (int(rec.get("trades") or 0), int(rec.get("wins") or 0), round(float(rec.get("profit") or 0), 2))


def candidates(doc: dict) -> list[dict]:
    """The records that pass `judge`, best worst month first, one per set of results (of
    twins, the one with the fewest filters)."""
    good = [r for r in doc.get("rules") or [] if judge(r)[0]]
    good.sort(key=lambda r: (-(r.get("rank") or 0), -(r.get("profit") or 0),
                             bool(r.get("skill")) + bool(r.get("tf")), r["id"]))
    seen, out = set(), []
    for r in good:
        sig = _same_results(r)
        if sig not in seen:
            seen.add(sig)
            out.append(r)
    return out


def _ledger_default(pid: str) -> list[dict]:
    from tradingagents import profiles

    p = profiles.dir_for(pid) / "auto_trade_ledger.jsonl"
    out: list[dict] = []
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"exit"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("action") == "exit" and r.get("dry_run"):
                    out.append(r)
    except OSError:
        return []
    return out


def practice(pid: str, since_s: float, now_s: float,
             ledger_of: Callable[[str], list[dict]] | None = None) -> tuple[bool, str]:
    """Is the room's own practice losing money? Only judged from `PRACTICE_MIN` closed trades."""
    lo = max(float(since_s or 0), now_s - PRACTICE_DAYS * DAY_S)
    rows = [r for r in (ledger_of or _ledger_default)(pid) if float(r.get("ts") or 0) >= lo]
    total = sum(float(r.get("pnl_est") or 0) for r in rows)
    if len(rows) >= PRACTICE_MIN and total < 0:
        return False, f"practice lost {total:+.2f} over its last {len(rows)} closed trades"
    return True, ""


def _say(log: list, now_s: float, pid: str, text: str) -> None:
    log.append({"at": now_s, "room": pid, "text": text})


def pick(now_s: float | None = None, *, doc: dict | None = None,
         ledger_of: Callable[[str], list[dict]] | None = None, save: bool = True) -> dict:
    """One daily pass. Returns what it did: {changed, kept, replaced, off, on, log}. Writes the
    picker file (unless `save` is False) ONLY when something changed or it has never run, so
    a quiet day leaves the file - and every reader's cache - alone. Never raises for a missing
    Forecast v4: the slots simply stay as they are."""
    from tradingagents import forecast_v4 as f4
    from tradingagents import profiles

    now_s = time.time() if now_s is None else now_s
    st = load()
    if st.get("enabled") is False:
        return {"skipped": "the picker is switched off", "changed": False}
    doc = doc if doc is not None else f4.load()
    if not doc or not doc.get("rules"):
        return {"skipped": "Forecast v4 has no rule sets yet - every room keeps its rule", "changed": False}

    have = dict(st.get("slots") or {})
    first = not have
    log: list[dict] = []
    kept, failed = {}, []
    for pid in slots():
        slot = have.get(pid)
        rule = (slot or {}).get("rule") or (profiles.get(pid) or {}).get("v4_rule")
        rid = f4.rule_id(**rule)
        slot = slot if isinstance(slot, dict) and slot.get("rule") else {
            "rule": dict(rule), "rule_id": rid, "off": False, "since_s": 0, "why": "the rule the room started with"}
        ok, why = judge(resolve(doc, rid))
        if ok and not slot.get("off"):
            ok, why = practice(pid, slot.get("since_s") or 0, now_s, ledger_of)
        if ok:
            if slot.get("off"):
                slot = {**slot, "off": False, "why": "its rule passes again"}
                _say(log, now_s, pid, f"back on: #{rid} passes again")
            kept[pid] = slot
        else:
            failed.append((pid, slot, why))

    taken = {_same_results(r) for r in (resolve(doc, s["rule_id"]) for s in kept.values()) if r}
    # a slot that just failed never takes its own rule set back (practice can fail a rule the
    # backtest still likes), nor a twin of it
    taken |= {_same_results(r) for r in (resolve(doc, old["rule_id"]) for _, old, _ in failed) if r}
    queue = [r for r in candidates(doc) if _same_results(r) not in taken]
    out = dict(kept)
    for pid, old, why in failed:
        if queue:
            rec = queue.pop(0)
            rule = _rule_of(rec)
            out[pid] = {"rule": rule, "rule_id": f4.rule_id(**rule), "off": False, "since_s": now_s,
                        "why": f"#{old['rule_id']} stopped: {why}", "worst_month": rec.get("rank"),
                        "profit": rec.get("profit")}
            _say(log, now_s, pid, f"#{old['rule_id']} replaced by #{out[pid]['rule_id']}: {why}")
        elif old.get("off"):
            out[pid] = old            # still nothing good enough: stays off, said once when it went off
        else:
            out[pid] = {**old, "off": True, "off_since_s": now_s,
                        "why": f"switched off: {why}, and no other rule set passes"}
            _say(log, now_s, pid, f"#{old['rule_id']} switched off: {why}; no other rule set passes")

    changed = first or any(out.get(p) != have.get(p) for p in out)
    new = {**st, "enabled": True, "slots": out, "last_pass_s": now_s,
           "log": (list(st.get("log") or []) + log)[-LOG_KEEP:]}
    if changed and save:
        _save(new)
        for line in log:
            _bell(line)
    return {"changed": changed, "slots": out, "log": log, "first": first}


def _bell(line: dict) -> None:
    """One bell per decision: it is the only way the operator hears that a room was swapped."""
    try:
        from tradingagents import notifications as n
        from tradingagents import profiles
        from tradingagents.positions_view import fmt_when

        n.record("picker", f"Picker: {line['text']}"[:200],
                 detail=f"{fmt_when(line['at'])} - slot {profiles.name_of(line['room'])}", ok=True)
    except Exception:
        pass        # a bell that fails never ends a pass


def words(pid: str) -> dict | None:
    """What a room's screen says about the picker: None for a room it does not fill."""
    from tradingagents import profiles
    from tradingagents.positions_view import fmt_when

    slot = profiles.picked(pid)
    if slot is None:
        return None
    since = slot.get("since_s") or 0
    return {"enabled": load().get("enabled") is not False, "off": bool(slot.get("off")),
            "rule_id": slot.get("rule_id"), "why": slot.get("why") or "",
            "since": fmt_when(since) if since else None,
            "last_pass": fmt_when(load()["last_pass_s"]) if load().get("last_pass_s") else None}


def set_enabled(on: bool) -> dict:
    """The operator's switch. Off only stops the daily pass: every room keeps the rule it follows now."""
    st = load()
    st["enabled"] = bool(on)
    _save(st)
    return {"enabled": bool(on)}


if __name__ == "__main__":
    import sys

    res = pick(save="--dry" not in sys.argv)
    print(json.dumps({k: v for k, v in res.items() if k != "slots"}, indent=1, default=str))
