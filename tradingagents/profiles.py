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

# The four rooms (operator, Sep 29, 2026). `rules` seeds a profile's watcher
# the first time it runs: the three rule sets from the 100-scenario research
# (https://claude.ai/artifact/A5FE8PZcbLsHHafhCUuBsZ), Main keeps its own.
BUILTIN = [
    {"id": MAIN, "name": "Main", "rules": None},
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
def _rule(window: int, line: float, trades: int) -> dict:
    return {"on_winrate": line, "off_winrate": line, "min_trades": trades,
            "tp_rule": ">", "max_sl": 2.0, "window_days": window, **NO_LIMIT}


# Main first, then the table, then the retired rooms — the order of the tabs
BUILTIN[1:1] = [
    {"id": "55D32617", "name": "#55D32617", "rules": _rule(15, 70.0, 50)},
    {"id": "4FC03172", "name": "#4FC03172", "rules": _rule(30, 70.0, 50)},
    {"id": "B2404C0B", "name": "#B2404C0B", "rules": _rule(15, 75.0, 50)},
    {"id": "6B08FF64", "name": "#6B08FF64", "rules": _rule(15, 80.0, 30)},
    {"id": "CC94D9FB", "name": "#CC94D9FB", "rules": _rule(30, 80.0, 30)},
]


def retired(pid: str) -> bool:
    return bool((get(pid) or {}).get("retired"))

_CURRENT: contextvars.ContextVar[str] = contextvars.ContextVar(
    "ta_profile", default=os.environ.get("TA_PROFILE") or MAIN)


def ids() -> list[str]:
    return [p["id"] for p in BUILTIN]


def get(pid: str) -> dict | None:
    return next((p for p in BUILTIN if p["id"] == pid), None)


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
