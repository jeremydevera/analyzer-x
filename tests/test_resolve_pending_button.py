"""ONE button that clears every fixable pending in the candle store.

Operator, Sep 04, 2026: *"RESOLVE THE PENDINGS IN CANDLE STORE, CRATE A BUTTON
FIRST CALLED 'RESOLVE PENDING' IF I CLICK THIS I WANT TO RESOLVE PENDINGS"*.

Three kinds of pending each needed a DIFFERENT button, and the reader had to
know which: pairs BEHIND and pairs NEVER STORED wanted UPDATE CANDLES, pairs
the last run LOST wanted RETRY FAILED — and UPDATE was disabled when the store
had no gaps, so a lost-only pending could not be cleared by the button the
panel pointed at. Measured on this store when the button was asked for: 5,022
behind, 45 never stored, 0 lost, plus 97 stored pairs on delisted contracts
that nothing can fetch.

ONE DEFINITION of "pending". The count on the button and the count in the
Pending tab come from the same route, so they cannot disagree — the arithmetic
used to live in the component (`retry.length + missing.length + behind`).
"""

import tradingagents.db_jobs as dj

SCREEN = "webapp/src/components/candles/DownloadScreen.tsx"
HISTORY = "webapp/src/components/candles/DownloadHistory.tsx"


def _r(p):
    return open(p, encoding="utf-8").read()


# ------------------------------------------------------------- what it fetches
def test_resolve_takes_every_fixable_kind_at_once(monkeypatch):
    """behind + never-stored + lost, in one queue, with no pair twice."""
    monkeypatch.setattr(dj, "live_symbols", lambda: {"A_USDT", "B_USDT"})
    monkeypatch.setattr(dj, "is_delisted", lambda c, live: False)

    from tradingagents import market_sweep as msw

    monkeypatch.setattr(msw, "candle_coverage", lambda: [
        {"symbol": "A_USDT", "timeframe": "15m", "last_ms": 1_000},
        {"symbol": "A_USDT", "timeframe": "1h", "last_ms": 2_000},
    ])
    pairs, gone, missing, lost_added = dj.resolve_pairs(
        [["B_USDT", "15m"], ["A_USDT", "15m"]])

    assert len(pairs) == len(set(pairs)), f"a pair twice is a pair fetched twice: {pairs}"
    # every stored pair (they are behind), every pair the venue lists that the
    # store lacks, and the lost ones — including a lost pair ALREADY stored,
    # which `update` reaches only by accident of the store walk
    assert ("A_USDT", "15m") in pairs and ("A_USDT", "1h") in pairs
    assert ("B_USDT", "15m") in pairs
    assert ("B_USDT", "1h") in pairs, "never-stored pairs must be in it"
    assert missing > 0


def test_a_lost_pair_already_in_the_store_is_still_redone(monkeypatch):
    """RETRY FAILED fetched it; UPDATE only reached it as part of the store
    walk, so it inherited the store walk's ORDER — last, behind 5,000 others."""
    monkeypatch.setattr(dj, "live_symbols", lambda: {"A_USDT"})
    monkeypatch.setattr(dj, "is_delisted", lambda c, live: False)
    from tradingagents import market_sweep as msw

    monkeypatch.setattr(msw, "candle_coverage", lambda: [
        {"symbol": "A_USDT", "timeframe": f"{i}h", "last_ms": 9_000_000_000}
        for i in range(1, 5)])
    pairs, _gone, _missing, _lost = dj.resolve_pairs([["A_USDT", "2h"]])
    # a KNOWN FAILURE goes first: it is the one the operator pressed the button
    # for, and a stopped run must not leave it for next time
    assert pairs[0] == ("A_USDT", "2h"), pairs[:3]


def test_the_job_accepts_the_mode():
    import inspect

    src = inspect.getsource(dj._run_download)
    assert 'mode == "resolve"' in src
    assert "resolve_pairs(" in src


# ------------------------------------------------------------------ the count
def test_pending_is_counted_in_one_place():
    """The button's number and the Pending tab's number are the same number."""
    import inspect

    src = inspect.getsource(dj.pending_work)
    assert "behind" in src and "missing" in src and "lost" in src
    # and the things NOTHING can fix are counted apart, never added in
    assert "delisted" in src and "empty" in src


def test_unfixable_pendings_are_not_counted_as_work(monkeypatch):
    """97 stored pairs sit on contracts MEXC dropped. A button offering them is
    a button that cannot succeed, and a count including them can never reach
    zero."""
    monkeypatch.setattr(dj, "_pending_sources", lambda: {
        "behind": 5022, "missing": 45, "lost": 0,
        "delisted": 97, "empty": 25})
    got = dj.pending_work()
    assert got["count"] == 5067, got
    assert got["unfixable"] == 122, got
    assert got["behind"] == 5022 and got["missing"] == 45


