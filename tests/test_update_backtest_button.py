"""UPDATE BACKTEST has to work from the BUTTON, not from a prompt.

Operator, 2026-09-03: *"apply the fix to the button 'update backtest' because i
dont want to fully rely on prompting you here i want to use the backtest
button"*. Everything that went wrong when I ran the update by hand was a
property of the job, not of my typing:

1. it was SEQUENTIAL. `_run_btupdate` looped `run_pair` one pair at a time —
   90 s for the first pair, 4,124 pairs to go — while the BACKTEST button
   beside it used every core. That is why the run that actually did the work
   was the backtest job with `fresh: False`.
2. an EMPTY coin list meant ZERO PAIRS. `[(c, tf) for c in [] ...]` is nothing,
   so clicking UPDATE without hand-picking 1,031 coins ran nothing and reported
   `0/0`.
3. the spec built by hand used BARE coin names, so all 4,124 pairs raised
   `no Min15 candles for CETUS`. `run_pair` takes `CETUS_USDT`.
"""

import tradingagents.db_jobs as dj

PANEL = "webapp/src/components/backtest/JobsPanel.tsx"


def _src(fn) -> str:
    import inspect

    return inspect.getsource(fn)


def test_the_update_runs_the_same_parallel_sweep_as_the_backtest():
    s = _src(dj._run_btupdate)
    assert "_run_backtest" in s, "must delegate to the parallel path"
    assert '"fresh": False' in s, "an update is a CONTINUATION, never a fresh sweep"
    assert 'files_key="btupdate"' in s and 'kind="btupdate"' in s, \
        "it must keep its own progress file, stop flag and bell entry"
    # the old serial loop is gone
    assert "run_pair(" not in s


def test_the_parallel_path_takes_the_job_it_is_running_for():
    import inspect

    for fn in (dj._run_backtest, dj._run_backtest_inner):
        p = inspect.signature(fn).parameters
        assert p["files_key"].default == "backtest"
        assert p["kind"].default == "backtest"
    inner = _src(dj._run_backtest_inner)
    # nothing may be hardcoded to the backtest job, or an update would write
    # over the backtest's progress and answer its stop flag
    assert 'FILES["backtest"]' not in inner
    assert '_stopping("backtest")' not in inner
    assert 'handoff_requested("backtest")' not in inner


def test_an_empty_coin_list_means_every_pair_in_the_store():
    s = _src(dj._run_btupdate)
    assert "stored_symbols()" in s
    assert "if not coins" in s


def test_stored_symbols_are_symbols_not_bare_coins(monkeypatch):
    """`run_pair` derives the coin by stripping `_USDT`; a bare name raises.

    The SOURCE moved on Sep 12, 2026: this patched `candle_coverage`, which
    opened and parsed all 5,235 candle files (1.77 GB) to return names the
    filenames already carry, and made UPDATE sit silent for 9m39s before it
    dispatched anything (RCA-2026-09-12-F). `candle_index` answers the same
    question incrementally. The assertion is unchanged, because the RULE is
    unchanged — symbols, deduped, sorted.
    """
    import tradingagents.market_sweep as msw

    monkeypatch.setattr(msw, "candle_index", lambda *a, **k: {
        "CETUS_USDT-15m": {"bars": 900},
        "BTC_USDT-1h": {"bars": 900},
        "BTC_USDT-4h": {"bars": 900},      # one coin, two frames, one name
    })
    got = dj.stored_symbols()
    assert got == ["BTC_USDT", "CETUS_USDT"], got


def test_stored_symbols_skips_a_pair_that_has_no_candles(monkeypatch):
    """`candle_coverage` skipped these (`if not ts: continue`) and the
    replacement must too: a zero-bar file handed to `run_pair` raises on every
    combination and the coin is counted FAILED."""
    import tradingagents.market_sweep as msw

    monkeypatch.setattr(msw, "candle_index", lambda *a, **k: {
        "GOOD_USDT-1h": {"bars": 500},
        "EMPTY_USDT-1h": {"bars": 0},
    })
    assert dj.stored_symbols() == ["GOOD_USDT"]


def test_the_button_is_clickable_without_picking_a_single_coin():
    p = open(PANEL, encoding="utf-8").read()
    i = p.index('start("btupdate")')
    frag = p[i - 400:i + 400]
    assert "!coins.length" not in frag, \
        "the button was disabled until 1,031 coins were picked by hand"
    assert "UPDATE ALL BACKTESTS" in frag, \
        "the LABEL must say what an empty picker will do (label-must-match-data)"
    assert "!tfs.length" in frag and "upd?.running" in frag


def test_the_button_says_what_it_will_continue():
    p = open(PANEL, encoding="utf-8").read()
    assert "every pair this machine has candles for" in p
