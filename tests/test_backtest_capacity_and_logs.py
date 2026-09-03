"""Use BOTH machines, and show what is pending and what broke.

Operator, 2026-09-03, after asking *"why did you not use github since its
free?"*: *"Apply the fix when clicking the update backtest i want you to detect
if there is a free both in github and machine, if there is error create a
seperate section called logs just like in candles module si i can see what is
pending on my side and what are errors"*.

GitHub had been idle for a whole day while this PC ground through 4,124 pairs,
because nothing ever asked whether it was free. And a backtest that failed on
860 pairs read as `done: 860, rows: 0` with no note, because the screen had
nowhere to show an error.
"""
import inspect
import io

from tradingagents import capacity as cap

PANEL = "webapp/src/components/backtest/JobsPanel.tsx"
LOGS = "webapp/src/components/backtest/LogsPanel.tsx"
PAGE = "webapp/src/app/(admin)/backtest/page.tsx"


def _r(p: str) -> str:
    return io.open(p, encoding="utf-8").read()


# --------------------------------------------------------------- the split
def test_both_free_means_both_run_and_neither_repeats_the_other():
    got = cap.split(["15m", "30m", "1h", "4h", "1d"],
                    to_local=True, to_cloud=True, workers=8)
    assert got["local"] and got["cloud"], "both free must mean both work"
    assert not set(got["local"]) & set(got["cloud"]), \
        "a timeframe on both sides would be measured twice"
    assert set(got["local"]) | set(got["cloud"]) == {"15m", "30m", "1h", "4h", "1d"}


def test_the_heavy_frames_go_to_the_twenty_runners():
    got = cap.split(["15m", "30m", "1h", "4h", "1d"],
                    to_local=True, to_cloud=True, workers=8)
    # 15m is 35,040 bars a year against 1d's 365 — the fleet takes the pain
    assert "15m" in got["cloud"] and "1d" in got["local"]


def test_one_timeframe_is_never_split_into_an_empty_half():
    got = cap.split(["1d"], to_local=True, to_cloud=True, workers=8)
    assert got["cloud"] == ["1d"] and got["local"] == []
    assert "cannot be split" in got["why"]


def test_a_busy_side_gets_nothing():
    busy_cloud = cap.split(["15m", "1d"], to_local=True, to_cloud=False)
    assert busy_cloud["cloud"] == [] and busy_cloud["local"] == ["15m", "1d"]
    busy_local = cap.split(["15m", "1d"], to_local=False, to_cloud=True)
    assert busy_local["local"] == [] and busy_local["cloud"] == ["15m", "1d"]
    neither = cap.split(["15m"], to_local=False, to_cloud=False)
    assert neither["local"] == [] and neither["cloud"] == []
    assert "nothing is free" in neither["why"]


def test_a_running_job_makes_this_pc_busy(monkeypatch):
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "status", lambda k: {"running": k == "backtest",
                                                 "done": 3660, "total": 4124})
    free, why = cap.local_free()
    assert not free and "3,660/4,124" in why


def test_a_queued_run_makes_github_busy(monkeypatch):
    from tradingagents import cloud_sweep as cs

    monkeypatch.setattr(cs, "available", lambda: (True, "me/repo"))
    monkeypatch.setattr(cs, "_runs", lambda slug, limit=5: [
        {"databaseId": 7, "status": "in_progress"}])
    free, why = cap.cloud_free()
    assert not free and "7" in why and "in progress" in why


# ------------------------------------------------------- the button uses it
def test_the_update_job_asks_where_to_run_and_dispatches_the_cloud_half():
    from tradingagents import db_jobs as dj

    s = inspect.getsource(dj._run_btupdate)
    assert "cap.plan(" in s, "the job must ask, not assume this PC"
    assert "cs.dispatch(" in s and 'timeframes=",".join(plan["cloud"])' in s
    # a cloud that refuses must not mean nothing is measured
    assert "GitHub refused the dispatch" in s
    assert '"local": tfs, "cloud": []' in s


