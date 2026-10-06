"""What every room is running right now, as Backtest v2 combinations.

The pair files keep these rows even when their target is not bigger than their
stop (backtest_report.store_keeps), because the watcher's hourly switch-off
check reads its rows from the pair files (strategy_watcher._fresh_row): a row
missing there is switched off at once, and the operator chose to leave the
rooms as they are (Oct 06, 2026, "Backtest tab only"). Spec:
docs/superpowers/specs/2026-10-06-backtest-v2-target-over-stop-design.md
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# pid -> (mtime_ns, frozenset of combos): a room whose file cannot be read
# keeps its last known combos rather than dropping to nothing
_CACHE: dict = {}


def _room_combos(settings: dict) -> frozenset:
    from tradingagents import auto_trader as at
    from tradingagents import backtest_report as br
    from tradingagents import forecast_v2 as f2

    out = set()
    for key, coins in (settings.get("strategy_coins") or {}).items():
        sp = None
        for coin in coins or ():
            if not at.book_names(settings, key, coin):
                continue
            if sp is None:
                if key not in at.STRATEGY_SPECS:
                    try:
                        at.merge_runtime_specs()
                    except Exception:                          # noqa: BLE001
                        pass
                sp = f2.spec_of(key)
            if not (sp.get("tf") and sp.get("signal") and sp.get("tp") is not None
                    and sp.get("sl") is not None):
                continue
            out.add(br.combo_of({"coin": coin, "tf": sp["tf"], "signal": sp["signal"],
                                 "th": sp.get("th") or 0.0, "sl": sp["sl"],
                                 "tp": sp["tp"]}))
    return frozenset(out)


def combos() -> frozenset:
    """What the pair-file writers call (tests patch this one, conftest.py)."""
    return read_combos()


def read_combos() -> frozenset:
    """Every (coin, tf, signal, th, sl, tp) any room has switched on now."""
    from tradingagents import auto_trader as at
    from tradingagents import profiles

    out: set = set()
    for pid in profiles.ids():
        try:
            path = Path(profiles.path(at.SETTINGS_PATH, pid))
        except ValueError:
            continue
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            _CACHE.pop(pid, None)            # no settings: the room runs nothing
            continue
        have = _CACHE.get(pid)
        if have is None or have[0] != mtime:
            try:
                settings = json.loads(path.read_text(encoding="utf-8") or "{}")
                got = _room_combos(settings if isinstance(settings, dict) else {})
            except (OSError, ValueError) as exc:
                logger.warning("running rows: %s settings unreadable (%s) - keeping its "
                               "last known strategies", pid, type(exc).__name__)
                got = have[1] if have else frozenset()
                _CACHE[pid] = (have[0] if have else -1, got)
                out |= got
                continue
            _CACHE[pid] = (mtime, got)
        out |= _CACHE[pid][1]
    return frozenset(out)
