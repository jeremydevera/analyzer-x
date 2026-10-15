"""A strategy practice still trades is re-tested, whatever its coin-wide cost
(RCA-2026-10-15-A).

The practice audit of Oct 15, 2026: three practice trades on QNTX 15m
(stoch14 and willr14, target 1%, stop 0.8%) had no backtest twin, because
their rows were last measured Oct 11, 2026 12:00pm. Every nightly update
since SKIPPED them: the measuring loop drops a combination whose COIN-WIDE
round trip is half its target or more (`GATE_BLOCK`), and QNTX's measured
0.66% against a 1% target. Practice kept trading them, because the runner
judges cost per ENTRY on the live book, and three of those entries passed.

On Backtest v2 every entry already asks the runner's own cost rule of its
own minute (`backtest_strategy(book=)` -> `auto_trader.entry_refusal`), with
the coin's flat cost where a minute has no reading. So with that book the
coin-wide skip only throws away strategies the minute rule would judge
trade by trade, the way practice does. It stays where there is no book
(v1, or a coin with no recorded book): `backtest_report.skips_by_coin_cost`.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from tradingagents import backtest_report as br, market_sweep as msw

SHARD = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "sweep_shard.py"
QNTX_RT, TP = 0.0066, 0.010           # Oct 15, 2026: 66% of a 1% target


def test_with_a_minute_book_the_coin_wide_cost_never_skips():
    book = {"t": [1], "buy": [0.001]}
    assert br.skips_by_coin_cost(QNTX_RT, TP, book) is False


def test_without_a_book_the_old_rule_holds():
    assert br.skips_by_coin_cost(QNTX_RT, TP, None) is True
    assert br.skips_by_coin_cost(0.002, TP, None) is False     # 20%: measured
    assert br.skips_by_coin_cost(None, TP, None) is False      # unknown cost


def test_the_github_test_asks_the_one_rule():
    """The nightly update's full measure (sweep_shard.run_pair) — the loop
    that left QNTX's rows on Oct 11."""
    src = SHARD.read_text(encoding="utf-8")
    loop = src[src.index("dirs_idx = [k2"):src.index("a LEARNED formula")]
    assert "br.skips_by_coin_cost(rt, tp, book)" in loop, loop
    assert "rt / tp >= GATE_BLOCK" not in loop


def test_update_this_backtest_asks_the_one_rule():
    """The PC's UPDATE THIS BACKTEST keeps its deployed exemption and its
    count, and asks the same rule with its own minute book."""
    src = inspect.getsource(msw.run_pair)
    i = src.index("br.skips_by_coin_cost(rt, tp, minute_book)")
    branch = src[i:i + 300]
    assert "not in deployed" in branch and "gated += 1" in branch
    assert "rt / tp >= GATE_BLOCK" not in src
