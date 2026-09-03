"""A candle download that loses a pair redoes THAT pair — and names every
pair it could not recover.

Operator, 2026-08-25, reading the bell after a 4,985-pair download:

    39,656,242 bars over 4985 pair(s) · 2 error(s):
    CHILLGUY_USDT 15m: IncompleteRead(183452 bytes read)

    "so you mean if download fails, it wont try again? this is a stupid
     design ... i want 10/10 accuracy on download"

What had happened: MEXC closed one connection after 183,452 bytes of one
kline page. `_run_download` caught it, appended the text, `continue`d. No
retry anywhere between the socket and that `except`. The store ended at
4,983 of 4,985 files, only the FIRST failure was ever written down (the
second — NAORIS_USDT 30m — had to be found by diffing the store against the
spec), and "update" mode walks the store, so a pair missing from the store
could never be fetched again by clicking anything.
"""
import http.client
import json

import pytest

from tradingagents import db_jobs


def _frame(n=1):
    import pandas as pd

    return pd.DataFrame({"Date": pd.to_datetime([1_787_000_000 + 900 * i
                                                for i in range(n)], unit="s"),
                         "Open": [1.0] * n, "High": [1.0] * n,
                         "Low": [1.0] * n, "Close": [1.0] * n,
                         "Volume": [1.0] * n})


@pytest.fixture
def job(monkeypatch, tmp_path):
    """The download job with the network and the store faked out.

    `fails` maps a pair to how many times refresh_candles raises before it
    succeeds (a very large number = never recovers)."""
    from tradingagents import market_sweep as msw, notifications as nt, parquet_store as pqs

    calls, saved, bell = [], [], []
    fails: dict = {}

    def refresh(c, tf, days=365):
        calls.append((c, tf))
        left = fails.get((c, tf), 0)
        if left > 0:
            fails[(c, tf)] = left - 1
            raise http.client.IncompleteRead(b"x" * 183452)
        return _frame(3), 3, "fetch"

    monkeypatch.setattr(msw, "refresh_candles", refresh)
    monkeypatch.setattr(msw, "candle_coverage", lambda: [])
    monkeypatch.setattr(pqs, "save_candles", lambda c, tf, df: saved.append((c, tf)))
    monkeypatch.setattr(nt, "record",
                        lambda kind, title, **kw: bell.append((title, kw)) or 1)
    monkeypatch.setattr(db_jobs, "_stopping", lambda kind: False)
    monkeypatch.setattr(db_jobs, "_pause", lambda seconds: None, raising=False)
    monkeypatch.setattr(db_jobs, "FILES", {
        "download": {"progress": tmp_path / "p.json",
                     "lost": tmp_path / "lost.json"}})
    return {"calls": calls, "saved": saved, "bell": bell, "fails": fails,
            "progress": lambda: json.loads((tmp_path / "p.json").read_text()),
            "lost": lambda: json.loads((tmp_path / "lost.json").read_text())}


def test_a_pair_that_fails_once_is_redone_alone_after_the_others(job):
    """CHILLGUY 15m dies on its first page. The other pairs keep going, then
    CHILLGUY is fetched again — and lands in the store like everyone else."""
    job["fails"][("CHILLGUY_USDT", "15m")] = 1
    db_jobs._run_download({"coins": ["APEX_USDT", "CHILLGUY_USDT", "NAORIS_USDT"],
                           "tfs": ["15m"]})
    assert job["calls"] == [("APEX_USDT", "15m"), ("CHILLGUY_USDT", "15m"),
                            ("NAORIS_USDT", "15m"),
                            ("CHILLGUY_USDT", "15m")], \
        "the failed pair is redone AFTER the rest, not the whole run again"
    assert sorted(job["saved"]) == [("APEX_USDT", "15m"), ("CHILLGUY_USDT", "15m"),
                                    ("NAORIS_USDT", "15m")]
    p = job["progress"]()
    assert p["errors"] == 0 and p["failed"] == []
    assert p["retries"] == 1
    # total counts PAIRS. A retry must never bump it, or the percentage runs
    # backwards the moment a coin fails.
    assert (p["done"], p["total"]) == (3, 3)
    assert p["bars_stored"] == 9
    title, kw = job["bell"][-1]
    assert title == "Download finished" and kw["ok"] is True


