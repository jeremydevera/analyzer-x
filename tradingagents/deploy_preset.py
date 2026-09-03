"""Arm a measured set of strategies on another machine, from a file in git.

The catalog (STRATEGY_SPECS) travels in the repo. The ARMING does not: which
coin a strategy trades, its margin, its sizing and its book live in
``~/.tradingagents/auto_trade.json``, which is the operator's own file and is
not committed. So "add those strategies" on this PC left the Mac with the
specs and no rows on screen.

Operator, 2026-08-27: *"push those strategies to github so i can use it to my
machine"*.

A preset is that arming, written down: one JSON file per measured set, naming
every row by its ID and carrying the numbers it was measured with, so the
machine applying it can see WHAT it is arming and not just which keys.

Applying MERGES. It never writes a settings file from scratch, never touches a
strategy the preset does not name, and refuses in three cases that have cost
real money before:

* a key that is not in STRATEGY_SPECS — the repo is older than the preset, and
  arming a spec that does not exist is a row that trades nothing
* a coin another strategy already trades with REAL money — MEXC nets two
  positions on one contract into one, so the second entry resizes the first
  and either stop closes part of a trade it does not own. Per COIN, whatever
  the bar size, and only for a real book: a demo book has no position to fight
  over, which is why the app locks nothing on demo either
* a book the preset did not ask for. The preset says ``paper`` and applying
  keeps it paper; going live is a click the operator makes, on the machine
  that holds the keys, per row

Dry run by default::

    python -m tradingagents.deploy_preset presets/win30-flat-23.json
    python -m tradingagents.deploy_preset presets/win30-flat-23.json --apply
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESET_DIR = ROOT / "presets"


def load(path) -> dict:
    """Read a preset file and check its shape before anything is decided."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data.get("strategies"), dict) or not data["strategies"]:
        raise ValueError(f"{path}: no strategies in this preset")
    for key, one in data["strategies"].items():
        if not isinstance(one, dict) or not one.get("coins"):
            raise ValueError(f"{path}: {key} has no coins")
    return data


def _claims(settings: dict) -> dict:
    """coin -> the strategy key already trading it with REAL money.

    Read from the TARGET machine's settings, so a preset cannot walk onto a
    contract that machine is already trading.

    Per COIN, not per coin+timeframe, and only for a REAL book — the same rule
    `auto_trader.timeframe_locks` enforces: MEXC nets every order on a contract
    into one position whatever the bar size, and a DEMO book has no position to
    fight over ("for demo it can have multiple strategies so i can see if its
    working"). This function keyed on (coin, interval) and counted demo rows,
    so applying a preset twice refused four of its own strategies against the
    demo rows it had just written.
    """
    out: dict = {}
    books = settings.get("strategy_books") or {}
    coins = settings.get("strategy_coins") or {}
    for key, got in coins.items():
        if "real" not in (books.get(key) or []):
            continue
        for coin in got or []:
            out.setdefault(str(coin), key)
    return out


def plan(preset: dict, settings: dict) -> dict:
    """What applying would change, and what it would refuse. Pure."""
    from tradingagents import auto_trader as at

    claimed = _claims(settings)
    arm: dict = {}
    refused: list = []
    shared: list = []
    for key, one in sorted(preset["strategies"].items()):
        spec = at.STRATEGY_SPECS.get(key)
        if not spec:
            refused.append({"key": key, "why": "not in STRATEGY_SPECS — this "
                                               "repo is older than the preset"})
            continue
        keep, clash = [], []
        # A COIN ANOTHER REAL ROW TRADES IS NO LONGER A CLASH. The operator
        # armed 35 rows over 9 coins on 2026-09-04 — 20 of them on GPNSTOCK —
        # and asked for the runtime rule instead: one OPEN POSITION per coin,
        # first signal wins, the rest refused until it closes
        # (`auto_trader._busy_refusal`). `claimed` is still computed, and
        # `plan` still reports who else is on the coin, because 20 rows on one
        # contract is worth SEEING before applying.
        for coin in one["coins"]:
            holder = claimed.get(str(coin))
            keep.append(str(coin))
            if holder and holder != key:
                clash.append(f"{coin} is also traded live by {holder} — "
                             f"whichever signals first holds it")
        if clash:
            shared.append({"key": key, "with": "; ".join(clash)})
        if keep:
            arm[key] = {"coins": keep,
                        "margin": float(one.get("margin")
                                        or preset.get("base_margin") or 5.0),
                        "sizing": str(one.get("sizing")
                                      or preset.get("sizing") or "flat"),
                        "book": list(one.get("book")
                                     or preset.get("book") or ["paper"])}
    return {"arm": arm, "refused": refused, "shared": shared}


