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

    # a pair the venue no longer lists is NAMED and still ATTEMPTED: the queue
    # must not delete unattempted work on a filtered, cached contract list, and
    # one attempt is what lets the loop classify it and clear lost.json
    assert "GONE_USDT 15m" in delisted
    assert ("GONE_USDT", "15m") in pairs, (
        "named, not dropped — CLAUDE.md: a failed age check KEEPS the coin")


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


def test_the_retry_button_names_a_delisted_pair_and_still_clears_it(monkeypatch):
    """It is OFFERED, on purpose: one retry attempts it, the loop classifies it
    on the venue's own answer, and lost.json is emptied. Dropping it from the
    button instead would leave it in that file for ever with nothing able to
    clear it — and would trust a filtered, cached list to delete work."""
    from tradingagents import api

    monkeypatch.setattr(dj, "_read", lambda *a, **k: {
        "pairs": [["MEZO_USDT", "15m"], ["AAA_USDT", "1h"]],
        "written": time.time()})
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"AAA_USDT"})
    got = api.candles_lost()
    assert [p["symbol"] for p in got["pairs"]] == ["MEZO_USDT", "AAA_USDT"]
    assert got["delisted_count"] == 1
    assert got["delisted"][0]["symbol"] == "MEZO_USDT"


def test_the_screen_names_the_delisted_and_the_gaps():
    p = open("webapp/src/components/candles/DownloadScreen.tsx",
             encoding="utf-8").read()
    assert "DELISTED on MEXC, skipped by every" in p
    assert "lost.delisted_count" in p
    assert "nothing can fetch a contract the venue dropped" in p


def test_no_route_can_call_an_old_file_a_recovery(monkeypatch, tmp_path):
    """Review, 2026-08-27: `_stored_now` was fixed in ONE of three call sites,
    so the panel still printed "MEZO 15m (14,030 bars, stored Aug 26 1:22am)"
    as RECOVERED for a run that failed on Aug 28 at 2:43am. `since` is required
    now, and both read routes pass the run's own timestamp."""
    import inspect

    from tradingagents import api, parquet_store as pqs

    sig = inspect.signature(api._stored_now)
    assert sig.parameters["since"].default is inspect.Parameter.empty, (
        "a default is what let two call sites keep the old lie")

    f = tmp_path / "MEZO_USDT-15m.parquet"
    f.write_bytes(b"x")
    monkeypatch.setattr(pqs, "_candle_path", lambda *a, **k: f)
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"MEZO_USDT"})
    run_ts = f.stat().st_mtime + 3600            # the run is an hour NEWER
    monkeypatch.setattr(dj, "_read", lambda *a, **k: {"pairs": [], "written": 0})

    row = {"kind": "download", "ok": False, "ts": run_ts,
           "meta": {"failed": ["MEZO_USDT 15m: IncompleteRead(1 byte)"],
                    "errors": 1}}
    import tradingagents.notifications as nt

    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [row])
    got = api.candles_lost()
    assert got["recovered"] == [], got["recovered"]
    resolved, why = api._download_resolution(dict(row))
    assert resolved is False and "still lost" in why, why
    assert "older than this run" in why, why
    # the fake file has no readable parquet metadata: `bars` is None, and
    # f"{None:,}" would raise — a truncated file must not 500 this route
    assert "unreadable" in why, why


def test_a_delisted_pair_is_never_listed_as_recovered(monkeypatch, tmp_path):
    from tradingagents import api, parquet_store as pqs
    import tradingagents.notifications as nt

    f = tmp_path / "MEZO_USDT-15m.parquet"
    f.write_bytes(b"x")
    monkeypatch.setattr(pqs, "_candle_path", lambda *a, **k: f)
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"OTHER_USDT"})
    monkeypatch.setattr(dj, "_read", lambda *a, **k: {"pairs": [], "written": 0})
    row = {"kind": "download", "ok": False, "ts": f.stat().st_mtime - 60,
           "meta": {"failed": ["MEZO_USDT 15m: no Min15 candles"], "errors": 1}}
    monkeypatch.setattr(nt, "recent", lambda limit=20, kind=None: [row])
    got = api.candles_lost()
    assert got["recovered"] == [], (
        "the file is newer than the run, but the contract is GONE: it belongs "
        "in the delisted line, not in recovered")


def test_a_failed_contract_lookup_is_remembered_briefly(monkeypatch):
    """`is_delisted` runs per pair inside routes the panel polls every 20-60 s.
    Without a negative cache a venue outage would re-enter list_contracts (with
    its own retry budget) on every one of them."""
    from tradingagents.dataflows import mexc_futures as fx

    calls = []
    dj._LIVE_CACHE.update(at=0.0, symbols=None, failed_at=0.0)
    monkeypatch.setattr(fx, "list_contracts",
                        lambda *a, **k: calls.append(1) or (_ for _ in ())
                        .throw(OSError("no net")))
    assert dj.live_symbols() is None
    assert dj.live_symbols() is None
    assert len(calls) == 1, "the failure is cached, not re-tried per call"
    dj._LIVE_CACHE.update(at=0.0, symbols=None, failed_at=0.0)


