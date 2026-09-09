"""PENDING = what BROKE, and it stays on the books until it is fixed.

Operator, 2026-09-09:

    "pending only means these are the candles that had problem during the
     update candles or download candle, resolve mean you will restart or
     resume where it crash / same as on backtest"

Before this, neither count meant that:

* CANDLES said 5,095 — almost every stored pair, because "behind" measures the
  CLOCK. It went 0 at 10:55pm to 5,095 by 9:33am with nothing failing.
* BACKTEST said 117 — pairs with no measurement file, whether a run had ever
  tried them or not.

And the real failures had nowhere durable to live: `db_download.lost.json` is
rewritten at the end of EVERY download ("a clean run empties it"), so a
whole-market run's losses vanished the moment somebody downloaded one coin.

Bugs the harddev loop found here before any of this ran, each with a test:

* ROUND 1 — the sweep records `CETUS_USDT` while `collect_into_store` clears
  `CETUS`. Nothing would ever come off the books: every landed pair would stay
  pending for ever.
* ROUND 3 — the resolve route reported `pending: 0` while dispatching twenty
  machines for one failed pair, because the success response still carried the
  never-measured tally.
"""
import pytest

from tradingagents import pending_ledger as pl


@pytest.fixture(autouse=True)
def _own_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "STATE_DIR", tmp_path)


def test_a_failure_goes_on_the_books_named():
    pl.record("candles", [("AAA_USDT", "15m", "IncompleteRead(183452 bytes)")])
    got = pl.pending("candles")
    assert len(got) == 1
    assert got[0]["symbol"] == "AAA_USDT" and got[0]["timeframe"] == "15m"
    # NAMED, never a bare count (CLAUDE.md)
    assert "IncompleteRead" in got[0]["why"]


def test_a_success_takes_it_off():
    pl.record("backtest", [("AAA_USDT", "1h", "worker: boom")])
    assert pl.count("backtest") == 1
    assert pl.clear("backtest", [("AAA_USDT", "1h")]) == 1
    assert pl.count("backtest") == 0


def test_the_two_spellings_of_a_pair_are_one_pair():
    """ROUND 1. The sweep holds `CETUS_USDT`; `collect_into_store` and the row
    files hold `CETUS`. Recorded under one and cleared under the other, a
    landed pair would stay pending for ever."""
    pl.record("backtest", [("CETUS_USDT", "4h", "worker: boom")])
    assert pl.clear("backtest", [("CETUS", "4h")]) == 1, \
        "the bare coin must clear the _USDT entry"
    assert pl.count("backtest") == 0

    pl.record("backtest", [("CETUS", "4h", "worker: boom")])
    assert pl.pending("backtest")[0]["symbol"] == "CETUS_USDT", \
        "one spelling on the books, whichever the caller used"


def test_the_books_survive_a_later_unrelated_run():
    """`db_download.lost.json` is rewritten by every download, so a
    whole-market run's losses died when someone fetched one coin."""
    pl.record("candles", [("AAA_USDT", "15m", "boom")])
    # a later run succeeds on something else entirely
    pl.clear("candles", [("ZZZ_USDT", "1d")])
    assert pl.count("candles") == 1, "an unrelated success must not clear it"


def test_repeated_failures_are_counted_not_duplicated():
    """"failed once yesterday" and "failed on every run for a week" are
    different problems."""
    for _ in range(3):
        pl.record("candles", [("AAA_USDT", "15m", "boom")])
    rows = pl.pending("candles")
    assert len(rows) == 1
    assert rows[0]["fails"] == 3


def test_the_first_seen_time_is_kept():
    pl.record("candles", [("AAA_USDT", "15m", "boom")], now=1000.0)
    pl.record("candles", [("AAA_USDT", "15m", "boom again")], now=2000.0)
    row = pl.pending("candles")[0]
    assert row["first"] == 1000.0 and row["last"] == 2000.0
    assert row["why"] == "boom again", "the newest reason is the useful one"


def test_worst_first():
    pl.record("candles", [("OLD_USDT", "15m", "boom")], now=100.0)
    for _ in range(5):
        pl.record("candles", [("BAD_USDT", "1h", "boom")], now=200.0)
    got = pl.pending("candles")
    assert got[0]["symbol"] == "BAD_USDT", "five failures outrank one"


