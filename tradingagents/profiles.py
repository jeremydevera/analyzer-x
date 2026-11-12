"""Trading profiles: separate rooms, each with its own settings, open
positions, trade record, runner and watcher.

Operator, Sep 29, 2026: *"when i switch to B52662ED i should see its own
tiles, own live trade, own demo trade, own calendar pnl, in short it has its
own room/ profile"*. Plan: docs/superpowers/plans/2026-09-29-trading-profiles.md.

`main` IS `~/.tradingagents` exactly as it always was — no file moved. Every
other profile is `~/.tradingagents/profiles/<ID>/`.

Which profile a piece of code is working for is `current()`: a ContextVar, so
one API process can serve four profiles at once (a request sets it, the
thread the route runs on inherits it), defaulting to the env `TA_PROFILE` so a
runner process started for a profile is that profile for its whole life.
"""
from __future__ import annotations

import contextlib
import contextvars
import os
import re
from pathlib import Path

MAIN = "main"
HOME = Path(os.path.expanduser("~/.tradingagents"))
_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# NO LIMIT ON HOW MANY (operator, Sep 30, 2026: "i dont want a limit remove
# it"): 0 = unlimited for the day, the total and per coin.
NO_LIMIT = {"max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0,
            # ...and RAW: the criteria and nothing else ("i want raw output")
            "raw": True}

# THE ROOM THAT WAS MAIN IS #09439DC2 (operator, Oct 14, 2026: "the main tab
# is a room strategy so what i want is to assign and id for it and create a new
# tab for it"). 09439DC2 is forecast_rules.rule_id of its rules — 90% wins, 20+
# trades in 30 days, TP wider than SL, stop 2% or tighter — the way the 1-4 day
# rooms were named. ONLY THE NAME: its id stays "main" and its folder stays
# ~/.tradingagents, so no file moves and nothing about trading changes. The
# word "Main" now names the Auto Trade tab of every room's past trades.
MAIN_DISPLAY_ID = "09439DC2"

# The four rooms (operator, Sep 29, 2026). `rules` seeds a profile's watcher
# the first time it runs: the three rule sets from the 100-scenario research
# (https://claude.ai/artifact/A5FE8PZcbLsHHafhCUuBsZ), Main keeps its own.
BUILTIN = [
    {"id": MAIN, "name": f"#{MAIN_DISPLAY_ID}", "display_id": MAIN_DISPLAY_ID, "rules": None},
    {"id": "DC57174E", "name": "#DC57174E",
     "rules": {"on_winrate": 80.0, "off_winrate": 80.0, "min_trades": 50,
               "tp_rule": ">", "max_sl": 2.0, **NO_LIMIT}},
    {"id": "CC8DC54C", "name": "#CC8DC54C",
     "rules": {"on_winrate": 80.0, "off_winrate": 80.0, "min_trades": 40,
               "tp_rule": ">", "max_sl": 2.0, **NO_LIMIT}},
    {"id": "B52662ED", "name": "#B52662ED",
     "rules": {"on_winrate": 70.0, "off_winrate": 70.0, "min_trades": 50,
               "tp_rule": ">", "max_sl": 2.0, **NO_LIMIT}},
]
# THE THREE ABOVE ARE RETIRED (operator, Sep 30, 2026: "undeploy my current
# live then deploy the table you mentined"): every row switched off and the
# watcher OFF, but the room stays — its runner finishes the practice trades
# still open, and its record and calendar are kept to compare against.
for _p in BUILTIN[1:]:
    _p["retired"] = True

# ...AND THE TABLE, one room per rule set, named by the rule set's id: the
# round-five research (https://claude.ai/artifact/UUNAie322TPyjJU8MaZtQo,
# 144 rule sets over 4,585,414 strategies, picked on Jul 01-Aug 31 and graded
# on Sep 01-Sep 30, 2026). Every rule of each is copied from its row; a
# 15-day window reads each row's own measured t15/w15.
def _rule(window: int, line: float, trades: int, judge: int = 0) -> dict:
    """A room's rules, raw. `judge` is the window its switch-off reads when it
    is not `window` (Oct 07, 2026: the 1-4 day rooms, switched off on 30)."""
    return {"on_winrate": line, "off_winrate": line, "min_trades": trades,
            "tp_rule": ">", "max_sl": 2.0, "window_days": window,
            **({"judge_days": judge} if judge else {}), **NO_LIMIT}


