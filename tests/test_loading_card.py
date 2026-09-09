"""One spinner, and under it the names of what is still loading.

The operator's own design (Sep 09, 2026): *"Why not just show a loading
spinning icon thats the simplest, then under that icon show whats being
loaded so im aware like — Loading backtesting / Then loading coins /
Loading etc"* — after an API restart's ~10 dark seconds painted every Auto
Trade panel red at once.

Verified on screen with the API actually killed: the card shows the spinner
and all seven names, zero red — and red returns for anything still failing
after LATE_MS, because a wait is honest for a while and then it is a failure
wearing a spinner.
"""

D = "webapp/src/components/trade/"
NAMES = ["summary", "positions", "strategies", "MEXC keys",
         "trade history", "profit", "runner feed"]


def _p(name: str) -> str:
    return open(f"{D}{name}.tsx", encoding="utf-8").read()


def test_the_screen_watches_all_seven_by_name():
    s = _p("AutoTradeScreen")
    assert "<LoadingOverlay waitlist={waitlist} />" in s
    for n in NAMES:
        assert f'"{n}"' in s, n


def test_the_screen_is_blurred_until_fully_loaded():
    """Operator, Sep 09, 2026: 'make the screen blurred until its fully
    loaded meaning only show the loading icon then the sentence loading
    candles or loading this etc'. Verified on screen with every API call
    held 4s: blur(8px) with all 7 names from the FIRST frame (358ms),
    filter none once the last name lands (17.7s under throttle)."""
    s = _p("AutoTradeScreen")
    assert "blur-sm" in s and "pointer-events-none select-none" in s
    # first paint blurs too: the server frame has an empty watchlist, and
    # without `started` the screen flashed sharp for ~1s (measured 396ms)
    assert "const blurred = !started" in s
    # frosted glass never becomes a lock: a name late past LATE_MS drops it
    assert "waitedMs <= LATE_MS" in s
    # the overlay wrapper is click-through once the blur drops
    o = _p("LoadingCard")
    assert "pointer-events-none absolute inset-0" in o
    assert "pointer-events-auto" in o


def test_every_panel_reports_when_its_data_lands():
    for f, n in [("SummaryRibbon", "summary"), ("PositionsPanel", "positions"),
                 ("StrategiesGrid", "strategies"), ("CredentialsPanel", "MEXC keys"),
                 ("TradeHistory", "trade history"), ("PnlPanel", "profit"),
                 ("FeedPanel", "runner feed")]:
        assert f'markReady("{n}")' in _p(f), f


def test_a_stuck_name_turns_red_instead_of_spinning_forever():
    s = _p("LoadingCard")
    assert "LATE_MS" in s and "still not loading" in s, \
        "fail loudly: a 30s wait is a failure wearing a spinner"


def test_young_errors_defer_to_the_card_and_late_ones_go_red():
    s = _p("PanelStatus")
    assert "if (young) return null;" in s
    assert "LATE_MS" in s
    # an error AFTER data was on screen is always red — that is real news
    assert "loaded" in s


def test_the_states_that_start_empty_carry_their_own_loaded_flag():
    """FeedPanel's lines and PnlPanel's days start as []/{}: a `!== null`
    check calls them loaded at birth, which put a red ApiError under 'Closed
    profit by coin' while everything else showed the spinner (caught on
    screen, Sep 09, 2026)."""
    for f in ("FeedPanel", "PnlPanel"):
        p = _p(f)
        assert "got.current = true" in p, f
        assert "loaded={got.current}" in p, f


def test_the_grid_reports_from_its_loader_not_the_save_button():
    s = _p("StrategiesGrid")
    i = s.index('markReady("strategies")')
    assert "setSettings(se.settings)" in s[max(0, i - 300):i], \
        "the first data landing marks ready — not SAVE CONFIG's success"