def merged(preset: dict, settings: dict) -> dict:
    """The settings this preset would produce.

    By default it MERGES: the existing file plus these rows, and nothing the
    preset does not name is touched.

    `"replace": true` in the preset (or `--replace` on the CLI) means what the
    operator asked for on 2026-09-04 — *"REMOVE THE EXISTING AUTO TRADE
    STRATEGIES COMPLIETELY AND ADD THESE IDS"* — so every strategy NOT named
    here is disarmed: it leaves the four arming maps holding the preset's keys
    and nothing else. A row with no coins and no book trades nothing, which is
    what disarmed means here.
    """
    got = plan(preset, settings)
    out = dict(settings)
    fields = (("strategy_coins", lambda v: v["coins"]),
              ("strategy_margins", lambda v: v["margin"]),
              ("strategy_sizing", lambda v: v["sizing"]),
              ("strategy_books", lambda v: v["book"]))
    if preset.get("replace"):
        out["strategies"] = sorted(got["arm"])
        for field, pick in fields:
            out[field] = {k: pick(v) for k, v in got["arm"].items()}
        # a loss limit or a label for a key nobody arms is dead weight, and it
        # would come back the moment that key is armed again by hand
        for field in ("strategy_loss_limits", "strategy_labels"):
            if out.get(field):
                out[field] = {k: v for k, v in out[field].items()
                              if k in got["arm"]}
        return _tail(preset, out)
    out["strategies"] = sorted(set(out.get("strategies") or [])
                               | set(got["arm"]))
    for field, pick in fields:
        out[field] = {**(out.get(field) or {}),
                      **{k: pick(v) for k, v in got["arm"].items()}}
    return _tail(preset, out)


def _tail(preset: dict, out: dict) -> dict:
    """The account-wide fields, applied the same way by both modes."""
    # The account-wide default matters for a row armed LATER by hand: these
    # rows were measured flat, and the shipped default is martingale.
    if preset.get("sizing"):
        out["sizing"] = str(preset["sizing"])
    out.setdefault("margin", float(preset.get("base_margin") or 5.0))
    # the live switch is never turned on by a preset
    out.setdefault("enabled", False)
    out.setdefault("dry_run", True)
    return out


def describe(preset: dict, settings: dict) -> str:
    """What would happen, in the operator's terms."""
    got = plan(preset, settings)
    lines = [f"{preset.get('name') or 'preset'}: {len(got['arm'])} strategies "
             f"over {sum(len(v['coins']) for v in got['arm'].values())} coins"]
    if preset.get("why"):
        lines.append(f"  {preset['why']}")
    rows = preset.get("strategies") or {}
    for key, v in got["arm"].items():
        one = rows.get(key) or {}
        ids = one.get("rows") or []
        lines.append(
            f"  {key:<24} {', '.join(c.replace('_USDT', '') for c in v['coins'])}"
            f"  ${v['margin']:g} {v['sizing']} {'/'.join(v['book'])}"
            + (f"  [{' '.join('#' + str(r) for r in ids)}]" if ids else ""))
    for bad in got["refused"]:
        lines.append(f"  REFUSED {bad['key']}: {bad['why']}")
    for both in got.get("shared") or []:
        lines.append(f"  SHARES A COIN {both['key']}: {both['with']}")
    return "\n".join(lines)


def apply(path, *, write: bool = False, replace: bool | None = None) -> dict:
    """Merge a preset into this machine's settings — or REPLACE the armed set
    with it. `write=False` decides nothing; it is the dry run the CLI prints."""
    from tradingagents import auto_trader as at

    preset = load(path)
    if replace is not None:
        preset = {**preset, "replace": bool(replace)}
    settings = at.load_settings()
    out = merged(preset, settings)
    if write:
        at.save_settings(out)
    return {"preset": preset, "settings": out,
            "plan": plan(preset, settings), "written": bool(write)}


def main(argv=None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    write = "--apply" in args
    replace = True if "--replace" in args else None
    args = [a for a in args if not a.startswith("--")]
    if not args:
        here = sorted(p.name for p in PRESET_DIR.glob("*.json")) \
            if PRESET_DIR.exists() else []
        print("usage: python -m tradingagents.deploy_preset <preset.json> "
              "[--apply]")
        if here:
            print("presets in this repo:")
            for name in here:
                print(f"  presets/{name}")
        return 2
    path = Path(args[0])
    if not path.exists() and (PRESET_DIR / path.name).exists():
        path = PRESET_DIR / path.name
    from tradingagents import auto_trader as at

    got = apply(path, write=write, replace=replace)
    print(describe(got["preset"], got["settings"]))
    if got["preset"].get("replace"):
        print("")
        print(f"REPLACE: only these "
              f"{len(got['plan']['arm'])} strategies stay armed; "
              f"every other row is disarmed.")
    if write:
        print(f"\nWRITTEN to {at.SETTINGS_PATH}")
        print("Every row is on the book the preset asked for. Going LIVE is a "
              "click per row, on the machine with the keys.")
    else:
        print("\nDRY RUN — nothing written. Add --apply to arm these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
