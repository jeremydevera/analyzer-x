"""The web app never uses all six browser lanes — page switches stay instant.

Operator, Sep 09, 2026: *"when im in backtest module and i click auto trade
tab why is it very slow? can you just swtich immediately and just inform me
its loading"*. Measured that day: 17 requests in flight on the Backtest
screen, the browser's six connections all held by slow API calls (the
500-row strategies query, GitHub status, the logs walk), and the click could
not change the URL for over TWO MINUTES — the next page's own fetch was
queued behind data. With the lane budget: 82 milliseconds.
"""

SRC = "webapp/src/lib/api.ts"


def _src() -> str:
    return open(SRC, encoding="utf-8").read()


def test_the_budget_leaves_two_lanes_free():
    s = _src()
    assert "const MAX_LANES = 4;" in s, \
        "4 of 6: two lanes must stay free for navigation and prefetch"


def test_every_helper_queues_through_the_budget():
    s = _src()
    assert s.count("await fetchLaned(`${API_BASE}${path}`") == 3, \
        "get, post AND postDetail — one bare fetch re-opens the stall"
    assert "fetch(`${API_BASE}" not in s.replace("fetchLaned(`${API_BASE}", ""), \
        "no direct fetch to the API remains"


def test_a_lane_is_freed_even_when_the_fetch_throws():
    """A thrown fetch that kept its lane would strangle the app four calls
    later — the free lives in `finally`."""
    s = _src()
    i = s.index("async function fetchLaned")
    body = s[i:s.index("}", s.index("finally", i))]
    assert "finally" in body and "freeLane()" in body
