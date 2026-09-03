"""The filters leave when the operator says so, they read as AND, and the sort
dropdown is gone.

Operator, 2026-08-27: *"i want a button 'Apply filters' when i click it apply
the filters present / when i input filters you you should read it as 'AND' /
example: all coins AND all timeframe AND all signals AND min trades =x AND min
win% = x / also remove the sort dropddown field"*.

Why a button at all — measured on the operator's own store (35,863,520 rows,
mechanical disk): a win % floor ranked by win % takes 30.33 s cold. Typing "50"
into a live-filtering box therefore asked the store for `>= 5` and then
`>= 50`, two half-minute reads, and painted whichever landed last. The boxes are
now a DRAFT and one button sends them.

The AND was always true in SQL — `rows_index._where` joins its terms with
" AND " — but nothing on screen said so, and a reader could fairly have read a
coin and a timeframe as alternatives.
"""
import re

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"


def _panel() -> str:
    return open(PANEL, encoding="utf-8").read()


def test_there_is_an_apply_filters_button_and_it_is_what_sends_them():
    p = _panel()
    assert "Apply filters" in p, "the button says what the operator asked for"
    apply_fn = re.search(r"const apply = \(\) => \{([^}]*)\}", p)
    assert apply_fn, "the handler must exist"
    body = apply_fn.group(1)
    assert "setApplied(draft)" in body, "clicking it sends the BOXES"
    assert "setPage(1)" in body and "setExtra([])" in body, (
        "a new filter is a new list: page 1, and the appended rows go")


def test_typing_alone_does_not_ask_the_store():
    """The request is built from `applied`, never from the boxes — otherwise
    every keystroke is another 30-second read."""
    p = _panel()
    load = p[p.index("const load = useCallback("):p.index("useEffect(load,")]
    for f in ("coin", "tf", "signal", "minTrades", "minWinrate", "maxTp"):
        assert f"applied.{f}" in load, f"the request must read applied.{f}"
    # and nothing in the request reads a raw box
    assert not re.search(r"minWinrate: minWinrate\b", load)
    assert not re.search(r"maxTp: maxTp\b", load)


def test_the_csv_downloads_what_the_table_shows_not_the_boxes():
    """The link is labelled with the APPLIED count — "download all (5,000+)
    CSV" — so a href built from the draft boxes would hand over a different
    slice than it names (label-must-match-data)."""
    p = _panel()
    csv = p[p.index("api.strategiesCsvUrl({"):]
    csv = csv[:csv.index("}}")]
    for f in ("coin", "tf", "signal", "minTrades", "minWinrate", "maxTp",
              "profitable"):
        assert f"applied.{f}" in csv, f"the CSV link ignores applied.{f}"


def test_the_button_says_when_the_boxes_are_not_applied_yet():
    """Otherwise the boxes and the table disagree with nothing saying so — the
    label-must-match-data failure this repo keeps paying for."""
    p = _panel()
    assert "const pending = " in p
    assert "not applied yet" in p
    assert "disabled={loading || !pending.length}" in p, (
        "nothing to apply, or a read already running — the button says so")


def test_the_filters_read_as_one_AND_sentence():
    p = _panel()
    # the helper now opens with the row-id override, so match from its name to
    # the join rather than assuming the first thing after `=>` is the array
    line = re.search(r"const andLine = \(f: typeof draft\) =>(.*?)\.join\(\" AND \"\)",
                     p, re.S)
    assert line, "the AND line must be built from the filter set"
    terms = line.group(1)
    # the operator's own example, term for term
    for term in ('f.coin || "all coins"', 'f.tf || "all timeframes"',
                 'f.signal || "all signals"', "min trades = ${f.minTrades}",
                 "min win % = ${f.minWinrate}", "max TP % = ${f.maxTp}"):
        assert term in terms, f"the AND line is missing {term}"
    assert '.join(" AND ")' in p, "ANDed, in those words"
    # it reads the DRAFT — what Apply will send — and names the applied set too
    assert "{andLine(draft)}" in p and "{andLine(applied)}" in p


def test_the_and_is_true_in_the_sql_too():
    """The sentence must not be a decoration over an OR: the store really does
    join every term with AND (rows_index._where)."""
    from tradingagents import rows_index as ri

    where, args = ri._where(coin="KAVA", tf="1h", signal="rsi14",
                            profitable=True, min_trades=100, min_winrate=50,
                            max_tp=4)
    assert where.count(" AND ") == 6, where
    assert " OR " not in where, where
    assert args == ["KAVA", "1h", "rsi14", 100, 50.0, 4.0], args


def test_the_sort_dropdown_is_gone_and_the_headers_still_sort():
    p = _panel()
    assert 'aria-label="Sort by"' not in p, "the dropdown was asked to go"
    assert "sort: " not in p, "and so were its 'sort: win %' options"
    # the headers are still the way to reorder, and still say which way
    # the month-window headers carry a "(2mo)" suffix, which is stripped
    # before the lookup — so match the CALL, not one exact spelling of it
    assert "const next = HEAD_SORT[h" in p
    assert '.replace(/ \(\d+mo\)$/, "")' in p, (
        "a windowed header must still find its own sort")
    assert "setDesc(!desc)" in p, "a second click flips the direction"
    assert "STRATEGY_SORTS[servedSort]" in p, "the arrow marks the SERVED order"


def test_ranking_by_win_percent_still_lands_with_a_trade_floor():
    """A rate needs a denominator. The dropdown used to add the 100-trade floor
    when win % was picked; the header click has to, because a header re-runs the
    query at once and a draft-only floor would not be in it — that is how
    `CHF 30m soldiers 100.00% over 1 trade` got to the top of the store."""
    p = _panel()
    head = p[p.index("const next = HEAD_SORT[h"):]
    head = head[:head.index("}}")]
    assert 'next === "winrate"' in head and "applied.minTrades === 0" in head
    assert "setMinTrades(100)" in head, "the box shows the floor"
    assert "setApplied((a) => ({ ...a, minTrades: 100 }))" in head, (
        "and the request carries it in the same breath")

def test_the_filter_line_describes_the_ROWS_not_the_request():
    """Measured 2026-08-27: `tf=1h AND trades>=120 AND win%>=55 AND TP>=4`
    ranked by profit answered HTTP 500 — the proxy gives up at 30 s, because
    the biggest profits are martingale rows winning 11-15% of the time, so the
    profit index has to be walked a long way to find 500 rows that pass. The
    old rows stayed on screen and the filter line said they matched the new
    filters. It must describe where the ROWS came from."""
    p = _panel()
    assert "const [servedFilters, setServedFilters]" in p
    load = p[p.index("const load = useCallback("):p.index("useEffect(load,")]
    ok = load[load.index("setServedTp("):load.index(".catch(")]
    assert "setServedFilters(applied)" in ok, (
        "only a SUCCESSFUL answer may claim the rows are its own")
    assert "{andLine(servedFilters)}" in p, "the line reads the served set"
    assert "was asked for and did not come back" in p, (
        "and a request that never landed is SAID, not silently dropped")


def test_a_timeout_is_reported_as_a_timeout():
    p = _panel()
    assert "const [failedAfter, setFailedAfter]" in p
    assert "setFailedAfter(waited)" in p, "how long it had run before it failed"
    assert "the proxy gave up" in p and "failedAfter >= 20" in p, (
        "HTTP 500 after half a minute is a timeout, and the message says so")
    assert "click that header" in p, "and names the cheap way to ask it"
