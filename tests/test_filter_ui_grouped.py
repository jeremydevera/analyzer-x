"""The Stored strategies filter bar, grouped — and every filter removable.

Operator, 2026-09-03: *"can you fix the filter ui in stored strategy its now
confusing"*. Measured on their own screen at 1600px before the change
(Playwright, `crop_strategies.png`):

* THIRTEEN controls in one `flex-wrap`, in an order nothing explains:
  `last [0] month(s) last [0] day(s) #id [coins] [timeframes] [groups]
  [signals]`, then a wrap, then `[sizing] min trades [0] min win % [0]
  max TP % [0] max SL % [0] ☐ profitable only [Apply filters]`.
* TWO adjacent boxes both labelled "last", one silently disabling the other.
* SIX number boxes all reading `0` — a filter that is OFF looked like a filter
  set to zero.
* The only summary was an eleven-clause sentence that said nothing was
  filtered ("all coins AND all timeframes AND all signals AND all groups AND
  any trades AND any win % AND any TP AND any SL AND flat and martingale AND
  losers included AND all history") — and the caption above it printed the
  same facts a second time.
* No way to drop ONE filter, and no clear-all at all.

Now: four labelled groups, blank boxes with an "any" placeholder, and one
removable CHIP per applied filter with a clear-all beside them. The chips are
built from what the store SERVED, never from the boxes — a chip describing
rows it did not come from is the failure this repo keeps paying for.
"""
import io
import re

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"


def src() -> str:
    return io.open(PANEL, encoding="utf-8").read()


# ------------------------------------------------------------ the four groups

def test_the_filters_are_grouped_and_every_group_is_labelled():
    p = src()
    assert "function FilterRow(" in p, "one labelled group, one component"
    for label in ("what", "how good", "window", "one row"):
        assert f'<FilterRow label="{label}"' in p, label
    # the label is what the eye holds on to, so it must be a real element
    row = p[p.index("function FilterRow("):]
    row = row[:row.index("\n}\n")]
    assert "uppercase" in row and "{label}" in row
    assert "{children}" in row


def test_every_control_still_exists_and_keeps_its_accessible_name():
    """Regrouping must not lose a filter. These are the operator's own boxes,
    each bought with its own ask."""
    p = src()
    for name in ("Coin", "Timeframe", "Group", "Signal", "Sizing",
                 "Minimum trades", "Minimum win rate percent",
                 "Maximum take profit percent", "Maximum stop loss percent",
                 "Last N months", "Last N days", "Row id"):
        assert f'aria-label="{name}"' in p, name
    assert "profitable only" in p
    assert "Apply filters" in p


def test_an_empty_number_box_is_blank_not_zero():
    """`0` in a filter box reads as "show me rows with zero trades"."""
    p = src()
    for box in ("minTrades", "minWinrate", "maxTp", "maxSl"):
        assert f'value={{{box} || ""}}' in p, box
    for box in ("months", "days"):
        assert f'value={{{box} || ""}}' in p, box
    # and each one says what blank MEANS
    assert p.count('placeholder="any"') >= 4, "the four quality boxes"
    assert p.count('placeholder="all"') >= 2, "the two window boxes"
    assert 'hint="blank = any"' in p and 'hint="blank = all history"' in p


def test_the_two_last_boxes_say_which_one_wins():
    """They sat side by side, both labelled "last", and setting months just
    greyed the other box out with no reason given."""
    p = src()
    win = p[p.index('<FilterRow label="window"'):]
    win = win[:win.index("</FilterRow>")]
    assert "month(s)" in win and "day(s)" in win
    assert "disabled={months > 0}" in win, "months still wins"
    assert "months wins while it is set" in win, "and now it SAYS so"
    assert ">or<" in win.replace(" ", "").replace("\n", ""), \
        "one window or the other, not two boxes reading `last … last …`"


# ------------------------------------------------------------------ the chips

