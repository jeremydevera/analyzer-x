"""UPDATE CANDLES settles both failure kinds by itself, with nobody prompting.

Operator, 2026-09-03: *"from the errors you got can you apply the fix when
updating candles because i want to fully use the ui instead of prompting
here"*.

The Sep 02, 2026 update of all 5,117 pairs ended "26 still lost", and neither
kind of loss needed a person:

  * ENPHSTOCK 1d raised ``JSONDecodeError: Expecting value: line 1 column 1
    (char 0)`` — MEXC answered with an EMPTY BODY. A second attempt gets the
    real thing, but ``json.JSONDecodeError`` is a ValueError carrying none of
    the transient marks, so ``is_transient`` said False: the run reported
    ``retries: 0`` and filed the pair for a human to press a button about.
  * The other 25 are five contracts MEXC LISTS and serves no candles for
    (AJINOMOTOSTOCK, CP, FASTRETAILSTOCK, SHINETSUSTOCK, TAIYOYUDENSTOCK ×
    five timeframes). ``looks_gone`` recognised the venue's answer, but the
    branch acting on it also required ``is_delisted`` — and these ARE listed —
    so they fell through to ``failed``, went onto ``lost.json``, and every
    later update re-queued them, failed again and kept the panel red. Which is
    word for word what ``is_delisted``'s own docstring was written about.

They are not dropped from the work: ``update_pairs`` still queues every pair
the store lacks, so each update attempts them once. Only the FILING changes.
"""
import json

from tradingagents import db_jobs as dj


def _progress() -> dict:
    return json.loads(dj.FILES["download"]["progress"].read_text(encoding="utf-8"))


def _lost() -> dict:
    return json.loads(dj.FILES["download"]["lost"].read_text(encoding="utf-8"))


def _download(monkeypatch, refresh, live, coins, tfs):
    from tradingagents import market_sweep as msw, parquet_store as pqs

    monkeypatch.setattr(dj, "RETRY_PAUSE_S", 0)
    monkeypatch.setattr(dj, "live_symbols", lambda *a, **k: live)
    monkeypatch.setattr(msw, "refresh_candles", refresh)
    monkeypatch.setattr(pqs, "save_candles", lambda *a, **k: None)
    dj._run_download({"mode": "download", "coins": coins, "tfs": tfs})


def _blank_frame():
    import pandas as pd

    return pd.DataFrame({"Date": [], "Open": [], "High": [],
                         "Low": [], "Close": [], "Volume": []})


# ----------------------------------------------------- 1. an empty body is weather

def test_an_empty_body_is_worth_another_go():
    """The exact exception ENPHSTOCK 1d raised, and how it arrives wrapped."""
    assert dj.is_transient(json.JSONDecodeError("Expecting value", "", 0))
    assert dj.is_transient(RuntimeError(
        "funding history is incomplete: page 2 failed "
        "(Expecting value: line 1 column 1 (char 0))"))
    assert dj.is_transient(RuntimeError("IncompleteRead(183452 bytes read)"))
    assert dj.is_transient(ValueError("Unterminated string starting at"))
    assert dj.is_transient(ValueError("Unexpected end of data"))


def test_a_real_fault_is_still_never_retried():
    """Widening `is_transient` must not turn every mistake into weather — a
    redo of a deterministic failure is three wasted attempts per pair."""
    assert not dj.is_transient(ValueError("unknown timeframe 7m"))
    assert not dj.is_transient(KeyError("Min15"))
    assert not dj.is_transient(RuntimeError("no Min15 candles for CP_USDT"))


