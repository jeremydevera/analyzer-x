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
    assert s.count("await fetchLaned(`${API_BASE}${path}`") == 4, \
        "get (first try + its restart retry), post AND postDetail — one " \
        "bare fetch re-opens the stall"
    assert "fetch(`${API_BASE}" not in s.replace("fetchLaned(`${API_BASE}", ""), \
        "no direct fetch to the API remains"


def test_a_lane_is_freed_even_when_the_fetch_throws():
    """A thrown fetch that kept its lane would strangle the app four calls
    later — the free lives in `finally`."""
    s = _src()
    fl = s[s.index("async function fetchLaned"):]
    fl = fl[:fl.index("\n}\n")]
    # the FETCH's finally (since Oct 07, 2026 an earlier one forgets a read's
    # waiting twin): the lane is freed whatever the fetch did
    after_fetch = fl[fl.index("await fetch("):]
    body = after_fetch[after_fetch.index("finally"):]
    body = body[:body.index("}")]
    # freeLane(behind) since the rooms got lanes of their own (Oct 01, 2026)
    assert "finally" in body and "freeLane(" in body


def test_leaving_a_page_gives_up_its_reads():
    """Operator, Oct 05, 2026: "when i go to errors tab or forecast tab, i need
    to refresh the whole page in order for it to load in safari browser".
    Measured in Safari's engine with the API answering in 20 s: Auto Trade
    held all four lanes and queued more, and Errors had not sent its one call
    45 s after it was opened from the menu. A page change refuses the old
    page's queued READS and cancels its reads in flight."""
    s = _src()
    np_ = s[s.index("export function newPage"):s.index("async function takeLane")]
    assert "_page += 1" in np_ and ".drop()" in np_ and "ctl.abort()" in np_
    fl = s[s.index("async function fetchLaned"):]
    fl = fl[:fl.index("\n}\n")]
    # only reads, never an order or a switch, and never the header's polls
    assert 'method === "GET" && !chrome' in fl and "const chrome = ALWAYS_ON.test(path)" in fl
    assert "signal: mine.ctl.signal" in fl and "throw new PageLeft()" in fl
    always = s[s.index("const ALWAYS_ON"):].split("\n", 1)[0]
    for route in ("health", "jobs", "notifications"):
        assert route in always, route


def test_the_page_change_is_told_before_the_new_page_asks():
    """A child's effects run before its parent's: newPage() in an effect would
    run AFTER the new page's first calls and cancel them. It is called during
    the layout's render, above the page."""
    lay = open("webapp/src/app/(admin)/layout.tsx", encoding="utf-8").read()
    pc = lay[lay.index("function PageChange"):lay.index("export default")]
    assert "usePathname()" in pc and "newPage()" in pc and "useEffect" not in pc
    body = lay[lay.index("export default"):]
    assert body.index("<PageChange />") < body.index("{children}")


def test_a_header_poll_never_stacks_up_behind_a_slow_api():
    """/api/jobs is asked every 4 s and survives every page change; with the
    API answering in 20 s its unanswered copies held every lane. A header call
    already on its way is shared, never sent twice."""
    s = _src()
    g = s[s.index("async function get<T>"):s.index("async function post<T>")]
    assert "ALWAYS_ON.test(path)" in g and "_sharedGets.get(key)" in g
    assert "_sharedGets.delete(key)" in g, "a finished call is never shared"


def test_the_header_never_holds_more_than_two_lanes():
    """With every answer slow, the header's polls held all four lanes and the
    page opened from the menu waited 20 s. They are capped at two."""
    s = _src()
    assert "const CHROME_LANES = 2;" in s
    tl = s[s.index("async function takeLane"):s.index("function freeLane")]
    assert "chromeNow < CHROME_LANES" in tl
    fl = s[s.index("function freeLane"):]
    fl = fl[:fl.index("\n}\n")]
    assert "chromeNow -= 1" in fl and "chromeNow < CHROME_LANES" in fl
