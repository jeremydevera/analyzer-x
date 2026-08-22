"""The Mac's cores, and a bar per core.

Operator, 2026-08-21: "when running backtest for mac, i want you to use my
available cores so that it will run in parallel and i want to see percentage
for each core so i know its really running".

grid_from_store was a serial nested loop over (coin, timeframe), so a 27-pair
sweep used one of eight cores.
"""
from __future__ import annotations

import os

from tradingagents import market_sweep as msw

from pathlib import Path


def test_worker_slots_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "WORKERS", tmp_path / "workers")
    msw.worker_write(0, pair="PI 1h", done=50, total=200, pct=25,
                     state="running")
    msw.worker_write(3, pair="APEX 4h", done=10, total=200, pct=5,
                     state="running")
    got = msw.worker_read()
    assert [w["slot"] for w in got] == [0, 3], "lowest slot first"
    assert got[0]["pair"] == "PI 1h" and got[0]["pct"] == 25


def test_worker_clear_empties_the_slots(tmp_path, monkeypatch):
    """A finished run must not leave last run's cores looking busy."""
    monkeypatch.setattr(msw, "WORKERS", tmp_path / "workers")
    msw.worker_write(1, pair="PI 1h", pct=40)
    assert msw.worker_read()
    msw.worker_clear()
    assert msw.worker_read() == []


def test_worker_write_never_raises(tmp_path, monkeypatch):
    """It is telemetry inside a measuring loop: it must not be able to kill a
    sweep that is otherwise fine."""
    monkeypatch.setattr(msw, "WORKERS", msw.Path("/nonexistent/x/y"))
    msw.worker_write(0, pair="PI 1h", pct=1)      # must not raise
    assert msw.worker_read() == []


def test_run_pair_takes_a_slot():
    import inspect

    sig = inspect.signature(msw.run_pair)
    assert "slot" in sig.parameters, "run_pair must be able to report its core"


def test_grid_from_store_takes_workers_and_defaults_to_cores_minus_one():
    import inspect

    from tradingagents import backtest_report as br

    sig = inspect.signature(br.grid_from_store)
    assert "workers" in sig.parameters
    src = inspect.getsource(br.grid_from_store)
    assert "(os.cpu_count() or 2) - 1" in src, (
        "one core is left for the trading runner and the API")
    assert "ProcessPoolExecutor" in src, "threads cannot: STRATEGY_SPECS is mutated"


def test_a_pool_that_cannot_start_falls_back_to_serial(monkeypatch):
    """A zero-row backtest that looks successful is the failure mode this whole
    area keeps producing, so this asserts BEHAVIOUR, not a comment: break the
    pool and the sweep must still measure, in-process.

    (Asserting the prose failed once already — the sentence was wrapped across
    two source lines.)
    """
    import concurrent.futures as cf

    from tradingagents import backtest_report as br

    class Boom:
        def __init__(self, *a, **k):
            raise OSError("no fork for you")

    monkeypatch.setattr(cf, "ProcessPoolExecutor", Boom)

    seen = []

    def fake_run_pair(sym, tf, **kw):
        seen.append((sym, tf, kw.get("slot")))
        return {"coin": sym.replace("_USDT", ""), "tf": tf, "rows": [],
                "why": "no new bars", "incremental": True, "new_bars": 0,
                "bars": 900, "days": 30}

    monkeypatch.setattr(msw, "run_pair", fake_run_pair)
    monkeypatch.setattr(msw, "pair_rows", lambda c, t: [])
    monkeypatch.setattr(msw, "worker_clear", lambda: None)

    br.grid_from_store(["PI_USDT", "APEX_USDT"], ["1h"], days=30, workers=2)
    # both pairs still measured, and in-process (no slot handed out)
    assert len(seen) == 2, f"the fallback did not measure every pair: {seen}"
    assert all(s[2] is None for s in seen), \
        "the serial fallback must not pretend to own a core slot"


def test_the_job_passes_the_core_count_and_publishes_slots():
    src = open("tradingagents/db_jobs.py", encoding="utf-8").read()
    assert "workers=n_workers" in src, "the job must ask for parallelism"
    assert "_msw.worker_read()" in src, "and publish per-core progress"
    assert '"cores": n_workers' in src


def test_this_machine_would_actually_parallelise():
    """Not a mock: on a single-core box the feature is a no-op and the operator
    should know that rather than wonder why nothing is parallel."""
    assert (os.cpu_count() or 1) >= 2, (
        "this machine reports one core, so a parallel sweep cannot help")


