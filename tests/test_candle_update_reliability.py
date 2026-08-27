"""Candle updating has to be right every time — the operator's own words:
*"this update candles is not reliable / make this reliable 10/10 because this is
critical for backtesting"* (2026-08-27).

The screenshot behind that sentence, and what each line was hiding:

  lost by the last download (Aug 27, 2026 2:43pm): MEZO 15m · MEZO 30m ·
  DRV 15m · MEZO 1h — RETRY fetches exactly these
      -> MEZO_USDT and DRV_USDT are DELISTED (999 live contracts, neither in
         it). Every download and every retry failed on them, they stayed in
         lost.json, the next update fetched them again, and the panel could
         never go green.

  FAILED · RESOLVED ... resolved — every pair that run lost is back in the store
      -> the retry stored ZERO bars. "Recovered" meant "a parquet exists", and
         MEZO's file had been sitting there since Aug 25 1:22pm. A file older
         than the run that lost the pair is not a recovery.

  store missing 20 of 4,995 pairs: DESTOCK 15m ... IOTSTOCK 1h and 12 more
      -> UPDATE walked the STORE, so a contract the store had never seen was
         never fetched by it. No button filled those.

  4,985 pair(s) stored · 3722 behind by more than a bar · furthest is DGAI 15m,
  50.3h
      -> the 12:53pm update was STOPPED, and the next update walks the same
         order from the top, so the tail keeps losing.
"""
import time

import pytest

from tradingagents import db_jobs as dj


def test_a_delisted_contract_is_named_not_retried(monkeypatch):
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"BTC_USDT"})
    assert dj.is_delisted("MEZO_USDT") is True
    assert dj.is_delisted("BTC_USDT") is False


def test_could_not_ask_is_not_everything_is_delisted(monkeypatch):
    """None means the venue could not be reached. Treating that as "delisted"
    would skip the entire store on one bad request."""
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: None)
    assert dj.is_delisted("ANYTHING_USDT") is False
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: set())
    assert dj.is_delisted("ANYTHING_USDT") is False, (
        "an EMPTY list is a failed request too, never a delisting")


def test_live_symbols_returns_none_when_the_venue_cannot_be_asked(monkeypatch):
    from tradingagents.dataflows import mexc_futures as fx

    dj._LIVE_CACHE.update(at=0.0, symbols=None)
    monkeypatch.setattr(fx, "list_contracts",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no net")))
    assert dj.live_symbols() is None
    dj._LIVE_CACHE.update(at=0.0, symbols=None)
    monkeypatch.setattr(fx, "list_contracts", lambda *a, **k: [])
    assert dj.live_symbols() is None, "empty is unusable, not authoritative"


def test_an_update_fetches_the_store_the_gaps_and_the_lost(monkeypatch):
    """Three sources, and the store alone is none of them."""
    now = time.time()
    monkeypatch.setattr(dj, "live_symbols",
                        lambda *a, **k: {"AAA_USDT", "NEW_USDT", "BBB_USDT",
                                         "LOST_USDT"})
    cov = [
        {"symbol": "AAA_USDT", "timeframe": "15m", "last_ms": (now - 3600) * 1000},
        {"symbol": "AAA_USDT", "timeframe": "1h", "last_ms": (now - 200000) * 1000},
        {"symbol": "BBB_USDT", "timeframe": "15m", "last_ms": (now - 60) * 1000},
        {"symbol": "GONE_USDT", "timeframe": "15m", "last_ms": (now - 99999) * 1000},
    ]
    monkeypatch.setattr(dj, "update_pairs", dj.update_pairs)   # keep the real one
    import tradingagents.market_sweep as msw

    monkeypatch.setattr(msw, "candle_coverage", lambda *a, **k: cov)

    pairs, delisted, n_missing, lost_added = dj.update_pairs(
        [["LOST_USDT", "4h"]])

    # every pair the store does not have is fetched, and ALL of them come
    # before any pair the store already holds — a pair with no file at all is
    # worse than a pair that is one bar behind. (AAA's other timeframes count:
    # the store holds AAA 15m and 1h, so AAA 30m/4h/1d are missing too.)
    assert ("NEW_USDT", "15m") in pairs
    assert n_missing == 4 * 5 - 3, n_missing        # 4 live x 5 tf minus 3 held
    held = {("AAA_USDT", "15m"), ("AAA_USDT", "1h"), ("BBB_USDT", "15m")}
    first_held = next(i for i, p in enumerate(pairs) if p in held)
    assert all(p not in held for p in pairs[:first_held])
    assert first_held == n_missing, (first_held, n_missing)

    # the pairs the store ALREADY HOLDS follow, MOST BEHIND FIRST
    stored_order = [p for p in pairs if p in held]
    assert stored_order == [("AAA_USDT", "1h"),      # 200,000 s behind
                           ("AAA_USDT", "15m"),      # 3,600 s
                           ("BBB_USDT", "15m")], stored_order   # 60 s

    # what the last run lost is asked for again (it is live, so it is fetchable)
    assert ("LOST_USDT", "4h") in pairs
    assert ("LOST_USDT", "4h") in lost_added, lost_added

    # and the delisted are dropped, by name
    assert "GONE_USDT 15m" in delisted
    assert all(p[0] != "GONE_USDT" for p in pairs), pairs


def test_the_store_is_walked_most_behind_first(monkeypatch):
    """A stopped update used to leave its tail untouched and the next one
    started from the same place: 3,722 pairs more than a bar behind, the
    furthest 50.3 h. Staleness order means a stop always did the work that
    mattered."""
    now = time.time()
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: None)
    import tradingagents.market_sweep as msw

    monkeypatch.setattr(msw, "candle_coverage", lambda *a, **k: [
        {"symbol": "FRESH_USDT", "timeframe": "15m", "last_ms": now * 1000},
        {"symbol": "OLD_USDT", "timeframe": "15m", "last_ms": (now - 180000) * 1000},
        {"symbol": "MID_USDT", "timeframe": "15m", "last_ms": (now - 7200) * 1000},
    ])
    pairs, _delisted, _n, _lost = dj.update_pairs([])
    assert [p[0] for p in pairs] == ["OLD_USDT", "MID_USDT", "FRESH_USDT"], pairs


