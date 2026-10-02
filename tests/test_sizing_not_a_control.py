"""Sizing stopped being a control on 2026-08-20; it must not stop being a VALUE.

Operator: "remove position sizing section because i always rely on strategy
always". The radio is gone. The danger is the one the removed code comment
recorded: when `sizing` was absent from the save payload, every Save silently
reverted a flat book to the martingale ladder — the dimension an audit showed
was producing the "13/13 green months" behind six live strategies. Removing the
widget must never become removing the value.

The widget-side tests read app.py, the retired Streamlit screen, and went with
it on Oct 02, 2026 (New Crypto, Analysis and LLM Models removed). The runner's
half — sizing_for and the staked margin — is what still trades, and stays.
"""
from __future__ import annotations

from tradingagents import auto_trader as at


def test_sizing_for_is_flat_whatever_the_file_says():
    """It defaulted to the ladder so a missing key could not silently switch a
    live book to flat. On Sep 11, 2026 the operator switched every book to
    flat on purpose ("just flat only ... do not double the margin for all
    martingale"), so the answer is flat for a missing key, a flat key and a
    martingale key alike — the value is kept in the file, and no longer
    decides a stake."""
    assert at.sizing_for({}) == "flat"
    assert at.sizing_for({"sizing": "flat"}) == "flat"
    assert at.sizing_for({"sizing": "martingale"}) == "flat"


def test_a_round_trip_through_sizing_for_is_stable():
    """Idempotent, and flat from any start: the value in the file no longer
    decides the stake (Sep 11, 2026), so feeding the answer back in must not
    change it either."""
    for v in ("flat", "martingale"):
        assert at.sizing_for({"sizing": at.sizing_for({"sizing": v})}) == "flat"


def test_the_staked_margin_never_escalates():
    """The runner's actual money maths. It used to be "unchanged by the UI
    removal" — flat stayed flat and the ladder still doubled. Since Sep 11,
    2026 ("just flat only ... do not double the margin for all martingale")
    the ladder does not escalate on real money either; only the backtest
    engine still measures it."""
    flat = {"sizing": "flat"}
    lad = {"sizing": "martingale"}
    assert at.staked_margin("k", flat, 0) == at.staked_margin("k", flat, 4), \
        "flat stakes the base at every rung"
    assert at.staked_margin("k", lad, 4) == at.staked_margin("k", lad, 0), \
        "a martingale setting stakes the base at every rung too"


