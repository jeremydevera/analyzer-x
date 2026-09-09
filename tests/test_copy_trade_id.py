"""An open trade's own id is copyable, in demo and in live.

Operator, Sep 10, 2026: *"i want ability to copy id of the open trades in
demo or live"*. The row already carried the STRATEGY id (#Y5UBBFPB, the row
in Stored strategies); what it never showed was THIS TRADE's id (FWQRY6Q4),
which is the string every ledger row for the trade carries and the one Trade
History prints once it closes. Two different ids on one row, so each button
says which it copies.

Verified on screen with a real clipboard: 6 open demo trades, clicked
FWQRY6Q4, clipboard read back "FWQRY6Q4", and the panel said "copied trade
FWQRY6Q4".
"""

PANEL = "webapp/src/components/trade/PositionsPanel.tsx"
HIST = "webapp/src/components/trade/TradeHistory.tsx"


def test_the_api_sends_the_trades_own_id():
    import inspect

    from tradingagents import positions_view as pv

    src = inspect.getsource(pv)
    assert '"trade_id": pos.get("trade_id") or ""' in src
    t = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    i = t.index("export interface PositionRow")
    assert "trade_id?: string;" in t[i:i + 900]


def test_both_ids_are_copyable_and_say_which_is_which():
    p = open(PANEL, encoding="utf-8").read()
    assert 'copy(r.id, `strategy ${r.id}`)' in p
    assert 'copy(r.trade_id as string, `trade ${r.trade_id}`)' in p
    # the labels a reader sees, so two ids on one row are never confused
    assert "copy the STRATEGY id" in p
    assert "copy THIS TRADE's id" in p


def test_a_copy_says_it_copied():
    """A click with no answer reads as a dead button, and a clipboard write
    can fail silently (permissions, an insecure origin)."""
    p = open(PANEL, encoding="utf-8").read()
    assert "setCopied(" in p and "copied {copied}" in p
    assert "could not copy" in p, "a failed copy must say so, never nothing"


def test_the_closed_trade_carries_the_same_copyable_id():
    """One string follows a trade from open to closed."""
    h = open(HIST, encoding="utf-8").read()
    assert "copy this trade's id" in h
    assert "writeText(String(r.id))" in h