def test_a_pair_is_given_up_only_after_every_retry(job):
    job["fails"][("CHILLGUY_USDT", "15m")] = db_jobs.PAIR_RETRIES
    db_jobs._run_download({"coins": ["CHILLGUY_USDT"], "tfs": ["15m"]})
    attempts = job["calls"].count(("CHILLGUY_USDT", "15m"))
    assert attempts == db_jobs.PAIR_RETRIES + 1, \
        "one first try plus PAIR_RETRIES redos"
    assert job["saved"] == [("CHILLGUY_USDT", "15m")]
    assert job["progress"]()["errors"] == 0


def test_a_pair_that_never_recovers_is_named_not_just_counted(job, capsys):
    """Two pairs die for good. Both are named — in the progress file, in the
    bell, and in the job's own log — so nobody has to diff the store against
    the spec to learn the second one was NAORIS_USDT 30m."""
    job["fails"][("CHILLGUY_USDT", "15m")] = 10 ** 6
    job["fails"][("NAORIS_USDT", "30m")] = 10 ** 6
    db_jobs._run_download({"coins": ["APEX_USDT", "CHILLGUY_USDT", "NAORIS_USDT"],
                           "tfs": ["15m", "30m"]})
    p = job["progress"]()
    assert p["errors"] == 2
    assert [f.split(":")[0] for f in p["failed"]] == ["CHILLGUY_USDT 15m",
                                                       "NAORIS_USDT 30m"]
    assert all("IncompleteRead(183452 bytes read)" in f for f in p["failed"])
    assert p["failed_pairs"] == [["CHILLGUY_USDT", "15m"], ["NAORIS_USDT", "30m"]]
    assert p["first_error"].startswith("CHILLGUY_USDT 15m:")
    assert (p["done"], p["total"]) == (6, 6), "a lost pair is still DONE work"
    assert p["retries"] == 2 * db_jobs.PAIR_RETRIES
    # the four pairs that worked are all in the store; the two that did not
    # are not — no half file, no mixture
    assert len(job["saved"]) == 4
    assert ("CHILLGUY_USDT", "15m") not in job["saved"]

    title, kw = job["bell"][-1]
    assert title == "Download finished with errors" and kw["ok"] is False
    assert "2 error(s)" in kw["detail"]
    assert "CHILLGUY_USDT 15m" in kw["detail"] and "NAORIS_USDT 30m" in kw["detail"], \
        "every lost pair is in the bell, not just errors[0]"
    assert kw["meta"]["failed"] == p["failed"]

    out = capsys.readouterr().out
    assert "CHILLGUY_USDT 15m failed (1/%d)" % db_jobs.PAIR_RETRIES in out
    assert "NAORIS_USDT 30m gave up" in out
    # the log line's own timestamp is the operator's format, never strftime's
    import re

    assert re.search(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}[ap]m", out), out


def test_many_lost_pairs_are_summarised_not_dumped_into_the_bell(job):
    coins = [f"C{i}_USDT" for i in range(8)]
    for c in coins:
        job["fails"][(c, "1h")] = 10 ** 6
    db_jobs._run_download({"coins": coins, "tfs": ["1h"]})
    _, kw = job["bell"][-1]
    assert "8 error(s)" in kw["detail"]
    assert "C0_USDT 1h" in kw["detail"] and "C4_USDT 1h" in kw["detail"]
    assert "and 3 more" in kw["detail"]
    assert len(job["progress"]()["failed"]) == 8, "the progress file keeps all of them"


