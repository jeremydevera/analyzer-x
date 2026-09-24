"""Open positions show ten rows a page.

Operator, `Sep 24, 2026`: *"for position section in live trade, set max of 10
rows then paginate it"*. The Sep 24 preset arms **537** paper slots across 326
keys, so the demo book can hold more open positions than fit on a screen.

Four things this pins, three of which are the ways it would break QUIETLY:

* **The page number is held by `PositionsPanel`, never by `Book`.** `Book` is
  defined inside the panel's body, so every render makes a NEW function — React
  reads that as a different component type, unmounts the old one and throws its
  state away. The panel re-renders once a SECOND (`useLiveRefresh(loadFeed,
  1_000)`), so a `useState` inside `Book` would send the operator back to page 1
  every second. It would look like a page control and behave like a flicker.
* **The current page is clamped where it is USED, not written back.** A
  position closing while the operator is on the last page must not leave them
  looking at an empty box, and the panel reloads itself every 15 s.
* **Both layouts slice the same list.** The phone cards and the desktop table
  are two renderings of one page; if one maps `rows` and the other `shown`,
  page 2 means two different things depending on the width of the window.
* **The header count stays the whole book.** `12 open` is every open position,
  not the ten on screen (`label-must-match-data`).
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
SRC = (REPO / "webapp" / "src" / "components" / "trade" / "PositionsPanel.tsx"
       ).read_text(encoding="utf-8")

# the body of the inner `Book` component, from its declaration to the close of
# the panel's own `return (`
BOOK = SRC[SRC.index("const Book = ("):SRC.index("  const real = data?.real")]


def test_a_page_holds_ten_rows():
    assert re.search(r"^const PER_PAGE = 10;$", SRC, re.M), (
        "the operator asked for a max of 10 rows a page")


def test_the_page_number_is_not_kept_inside_Book():
    """The flicker bug: state in a component whose identity changes every
    render is reset every render, and this panel renders once a second."""
    assert "useState" not in BOOK, (
        "`Book` is re-created on every render — state kept in it is thrown "
        "away once a second by the price feed's refresh")
    page_state = re.search(
        r"const \[page, setPage\] = useState<\{ REAL: number; paper: number \}>",
        SRC)
    assert page_state, "the panel itself must hold the page number for both books"
    assert page_state.start() < SRC.index("const Book = ("), (
        "the page state has to be declared in the panel, above `Book`")


def test_both_books_page_apart():
    assert "{ REAL: 1, paper: 1 }" in SRC, (
        "real and paper are separate boxes and page separately")
    assert "page[book]" in BOOK and "[book]: Math" in BOOK, (
        "each book reads and writes its own page number")


def test_the_page_is_clamped_at_render_so_a_close_cannot_empty_it():
    assert "Math.min(Math.max(1, page[book]), pages)" in BOOK, (
        "a position closing on the last page must not leave a blank box")
    assert re.search(r"setPage\(\(p\) => \(\{ \.\.\.p, \[book\]: "
                     r"Math\.min\(Math\.max\(1, n\), pages\) \}\)\)", BOOK), (
        "the jump is clamped too, or `next` walks past the end")


def test_one_slice_feeds_the_phone_cards_and_the_desktop_table():
    assert "const shown = rows.slice(from, from + PER_PAGE);" in BOOK
    assert BOOK.count("shown.map(") == 2, (
        "both the phone cards and the table render the page, and the same one")
    assert "rows.map(" not in BOOK, (
        "a layout still mapping the FULL list ignores the page entirely")


def test_the_count_in_the_header_is_the_whole_book_not_the_page():
    assert "· {rows.length} open" in BOOK, (
        "`12 open` means twelve positions are open, never ten on screen")
    assert "showing ${from + 1}–${from + shown.length}" in BOOK, (
        "when the page is a slice of the book it says which slice")


def test_there_is_a_pager_to_press():
    for want in (">prev</button>", ">next</button>", "pageWindow(cur, pages)"):
        assert want in BOOK, f"the pager is missing {want}"
    assert 'import { pageWindow } from "@/lib/pager";' in SRC, (
        "the page numbers come from the one helper the backtest pager uses")
    assert "disabled={cur === 1}" in BOOK and "disabled={cur === pages}" in BOOK


def test_the_pager_only_appears_when_there_is_a_second_page():
    assert "{pages > 1 && (" in BOOK, (
        "a pager under a three-row book is furniture, not a control")
