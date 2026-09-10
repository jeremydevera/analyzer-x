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
    # COMPUTED from the trade's own facts, not read back from the book: since
    # Sep 10, 2026 a demo trade and its live twin share one id, and a position
    # opened before that rule would otherwise keep its old name until it
    # closed — the pair the operator was trying to match was an OPEN one.
    assert '"trade_id": _trade_id_of(sym, pos)' in src
    assert '"trade_id": pos.get("trade_id") or ""' not in src
    assert "at.trade_id_of(sym, pos)" in src, "auto_trader owns the rule"
    t = open("webapp/src/lib/api.ts", encoding="utf-8").read()
    i = t.index("export interface PositionRow")
    assert "trade_id?: string;" in t[i:i + 900]


def test_both_ids_use_the_ONE_copy_control():
    """Operator, Sep 10, 2026: *"i still cannot copy the id ... y5ubbfpb"*.
    The grid had a copy control with an ICON (so the id looks copyable) and a
    hidden-textarea fallback; the positions table had a hand-rolled button
    with neither. One component now, so the next table cannot be born
    broken."""
    p = open(PANEL, encoding="utf-8").read()
    assert 'import CopyableId from "./CopyableId";' in p
    assert "<CopyableId id={r.id} />" in p
    assert 'prefix="trade "' in p and "value={r.trade_id}" in p
    assert "navigator.clipboard" not in p, "no second hand-rolled copy path"
    g = open("webapp/src/components/trade/StrategiesGrid.tsx",
             encoding="utf-8").read()
    assert 'import CopyableId from "./CopyableId";' in g
    assert "function CopyableId" not in g, "one definition, not two"


def test_the_copy_control_works_without_the_async_clipboard():
    """A browser that refuses navigator.clipboard (an iframe, an insecure
    origin, a permission policy) still copies through a hidden textarea —
    proven on screen with navigator.clipboard deleted: status read "copied"."""
    c = open("webapp/src/components/trade/CopyableId.tsx", encoding="utf-8").read()
    assert "document.execCommand" in c and "createElement(\"textarea\")" in c
    assert "could not copy — select it and press Ctrl+C" in c,         "a failed copy must say what to do instead"
    # an icon is what makes the id LOOK copyable — the first complaint
    assert "<svg" in c and 'aria-label={`copy ${prefix}${id}`}' in c


def test_the_label_names_what_the_reader_sees():
    """The trade button reads "trade FWQRY6Q4" while only the id lands on the
    clipboard; the label must follow the SCREEN, or a screen reader and the
    screen disagree about one button."""
    c = open("webapp/src/components/trade/CopyableId.tsx", encoding="utf-8").read()
    assert "copy ${prefix}${id} to the clipboard" in c
    assert "value ?? `${prefix}${id}`" in c, "the CLIPBOARD may still differ"


def test_the_closed_trade_carries_the_same_copyable_id():
    """One string follows a trade from open to closed."""
    h = open(HIST, encoding="utf-8").read()
    assert "copy this trade's id" in h
    assert "writeText(String(r.id))" in h