def test_the_pause_before_a_redo_is_real_but_skipped_when_nothing_failed(job, monkeypatch):
    """A redo straight after the failure hits the same bad connection. The
    job waits RETRY_PAUSE_S first — and never waits when nothing failed."""
    waits = []
    monkeypatch.setattr(db_jobs, "_pause", lambda seconds: waits.append(seconds))
    db_jobs._run_download({"coins": ["APEX_USDT"], "tfs": ["15m"]})
    assert waits == []
    job["fails"][("CHILLGUY_USDT", "15m")] = 1
    db_jobs._run_download({"coins": ["CHILLGUY_USDT"], "tfs": ["15m"]})
    assert waits == [db_jobs.RETRY_PAUSE_S]
    assert db_jobs.RETRY_PAUSE_S >= 1.0


def test_update_mode_fetches_the_pairs_the_last_download_lost(job, monkeypatch, tmp_path):
    """"update" walks the STORE. A pair the last download lost is not in the
    store, so before this it could never be fetched again by clicking
    anything. Now the last run's failed_pairs are queued too."""
    from tradingagents import market_sweep as msw

    # This test is about the LOST pairs. `update` also fills pairs the venue
    # LISTS that the store has never seen, so the contract list is pinned out of
    # the way here — that half is covered in test_candle_update_reliability.py.
    monkeypatch.setattr(db_jobs, "live_symbols", lambda *a, **k: None)
    monkeypatch.setattr(msw, "candle_coverage", lambda: [
        {"symbol": "APEX_USDT", "timeframe": "1h"}])
    (tmp_path / "lost.json").write_text(json.dumps({
        "pairs": [["CHILLGUY_USDT", "15m"], ["APEX_USDT", "1h"]]}))
    # what start() leaves on disk the moment the job is launched: a stub
    # with none of the last run's fields. The lost pairs must not live there.
    (tmp_path / "p.json").write_text(json.dumps({
        "running": True, "started": 1787680000, "done": 0, "total": 0,
        "now": "starting"}))
    db_jobs._run_download({"mode": "update"})
    assert job["calls"] == [("APEX_USDT", "1h"), ("CHILLGUY_USDT", "15m")], \
        "the lost pair is added once; a pair already in the store is not doubled"
    p = job["progress"]()
    assert p["errors"] == 0 and p["failed_pairs"] == []
    assert "1 pair(s) the last download lost" in p["note"]
    assert job["lost"]()["pairs"] == [], "recovered: the next update will not ask again"


def test_the_pairs_a_run_gives_up_on_are_written_for_the_next_update(job):
    job["fails"][("NAORIS_USDT", "30m")] = 10 ** 6
    db_jobs._run_download({"coins": ["APEX_USDT", "NAORIS_USDT"], "tfs": ["30m"]})
    assert job["lost"]()["pairs"] == [["NAORIS_USDT", "30m"]]


def test_a_deterministic_failure_is_named_at_once_not_retried(job, monkeypatch):
    """A contract with no Min15 history will have none in three seconds
    either. Redoing it three times costs requests and hides the real answer;
    only a failure of the WIRE earns a redo."""
    from tradingagents import market_sweep as msw
    from tradingagents.dataflows import mexc_futures as fx

    def refresh(c, tf, days=365):
        job["calls"].append((c, tf))
        raise fx.MexcFuturesError("no Min15 candles for GONE_USDT")

    monkeypatch.setattr(msw, "refresh_candles", refresh)
    # GONE_USDT is still LISTED here. That is not a DELISTING — that path needs
    # both halves, the venue's empty answer AND the symbol being absent from
    # the live list (test_candle_update_reliability.py) — but it is not a fault
    # to clear either: see test_update_settles_its_own_errors.py. 25 of the 26
    # "errors" on Sep 02, 2026 were exactly this, and being filed as failures
    # put them back on the queue at every update and kept the panel red.
    monkeypatch.setattr(db_jobs, "live_symbols", lambda *a, **k: {"GONE_USDT"})
    db_jobs._run_download({"coins": ["GONE_USDT"], "tfs": ["15m"]})
    assert job["calls"] == [("GONE_USDT", "15m")], "asked once, never redone"
    p = job["progress"]()
    assert p["retries"] == 0
    assert p["empty"] == ["GONE_USDT 15m"], "named, so it is not a silence"
    assert p["failed"] == [] and p["errors"] == 0
    assert job["lost"]()["pairs"] == [], "and not queued for the retry button"
    assert not p.get("delisted"), (
        "a LISTED contract with no candles is not a delisting")