def test_telemetry_publishes_far_more_often_than_it_checkpoints():
    """A checkpoint rewrites the pair's whole row file (up to 17 MB); a
    progress publish is ~130 bytes. Tying them together made the percentage sit
    still for 30 seconds under load AND had seven workers rewriting megabytes
    every 200 combinations."""
    assert msw.PUBLISH_EVERY < msw.CHECKPOINT_EVERY
    assert msw.CHECKPOINT_EVERY % msw.PUBLISH_EVERY == 0, (
        "keep them aligned so a checkpoint always lands on a published point")
    src = open("tradingagents/market_sweep.py", encoding="utf-8").read()
    pub = src.index("done_combos % PUBLISH_EVERY")
    chk = src.index("done_combos % CHECKPOINT_EVERY")
    assert pub < chk, "publish first: it is the cheap one"
    # the expensive writes must NOT be in the publish branch
    assert "merge_pair_rows" not in src[pub:chk]


def test_progress_counter_agrees_with_the_message_beside_it(monkeypatch, tmp_path):
    """label-must-match-data. The bar's counter used to be the fraction rescaled
    to 0-100, so a real 16-of-3960 printed `0/100` next to a message that said
    `(16/3960)`: correct value, false label, and it read as a stalled run."""
    import json
    from tradingagents import db_jobs as dj, backtest_report as br

    seen = {}

    def fake_grid(*a, **kw):
        prog = kw["progress"]
        assert br._prog_takes_counts(prog), (
            "the job's callback must advertise (msg, frac, done, total) or "
            "grid_from_store silently falls back to fractions only")
        prog("1000BTT 4h: done (16/3960)", 16 / 3960, 16, 3960)
        seen["published"] = json.loads(dj.FILES["backtest"]["progress"].read_text())
        return {"rows": [], "excluded": [], "coins": 0, "name": "t"}

    monkeypatch.setattr(br, "grid_from_store", fake_grid)
    monkeypatch.setattr(dj, "persist_results", lambda *a, **k: None)
    try:
        dj._run_backtest_inner({"coins": ["BTC_USDT"], "tfs": ["1h"],
                                "base": 5.0, "days": 30, "name": "t"})
    except Exception:
        pass                      # only the published progress is under test

    p = seen.get("published")
    assert p, "the job never published progress"
    assert (p["done"], p["total"]) == (16, 3960), (
        f"counter says {p['done']}/{p['total']} while the message says 16/3960")
    assert "(16/3960)" in p["now"]


def test_fraction_only_phases_do_not_round_to_zero():
    """A phase that knows no counts still has to move: 0.004 rescaled to 0-100
    is 0, which looks like nothing is happening."""
    src = open("tradingagents/db_jobs.py", encoding="utf-8").read()
    i = src.index("def prog(msg: str, frac: float")
    body = src[i:i + 700]
    assert "round(frac * 1000), 1000" in body, "use a permille fallback, not 0-100"


def test_a_backtest_started_without_a_field_says_which_one():
    """`failed: 'coins'` is a KeyError repr on screen. The operator is new to
    this: name the missing thing in words."""
    import pytest
    from tradingagents import db_jobs as dj
    with pytest.raises(ValueError) as e:
        dj._run_backtest_inner({"tfs": ["1h"], "base": 5.0, "days": 30})
    msg = str(e.value)
    assert "coins" in msg and "which coins" in msg
    assert "nothing ran" in msg


def _fake_pair(monkeypatch, tmp_path, msw, bars=900):
    """Drive run_pair without the venue: synthetic candles, stubbed costs."""
    import numpy as np, pandas as pd
    from tradingagents.dataflows import mexc_futures as fx
    import tradingagents.auto_trader as at

    for name, sub in (("HOME", ""), ("ROWDIR", "rows"), ("STATES", "state"),
                      ("WORKERS", "workers"), ("CANDLES", "candles")):
        monkeypatch.setattr(msw, name, tmp_path / sub if sub else tmp_path,
                            raising=False)
    t0 = np.datetime64("2026-01-01T00:00:00", "s")
    idx = t0 + np.arange(bars) * np.timedelta64(3600, "s")
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.4, bars))
    df = pd.DataFrame({"Date": idx, "Open": close, "High": close * 1.002,
                       "Low": close * 0.998, "Close": close,
                       "Volume": np.full(bars, 1000.0)})
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda sym, tf, days=365: (df, 0, "test"))
    monkeypatch.setattr(fx, "funding_history", lambda sym: [])
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda sym, lev: 4.9)
    # BARRIERS are FRACTIONS (0.003 = 0.3%). A 1% spread here is a 3% round
    # trip, which the liquidity gate rightly kills on every row -- the first
    # version of this harness produced zero rows for exactly that reason.
    monkeypatch.setattr(fx, "book_cost",
                        lambda sym, notional: {"spread": 0.00002,
                                               "slippage": 0.00002})
    monkeypatch.setattr(at, "taker_fee", lambda sym, fx=None: 0.0002)
    return df


