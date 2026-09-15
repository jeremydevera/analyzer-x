"""Going demo-only stopped the runner looking at the live book at all.

Operator, `Sep 16, 2026`: *"CAN YOU TURN OF LIVE, I WANT DEOM ONLY"*, then,
an hour later: *"FOR DEMO CTTKPGQE I'VE ALREADY TP IT WHY IS IT NOT IN LIVE
TRADE HISTORY?"* and *"when it close in mexc i does not reflect in ui"*.

Measured on their own machine:

    2:08am  all 85 strategies switched to ["paper"]
    2:14am  last `scan CTC_USDT[real]` line in auto_trade.log
    2:37am  MEXC closed position 1498235091 — exit 0.10003, realised +1.4398
    3:13am  the book still lists CTC_USDT#live#killzone_4h_sl3tp15 as OPEN,
            the ledger holds 0 live exit rows for trade CTTKPGQE, and the
            exchange reports 4 open positions with CTC not among them

`run_cycle` walks `active_modes(settings)`, which answers *which books do the
ARMED strategies want*. With everything on demo it returns `[True]`, so
`process_symbol` was never called for the live book — and the slot-level
rescue written for exactly this case ("no strategy armed in this book but a
position is open — tracking its EXIT only") lives INSIDE `process_symbol`.
The fix for the identical 2026-08-17 XAUT incident had been put one layer too
low, under a caller that had already decided not to call it.

Two rules, one per section:

* the live book is visited whenever the BOOK holds real money, whatever the
  settings say is armed — `dry` is a property of the position, fixed at
  entry, and it is the only honest test of "is there money on the exchange";
* a coin keeps its place in the cycle while it holds a real position, even if
  no strategy names it any more.

ENTRIES are untouched: `process_symbol`'s book filter still governs them and
the rescued strategy is added to `tripped`, so the live pass is exits only.
"""
from __future__ import annotations

import inspect

import tradingagents.auto_trader as at


def _state(**slots) -> dict:
    return dict(slots)


def _pos(dry: bool) -> dict:
    return {"side": -1, "vol": 98, "entry": 0.10166, "tp": 0.10014,
            "sl": 0.10471, "margin": 5.0, "strategy": "killzone_4h_sl3tp15",
            "entry_ts": 1789473600, "dry": dry, "opened_at": 1789494216,
            "trade_id": "CTTKPGQE"}


# ------------------------------------------- 1. the live book is still walked
def test_a_real_position_is_seen_even_with_nothing_armed_live():
    """The operator's exact state: every strategy demo, one real position
    open. `_has_real_position` is what makes the cycle look at the live book
    anyway."""
    st = _state(**{"CTC_USDT#live#killzone_4h_sl3tp15": {"position": _pos(False)}})
    assert at._has_real_position(st) is True


def test_a_book_holding_only_demo_positions_does_not_force_it():
    """A paper position is not money at risk, and forcing a live pass for one
    would make real venue calls for a trade that does not exist there."""
    st = _state(**{"CTC_USDT#paper#killzone_4h_sl3tp15": {"position": _pos(True)}})
    assert at._has_real_position(st) is False
    assert at._has_real_position({}) is False
    assert at._has_real_position({"x": None, "_tripped_logged": 1}) is False


def test_the_cycle_adds_the_live_book_when_real_money_is_open():
    """The bug, at the line that caused it: `modes = active_modes(settings)`
    and nothing else."""
    src = inspect.getsource(at.run_cycle)
    i = src.index("modes = active_modes(settings)")
    after = src[i:i + 2200]
    assert "_has_real_position(state)" in after, (
        "the cycle still trusts active_modes alone, so a demo-only settings "
        "file hides every open real position from its own exit path")
    assert "False not in modes" in after, "it must not add the live book twice"
    assert "modes = [*modes, False]" in after


def test_it_does_not_force_the_live_book_when_nothing_is_open():
    """No real position, no live pass — otherwise every demo-only cycle makes
    venue calls for nothing."""
    src = inspect.getsource(at.run_cycle)
    i = src.index("modes = active_modes(settings)")
    assert "if False not in modes and _has_real_position(state):" in src[i:i + 2200]


# --------------------------------------- 2. the coin keeps its place too
def test_a_coin_no_strategy_names_is_still_in_the_cycle():
    """Deleting a strategy must not hide the position it left behind. The
    symbol is read off the SLOT KEY, because a position dict carries no
    symbol of its own."""
    src = inspect.getsource(at.run_cycle)
    i = src.index("symbols: list[str] = []")
    block = src[i:i + 1400]
    assert 'str(slot).split("#", 1)[0]' in block
    assert 'not pos.get("dry")' in block, "only REAL positions earn this"
    assert "symbols.append(sym)" in block


# ------------------------------------------------ 3. entries stay closed
def test_the_live_pass_is_exits_only():
    """`process_symbol` filters entries by book and adds the rescued strategy
    to `tripped`; both must still be there, or this change would place real
    orders on a strategy the operator set to demo — which is what happened to
    XAUT on 2026-08-18."""
    src = inspect.getsource(at._process_slot)
    assert "dry in books_for(k, settings)" in src, "the entry filter is gone"
    i = src.index("no strategy armed in this book but a position is open")
    before = src[max(0, i - 900):i]
    assert "tripped = frozenset(tripped) | {_rescue}" in before, \
        "the rescued strategy must be tripped, or the live pass can ENTER"


def test_the_exchange_decides_whether_it_is_gone():
    """Rule 14. The close is detected from `open_positions`, never from a
    local price comparison."""
    src = inspect.getsource(at._process_slot)
    i = src.index("live_gone = False")
    after = src[i:i + 1400]
    assert "fx.open_positions(symbol)" in after
    assert "not any(" in after
