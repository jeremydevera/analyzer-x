"""The list SAYS it is loading — because a slow filter looked like a broken one.

Operator, 2026-08-27: *"if i set a winrate its very slow can you show if its
loading so i know its loading same as for other filters becuase i thought its
not working, its just loading"*.

Measured on the operator's own store (35,863,520 rows, mechanical disk, a sweep
running), which is why this is not a cosmetic ask:

    winrate >= 57 ORDER BY winrate DESC LIMIT 200   cold   30.33 s
    + TP >= 4 on top of it                                 55.01 s
    max_tp = 4 in the default profit order                  0.18 s

For thirty seconds the panel showed the PREVIOUS answer with nothing moving —
the exact screen a filter that does nothing would give. Four things now:

* a spinner with `role="status"`, saying what it is searching and for how long
  (`waited`), so a long wait visibly PROGRESSES;
* a line naming the request in flight, because the caption above it still
  describes the previous answer (label-must-match-data);
* `aria-busy` and a dim on the table, so stale rows do not read as fresh;
* a stale-answer guard: once a query can take 30 s, two filters typed in a row
  can come back in either order, and the older answer must not win.

This is a React component, so the assertions are on the source — the same shape
as the filter-wiring tests beside it. The behaviour itself is verified in the
browser with Playwright against the real store (see the session notes).
"""
import re

PANEL = "webapp/src/components/backtest/StrategiesPanel.tsx"


def _panel() -> str:
    return open(PANEL, encoding="utf-8").read()


def test_a_request_in_flight_sets_a_loading_flag():
    p = _panel()
    assert "const [loading, setLoading] = useState(false)" in p
    # set BEFORE the call, cleared in a finally so an error cannot leave the
    # spinner spinning forever
    body = p[p.index("const load = useCallback("):p.index("useEffect(load,")]
    assert "setLoading(true)" in body, "the flag must be set before the fetch"
    assert re.search(r"\.finally\(\(\) => \{[^}]*setLoading\(false\)", body), (
        "cleared in finally — a rejected request must not spin forever")


def test_the_spinner_says_what_it_is_doing_and_for_how_long():
    p = _panel()
    assert 'role="status"' in p and 'aria-live="polite"' in p
    assert "animate-spin" in p, "it has to visibly move"
    assert "const [waited, setWaited] = useState(0)" in p
    assert "setInterval(" in p and "setWaited(" in p, "the seconds must tick"
    # the seconds reset when the request ends, or the next wait starts at 30
    assert "setWaited(0)" in p


def test_it_names_the_request_not_the_rows_on_screen():
    """The caption above describes the PREVIOUS answer while a new filter runs,
    so the loading line must name what was actually asked for — derived from
    the request state, never a literal."""
    p = _panel()
    # it prints the SAME ANDed sentence the filter line does, over `applied`,
    # plus the order — one wording for the whole panel (operator, 2026-08-27)
    asking = p[p.index("const asking = "):p.index("const pages = ")]
    assert "andLine(applied)" in asking, asking
    assert "STRATEGY_SORTS[sort]" in asking, "and which way it is ranked"
    # and that sentence names every box, so nothing sent goes unmentioned
    line = p[p.index("const andLine = "):p.index('.join(" AND ")')]
    for box in ("coin", "tf", "signal", "minTrades", "minWinrate", "maxTp",
                "profitable"):
        assert f"f.{box}" in line, f"the loading line ignores {box}"
    assert "the figures above are still the previous" in p


def test_the_table_is_marked_busy_and_dimmed():
    p = _panel()
    assert "aria-busy={loading}" in p
    assert 'showLoad ? "opacity-40" : ""' in p


def test_the_spinner_waits_before_appearing():
    """The list re-polls every 5 s while the indexer is behind; a pill that
    blinks on each of those reads as a glitch."""
    p = _panel()
    assert "const [showLoad, setShowLoad] = useState(false)" in p
    assert "setTimeout(() => setShowLoad(true), 300)" in p
    assert "clearTimeout(gate)" in p, "the gate must be cleared on unmount"
    # and the pill itself is gated, not the raw flag
    assert "{showLoad && (" in p


def test_a_slow_older_answer_cannot_overwrite_a_newer_one():
    """Two filters typed in a row: at 30 s a query the operator has already
    replaced can land last and repaint the rows it was replaced by."""
    p = _panel()
    assert "const reqRef = useRef(0)" in p
    assert "const mine = ++reqRef.current" in p
    assert p.count("if (mine !== reqRef.current) return") == 2, (
        "both the success and the failure path must check")
    assert "if (mine === reqRef.current) setLoading(false)" in p


def test_every_filter_shares_the_one_indicator():
    """"same as for other filters" — one `load` serves every control, so the
    spinner covers the coin, timeframe, signal, sort, trades, win % and TP
    changes rather than being wired to one box."""
    p = _panel()
    # every box lands in `applied` through the one Apply filters button, and
    # `load` depends on `applied` — so one spinner covers all of them
    assert re.search(r"\}, \[applied, sort, desc, page, perPage\]\);", p), (
        "load must depend on the applied filter set")
    draft = re.search(r"const draft = \{([^}]*)\}", p)
    assert draft, "the draft set must exist"
    for box in ("coin", "tf", "signal", "profitable", "minTrades",
                "minWinrate", "maxTp"):
        assert box in draft.group(1), f"the draft ignores {box}"
    # the appending button keeps its own words, and still says them
    assert 'loadingMore ? "loading…"' in p

def test_a_background_refresh_never_touches_the_button():
    """Operator, 2026-08-27: *"why does the button apply serach keeps on
    searching 1s? i dont want that"*. Two timers refresh this list by
    themselves — every 5 s while the indexer is behind (2 pairs behind on this
    store, so for ever) and every 15 s while an index builds. Both went through
    the same `load` as the Apply click, so the button announced work nobody
    asked for, twelve times a minute."""
    p = _panel()
    assert "const load = useCallback((background = false)" in p
    assert "if (!background) setLoading(true)" in p, (
        "a timer's refresh must not spin the button")
    # both timers are background, and neither queues behind a slow request
    assert p.count("if (!inFlight.current) load(true)") == 2, (
        "the 5 s and the 15 s refresh")
    assert "const inFlight = useRef(false)" in p
    assert "inFlight.current = false" in p, "cleared when the request ends"


def test_the_operators_own_action_still_spins():
    """The click, the page and the header are foreground: `load()` with no
    argument, which is what the effect calls."""
    p = _panel()
    assert "useEffect(load, [load]);" in p