def test_looks_gone_only_matches_the_venues_empty_answer():
    assert dj.looks_gone("no Min15 candles for MEZO_USDT")
    assert dj.looks_gone("klines returned 0 bars")
    assert not dj.looks_gone("IncompleteRead(183452 bytes read)")
    assert not dj.looks_gone("HTTPSConnectionPool: Read timed out")
    assert not dj.looks_gone("429 Too Many Requests")


def test_the_gaps_count_excludes_what_no_run_can_fetch(monkeypatch):
    """Review, 2026-08-27: counting a delisted pair in "N behind by more than a
    bar" makes that number unreachable and pins "furthest behind" on a contract
    nothing can fetch — MEZO 15m at 50.4 h, for ever."""
    import time as _t

    from tradingagents import api, market_sweep as msw

    now = _t.time()
    api._GAP_CACHE.update(at=0.0, payload=None)
    monkeypatch.setattr(api, "_warm_gap_index", lambda *a, **k: None)
    monkeypatch.setattr(msw, "candle_index", lambda scan=False: {
        "a": {"symbol": "GONE_USDT", "timeframe": "15m", "bars": 10,
              "last_ms": (now - 200000) * 1000},
        "b": {"symbol": "LIVE_USDT", "timeframe": "15m", "bars": 10,
              "last_ms": (now - 7200) * 1000},
    })
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"LIVE_USDT"})
    got = api.candle_gaps()
    assert got["behind"] == 1, got
    assert got["worst"]["symbol"] == "LIVE_USDT", got["worst"]
    assert got["delisted_count"] == 1
    assert got["delisted"][0]["symbol"] == "GONE_USDT"
    assert got["pairs"] == 2, "the STORE still holds both — that count is honest"
    api._GAP_CACHE.update(at=0.0, payload=None)


def test_the_screen_names_the_uncatchable_pairs():
    p = open("webapp/src/components/candles/DownloadScreen.tsx",
             encoding="utf-8").read()
    assert "more stored but DELISTED on MEXC" in p
    assert "they are not counted above" in p


@pytest.fixture
def job(monkeypatch, tmp_path):
    """A real _run_download with the wire and the store stubbed, so the LOOP's
    own classification is what gets tested (review: the fix lived in a branch no
    test entered)."""
    import json

    from tradingagents import market_sweep as msw, parquet_store as pqs
    from tradingagents.dataflows import mexc_futures as fx

    calls, errors = [], {}

    def refresh(c, tf, days=365):
        calls.append((c, tf))
        if (c, tf) in errors:
            raise fx.MexcFuturesError(errors[(c, tf)])
        return object(), 7, "delta"

    monkeypatch.setattr(msw, "refresh_candles", refresh)
    monkeypatch.setattr(pqs, "save_candles", lambda *a, **k: None)
    monkeypatch.setattr(dj, "_stopping", lambda kind: False)
    monkeypatch.setattr(dj, "_pause", lambda *a, **k: None)
    monkeypatch.setattr(dj, "FILES", {"download": {
        "progress": tmp_path / "p.json", "lost": tmp_path / "lost.json"}})
    bell = []
    import tradingagents.notifications as nt

    monkeypatch.setattr(nt, "record", lambda *a, **k: bell.append((a, k)))
    return {"calls": calls, "errors": errors, "bell": bell,
            "progress": lambda: json.loads((tmp_path / "p.json").read_text()),
            "lost": lambda: json.loads((tmp_path / "lost.json").read_text())}


def test_the_loop_skips_a_delisted_pair_without_calling_it_an_error(job,
                                                                   monkeypatch):
    """The branch the fix lives in, end to end: not an error, not in lost.json,
    the run still counts as OK, and the bell names it."""
    job["errors"][("MEZO_USDT", "15m")] = "no Min15 candles for MEZO_USDT"
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"AAA_USDT"})
    dj._run_download({"coins": ["MEZO_USDT", "AAA_USDT"], "tfs": ["15m"]})

    p = job["progress"]()
    assert p["errors"] == 0, p
    assert p["failed"] == [] and p["failed_pairs"] == []
    assert p["delisted"] == ["MEZO_USDT 15m"], p["delisted"]
    assert job["lost"]()["pairs"] == [], "never queued again"
    assert p["done"] == 2, "a skipped pair is still SETTLED, not left pending"
    # the bell says OK and names it — a click that did nothing must be
    # distinguishable from a click that worked
    (args, kw) = job["bell"][-1]
    assert kw["ok"] is True, kw
    assert "delisted, skipped: MEZO_USDT 15m" in kw["detail"], kw["detail"]


