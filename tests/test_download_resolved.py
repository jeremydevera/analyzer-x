"""A failed download that has since been made whole says RESOLVED everywhere
it is shown — and "whole" is measured against the store, never assumed.

Operator, 2026-08-25, with 4,985 of 4,985 pairs in the store:

    "then why do i still see 39,656,242 bars over 4985 pair(s) · 2 error(s):
     CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)
     this is clearly a bug"

The bell and the history kept printing the 2:00pm failure in red as if it
were live. A failed run is resolved when every pair it NAMED is in the store
and — for the errors it did not name — the store is complete: every
contract MEXC lists, on all five timeframes, has a file.
"""
import pandas as pd
import pytest

from tradingagents import api, notifications as nt, parquet_store as pqs

FAILED_2PM = {
    "id": 1, "ts": 1787680852.35, "kind": "download", "ok": 0,
    "title": "Download finished with errors",
    "detail": "39,656,242 bars over 4985 pair(s) · 2 error(s): "
              "CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)",
    "meta": {"pairs": 4985, "bars": 39656242, "errors": 2, "stopped": False,
             "mode": "download"}, "read_at": None,
}


def _frame(n=3):
    return pd.DataFrame({"Date": pd.to_datetime([1_787_000_000 + 900 * i
                                                for i in range(n)], unit="s"),
                         "Open": [1.0] * n, "High": [1.0] * n, "Low": [1.0] * n,
                         "Close": [1.0] * n, "Volume": [1.0] * n})


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two contracts on the venue, a store to fill, a bell with the 2pm row."""
    from tradingagents.dataflows import mexc_futures as fx

    monkeypatch.setattr(pqs, "CANDLES", tmp_path / "candles")
    monkeypatch.setattr(fx, "list_contracts",
                        lambda: [{"symbol": "CHILLGUY_USDT"}, {"symbol": "NAORIS_USDT"}])
    monkeypatch.setattr(api, "_COMPLETENESS_CACHE", {"at": 0.0, "payload": None})
    monkeypatch.setattr(nt, "recent", lambda limit=30, kind=None, unread_only=False: [dict(FAILED_2PM)])
    monkeypatch.setattr(nt, "unread_count", lambda: 0)

    def fill(*pairs):
        for sym, tf in pairs:
            pqs.save_candles(sym, tf, _frame())
    return fill


ALL_TEN = [(c, tf) for c in ("CHILLGUY_USDT", "NAORIS_USDT")
           for tf in ("15m", "30m", "1h", "4h", "1d")]


def test_completeness_is_measured_against_the_venue_times_five_timeframes(world):
    world(*ALL_TEN[:-1])
    got = api.candles_completeness()
    assert (got["contracts"], got["wanted"], got["stored"]) == (2, 10, 9)
    assert got["missing"] == [{"symbol": "NAORIS_USDT", "timeframe": "1d"}]
    assert got["complete"] is False
    world(ALL_TEN[-1])
    api._COMPLETENESS_CACHE["at"] = 0.0             # the cache is 5 minutes; skip it here
    got = api.candles_completeness()
    assert got["complete"] is True and got["missing"] == []


def test_a_failed_run_is_resolved_only_when_the_store_is_whole(world):
    # the named pair is back but the unnamed one is not: NOT resolved
    world(("CHILLGUY_USDT", "15m"))
    row = api.notifications_list()["rows"][0]
    assert row["resolved"] is False
    assert "1 pair" in row["resolved_why"] and "NAORIS_USDT 1d" not in row["resolved_why"]

    world(*ALL_TEN)
    api._COMPLETENESS_CACHE["at"] = 0.0
    row = api.notifications_list()["rows"][0]
    assert row["resolved"] is True
    assert row["resolved_why"] == "resolved — the store holds all 10 pairs (2 contracts × 5 timeframes)"


def test_a_named_pair_still_missing_keeps_the_failure_live(world):
    world(*[p for p in ALL_TEN if p != ("CHILLGUY_USDT", "15m")])
    row = api.notifications_list()["rows"][0]
    assert row["resolved"] is False
    assert "CHILLGUY_USDT 15m" in row["resolved_why"]


def test_history_rows_carry_the_same_verdict(world):
    world(*ALL_TEN)
    row = api.download_history()["rows"][0]
    assert row["resolved"] is True
    assert row["resolved_why"].startswith("resolved — ")


def test_an_ok_row_has_nothing_to_resolve(world, monkeypatch):
    ok = dict(FAILED_2PM, id=2, ok=1, title="Download finished",
              detail="53,393 bars over 4 pair(s)",
              meta={"pairs": 4, "bars": 53393, "errors": 0, "stopped": False,
                    "mode": "download"})
    monkeypatch.setattr(nt, "recent", lambda limit=30, kind=None, unread_only=False: [ok])
    row = api.notifications_list()["rows"][0]
    assert row["resolved"] is None and row["resolved_why"] == ""


def test_the_venue_being_unreachable_is_unknown_not_resolved(world, monkeypatch):
    from tradingagents.dataflows import mexc_futures as fx

    world(("CHILLGUY_USDT", "15m"))
    monkeypatch.setattr(fx, "list_contracts", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    api._COMPLETENESS_CACHE["at"] = 0.0
    row = api.notifications_list()["rows"][0]
    assert row["resolved"] is False
    assert "could not" in row["resolved_why"]
