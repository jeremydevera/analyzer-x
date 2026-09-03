"""The caption and the arrow must describe the rows ON SCREEN.

Operator, 2026-08-26: "when i clickk winrate header, the only sorted are the
ones on the page. i want you to sort all".

What actually happened: `GET /api/strategies?sort=winrate&min_trades=100`
answered 503 — rows_winrate had been dropped by an interrupted bulk fill and
was rebuilding — so the panel kept the PROFIT rows on screen (correct: losing
them would be worse) while the caption said "highest win % first" and the
header showed "win % ↓". The list was never sorted by win rate at all; the
words said it was. Sorting IS server-side and global: what was missing was
telling the truth while the store caught up.

So the panel renders the order the SERVER SERVED, and the requested order only
appears as "preparing…" until it arrives.
"""
import pathlib
import re

SRC = pathlib.Path("webapp/src/components/backtest/StrategiesPanel.tsx").read_text(encoding="utf-8")


def test_the_panel_tracks_the_order_the_server_served():
    assert "servedSort" in SRC and "servedDesc" in SRC, \
        "the rendered order must come from the response, not the request"
    # set from the payload
    assert re.search(r"setServedSort\(\(?d\.sort", SRC), (
        "servedSort must be read from the payload, not the request")
    assert re.search(r"setServedDesc\(d\.desc", SRC), (
        "servedDesc must be read from the payload too")


def test_the_caption_and_the_arrow_use_the_served_order():
    cap = SRC[SRC.index("rows ${shown.length"):SRC.index("</p>", SRC.index("rows ${shown.length"))]
    assert "servedSort" in cap, "the caption must name the order actually shown"
    heads = SRC[SRC.index("HEAD_SORT[h"):]
    marker = heads[:heads.index("</TableCell>")]
    assert "servedSort" in marker, "the arrow must sit on the column actually sorted"


def test_a_refused_sort_says_it_is_preparing_and_names_what_is_shown():
    assert "preparing" in SRC.lower() or "being built" in SRC.lower()
    # the note must name BOTH the wanted order and the one on screen
    note = SRC[SRC.index("{waiting &&"):]
    note = note[:note.index("</p>")]
    assert "STRATEGY_SORTS[sort]" in note and "STRATEGY_SORTS[servedSort]" in note, note


def test_the_headers_are_the_sort_control_and_they_show_the_request():
    """The sort DROPDOWN is gone — the operator asked for it removed on
    2026-08-27 ("also remove the sort dropddown field"), because the column
    headers already sort and two controls for one thing disagree. So the rule
    moves to the headers: a click sets the order, a second click flips it, and
    the header that is highlighted is the one the rows are ACTUALLY in
    (servedSort), with the requested one marked separately while it loads."""
    assert "value={sort}" not in SRC, "the dropdown was asked to go"
    click = SRC[SRC.index("const next = HEAD_SORT[h"):]
    click = click[:click.index("}}")]
    assert "setSort(next)" in click and "setDesc(" in click, click
    assert "if (next === sort) { setDesc(!desc); return; }" in click, click
    # the highlight is derived from what the SERVER served, never the request
    heads = SRC[SRC.index("HEAD_SORT[h"):]
    assert "STRATEGY_SORTS[servedSort]" in heads
    assert "STRATEGY_SORTS[sort]" in heads