def test_the_button_says_where_it_will_run_before_it_is_clicked():
    p = _r(PANEL)
    assert "api.backtestCapacity(" in p
    assert "UPDATE splits it" in p
    assert "cap.runners" in p and "cap.workers" in p
    # DERIVED, never a literal: the reason a side is skipped is the API's own
    assert "cap.local_why" in p and "cap.cloud_why" in p


# ---------------------------------------------------------------- the LOGS
def test_pending_counts_the_store_as_it_is_now(tmp_path, monkeypatch):
    from tradingagents import backtest_logs as bl, market_sweep as msw

    candles, states = tmp_path / "candles", tmp_path / "state"
    candles.mkdir(), states.mkdir()
    for n in ("BTC_USDT-15m", "BTC_USDT-1d", "ETH_USDT-15m"):
        (candles / f"{n}.json").write_text("{}")
    (states / "BTC-15m.json").write_text("{}")      # measured; the other two are not
    monkeypatch.setattr(msw, "CANDLES", candles)
    monkeypatch.setattr(msw, "STATES", states)
    got = bl.pending(force=True)
    assert got["stored"] == 3 and got["count"] == 2 and got["measured"] == 1
    assert got["by_timeframe"] == {"1d": 1, "15m": 1}
    named = {(x["symbol"], x["timeframe"]) for x in got["pairs"]}
    assert named == {("BTC_USDT", "1d"), ("ETH_USDT", "15m")}


def test_every_failed_pair_is_named_not_counted(tmp_path, monkeypatch):
    import json

    from tradingagents import backtest_logs as bl, db_jobs as dj

    f = tmp_path / "p.json"
    f.write_text(json.dumps({"failed": ["CETUS_USDT 15m: no Min15 candles",
                                        "PI_USDT 1h: klines returned 0 bars"],
                             "finished": 1756800000}))
    monkeypatch.setitem(dj.FILES["btupdate"], "progress", f)
    got = bl._job_errors("btupdate")
    assert [x["pair"] for x in got] == ["CETUS_USDT 15m", "PI_USDT 1h"]
    assert got[0]["text"] == "no Min15 candles"
    assert got[0]["where"] == "this PC"


def test_a_shard_that_never_reported_is_not_counted_as_clean():
    p = _r(LOGS)
    assert "silent" in p, "a silent shard's failures cannot be read"
    assert "no error has been named by this PC" in p
    assert "so its failures are unknown" in p


def test_the_cloud_shard_names_what_it_lost():
    sh = _r(".github/scripts/sweep_shard.py")
    pr = _r(".github/scripts/progress.py")
    assert "failed=failed" in sh, "the done report must carry the names"
    assert '"failed":' in pr, "the published payload must carry them"
    # a runner killed at six hours never reaches the done report
    assert "lost so far" in sh


def test_the_logs_section_exists_and_is_on_the_page():
    page = _r(PAGE)
    assert "LogsPanel" in page
    p = _r(LOGS)
    assert ">LOGS<" in p
    assert "api.backtestLogs()" in p
    # counts are labels DERIVED from the payload, never literals
    assert "pending" in p and "error" in p


def test_the_update_job_does_not_count_itself_as_the_busy_machine(monkeypatch):
    """`_run_btupdate` asks from INSIDE the update job.

    Its own pid file and progress file both say "running". Without excluding
    itself the job decides this PC is busy and hands every timeframe to
    GitHub — leaving the machine it is running on with nothing to do.
    """
    from tradingagents import db_jobs as dj

    monkeypatch.setattr(dj, "status",
                        lambda k: {"running": k == "btupdate", "done": 0, "total": 0})
    free, why = cap.local_free(ignore=("btupdate",))
    assert free, why
    assert not cap.local_free()[0], "without the exclusion it must look busy"
    # and the job passes it
    assert 'ignore=("btupdate",)' in inspect.getsource(dj._run_btupdate)


def test_an_unreadable_job_kind_is_idle_not_busy(monkeypatch):
    """Unknown must never be the reason this machine measures nothing."""
    from tradingagents import db_jobs as dj

    def boom(kind):
        raise KeyError(kind)

    monkeypatch.setattr(dj, "status", boom)
    assert cap.local_free()[0] is True
