"""Funding history is either COMPLETE or an error — never quietly short.

Found live on Aug 26, 2026 while measuring BTC_USDT 1h for the confluence
study: `fx.funding_history("BTC_USDT")` died with
`IncompleteRead(8984 bytes read)` — the same cut-connection failure that lost
CHILLGUY 15m during the candle download, from the one keyless fetch in the
module that still called `urlopen` directly instead of `_get_public`, so the
retry added that morning did not cover it.

The worse half was the handler. A page that failed was logged at WARNING and
`break` ended the paging loop, so the function RETURNED THE PAGES IT HAD.
Funding is one of the three mandatory costs (CLAUDE.md rule 9): a half-read
history makes every trade in the affected window cheaper than reality, in the
direction that flatters the strategy, and no column anywhere says the history
was short. Measured for scale on the live five: funding was -4.7% of PROVE's
profit and +0.5% on XAUT.

So: the fetch retries (through `_get_public`), and a page that still fails
raises. An empty answer from the venue is a legitimate empty list — a contract
with no settlements yet is not an error.
"""
import http.client
import json

import pytest

from tradingagents.dataflows import mexc_futures as fx


def _page(rows, total_page=1):
    return {"success": True, "data": {"totalPage": total_page,
                                      "resultList": rows}}


def _rows(n, start=1_787_000_000_000):
    return [{"settleTime": start + i * 28_800_000, "fundingRate": 0.0001 * i,
             "collectCycle": 8} for i in range(n)]


@pytest.fixture
def wire(monkeypatch):
    """Script _get_public: each call pops the next outcome (raise or payload)."""
    script, calls = [], []

    def get_public(url):
        calls.append(url)
        step = script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(fx, "_get_public", get_public)
    monkeypatch.setattr(fx.time, "sleep", lambda s: None)
    return {"script": script, "calls": calls}


def test_the_fetch_goes_through_the_retrying_helper():
    """Not urlopen: that is the whole bug. _get_public retries a cut wire."""
    import inspect

    src = inspect.getsource(fx.funding_history)
    assert "_get_public(" in src
    assert "urlopen(" not in src


def test_every_page_is_collected_in_settlement_order(wire):
    wire["script"] += [_page(_rows(100), total_page=2),
                       _page(_rows(20, start=1_790_000_000_000), total_page=2)]
    got = fx.funding_history("BTC_USDT")
    assert len(got) == 120
    assert [d["settle_ms"] for d in got] == sorted(d["settle_ms"] for d in got)
    assert got[0]["cycle_h"] == 8


def test_a_page_that_fails_raises_rather_than_returning_half(wire):
    """The failure that started this: page 2 of 5 dies. Returning page 1 alone
    would charge a fifth of the real funding and say nothing."""
    wire["script"] += [_page(_rows(100), total_page=5),
                       fx.MexcFuturesError("transport failure: "
                                           "IncompleteRead(8984 bytes read) after 3 attempts")]
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx.funding_history("BTC_USDT")
    msg = str(exc.value)
    assert "funding" in msg.lower() and "page 2" in msg
    assert "IncompleteRead" in msg, "the real cause must survive into the message"


def test_a_venue_with_no_settlements_is_an_empty_list_not_an_error(wire):
    wire["script"] += [_page([], total_page=1)]
    assert fx.funding_history("NEW_USDT") == []


def test_a_malformed_page_is_an_error_too(wire):
    wire["script"] += [json.loads('{"success":true,"data":{"resultList":[{"settleTime":"x"}]}}')]
    with pytest.raises(fx.MexcFuturesError):
        fx.funding_history("BTC_USDT")


def test_an_incomplete_read_reaches_the_caller_as_transient(wire):
    """The supervisor decides retry-vs-give-up from this, so the class and the
    wording both matter."""
    from tradingagents import db_jobs

    wire["script"] += [http.client.IncompleteRead(b"x" * 8984)]
    with pytest.raises(Exception) as exc:
        fx.funding_history("BTC_USDT")
    assert db_jobs.is_transient(exc.value)


def test_the_sweep_does_not_silently_charge_zero_funding():
    """market_sweep.run_pair wrapped the call in `except Exception: fund = []`,
    which turned an unreadable history into a backtest with NO funding charged
    — the same lie one layer up. A failed read must reach the pool, which
    discards the pair and redoes it (PAIR_RETRIES)."""
    import inspect

    from tradingagents import market_sweep as msw

    src = inspect.getsource(msw.run_pair)
    i = src.index("funding_history(")
    window = src[max(0, i - 300):i + 300]
    assert "fund = []" not in window, \
        "an unreadable funding history must not become zero funding"


def test_the_page_budget_fits_a_four_hourly_coins_full_history(wire):
    """The budget is a runaway backstop, not a cap on real history.

    It was 20 pages. BTC settles every 8 hours and fills 17, so nothing looked
    wrong -- but FLUX_USDT settles every FOUR hours and has 33. Once truncation
    became an error (this file's first fix), the strictness turned those coins
    into excluded pairs: on Aug 26, 2026 the 1h/4h sweep printed
    "FLUX 4h: failed (funding history for FLUX_USDT is incomplete: stopped at
    the 20-page budget)" and dropped the contract after its retries.
    """
    assert fx.funding_history.__defaults__[0] >= 100, \
        "the budget must fit a 4-hourly coin's whole history"
    pages = 33
    for i in range(pages):
        wire["script"].append(_page(_rows(100, start=1_700_000_000_000 + i * 100 * 14_400_000),
                                    total_page=pages))
    got = fx.funding_history("FLUX_USDT")
    assert len(got) == pages * 100
    assert len(wire["calls"]) == pages


def test_a_history_longer_than_the_budget_is_still_an_error(wire, monkeypatch):
    """Exhausting the backstop with pages the venue says exist is incomplete,
    and incomplete funding is never returned quietly."""
    monkeypatch.setattr(fx, "_PUBLIC_RETRIES", 1)
    for i in range(3):
        wire["script"].append(_page(_rows(100), total_page=99))
    with pytest.raises(fx.MexcFuturesError) as exc:
        fx.funding_history("LONG_USDT", max_pages=3)
    assert "3-page budget" in str(exc.value)