# Main first, then the table, then the retired rooms — the order of the tabs
BUILTIN[1:1] = [
    {"id": "55D32617", "name": "#55D32617", "rules": _rule(15, 70.0, 50)},
    {"id": "4FC03172", "name": "#4FC03172", "rules": _rule(30, 70.0, 50)},
    {"id": "B2404C0B", "name": "#B2404C0B", "rules": _rule(15, 75.0, 50)},
    {"id": "6B08FF64", "name": "#6B08FF64", "rules": _rule(15, 80.0, 30)},
    {"id": "CC94D9FB", "name": "#CC94D9FB", "rules": _rule(30, 80.0, 30)},
    # THE LAST 1, 2, 3 AND 4 DAYS (operator, Oct 07, 2026: "can you create a
    # room strategy that has criteria that looks for past 1 day or 2 days or 3
    # days or 4 days ... (create seperate room for each)"): switched on at 80%+
    # with 30+ trades INSIDE those days, switched off on "the DEMO 30 DAYS
    # figure". Each named by its id (forecast_rules.rule_id of its rule set,
    # judge_days included). docs/superpowers/specs/2026-10-07-short-window-rooms-design.md
    {"id": "99E79CBA", "name": "#99E79CBA", "rules": _rule(1, 80.0, 30, judge=30)},
    {"id": "C7396286", "name": "#C7396286", "rules": _rule(2, 80.0, 30, judge=30)},
    {"id": "1D4274C1", "name": "#1D4274C1", "rules": _rule(3, 80.0, 30, judge=30)},
    {"id": "8F0C7926", "name": "#8F0C7926", "rules": _rule(4, 80.0, 30, judge=30)},
    # 2:1 AFTER REAL FEES (operator, Oct 17, 2026: "Room for #BBE0A361"): the
    # one rule set prompt 4 kept when one win, after the fees its trades
    # really paid, must pay two losses — 65% wins, 30+ trades in 30 days, any
    # TP, stop 1% or tighter, target 2% or wider. Found on BANANA 30m cx_veto
    # 2.5% / 1%: 18 trades Jul 11 - Oct 11, 2026, 8W/10L, +$6.92, a win +$2.15
    # against a loss -$1.03. The rooms' own 2:1 floor (watcher_policy min_pay).
    {"id": "BBE0A361", "name": "#BBE0A361",
     "rules": {**_rule(30, 65.0, 30), "tp_rule": "any", "max_sl": 1.0, "min_tp": 2.0}},
    # THE SKILL ROOMS (Nov 10, 2026): Forecast v4's three best rule sets as
    # practice rooms. They are FOLLOWED, never run: a separate follower (a later
    # task) writes their trades from Backtest v4's own engine, so no runner may
    # ever start here -- a normal runner would book TP/SL exits and write
    # `paper_cleared` rows on positions it does not own. `rules` stays None (no
    # watcher rules); `v4_rule` is forecast_v4.rule_id's input, so
    # forecast_v4.rule_id(**v4_rule) == the room's id.
    # docs/superpowers/specs/2026-11-10-skill-rooms-design.md
    {"id": "D7EN8BNV", "name": "#D7EN8BNV", "rules": None, "follows": "v4",
     "v4_rule": {"window": 30, "win_rate": 90, "min_trades": 20, "tp_rule": "any",
                 "sl_cap": 0.0, "tf": "", "skill": ""}},
    {"id": "RSS7CUKH", "name": "#RSS7CUKH", "rules": None, "follows": "v4",
     "v4_rule": {"window": 30, "win_rate": 80, "min_trades": 20, "tp_rule": "any",
                 "sl_cap": 1.5, "tf": "", "skill": ""}},
    {"id": "7T3VJU82", "name": "#7T3VJU82", "rules": None, "follows": "v4",
     "v4_rule": {"window": 30, "win_rate": 80, "min_trades": 20, "tp_rule": "any",
                 "sl_cap": 0.0, "tf": "1h", "skill": ""}},
]

