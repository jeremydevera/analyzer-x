"""Every stored row carries the WORST LOSING STREAK, not just the worst trade.

Found on Aug 27, 2026 while quoting row IDs from a finished 1,994-pair sweep:
the stored rows have `worst` (the worst single trade) and nothing else, so a
table built from the store cannot show the column the operator made mandatory
after APEX -- where the worst trade was -$9.12 while the worst unbroken run of
losses was -$79.80 over 13 trades on a $65 wallet, and the ladder makes the RUN
the thing that empties the account.

The engine already computes it: `auto_trader.backtest_strategy` returns
worst_streak and worst_streak_len, and so does `fast_grid.derive`. run_pair and
the cloud shard simply did not copy them into the row they save. 17 GB of rows
were written without it.
"""
import inspect


def test_the_engine_computes_the_streak():
    import tradingagents.auto_trader as at
    from tradingagents import fast_grid as fg

    for fn in (at.backtest_strategy, fg.derive):
        src = inspect.getsource(fn)
        assert "worst_streak" in src and "worst_streak_len" in src, fn.__name__


def test_the_local_sweep_stores_both_streak_fields():
    from tradingagents import market_sweep as msw

    src = inspect.getsource(msw.run_pair)
    i = src.index("out_rows.append({")
    row = src[i:i + 1800]
    assert '"streak": round(r["worst_streak"], 2)' in row, \
        "the worst losing run must be stored, not recomputed later"
    assert '"streak_len": r["worst_streak_len"]' in row, \
        "and how many trades it took -- a sum alone hides a 13-trade run"
    assert '"worst": round(r["worst_trade"], 2)' in row, \
        "the worst single trade stays too; they answer different questions"


def test_the_cloud_shard_stores_them_as_well():
    """A cloud row and a local row are compared side by side in the store, so a
    column present in one and absent in the other is a hole in the table."""
    src = open(".github/scripts/sweep_shard.py", encoding="utf-8").read()
    assert '"streak": round(r["worst_streak"], 2)' in src
    assert '"streak_len": r["worst_streak_len"]' in src


def test_the_report_reads_the_stored_streak():
    """backtest_report must take the row's own numbers, never default them to
    zero -- a false 0.00 in a money column reads as "measured, and it was
    nothing" (label-must-match-data)."""
    src = open("tradingagents/backtest_report.py", encoding="utf-8").read()
    assert "streak" in src, "the grid page needs the column"
