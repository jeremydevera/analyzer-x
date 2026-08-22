"""The screener route must never let "could not check" look like "nothing new".

A sweep that came from a stale cache, or that failed to resolve some symbols,
says so in the payload — the count line on screen is built from these fields.
"""

import pytest
from fastapi.testclient import TestClient

from tradingagents.api import app
from tradingagents.dataflows import mexc


def _coin(base="CATE", vol=50000.0):
    return mexc.NewCoin(symbol=f"{base}USDT", base=base, name=base,
                        contract="0xabc", listed_at_ms=1_787_000_000_000,
                        listed_date="2026-08-20", age_hours=30.0, price=0.0012,
                        change_pct=12.5, quote_volume=vol)


@pytest.fixture()
def client():
    return TestClient(app)


def test_new_listings_carry_every_row_and_the_sweep_coverage(client,
                                                             monkeypatch):
    monkeypatch.setattr(mexc, "screen_new_listings", lambda **kw: mexc.ScreenResult(
        coins=[_coin(), _coin("DOGE2", 900.0)], scanned=1712, unresolved=4,
        hidden_by_volume=31, hidden_by_age=7, fetched_at=1_787_000_000.0,
        from_cache=True, stale=False))
    got = client.get("/api/crypto/new").json()
    assert [r["base"] for r in got["rows"]] == ["CATE", "DOGE2"]
    assert got["scanned"] == 1712 and got["unresolved"] == 4
    assert got["hidden_by_volume"] == 31 and got["hidden_by_age"] == 7
    assert got["from_cache"] is True and got["stale"] is False
    assert got["rows"][0]["age_days"] == 1


def test_a_stale_sweep_is_flagged_not_silently_served(client, monkeypatch):
    monkeypatch.setattr(mexc, "screen_new_listings", lambda **kw: mexc.ScreenResult(
        coins=[], scanned=0, unresolved=0, hidden_by_volume=0, hidden_by_age=0,
        fetched_at=1.0, from_cache=True, stale=True))
    got = client.get("/api/crypto/new").json()
    assert got["stale"] is True and got["rows"] == []


def test_filters_reach_the_screener_verbatim(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(mexc, "screen_new_listings", lambda **kw: seen.update(kw) or
                        mexc.ScreenResult(coins=[], scanned=0, unresolved=0,
                                          hidden_by_volume=0, hidden_by_age=0,
                                          fetched_at=1.0, from_cache=False))
    client.get("/api/crypto/new?min_volume=25000&min_age_hours=6&max_age_hours=48&include_all=true")
    assert seen["min_quote_volume"] == 25000.0
    assert seen["min_age_hours"] == 6.0 and seen["max_age_hours"] == 48.0
    assert seen["include_all"] is True


def test_upcoming_failure_reports_why_instead_of_an_empty_list(client,
                                                              monkeypatch):
    def boom():
        raise mexc.MexcUnavailable("host blocked")
    monkeypatch.setattr(mexc, "upcoming_listings", boom)
    got = client.get("/api/crypto/upcoming").json()
    assert got["rows"] == [] and "host blocked" in got["why"]


# --- the listing watcher --------------------------------------------------
# The screener could watch for new listings and alarm. It was missing from the
# React port entirely. The rule that makes it usable: an empty baseline SEEDS,
# it does not announce the whole exchange.

def test_the_first_tick_seeds_and_announces_nothing(client, monkeypatch):
    monkeypatch.setattr(mexc, "poll_new_listings",
                        lambda known, **kw: ([], {"AUSDT", "BUSDT"}))
    got = client.post("/api/crypto/watch", json={"known": []}).json()
    assert got["found"] == [] and got["seeded"] is True
    assert set(got["known"]) == {"AUSDT", "BUSDT"}


def test_a_later_tick_reports_only_what_is_new(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(mexc, "poll_new_listings",
                        lambda known, **kw: seen.update(known=known, kw=kw) or
                        ([{"symbol": "CUSDT", "base": "C", "age_hours": 2.0}],
                         {"AUSDT", "CUSDT"}))
    monkeypatch.setattr(mexc, "merge_new_listings", lambda found: len(found))
    got = client.post("/api/crypto/watch",
                      json={"known": ["AUSDT"], "max_age_hours": 12}).json()
    assert [r["symbol"] for r in got["found"]] == ["CUSDT"]
    assert got["seeded"] is False and got["merged_into_sweep"] == 1
    assert seen["known"] == {"AUSDT"} and seen["kw"]["max_age_hours"] == 12.0


def test_a_watch_failure_says_why_and_keeps_the_baseline(client, monkeypatch):
    def boom(known, **kw):
        raise mexc.MexcRateLimited("429")
    monkeypatch.setattr(mexc, "poll_new_listings", boom)
    got = client.post("/api/crypto/watch", json={"known": ["AUSDT"]}).json()
    assert got["found"] == [] and "429" in got["why"]
    assert got["known"] == ["AUSDT"], "a failed tick must not reset the baseline"


def test_candles_come_back_as_plain_rows_for_the_chart(client, monkeypatch):
    import pandas as pd

    from tradingagents.dataflows import mexc_futures as fx
    df = pd.DataFrame({"Date": pd.to_datetime([1_787_000_000], unit="s"),
                       "Open": [1.0], "High": [2.0], "Low": [0.5],
                       "Close": [1.5], "Volume": [10.0]})
    monkeypatch.setattr(fx, "klines", lambda s, i, n: df)
    got = client.get("/api/crypto/candles?symbol=APEX_USDT&interval=Min60").json()
    assert got["rows"] == [{"t": 1_787_000_000_000, "o": 1.0, "h": 2.0,
                            "l": 0.5, "c": 1.5, "v": 10.0}]