# THE OLD ROOMS ARE OFF, TABS AND ALL (operator, Nov 11, 2026: "i said undeploy
# the old existing rooms / only deploy your 3 suggested room", after their
# watchers had been switched off on Nov 10 with the tabs left up). "Off" is the
# STANDING SETUP's word: no tab at all (`retired`), the room kept in BUILTIN
# only so its runner could finish a practice trade still open (none was: all
# ten held 0 open positions and 0 switched-on rows on Nov 11, 2026 7:35am).
# #09439DC2 (the room `main`) is not among them: they did not name it.
OFF_NOV11 = ("55D32617", "4FC03172", "B2404C0B", "6B08FF64", "CC94D9FB",
             "99E79CBA", "C7396286", "1D4274C1", "8F0C7926", "BBE0A361")
for _p in BUILTIN:
    if _p["id"] in OFF_NOV11:
        _p["retired"] = True

# ...AND #09439DC2 TOO (operator, Nov 11, 2026: "remove 09439DC2", asked if
# only the three skill rooms should show). The room whose id is `main` is OFF
# like the ten: no tab, its watcher off (`mode_of`), out of the Main tab's past
# trades. ONLY THE ROOM: its id stays `main` and its folder stays
# ~/.tradingagents, the base every call outside a room still reads (0 open
# trades and 0 switched-on rows on Nov 11, 2026). `name_of` still prints
# #09439DC2 for it.
MAIN_OFF = True
for _p in BUILTIN:
    if _p["id"] == MAIN and MAIN_OFF:
        _p["retired"] = True


def follows(pid: str) -> str | None:
    """"v4" for a room whose trades a follower writes from Backtest v4 (no
    runner, no watcher ever); None for every other room."""
    return (get(pid) or {}).get("follows") or None


# THE DAILY PICKER'S SLOTS (operator, Nov 12, 2026: "can i have a logic to run
# the best switch-on for this month ... i will not manually search for best
# switch on and deploy and undeploy what is not working"). The three skill
# rooms are FIXED SLOTS: `tradingagents/v4_picker.py` writes
# `~/.tradingagents/v4/picker.json` once a day, and a slot there says which rule
# set the room follows now (and whether the room is off). The room's id and
# folder never change - only the rule it follows - and with no file (a test, a
# machine that never ran the picker) every room follows its BUILTIN rule.
PICKER_PATH: Path | None = None
_PICKER_CACHE: dict = {"key": None, "data": {}}


def _picker_file() -> Path | None:
    if PICKER_PATH is not None:
        return Path(PICKER_PATH)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None          # a test never reads this PC's real picks
    return HOME / "v4" / "picker.json"