def test_a_transient_failure_is_redone_inside_the_run(monkeypatch):
    """ENPHSTOCK's kind. The operator must never see it on screen."""
    calls = {"n": 0}

    def flaky(sym, tf, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return _blank_frame(), 7, "api"

    _download(monkeypatch, flaky, ["ENPHSTOCK_USDT"], ["ENPHSTOCK_USDT"],
              ["1d"])

    assert calls["n"] == 2, "it must have tried again by itself"
    got = _progress()
    assert got["retries"] == 1
    assert got["errors"] == 0 and got["failed"] == []
    assert got["bars_stored"] == 7
    assert _lost()["pairs"] == [], "nothing left for the operator to press"


# ------------------------------------ 2. "the venue has nothing" is not a fault

def test_the_venues_empty_answer_is_recognised():
    assert dj.looks_gone("no Min15 candles for AJINOMOTOSTOCK_USDT")
    assert dj.looks_gone("no Day1 candles for CP_USDT")
    assert dj.looks_gone("klines returned 0 bars")
    # and one bad minute on a live pair is NOT that
    assert not dj.looks_gone("timed out")
    assert not dj.looks_gone("connection reset by peer")


def test_a_listed_pair_with_no_candles_is_named_not_queued_as_lost(monkeypatch):
    """The 25. Named, so it is not a silence — and OFF the retry list, or
    every later update re-queues it and the panel never goes green."""
    def nothing(sym, tf, **kw):
        raise RuntimeError(f"no Min15 candles for {sym}")

    # LISTED: this is what made the old branch fall through to `failed`
    _download(monkeypatch, nothing, ["AJINO_USDT"], ["AJINO_USDT"], ["15m"])

    got = _progress()
    assert got["errors"] == 0, "not an error: the venue has nothing to give"
    assert got["failed"] == []
    assert got["failed_pairs"] == [], "and NOTHING on the retry list"
    assert got["empty"] == ["AJINO_USDT 15m"], "but NAMED"
    assert got["delisted"] == []
    assert "serves no candles" in got["note"]
    assert _lost()["pairs"] == []


def test_a_delisted_contract_still_takes_the_delisted_path(monkeypatch):
    """Both branches share a condition now; the distinction must survive."""
    def nothing(sym, tf, **kw):
        raise RuntimeError(f"no Min15 candles for {sym}")

    _download(monkeypatch, nothing, ["SOMETHINGELSE_USDT"], ["MEZO_USDT"],
              ["15m"])

    got = _progress()
    assert got["delisted"] == ["MEZO_USDT 15m"]
    assert got["empty"] == []
    assert got["errors"] == 0 and got["failed_pairs"] == []


def test_an_unreadable_contract_list_never_makes_a_pair_delisted(monkeypatch):
    """`is_delisted` answers False when it cannot ask, so a pair the venue
    serves nothing for is `empty`, never wrongly called delisted."""
    def nothing(sym, tf, **kw):
        raise RuntimeError(f"no Day1 candles for {sym}")

    # live=None: the venue could not be asked
    _download(monkeypatch, nothing, None, ["CP_USDT"], ["1d"])

    got = _progress()
    assert got["delisted"] == []
    assert got["empty"] == ["CP_USDT 1d"]


# ------------------------------------------- 3. a real loss is still a real loss

def test_a_pair_it_genuinely_lost_is_still_named_and_still_queued(monkeypatch):
    """The point is not to hide failures — it is to stop filing non-failures."""
    def dead(sym, tf, **kw):
        raise TimeoutError("timed out")

    _download(monkeypatch, dead, ["FLAKY_USDT"], ["FLAKY_USDT"], ["15m"])

    got = _progress()
    assert got["errors"] == 1
    assert got["failed"] and got["failed"][0].startswith("FLAKY_USDT 15m:")
    assert got["failed_pairs"] == [["FLAKY_USDT", "15m"]]
    assert got["retries"] == dj.PAIR_RETRIES, "it tried before giving up"
    assert got["empty"] == [] and got["delisted"] == []
    assert _lost()["pairs"] == [["FLAKY_USDT", "15m"]], "the button gets it"


def test_the_bell_says_how_many_pairs_the_venue_serves_nothing_for(monkeypatch):
    """25 of 26 "errors" were this. If the run does not say so, the operator
    reads 26 problems where there is one."""
    from tradingagents import notifications as nt

    def nothing(sym, tf, **kw):
        raise RuntimeError(f"no Min15 candles for {sym}")

    _download(monkeypatch, nothing, ["A_USDT", "B_USDT"],
              ["A_USDT", "B_USDT"], ["15m"])

    row = nt.recent(limit=1, kind="download")[0]
    assert row["meta"]["empty"] == ["A_USDT 15m", "B_USDT 15m"]
    assert row["meta"]["errors"] == 0
    assert "2 pair(s) the venue serves no candles for" in row["detail"]
    assert row["ok"] is True
