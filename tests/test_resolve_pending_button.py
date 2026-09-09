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
    # since 2026-09-09 the mode fetches the PENDING LEDGER — "resolve mean you
    # will restart or resume where it crash" — not a whole-store walk
    assert '_pl.pending("candles")' in src


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





# --------------------------------------------------------------------------
# PENDING = WHAT BROKE (2026-09-09). "pending only means these are the candles
# that had problem during the update candles or download candle, resolve mean
# you will restart or resume where it crash."
# --------------------------------------------------------------------------
def test_resolve_fetches_only_what_failed(monkeypatch, tmp_path):
    """It used to queue 5,192 pairs on a store where nothing had failed — a
    whole-market update wearing the word "resolve"."""
    from tradingagents import pending_ledger as pl

    monkeypatch.setattr(pl, "STATE_DIR", tmp_path)
    pl.record("candles", [("AAA_USDT", "15m", "IncompleteRead"),
                          ("BBB_USDT", "1h", "timeout")])
    got = [(r["symbol"], r["timeframe"]) for r in pl.pending("candles")]
    assert sorted(got) == [("AAA_USDT", "15m"), ("BBB_USDT", "1h")]


def test_a_pair_that_succeeds_comes_off_the_books(monkeypatch, tmp_path):
    """RESUME means the problem is GONE when it is fixed — by any run, not
    only by the retry that was aimed at it."""
    from tradingagents import pending_ledger as pl

    monkeypatch.setattr(pl, "STATE_DIR", tmp_path)
    pl.record("candles", [("AAA_USDT", "15m", "IncompleteRead")])
    assert pl.count("candles") == 1
    pl.clear("candles", [("AAA_USDT", "15m")])
    assert pl.count("candles") == 0


def test_the_queue_is_the_ledger(monkeypatch, tmp_path):
    """`queue` on the badge is what RESOLVE would fetch. It used to be derived
    from a whole-store walk and disagreed with the button's own count."""
    from tradingagents import db_jobs as dj, pending_ledger as pl

    monkeypatch.setattr(pl, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dj, "_pending_sources", lambda: {
        "behind": 5000, "missing": 3, "lost": 0, "delisted": 0, "empty": 0})
    pl.record("candles", [("AAA_USDT", "15m", "boom")])
    got = dj.pending_work()
    assert got["queue"] == 1, "the queue is the failure ledger"
    assert got["count"] == 5003, "the old arithmetic stays under its own name"
