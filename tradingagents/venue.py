"""Which exchange this app trades — the ONE place that knows (Oct 10, 2026).

The operator: *"okay switch to gate from now on, this means every logic in my
app will be gate instead of mexc"*. Every caller reaches the exchange through
`tradingagents.dataflows.exchange`, which asks `current()` which adapter to
hand the call to. Spec: docs/superpowers/specs/2026-10-10-switch-to-gate-design.md.

Order of authority:

1. `TA_VENUE` in the environment — GitHub's machines have no file, so their
   workflows set it; tests pin it (conftest) so no test reads the operator's
   own file.
2. `~/.tradingagents/venue.json`, written by the cutover
   (`tradingagents.venue_switch`) in the same breath as it moves the MEXC
   data aside.
3. Nothing written: **mexc**. The MEXC data still sits in every folder until
   the cutover moves it, so a restart before the cutover must never start
   filling those folders with another exchange's numbers.

A broken file is an ERROR, never "probably MEXC": trading one exchange's
prices against the other exchange's backtests is the failure this whole
module exists to prevent.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

VENUE_FILE = Path(os.path.expanduser("~/.tradingagents")) / "venue.json"

NAMES = {"mexc": "MEXC", "gate": "Gate"}
DEFAULT = "mexc"


def _check(v: str, where: str) -> str:
    v = str(v or "").strip().lower()
    if v not in NAMES:
        raise ValueError(f"unknown exchange {v!r} in {where}; "
                         f"use one of {', '.join(sorted(NAMES))}")
    return v


# The file's answer, kept until the file changes: `backtest_report.row_code`
# asks once per row and a report hashes 250,000 of them.
_SEEN: dict = {}


def current() -> str:
    """"gate" or "mexc"."""
    env = os.environ.get("TA_VENUE", "").strip()
    if env:
        return _check(env, "TA_VENUE")
    try:
        st = os.stat(VENUE_FILE)
    except FileNotFoundError:
        return DEFAULT
    key = (str(VENUE_FILE), st.st_mtime_ns, st.st_size)
    hit = _SEEN.get("file")
    if hit and hit[0] == key:
        return hit[1]
    try:
        raw = VENUE_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT
    try:
        v = _check(json.loads(raw).get("venue"), str(VENUE_FILE))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{VENUE_FILE} cannot be read ({exc}) — refusing "
                         f"to guess which exchange this app trades") from exc
    _SEEN["file"] = (key, v)
    return v


def since() -> float:
    """When this PC switched to the exchange it trades (venue.json's
    `since`), or 0 when nothing was ever switched. A GitHub run STARTED
    before it measured the other exchange (cloud_autopilot skips it)."""
    try:
        return float(json.loads(VENUE_FILE.read_text(encoding="utf-8"))
                     .get("since") or 0.0)
    except (OSError, ValueError, AttributeError, TypeError):
        return 0.0


def name() -> str:
    """The exchange as a screen prints it: "Gate" / "MEXC"."""
    return NAMES[current()]


def set_current(v: str) -> None:
    """Write the switch. Only the cutover calls this: it moves the other
    exchange's data aside first (venue_switch)."""
    v = _check(v, "set_current")
    VENUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VENUE_FILE.with_name(f"{VENUE_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"venue": v, "since": time.time()}),
                   encoding="utf-8")
    os.replace(tmp, VENUE_FILE)


# ------------------------------------------------------------------ kinds
# What a coin IS (spec D5). MEXC names every tokenized stock with a STOCK
# suffix, so the name was the answer. Gate names stocks by ticker
# (AAPL_USDT) and says what each contract is in its own list
# (`contract_type`: stocks, indices, metals, forex, commodities, "" for
# crypto) — so under Gate the list decides, never the name.
def kind(symbol: str) -> str:
    """"crypto" | "stocks" | "indices" | "metals" | "forex" |
    "commodities" | "unlisted" (Gate does not list it)."""
    sym = str(symbol or "").upper()
    if current() == "mexc":
        return ("stocks" if sym.removesuffix("_USDT").endswith("STOCK")
                else "crypto")
    from tradingagents.dataflows import gate_futures as gf  # noqa: PLC0415

    if not sym.endswith("_USDT"):
        sym += "_USDT"
    try:
        kinds = gf.contract_types()
    except Exception:                                          # noqa: BLE001
        return "unknown"        # never fetched and Gate unreachable
    return kinds.get(sym, "unlisted")


def is_stock_like(symbol: str) -> bool:
    """A tokenized stock or US ETF: trades in its home market's hours."""
    return kind(symbol) == "stocks"


def coins_of_kind(kind_name: str) -> list[str]:
    """Bare coin names (the row store's `coin`, no `_USDT`) of one kind, from
    the venue's own list — the crypto/stocks filter's list under Gate."""
    from tradingagents.dataflows import gate_futures as gf  # noqa: PLC0415

    return sorted(s.removesuffix("_USDT") for s, k in gf.contract_types().items()
                  if k == kind_name)


def stock_symbols() -> list[str]:
    """Every listed stock contract, sorted (the crypto/stocks filter's list
    under Gate)."""
    if current() == "mexc":
        raise ValueError("under MEXC a stock is read off its name; there is "
                         "no list to ask for")
    from tradingagents.dataflows import gate_futures as gf  # noqa: PLC0415

    return sorted(s for s, k in gf.contract_types().items() if k == "stocks")
