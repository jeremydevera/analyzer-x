"""The Auto Trade tables are readable on a phone.

Operator, `Sep 23, 2026`, reading the app on their phone over Tailscale for the
first time: *"in mobile. the live trade table is not mobile responsive"*.

Both tables on that screen are built to WRAP rather than scroll sideways — the
`Table` component sets `table-fixed` and its cells `break-words`, and its own
comment says the Auto Trade screen must not scroll sideways. Then:

* `PositionsPanel` (the OPEN trades) lays out **15 columns**. On a 390px phone
  that is 26px each.
* `TradeHistory` (the closed ones) lays out **10**, and puts
  `whitespace-nowrap` on nearly every cell, which defeats the wrapping the
  table was designed around — so the text was clipped by the card's
  `overflow-hidden` rather than wrapped.

Below `md` both now render the same rows as stacked cards. The table is
untouched above `md`, where fifteen columns side by side is the point.

WHY NOTHING CAUGHT IT: every check in this repo renders at desktop width. The
Playwright gate (`.claude/skills/verify-ui-change`) screenshots one viewport,
and `test_port_audit` asks whether a control EXISTS, not whether it can be
seen. A column pushed off a 390px screen exists perfectly.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
TRADE = REPO / "webapp" / "src" / "components" / "trade"

# (file, how many columns its table lays out)
TABLES = [("PositionsPanel.tsx", 15), ("TradeHistory.tsx", 10)]


def _src(name: str) -> str:
    return (TRADE / name).read_text(encoding="utf-8")


def test_each_trade_table_has_a_phone_layout_and_hides_the_table():
    """A phone gets cards; `md` and up gets the table. Both halves are needed:
    rendering both would show every row twice."""
    for name, _cols in TABLES:
        s = _src(name)
        assert "md:hidden" in s, f"{name} has no phone layout"
        assert "hidden w-full md:block" in s, \
            f"{name} still shows its table on a phone as well as the cards"


def test_the_phone_layout_can_still_CLOSE_a_real_position():
    """The one thing this panel must never be is a screen where real money is
    open and the button to shut it is off the side of the display."""
    s = _src("PositionsPanel.tsx")
    mobile = s[s.index("md:hidden"):s.index("hidden w-full md:block")]
    assert "closeOne(r)" in mobile, "no close button on the phone card"
    assert 'book === "REAL"' in mobile, \
        "and it must still be offered only for the real book"


def test_the_phone_layout_keeps_the_ids_copyable():
    """Two ids live on one row — the trade and the strategy — and being able
    to copy them is what "i still cannot copy the id ... y5ubbfpb" bought."""
    pos = _src("PositionsPanel.tsx")
    mobile = pos[pos.index("md:hidden"):pos.index("hidden w-full md:block")]
    assert "CopyableId" in mobile
    hist = _src("TradeHistory.tsx")
    m2 = hist[hist.index("md:hidden"):hist.index("hidden w-full md:block")]
    assert "clipboard?.writeText" in m2, "the trade id must stay copyable"
    assert "CopyableId" in m2, "and the strategy id with it"


def test_the_empty_state_still_speaks_on_a_phone():
    """It lives inside the table body, so hiding the table would have hidden
    the sentence that says WHAT was searched — an empty screen speaking for a
    store nobody counted (CLAUDE.md, Sep 12, 2026)."""
    s = _src("TradeHistory.tsx")
    mobile = s[s.index("md:hidden"):s.index("hidden w-full md:block")]
    assert "No trade or strategy id matching" in mobile
    assert "examined" in mobile, "it must still say how many were examined"


def test_the_column_counts_that_made_this_necessary_have_not_grown_quietly():
    """If a table grows past what the cards show, the phone view starts
    hiding data instead of re-arranging it. This is the tripwire."""
    pos = _src("PositionsPanel.tsx")
    heads = re.search(r"const HEADS: \[string, string\]\[\] = \[(.*?)\];",
                      pos, re.S)
    assert heads, "PositionsPanel no longer declares HEADS"
    assert heads.group(1).count("[") == 15, \
        "the positions table changed width — check the phone card still " \
        "shows what a person needs, then update this number"

    hist = _src("TradeHistory.tsx")
    h = re.search(r"const HEADS = \[(.*?)\];", hist, re.S)
    assert h, "TradeHistory no longer declares HEADS"
    assert len(re.findall(r'"[^"]+"', h.group(1))) == 10, \
        "the history table changed width — same check"