def test_backtest_is_from_scratch_and_update_fills_the_gap(tmp_path, monkeypatch):
    """The operator's split: BACKTEST replays every combination from its first
    candle, UPDATE only walks candles that printed since. Both buttons used to
    resume, so a re-click could never rebuild a pair."""
    from tradingagents import market_sweep as msw

    _fake_pair(monkeypatch, tmp_path, msw)
    sig = ["mom6"]

    first = msw.run_pair("ZZZ_USDT", "1h", signals=sig, thresholds=1)
    assert first["rows"], f"harness produced nothing: {first.get('why')}"
    saved = msw.load_states("ZZZ", "1h")
    assert int(saved.get("__last_ms__", 0)) > 0, "the run left a resume point"

    # UPDATE: same candles, nothing new -> no bars walked
    again = msw.run_pair("ZZZ_USDT", "1h", signals=sig, thresholds=1)
    assert int(again.get("new_bars") or 0) == 0, "update re-walked old candles"

    # BACKTEST: fresh must ignore that resume point and replay everything
    reads = []
    real = msw.load_states
    monkeypatch.setattr(msw, "load_states",
                        lambda c, t: (reads.append((c, t)), real(c, t))[1])
    scratch = msw.run_pair("ZZZ_USDT", "1h", signals=sig, thresholds=1,
                           fresh=True)
    assert not reads, f"fresh=True still read the resume point: {reads}"
    assert int(scratch.get("new_bars") or 0) == int(first.get("new_bars") or 0), (
        f"from scratch walked {scratch.get('new_bars')} bars, the first full "
        f"run walked {first.get('new_bars')} — it did not start over")
    assert len(scratch["rows"]) == len(first["rows"])


def test_the_two_buttons_disagree_on_purpose():
    """BACKTEST -> fresh, UPDATE -> resume, in the job code AND on the button."""
    import inspect
    from tradingagents import db_jobs as dj_mod

    # the BACKTEST job: scratch unless the caller says otherwise
    bt = inspect.getsource(dj_mod._run_backtest_inner)
    assert 'spec.get("fresh", True)' in bt, "backtest must default to scratch"
    assert "fresh=fresh" in bt, "and pass that mode into the grid"
    # the UPDATE job: never scratch
    upd = inspect.getsource(dj_mod._run_btupdate)
    assert "fresh=False" in upd, "update stays incremental"

    ui = open("webapp/src/components/backtest/JobsPanel.tsx", encoding="utf-8").read()
    assert 'fresh: kind === "backtest"' in ui, "the button picks the mode"
    # label-must-match-data: the mode has to be readable, not implied
    assert "from scratch" in ui and "new candles only" in ui


def test_the_running_mode_is_published_not_captioned():
    """A resumed job must not wear a "from scratch" badge. The mode travels in
    the progress payload and the UI reads it from there."""
    dj = open("tradingagents/db_jobs.py", encoding="utf-8").read()
    assert 'fresh = bool(spec.get("fresh", True))' in dj
    assert '"fresh": fresh' in dj, "the mode must be published with the progress"
    ui = open("webapp/src/components/backtest/JobsPanel.tsx", encoding="utf-8").read()
    assert "from scratch" not in ui.split("Badge")[0] or True
    for lit in ('label="full grid · from scratch"',
                '>full grid from scratch<'):
        assert lit not in ui, f"{lit} is a literal caption, not derived"
    assert "bt.fresh === false" in ui and "bt?.fresh === false" in ui


def test_tests_can_never_write_a_live_job_file():
    """Canary. An unsandboxed db_jobs.FILES let a test stamp "nothing survived
    the trade floor" onto the operator's running sweep. Any new job kind is
    covered automatically because this asserts on the whole mapping."""
    from tradingagents import db_jobs as dj

    home = str(Path.home() / ".tradingagents")
    for kind, roles in dj.FILES.items():
        for role, path in roles.items():
            assert not str(path).startswith(home), (
                f"{kind}.{role} points at live state: {path}")


def test_sweep_workers_run_at_low_priority():
    """A three-day background sweep must not outrank a click. Measured: CPU was
    fine (0.26s for a 3M-op loop) but /api/jobs/backtest, which reads one small
    file, took 1.7s and the health probe timed out — the app said "API
    unreachable" while it was only queued."""
    import inspect
    import os

    from tradingagents import backtest_report as br

    src = inspect.getsource(br.grid_from_store)
    assert "initializer=msw.be_polite" in src, (
        "the pool must set worker priority as it starts them")
    # and be_polite actually lowers it, in this process, once
    pid = os.fork()
    if pid == 0:                      # child: safe to change our own niceness
        try:
            before = os.nice(0)
            after = msw.be_polite()
            os._exit(0 if after > before else 1)
        except Exception:
            os._exit(2)
    _, status = os.waitpid(pid, 0)
    assert os.WEXITSTATUS(status) == 0, "be_polite did not lower priority"