def test_there_is_one_chip_per_filter_and_none_is_missing():
    """A filter that cannot be seen cannot be removed. Every key the request
    carries has to be nameable as a chip."""
    p = src()
    body = p[p.index("const chipsOf ="):]
    body = body[:body.index("\n  };")]
    for key in ("coin", "tf", "group", "signal", "sizing", "minTrades",
                "minWinrate", "maxTp", "maxSl", "profitable", "months",
                "days", "rowId"):
        assert f"f.{key}" in body, key
    # in the unit its own COLUMN prints, and pointing the way the box points
    assert "win % ≥ ${f.minWinrate}" in body
    assert "trades ≥ ${f.minTrades}" in body
    assert "TP ≤ ${f.maxTp}%" in body, "the TP box is a CEILING (2026-09-03)"
    assert "SL ≤ ${f.maxSl}%" in body, "and the SL box always was"
    assert "every other filter ignored" in body, "an id names ONE row"


def test_the_chips_describe_what_the_store_SERVED():
    """On a 503 the request moves and the rows do not. A chip built from the
    boxes would then label rows it did not come from."""
    p = src()
    i = p.index("const chips = chipsOf({")
    call = p[i:i + 600]
    assert "...servedFilters," in call
    # the four floors from the API's own echo, which is what it says it applied
    for served in ("servedTrades > 0", "servedWinrate > 0", "servedTp > 0",
                   "servedSl > 0"):
        assert served in call, served


def test_every_chip_can_be_removed_on_its_own():
    p = src()
    assert "const clearOne = (k: keyof typeof NO_FILTERS) => {" in p
    one = p[p.index("const clearOne ="):]
    one = one[:one.index("\n  };")]
    # the BOX and the REQUEST, or the chip comes straight back
    assert "setBox[k](NO_FILTERS[k] as never)" in one
    assert "setApplied((a) => ({ ...a, [k]: NO_FILTERS[k] }))" in one
    assert "setPage(1)" in one, "a narrower list starts at page 1"
    # a real button with a real name, not a clickable div
    assert 'aria-label={`remove filter ${c.text}`}' in p
    assert "onClick={() => clearOne(c.k)}" in p


def test_there_is_a_clear_all_and_it_clears_every_filter():
    p = src()
    assert ">\n              clear all\n            </button>" in p \
        or "clear all" in p
    body = p[p.index("const clearAll ="):]
    body = body[:body.index("\n  };")]
    assert "Object.keys(NO_FILTERS)" in body, "every box, not a list to forget"
    assert "setApplied({ ...NO_FILTERS })" in body
    # NO_FILTERS must cover the whole request, or clear-all leaves one on
    no = p[p.index("const NO_FILTERS = {"):]
    no = no[:no.index("\n  };")]
    for key in ("coin", "tf", "signal", "profitable", "minTrades",
                "minWinrate", "maxTp", "maxSl", "sizing", "rowId", "group",
                "months", "days"):
        assert f"{key}:" in no, key


def test_nothing_filtered_says_so_in_one_line():
    """Eleven "all X AND" clauses to say the list is unfiltered was the worst
    of it."""
    p = src()
    assert "nothing — every stored strategy in the store" in p
    assert "showing rows where:" in p


# ----------------------------------------------------- the caption stops repeating

def test_the_caption_no_longer_repeats_the_filter_line():
    p = src()
    cap = p[p.index("{total.toLocaleString()}"):]
    cap = cap[:cap.index("</p>")]
    # comments explain what was REMOVED, so they quote it — read the markup
    cap = re.sub(r"\{/\*.*?\*/\}", "", cap, flags=re.S)
    for gone in ("losers included", "at least ${servedTrades}",
                 "or better", "or tighter", "· filters:"):
        assert gone not in cap, f"the caption still repeats: {gone}"
    # the facts that are NOT filters stay
    assert "coins" in cap and "timeframes" in cap and "signals" in cap
    assert "rows ${shown.length" in cap


def test_the_tp_filter_never_points_both_ways_at_once():
    """`TP 4% or tighter` sat in the caption while the box said `min TP %` —
    a label arguing with its own filter. Whatever the direction is, every
    place that prints it must agree with the box."""
    p = src()
    assert "min TP %" not in p, "the box is a ceiling now (2026-09-03)"
    assert "max TP %" in p
    for wrong in ("TP ≥ ${maxTp}", "TP ≥ ${f.maxTp}", "min TP % = ${f.maxTp}"):
        assert wrong not in p, wrong
    # every rendered TP threshold reads as a ceiling
    for m in re.finditer(r"TP [≥≤] \$\{[^}]*[Tt]p\}", p):
        assert "≤" in m.group(0), m.group(0)
