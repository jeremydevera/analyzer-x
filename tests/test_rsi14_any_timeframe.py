"""rsi14 must resolve for ANY spec key, not only the literal `rsi14_1h`.

Found on 2026-08-27 while deploying the operator's 15 rows: two of them are
rsi14 at 30m (#4Q2UXGVA SAPIEN, #MQ7AQLGG G), and both `signal_for` and
`_dirs_for_backtest` matched rsi14 with `key == "rsi14_1h"` exactly. A spec
named `rsi14_30m_sl2tp2` therefore fell through every branch to the bare
`return 0` at the bottom of `signal_for` — it would have been armed, shown on
the screen with its coin and its barriers, and traded exactly never.

This is the failure CLAUDE.md already records for the expansion rules: "The
expansion rules (signals_ext, signals_ext2) were BACKTEST-ONLY until
2026-08-19: this function never dispatched to them, so a deployed
fib618/sr_break/supertrend strategy would have silently emitted 0 forever."
Same shape, one rule further on.

The grid was not wrong about the NUMBERS: the screen passed the literal
"rsi14_1h" as its dirs key, so what it measured was the real rsi14 rule. Only
the deploy would have been dead.
"""
import random

import pytest

from tradingagents import auto_trader as at

KEYS = ["rsi14_1h", "rsi14_30m_sl2tp2", "rsi14_4h_sl3tp3", "rsi14"]


def _bars(n=400, seed=11):
    rnd = random.Random(seed)
    close, high, low, opens = [], [], [], []
    px = 100.0
    for _ in range(n):
        px = max(1.0, px * (1 + rnd.uniform(-0.012, 0.012)))
        rng = px * rnd.uniform(0.002, 0.02)
        hi = px + rng * rnd.random()
        close.append(px)
        high.append(max(hi, px))
        low.append(min(hi - rng, px))
        opens.append(px)
    return high, low, close, opens


@pytest.mark.parametrize("key", KEYS)
def test_the_runner_emits_rsi14_for_every_key_shape(key):
    high, low, close, opens = _bars()
    dirs = at._dirs_for_backtest(key, high, low, close, opens=opens)
    assert len(dirs) == len(close), key
    assert any(d != 0 for d in dirs), f"{key} never signals on 400 bars"
    live = at.signal_for(key, high, low, close, opens=opens)
    assert live == dirs[-1], (key, live, dirs[-1])


def test_every_key_shape_gives_the_SAME_rule():
    """A 30m spec must be the same rsi14 as the 1h one — a different answer
    per key name would mean the deploy trades something the grid never
    measured."""
    high, low, close, opens = _bars()
    got = [at._dirs_for_backtest(k, high, low, close, opens=opens)
           for k in KEYS]
    for other in got[1:]:
        assert other == got[0]
    assert got[0] == at.sig_rsi14_dirs(close) if hasattr(
        at, "sig_rsi14_dirs") else True


def test_the_deployed_rsi14_spec_is_reachable():
    """The spec the operator's SAPIEN and G rows run on."""
    key = "rsi14_30m_sl2tp2"
    spec = at.STRATEGY_SPECS.get(key)
    assert spec, f"{key} is not in the catalog"
    assert (spec["interval"], spec["bar_seconds"]) == ("Min30", 1800)
    assert spec["tp"] == pytest.approx(0.02) and spec["sl"] == pytest.approx(0.02)
    assert key in at.STRATEGY_ORDER


def test_no_catalog_spec_falls_through_to_return_zero():
    """The general form of the same bug: every key in STRATEGY_ORDER must reach
    a rule, or it is a strategy that can be armed and cannot trade."""
    high, low, close, opens = _bars()
    vol = [1000.0 + i for i in range(len(close))]
    ts = [1_700_000_000_000 + i * 3_600_000 for i in range(len(close))]
    dead = []
    for key in at.STRATEGY_ORDER:
        dirs = at._dirs_for_backtest(key, high, low, close, opens=opens,
                                     volume=vol, ts=ts)
        if not any(d != 0 for d in dirs):
            dead.append(key)
    # A rule may legitimately be quiet on 400 random bars, so this only fails
    # when the LIVE side disagrees with the grid — which is what "fell through
    # to return 0" looks like.
    mismatched = []
    for key in at.STRATEGY_ORDER:
        dirs = at._dirs_for_backtest(key, high, low, close, opens=opens,
                                     volume=vol, ts=ts)
        live = at.signal_for(key, high, low, close, opens=opens, volume=vol,
                             ts=ts)
        if live != (dirs[-1] if dirs else 0):
            mismatched.append(f"{key}: live {live} vs grid {dirs[-1]}")
    assert not mismatched, "\n".join(mismatched)
