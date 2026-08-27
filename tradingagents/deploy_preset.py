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
* a coin already claimed on that timeframe by a different strategy — MEXC nets
  two positions on one contract into one, so the second entry resizes the
  first and either stop closes part of a trade it does not own
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
    """(coin, timeframe) -> the strategy key already holding it.

    Read from the TARGET machine's settings, so a preset cannot walk onto a
    contract that machine is already trading on that timeframe.
    """
    from tradingagents import auto_trader as at

    out: dict = {}
    coins = settings.get("strategy_coins") or {}
    for key, got in coins.items():
        spec = at.STRATEGY_SPECS.get(key) or {}
        tf = str(spec.get("interval") or "")
        for coin in got or []:
            out[(str(coin), tf)] = key
    return out


def plan(preset: dict, settings: dict) -> dict:
    """What applying would change, and what it would refuse. Pure."""
    from tradingagents import auto_trader as at

    claimed = _claims(settings)
    arm: dict = {}
    refused: list = []
    for key, one in sorted(preset["strategies"].items()):
        spec = at.STRATEGY_SPECS.get(key)
        if not spec:
            refused.append({"key": key, "why": "not in STRATEGY_SPECS — this "
                                               "repo is older than the preset"})
            continue
        tf = str(spec.get("interval") or "")
        keep, clash = [], []
        for coin in one["coins"]:
            holder = claimed.get((str(coin), tf))
            if holder and holder != key:
                clash.append(f"{coin} is already traded by {holder} on {tf}")
            else:
                keep.append(str(coin))
        if clash:
            refused.append({"key": key, "why": "; ".join(clash)})
        if keep:
            arm[key] = {"coins": keep,
                        "margin": float(one.get("margin")
                                        or preset.get("base_margin") or 5.0),
                        "sizing": str(one.get("sizing")
                                      or preset.get("sizing") or "flat"),
                        "book": list(one.get("book")
                                     or preset.get("book") or ["paper"])}
    return {"arm": arm, "refused": refused}


def merged(preset: dict, settings: dict) -> dict:
    """The settings this preset would produce — the existing file plus these
    rows. Nothing the preset does not name is touched."""
    got = plan(preset, settings)
    out = dict(settings)
    out["strategies"] = sorted(set(out.get("strategies") or [])
                               | set(got["arm"]))
    for field, pick in (("strategy_coins", lambda v: v["coins"]),
                        ("strategy_margins", lambda v: v["margin"]),
                        ("strategy_sizing", lambda v: v["sizing"]),
                        ("strategy_books", lambda v: v["book"])):
        out[field] = {**(out.get(field) or {}),
                      **{k: pick(v) for k, v in got["arm"].items()}}
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
    return "\n".join(lines)


def apply(path, *, write: bool = False) -> dict:
    """Merge a preset into this machine's settings. `write=False` decides
    nothing — it is the dry run the CLI prints."""
    from tradingagents import auto_trader as at

    preset = load(path)
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

    got = apply(path, write=write)
    print(describe(got["preset"], got["settings"]))
    if write:
        print(f"\nWRITTEN to {at.SETTINGS_PATH}")
        print("Every row is on the book the preset asked for. Going LIVE is a "
              "click per row, on the machine with the keys.")
    else:
        print("\nDRY RUN — nothing written. Add --apply to arm these.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
