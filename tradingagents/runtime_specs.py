"""Strategy keys the watcher added while the app was running.

A key is a recipe (interval, bar length, TP, SL, threshold). The committed
blocks in auto_trader.py were written by hand-run generators; the watcher
cannot commit code, so it writes here and auto_trader merges the file on every
load_settings() (mtime-cached). A key that already exists with a DIFFERENT
spec is refused: one name means one recipe, on every screen and in every book.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PATH = Path(os.path.expanduser("~/.tradingagents")) / "runtime_specs.json"


def load() -> dict:
    try:
        got = json.loads(PATH.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def register(key: str, spec: dict) -> str:
    from tradingagents import auto_trader as at

    # A clash is judged against what is COMMITTED or already in the FILE —
    # never against a key that is only in this process's memory. A preview
    # check once put a key in memory, and the act pass afterwards answered
    # "same" and wrote nothing, so the runner never learned the key.
    committed = getattr(at, "_COMMITTED_KEYS", frozenset())
    reg = load()
    have = at.STRATEGY_SPECS.get(key) if key in committed else reg.get(key)
    if have is not None:
        if dict(have) != dict(spec):
            raise ValueError(f"{key} already means {have}, not {spec}")
        return "same"
    reg[key] = dict(spec)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(reg, sort_keys=True), encoding="utf-8")
    os.replace(tmp, PATH)
    return "added"