def test_the_two_kinds_are_separate():
    pl.record("candles", [("AAA_USDT", "15m", "boom")])
    assert pl.count("backtest") == 0
    pl.record("backtest", [("BBB_USDT", "1h", "boom")])
    assert pl.count("candles") == 1 and pl.count("backtest") == 1


def test_an_unknown_kind_is_refused_loudly():
    """A typo'd kind must not silently write a file nothing reads."""
    with pytest.raises(ValueError):
        pl.path("candels")


def test_a_corrupt_file_reads_as_empty_not_a_crash():
    pl.path("candles").write_text("not json")
    assert pl.pending("candles") == []
    # and it can still be written
    pl.record("candles", [("AAA_USDT", "15m", "boom")])
    assert pl.count("candles") == 1


def test_rubbish_input_is_skipped_not_fatal():
    assert pl.record("candles", [None, (), ("A_USDT",), ("", "15m", "x")]) == 0
    assert pl.count("candles") == 0
    assert pl.clear("candles", [None, ()]) == 0


def test_summary_names_every_pair():
    pl.record("candles", [("AAA_USDT", "15m", "boom"),
                          ("BBB_USDT", "1h", "timeout")])
    got = pl.summary("candles")
    assert got["count"] == 2
    names = {(p["symbol"], p["timeframe"]) for p in got["pairs"]}
    assert names == {("AAA_USDT", "15m"), ("BBB_USDT", "1h")}
    # the dates go through the one formatter (CLAUDE.md)
    assert got["pairs"][0]["first"] and "," in got["pairs"][0]["first"]


# ------------------------------------------------ who fills and clears it
def test_the_download_records_failures_and_clears_successes():
    import inspect

    from tradingagents import db_jobs as dj

    src = inspect.getsource(dj._run_download)
    assert '_pl.clear("candles", ok_pairs)' in src
    assert '_pl.record("candles"' in src
    # cleared FIRST, so a pair that failed then succeeded inside one run (a
    # redo that worked) does not end the run on the books
    assert src.index('_pl.clear("candles"') < src.index('_pl.record("candles"')


def test_the_sweep_records_failures_and_clears_successes():
    import inspect

    from tradingagents import backtest_report as br

    src = inspect.getsource(br.grid_from_store)
    assert '_ledger("clear"' in src and '_ledger("record"' in src


def test_the_collector_clears_what_it_landed():
    import inspect

    from tradingagents import cloud_sweep as cs

    src = inspect.getsource(cs.collect_into_store)
    assert '_pl.clear("backtest", sorted(written))' in src


def test_a_fleet_loss_lands_on_the_books():
    """A shard's named losses went to the LOGS panel only, so a pair the cloud
    gave up on was invisible to RESOLVE and no button would retry it."""
    import inspect

    from tradingagents import backtest_logs as bl

    # `_read_cloud_errors` is where the shard rows are parsed — `_cloud_errors`
    # is the cached wrapper in front of it.
    src = inspect.getsource(bl._read_cloud_errors)
    assert '_pl.record("backtest", on_books' in src


def test_no_writer_can_take_the_job_down():
    """Bookkeeping must never lose a measurement that already succeeded."""
    import inspect

    from tradingagents import backtest_report as br, cloud_sweep as cs, db_jobs as dj

    for fn in (dj._run_download, br.grid_from_store, cs.collect_into_store):
        src = inspect.getsource(fn)
        # EVERY use, not just the first. `_run_download` READS the ledger to
        # build the RESOLVE queue and WRITES it at the end; the read was
        # unguarded and would have killed the whole job before it fetched a
        # single pair — this test only found it once it stopped checking the
        # first occurrence alone (harddev round 4).
        uses = [k for k in range(len(src)) if src.startswith("pending_ledger", k)]
        assert uses, f"{fn.__name__} no longer touches the ledger"
        for i in uses:
            assert "except Exception" in src[i:i + 1200], \
                f"{fn.__name__} has an unguarded ledger use"
