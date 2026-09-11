"""An empty PAGE is not an empty STORE.

Operator, `Sep 12, 2026`, with three filters on — Past 30 days, Winrate 85% or
better, TP at least as wide as SL:

    "no stored strategy passes Past 30 days with Winrate 85% or better with TP
     at least as wide as SL — lower the floor to see what is close."

then *"is this accurate?"*, then *"does my filter really shows 0 result?"*

It was not accurate. Measured on the operator's own index the same minute:

* `winrate >= 85 AND tp >= sl` matches **893,508** rows of 96,307,386;
* a days window re-measures every row from this PC's candles, so the panel
  asks for `DAYS_PAGE = 25` and the API refuses more than `DAYS_ROW_MAX = 50`;
* those 25 are the 25 with the biggest WHOLE-HISTORY profit, and
  `window_floors` cut all 25 for missing 85% inside the window;
* re-measuring rows the page never asked for found 30 passing on 0G 15m alone
  (`cf_obretest_l1` tp2.5/sl1.2 flat: 2 trades, 2W/0L, 100%, +$4.79).

So the sentence was a claim about 893,508 rows made after checking 25 —
0.003% — and it sent the operator to widen a filter that was fine.
"""
import pathlib

import pytest

PANEL = pathlib.Path("webapp/src/components/backtest/StrategiesPanel.tsx")


@pytest.fixture(scope="module")
def body():
    return PANEL.read_text(encoding="utf-8")


def test_the_empty_message_never_speaks_for_rows_it_did_not_check(body):
    """The bug itself: one sentence, "no stored strategy passes <every chip>",
    printed whether the store was empty or merely unexamined."""
    i = body.index("no stored strategy passes")
    # that wording may only survive on the branch where NOTHING matched
    before = body[:i]
    assert "total > 0 && winHidden > 0" in before, (
        "the windowed case must be answered before the flat 'nothing passes' "
        "sentence is allowed to print")


def test_it_names_how_many_matched_and_how_many_were_actually_checked(body):
    assert "</b> stored" in body, "the match count leads the sentence"
    assert "could only check" in body, "it must say the page was partial"
    assert "<b>{winHidden.toLocaleString()}</b> of them" in body, (
        "the checked count is winHidden — the rows really re-measured — not "
        "an estimate from askPage")
    assert "filter to" in body and "see all {total.toLocaleString()}" in body, (
        "and it must name the way out, with the full count")


def test_the_window_is_only_blamed_when_it_actually_cut_something(body):
    """LOOP ROUND 1. With a capped count the page can be sent past the last
    row (`setPage(capped ? Math.max(1, n) : ...)`), which also empties the
    table with total > 0. Blaming the window there is a second false label."""
    assert "(servedFilters.days > 0 || servedFilters.months > 0) && total > 0 && winHidden > 0" in body
    assert "total > 0 && page > 1 ?" in body, "the paged-past-the-end case is its own answer"


def test_a_capped_total_is_never_printed_as_exact(body):
    """LOOP ROUND 1. `total_capped` means `total` is a floor. The rest of this
    panel prints `{total}{capped ? "+" : ""}`; this sentence must too."""
    i = body.index("could only check")
    near = body[i - 1400:i + 900]
    assert near.count('capped ? "+" : ""') >= 2, (
        "both the match count and the 'see all N' figure carry the + ")


def test_the_MONTHS_window_gets_the_same_answer_as_days(body):
    """LOOP ROUND 2. `RESTATE_MAX = 1`, so a months window restates at most
    ONE row and `window_floors` can empty the page from it — the same shape,
    and the first fix covered only `days`."""
    assert "servedFilters.months > 0" in body.split("could only check")[0][-1800:]
    assert 'c.k !== "days" && c.k !== "months"' in body, (
        "the window's own chip must not be listed among the filters that DID "
        "match — it is the one that was barely tested")


def test_the_filter_set_is_named_once(body):
    """LOOP ROUND 4. `chips` already holds coin, tf, signal and "Made money";
    the sentence appended all four again in different words, so with the
    profit filter on it read "passes Made money ... and profit above zero"."""
    i = body.index("no stored strategy passes")
    tail = body[i:i + 700]
    assert "profit above zero" not in tail, "printed twice: it is already a chip"
    assert "[coin, tf, signal].filter(Boolean)" not in tail, (
        "coin/tf/signal are chips (k: coin/tf/signal) — naming them again is "
        "the same filter in two wordings")


def test_the_caps_that_make_this_possible_are_still_what_the_message_says():
    """If DAYS_PAGE or DAYS_ROW_MAX move, the sentence's arithmetic moves with
    them — this test exists so the number cannot drift away from the words."""
    from tradingagents import api

    assert api.DAYS_ROW_MAX == 50
    assert api.RESTATE_MAX == 1
    assert "const DAYS_PAGE = 25;" in PANEL.read_text(encoding="utf-8")


def test_the_window_really_can_hide_passing_rows():
    """The measurement behind the whole entry: `window_floors` cuts on the
    WINDOW's win rate, so a row over 85% for its whole life is dropped for a
    quiet month — which is correct, and is exactly why the page may not
    report its own silence as the store's."""
    from tradingagents import rows_index as ri

    # READ THE EMITTER (rule 23): it judges only rows marked `restated`, and
    # on the WINDOW's own fields (`w_winrate`), never the whole-history
    # `winrate` the SQL floor used. My first draft of this test asserted on
    # `winrate` and passed 2 rows through, which is the same mistake in
    # miniature — believing a field name instead of reading the branch.
    rows = [
        # 95% for its whole life, 50% inside the window -> CUT
        {"winrate": 95.0, "restated": True, "w_winrate": 50.0,
         "w_trades": 4, "w_profit": -1.0},
        # still over the floor inside the window -> KEPT
        {"winrate": 95.0, "restated": True, "w_winrate": 100.0,
         "w_trades": 2, "w_profit": 4.79},
        # no candles on this PC, so it could not be restated -> KEPT as-is
        {"winrate": 95.0, "restated": False},
    ]
    kept, hidden = ri.window_floors(rows, min_winrate=85.0, min_trades=0,
                                    profitable=False)
    assert hidden == 1, "only the row that missed INSIDE the window is cut"
    assert len(kept) == 2
    assert kept[0]["w_winrate"] == 100.0
    assert kept[1]["restated"] is False, (
        "a row the window could not re-measure is kept, not counted against "
        "the operator")