def test_a_connection_cut_mid_body_counts_as_transient():
    """IncompleteRead is an http.client.HTTPException, not an OSError — the
    supervisor's type list did not know it, so the very error that lost
    CHILLGUY 15m would have read as deterministic."""
    assert db_jobs.is_transient(http.client.IncompleteRead(b"x" * 183452))
    assert db_jobs.is_transient(http.client.RemoteDisconnected("closed"))


def test_a_stop_click_during_the_redo_pass_still_stops(job, monkeypatch):
    job["fails"][("CHILLGUY_USDT", "15m")] = 1
    seen = []

    def stopping(kind):
        seen.append(1)
        return len(seen) > 2          # APEX, CHILLGUY(fail) ... then stop

    monkeypatch.setattr(db_jobs, "_stopping", stopping)
    db_jobs._run_download({"coins": ["APEX_USDT", "CHILLGUY_USDT"], "tfs": ["15m"]})
    p = job["progress"]()
    assert p["stopped"] is True
    assert job["calls"].count(("CHILLGUY_USDT", "15m")) == 1


def test_retry_mode_downloads_exactly_the_lost_pairs_and_nothing_else(job, monkeypatch, tmp_path):
    """The RETRY FAILED button: the pairs the last run gave up on, by
    themselves. Not the store walk of UPDATE, not a re-download."""
    from tradingagents import market_sweep as msw

    monkeypatch.setattr(msw, "candle_coverage", lambda: [
        {"symbol": "APEX_USDT", "timeframe": "1h"}])
    (tmp_path / "lost.json").write_text(json.dumps({
        "pairs": [["CHILLGUY_USDT", "15m"], ["NAORIS_USDT", "30m"],
                  ["CHILLGUY_USDT", "15m"]]}))            # a duplicate is one pair
    db_jobs._run_download({"mode": "retry"})
    assert job["calls"] == [("CHILLGUY_USDT", "15m"), ("NAORIS_USDT", "30m")]
    p = job["progress"]()
    assert (p["done"], p["total"]) == (2, 2) and p["errors"] == 0
    assert p["mode"] == "retry"
    assert "retried 2 lost pair(s)" in p["note"]
    assert job["lost"]()["pairs"] == []


def test_retry_mode_with_nothing_lost_does_nothing_and_says_so(job, tmp_path):
    (tmp_path / "lost.json").write_text(json.dumps({"pairs": []}))
    db_jobs._run_download({"mode": "retry"})
    assert job["calls"] == []
    p = job["progress"]()
    assert (p["done"], p["total"]) == (0, 0)
    assert "nothing to retry" in p["note"]
    title, kw = job["bell"][-1]
    assert title == "Download finished" and "nothing to retry" in kw["detail"]


def test_a_pair_lost_again_on_retry_stays_in_the_lost_file(job, tmp_path):
    (tmp_path / "lost.json").write_text(json.dumps({
        "pairs": [["CHILLGUY_USDT", "15m"], ["NAORIS_USDT", "30m"]]}))
    job["fails"][("NAORIS_USDT", "30m")] = 10 ** 6
    db_jobs._run_download({"mode": "retry"})
    assert job["lost"]()["pairs"] == [["NAORIS_USDT", "30m"]]
    assert job["saved"] == [("CHILLGUY_USDT", "15m")]