def test_nothing_pending_is_zero_not_a_falsehood(monkeypatch):
    monkeypatch.setattr(dj, "_pending_sources", lambda: {
        "behind": 0, "missing": 0, "lost": 0, "delisted": 97, "empty": 25})
    got = dj.pending_work()
    assert got["count"] == 0
    assert got["unfixable"] == 122, "still reported, just not as work"


# ----------------------------------------------------------------- the button
def test_the_button_exists_and_says_what_it_will_do():
    s = _r(SCREEN)
    assert "RESOLVE PENDING" in s
    assert 'mode: "resolve"' in s
    # the label carries the COUNT, derived from the route
    assert "pending?.count" in s


def test_the_button_is_live_whenever_anything_is_fixable():
    """UPDATE was disabled on `!gaps?.pairs`, so a lost-only pending could not
    be cleared by any enabled button."""
    s = _r(SCREEN)
    i = s.index("onClick={resolve}")
    frag = s[max(0, i - 300):i + 500]
    assert "!pending?.count" in frag, "enabled exactly when there is work"
    assert "dl?.running" in frag, "and never while a download is running"


def test_the_pending_tab_reads_the_same_route():
    h = _r(HISTORY)
    assert "api.candlePending()" in h, \
        "one definition of pending, or the two counts drift"


def test_the_queue_is_exactly_what_the_button_counted(monkeypatch):
    """The number on the button IS the number of pairs the run touches.

    `update_pairs` walks EVERY stored pair: measured on the operator's store it
    queued 5,192 pairs when 5,067 things were pending, so 125 already-current
    pairs each cost a request that returns nothing and the button's label
    disagreed with its own run (label-must-match-data).
    """
    from tradingagents import market_sweep as msw

    now = 1_800_000_000
    monkeypatch.setattr(dj.time, "time", lambda: now)
    monkeypatch.setattr(dj, "live_symbols", lambda: {"A_USDT", "B_USDT"})
    monkeypatch.setattr(dj, "is_delisted", lambda c, live: False)
    monkeypatch.setattr(dj, "_read", lambda p: {"pairs": [["B_USDT", "1h"]]})
    # A 15m pair four hours behind; a 1h pair CURRENT; B_USDT 1h stored but
    # lost by the last run.
    monkeypatch.setattr(msw, "candle_index", lambda scan=False: {
        "A_USDT-15m": {"symbol": "A_USDT", "timeframe": "15m",
                       "last_ms": (now - 4 * 3600) * 1000},
        "A_USDT-1h": {"symbol": "A_USDT", "timeframe": "1h",
                      "last_ms": now * 1000},
        "B_USDT-1h": {"symbol": "B_USDT", "timeframe": "1h",
                      "last_ms": now * 1000},
    })
    work = dj.pending_work()
    pairs, _gone, _missing, _lost = dj.resolve_pairs([["B_USDT", "1h"]])

    assert ("A_USDT", "1h") not in pairs, \
        "a pair that is already current is not pending and must not be fetched"
    assert pairs[0] == ("B_USDT", "1h"), "the known failure goes first"
    assert len(pairs) == work["count"], (len(pairs), work)


def test_the_queue_and_the_count_are_both_published(monkeypatch):
    """They are DIFFERENT numbers and the screen shows both.

    Measured on the operator's store, Sep 04, 2026: 5,077 pending, 5,173 pairs
    touched. The 96 extra are pairs on contracts MEXC dropped that are also
    behind — they get one confirming attempt, because the contract list is
    filtered by apiAllowed and by quote and a stale answer must not delete work
    from the queue (CLAUDE.md). A 97th delisted pair is current, so it is not
    queued at all. Neither number may stand in for the other.
    """
    monkeypatch.setattr(dj, "_pending_sources", lambda: {
        "behind": 5022, "missing": 45, "lost": 10,
        "delisted": 97, "empty": 0, "indexing": False})
    monkeypatch.setattr(dj, "resolve_pairs",
                        lambda lost: ([("X", "1h")] * 5173, [], 45, []))
    monkeypatch.setattr(dj, "_read", lambda p: {"pairs": []})
    got = dj.pending_work()
    assert got["count"] == 5077 and got["queue"] == 5173

    s = _r(SCREEN)
    assert "pending?.queue" in s, "the dialog must show what will be touched"
    assert "attempted once to confirm" in s


def test_the_queue_falls_back_rather_than_raising(monkeypatch):
    """A count that raises is a screen with no button at all."""
    def boom(lost):
        raise RuntimeError("index gone")

    monkeypatch.setattr(dj, "_pending_sources", lambda: {
        "behind": 3, "missing": 0, "lost": 0, "delisted": 0, "empty": 0})
    monkeypatch.setattr(dj, "resolve_pairs", boom)
    monkeypatch.setattr(dj, "_read", lambda p: {"pairs": []})
    got = dj.pending_work()
    assert got["count"] == 3 and got["queue"] == 3
