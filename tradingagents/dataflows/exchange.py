"""The ONE door to the exchange (Oct 10, 2026, spec D2).

Every caller imports this as `fx`::

    from tradingagents.dataflows import exchange as fx
    fx.klines("BTC_USDT", "Min60", 300)

and each attribute is handed to the venue's adapter AT CALL TIME —
`gate_futures` or `mexc_futures`, whichever `tradingagents.venue.current()`
names. Nothing is copied at import, so:

* the switch is one setting (venue.json, or `TA_VENUE` on GitHub), and
* a test that monkeypatches `mexc_futures.klines` still reaches the code it
  drives.

This module defines nothing an adapter answers, on purpose: a module-level
name here would shadow the adapter's and silently pin one exchange.
`tests/test_one_door_to_the_exchange.py` keeps every app module behind it.
"""
from __future__ import annotations

import sys
import types


def adapter():
    """The module that talks to the exchange this app trades."""
    from tradingagents import venue  # noqa: PLC0415

    if venue.current() == "gate":
        from tradingagents.dataflows import gate_futures  # noqa: PLC0415
        return gate_futures
    from tradingagents.dataflows import mexc_futures  # noqa: PLC0415
    return mexc_futures


def __getattr__(name: str):
    mod = adapter()
    try:
        return getattr(mod, name)
    except AttributeError:
        from tradingagents import venue  # noqa: PLC0415
        raise AttributeError(
            f"the {venue.name()} adapter has no {name!r}") from None


class _Door(types.ModuleType):
    """A WRITE through the door lands on the adapter, never on the door.

    `monkeypatch.setattr(shard.fx, "klines", fake)` used to put `klines` in
    THIS module's own namespace, and the cleanup then put the adapter's real
    function there — pinned for the rest of the process. Every later test
    that patched `mexc_futures.klines` was bypassed and reached the network
    (found Oct 10, 2026: the replay shard's tests passed alone and failed
    after the sweep shard's). Production code never writes here; the guard is
    for the one caller that does."""

    def __setattr__(self, name, value):
        if name.startswith("__"):
            super().__setattr__(name, value)
        else:
            setattr(adapter(), name, value)

    def __delattr__(self, name):
        if name.startswith("__"):
            super().__delattr__(name)
        else:
            delattr(adapter(), name)


sys.modules[__name__].__class__ = _Door