def picker_state() -> dict:
    """The picker's record, {} when there is none or it cannot be read (a room
    then follows its BUILTIN rule - never an error on a screen)."""
    f = _picker_file()
    if f is None:
        return {}
    try:
        st = f.stat()
        key = (str(f), st.st_mtime_ns, st.st_size)
        if _PICKER_CACHE["key"] == key:
            return _PICKER_CACHE["data"]
        import json as _json

        data = _json.loads(f.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
        _PICKER_CACHE.update(key=key, data=data)
        return data
    except (OSError, ValueError):
        return {}


def picked(pid: str) -> dict | None:
    """The picker's slot for a follower room: {rule, rule_id, off, since_s, why}."""
    if follows(pid) != "v4":
        return None
    slot = (picker_state().get("slots") or {}).get(pid)
    return slot if isinstance(slot, dict) and isinstance(slot.get("rule"), dict) else None


def v4_rule(pid: str) -> dict | None:
    """A copy of a follower room's rule set (forecast_v4.rule_id's arguments): the
    rule the daily picker gave its slot, else the room's own BUILTIN rule."""
    slot = picked(pid)
    if slot:
        return dict(slot["rule"])
    r = (get(pid) or {}).get("v4_rule")
    return dict(r) if r else None


def picker_off(pid: str) -> bool:
    """True when the picker switched this slot off: no rule set passes for it today."""
    slot = picked(pid)
    return bool(slot and slot.get("off"))


def rule_name(pid: str) -> str:
    """What a follower room's TAB says: the rule set it follows today, `#CKVS7G7Z`
    (the room's own id when the picker has given it nothing)."""
    slot = picked(pid)
    rid = (slot or {}).get("rule_id")
    return f"#{rid}" if rid else name_of(pid)


def retired(pid: str) -> bool:
    return bool((get(pid) or {}).get("retired")) or picker_off(pid)


def shown() -> list[str]:
    """The rooms that get a TAB. A retired room gets none (operator, Oct 01,
    2026: "if i say off you should completely remoev the tab"); it stays in
    BUILTIN only so its runner can finish the practice trades still open and
    its record stays on disk. A slot the picker switched off gets none either."""
    return [p["id"] for p in BUILTIN if not retired(p["id"])]

def history_rooms() -> list[str]:
    """The rooms whose trades the Main tab lists: every room with a tab PLUS a slot the picker
    switched off - it has no tab, but what it traded is still the operator's record (a room
    retired by hand stays out, as before)."""
    tabs = shown()
    return tabs + [p["id"] for p in BUILTIN
                   if p["id"] not in tabs and not p.get("retired") and picker_off(p["id"])]


_CURRENT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ta_profile", default=os.environ.get("TA_PROFILE") or MAIN)


def ids() -> list[str]:
    return [p["id"] for p in BUILTIN]


def get(pid: str) -> dict | None:
    return next((p for p in BUILTIN if p["id"] == pid), None)


def name_of(pid: str) -> str:
    """How a room is PRINTED — the one place (Oct 14, 2026): `#09439DC2` for
    the room whose id is `main`, `#<id>` for every other room, known or not."""
    p = get(pid)
    return p["name"] if p else f"#{pid}"


def valid(pid: str | None) -> bool:
    return bool(pid) and get(str(pid)) is not None


def current() -> str:
    pid = _CURRENT.get()
    return pid if valid(pid) else MAIN


@contextlib.contextmanager
def using(pid: str):
    """Work as profile `pid` inside the block (this thread/context only)."""
    if not valid(pid):
        raise ValueError(f"unknown profile {pid!r}; the profiles are {ids()}")
    tok = _CURRENT.set(pid)
    try:
        yield pid
    finally:
        _CURRENT.reset(tok)


def set_current(pid: str) -> contextvars.Token:
    """For a request middleware: set, and hand back the token to reset."""
    if not valid(pid):
        raise ValueError(f"unknown profile {pid!r}; the profiles are {ids()}")
    return _CURRENT.set(pid)


def reset(tok: contextvars.Token) -> None:
    _CURRENT.reset(tok)


def dir_for(pid: str, home: Path | None = None) -> Path:
    """The profile's folder. Main is the home itself."""
    root = Path(home) if home is not None else HOME
    if pid == MAIN:
        return root
    if not _ID.match(pid or ""):
        raise ValueError(f"bad profile id {pid!r}")
    return root / "profiles" / pid


def path(global_path: Path, pid: str | None = None) -> Path:
    """`global_path` as it is for profile `pid` (default: the current one).

    Main gets `global_path` ITSELF — read at the call, so a test that
    monkeypatches `at.LEDGER_PATH` still points Main at its fixture. Any
    other profile gets the same file name inside its own folder."""
    pid = current() if pid is None else pid
    p = Path(global_path)
    if pid == MAIN:
        return p
    # beside the file it replaces, so a test that points a path at tmp_path
    # keeps every profile's copy inside tmp_path too
    d = dir_for(pid, home=p.parent)
    d.mkdir(parents=True, exist_ok=True)
    return d / p.name