def test_a_transient_failure_on_a_delisted_symbol_is_still_a_failure(job,
                                                                    monkeypatch):
    """Both facts, in the loop: a WIRE error is retried and then named, even for
    a symbol the venue no longer lists. Only the venue's own "no candles"
    answer may reclassify a pair as gone."""
    job["errors"][("MEZO_USDT", "15m")] = "IncompleteRead(183452 bytes read)"
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"AAA_USDT"})
    dj._run_download({"coins": ["MEZO_USDT"], "tfs": ["15m"]})
    p = job["progress"]()
    assert p["errors"] == 1 and not p["delisted"], p
    assert p["failed"] == ["MEZO_USDT 15m: IncompleteRead(183452 bytes read)"]
    assert job["lost"]()["pairs"] == [["MEZO_USDT", "15m"]], (
        "a wire failure stays LOST so the next update asks again — the retry "
        "ladder itself is covered in test_download_retry.py")


def test_retry_mode_attempts_a_delisted_pair_once_and_clears_it(job,
                                                               monkeypatch):
    """It is offered on purpose: one attempt lets the loop classify it and empty
    lost.json, so the button can finally go quiet."""
    import json

    (dj.FILES["download"]["lost"]).write_text(json.dumps(
        {"pairs": [["MEZO_USDT", "15m"]], "written": 0}))
    job["errors"][("MEZO_USDT", "15m")] = "no Min15 candles for MEZO_USDT"
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: {"AAA_USDT"})
    dj._run_download({"mode": "retry"})
    assert job["calls"] == [("MEZO_USDT", "15m")], job["calls"]
    p = job["progress"]()
    assert p["errors"] == 0 and p["delisted"] == ["MEZO_USDT 15m"]
    assert job["lost"]()["pairs"] == [], "cleared for good"


def test_update_backtest_survives_its_own_handoff_check(monkeypatch, tmp_path):
    """Operator, 2026-09-03: *"i want to use the backtest button"*.

    UPDATE BACKTEST now delegates to the parallel sweep with its own
    `kind="btupdate"`, and that sweep asks `handoff_requested(kind)` from the
    per-pair callback. `FILES["btupdate"]` declared no handoff file, so the
    FIRST finished pair raised `KeyError: 'handoff'` inside the progress
    callback, `_run_backtest` caught it and the run ended
    "Backtest update FAILED" — the button could not complete one pair. Every
    test of that button was source inspection, which cannot see this.

    So this one RUNS it, with the grid stubbed out: the stub calls the progress
    callback exactly as a finished pair does.
    """
    import json

    from tradingagents import backtest_report as br

    seen = {}

    def grid(coins, tfs, **kw):
        seen.update(coins=list(coins), tfs=list(tfs), fresh=kw.get("fresh"))
        # what a finished pair does — the line that used to raise
        kw["progress"]("CETUS_USDT 15m", 0.5, 1, 2)
        return {"rows": []}

    monkeypatch.setattr(br, "grid_from_store", grid)
    # keep it on THIS PC and off the network: the capacity check lists GitHub
    # runs, which a unit test must never do (2026-09-03)
    monkeypatch.setattr(dj.cap, "plan",
                        lambda tfs, ignore=(): {"local": list(tfs), "cloud": [],
                                                "why": "stubbed"})
    monkeypatch.setattr(dj, "FILES", {"btupdate": {
        "progress": tmp_path / "p.json", "spec": tmp_path / "s.json",
        "pid": tmp_path / "pid", "stop": tmp_path / "STOP",
        "handoff": tmp_path / "HANDOFF"}})

    dj._run_btupdate({"coins": ["CETUS_USDT"], "tfs": ["15m"], "days": 365,
                      "base": 5.0})

    p = json.loads((tmp_path / "p.json").read_text())
    # The KeyError was caught by `_run_backtest` and written here as `failed`,
    # which is the whole assertion. `running` is NOT checked: the heartbeat
    # thread is joined with a 3 s timeout, so on a loaded machine its last beat
    # can land after the terminal write and that flapped in a full-suite run.
    assert not p.get("failed"), p
    assert seen["fresh"] is False, "an update CONTINUES; it never starts over"
    assert seen["coins"] == ["CETUS_USDT"]


def test_every_job_kind_answers_the_handoff_question(monkeypatch, tmp_path):
    """A job kind that declares no handoff file answers False — never raises.
    The check runs once per finished pair, so an exception there kills a run
    that has already measured thousands of pairs."""
    monkeypatch.setattr(dj, "FILES", {
        "btupdate": {"progress": tmp_path / "p.json",
                     "handoff": tmp_path / "HANDOFF"},
        "stratbt": {"progress": tmp_path / "s.json"}})       # no handoff at all
    assert dj.handoff_requested("stratbt") is False
    assert dj.handoff_requested("btupdate") is False
    dj.request_handoff("btupdate")
    assert dj.handoff_requested("btupdate") is True
    dj.clear_handoff("btupdate")
    assert dj.handoff_requested("btupdate") is False
    dj.clear_handoff("stratbt")                              # a no-op, not a raise


def test_every_job_that_runs_the_sweep_declares_a_handoff_file():
    """`_run_backtest_inner` asks for it; whoever runs it must declare it."""
    for kind in ("backtest", "btupdate"):
        assert "handoff" in dj.FILES[kind], kind