def test_recovered_means_fetched_SINCE_the_run_that_lost_it(monkeypatch, tmp_path):
    """The false RESOLVED. A parquet from Aug 25 1:22pm is not a recovery of a
    pair lost at 2:43pm on Aug 27."""
    from tradingagents import api, parquet_store as pqs

    f = tmp_path / "MEZO_USDT-15m.parquet"
    f.write_bytes(b"not really parquet")
    monkeypatch.setattr(pqs, "_candle_path", lambda *a, **k: f)
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"MEZO_USDT"})

    old = f.stat().st_mtime
    assert api._stored_now("MEZO_USDT", "15m", since=old + 60)["recovered"] is False
    assert api._stored_now("MEZO_USDT", "15m", since=old - 60)["recovered"] is True
    # and the file's own age travels with it, so a label can be checked
    got = api._stored_now("MEZO_USDT", "15m", since=old + 60)
    assert got["exists"] is True and got["when"]


def test_a_delisted_pair_resolves_a_failed_run_and_says_why(monkeypatch):
    from tradingagents import api

    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"BTC_USDT"})
    row = {"kind": "download", "ok": False, "ts": time.time(),
           "meta": {"failed": ["MEZO_USDT 15m: no Min15 candles for MEZO_USDT"],
                    "errors": 1}}
    resolved, why = api._download_resolution(row)
    assert resolved is True, why
    assert "DELISTED" in why and "MEZO 15m" in why, why
    assert "cannot be fetched by any run" in why, why


def test_a_pair_that_is_still_missing_is_still_lost(monkeypatch, tmp_path):
    from tradingagents import api, parquet_store as pqs

    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"AAA_USDT"})
    monkeypatch.setattr(pqs, "_candle_path", lambda *a, **k: tmp_path / "nope")
    row = {"kind": "download", "ok": False, "ts": time.time(),
           "meta": {"failed": ["AAA_USDT 15m: IncompleteRead(183452 bytes)"],
                    "errors": 1}}
    resolved, why = api._download_resolution(row)
    assert resolved is False
    assert "still lost" in why and "AAA 15m" in why and "no file" in why, why


def test_the_retry_button_is_not_offered_a_pair_it_cannot_fetch(monkeypatch):
    from tradingagents import api

    monkeypatch.setattr(dj, "_read", lambda *a, **k: {
        "pairs": [["MEZO_USDT", "15m"], ["AAA_USDT", "1h"]],
        "written": time.time()})
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"AAA_USDT"})
    got = api.candles_lost()
    assert [p["symbol"] for p in got["pairs"]] == ["AAA_USDT"], got["pairs"]
    assert got["delisted_count"] == 1
    assert got["delisted"][0]["symbol"] == "MEZO_USDT"


def test_the_screen_names_the_delisted_and_the_gaps():
    p = open("webapp/src/components/candles/DownloadScreen.tsx",
             encoding="utf-8").read()
    assert "DELISTED on MEXC, skipped by every" in p
    assert "lost.delisted_count" in p
    assert "nothing can fetch a contract the venue dropped" in p
