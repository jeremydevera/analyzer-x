"""One-time hand-over to the skill rooms (Nov 10, 2026).

The operator: "can you deploy this 3 and remove the existing strategy in my
auto trade". The three skill rooms (#D7EN8BNV, #RSS7CUKH, #7T3VJU82) trade
Backtest v4's strategies; the ten older rooms below stop switching rows on
and off. Spec: docs/superpowers/specs/2026-11-10-skill-rooms-design.md.

`retire_others()` turns those ten watchers OFF and nothing else:
  * the room whose id is `profiles.MAIN` is never touched;
  * no slot is disarmed, so a slot holding "real" is never touched (the ten
    rooms hold no switched-on rows at the hand-over, and a watcher that is
    off changes none);
  * open practice trades are left to their runners, as `retire_room` does.
Running it twice writes nothing the second time.
"""
from __future__ import annotations

import time

OTHERS = ("55D32617", "4FC03172", "B2404C0B", "6B08FF64", "CC94D9FB",
          "99E79CBA", "C7396286", "1D4274C1", "8F0C7926", "BBE0A361")

REASON = "watcher off: replaced by the skill rooms (operator, Nov 10, 2026)"


def retire_others() -> dict:
    """Each of the ten rooms' watcher OFF; returns `{room id: watcher mode}`."""
    from tradingagents import local_history as lh
    from tradingagents import profiles
    from tradingagents import strategy_watcher as sw

    out: dict = {}
    for pid in OTHERS:
        if pid == profiles.MAIN or not profiles.valid(pid):
            continue
        with profiles.using(pid):
            sw.set_mode("off")
            # the reason goes into this room's own deploy history, where the
            # operator reads what happened to a room
            lh.record_deployment({"changed_at": int(time.time()),
                                  "strategy_key": "watcher", "symbol": "ALL",
                                  "action": "watcher_off", "note": REASON})
            out[pid] = sw.mode_of(sw._read())
    return out


if __name__ == "__main__":
    import json
    import sys

    if sys.argv[1:] == ["retire_others"]:
        print(json.dumps(retire_others(), indent=2))
    else:
        sys.exit("usage: python -m tradingagents.v4_rooms retire_others")
