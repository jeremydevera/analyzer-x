"""The ten confluence setups, at three levels, in BOTH dispatch paths.

Operator, 2026-08-26, after reading the BTC study: "add these combinations to
all coins for 1hr and 4hr timeframe then do backtest for past 2 months".

What has to hold before a rule may enter the grid:
  * it is dispatched by the BACKTEST path and by the LIVE path, and the two
    agree on the last bar -- the 2026-08-19 incident was a backtest-only
    expansion, where a deployed fib618 strategy would have emitted 0 forever
  * it cannot read the future: truncating the history must not change the
    signals that remain
  * the levels are FILTERS -- level 2's signals are a subset of level 1's,
    which are a subset of the setup's own
  * a missing stream makes it abstain, never guess
  * no rule reaches back further than market_sweep.CONTEXT_BARS, or an
    incremental pass computes a different rule from a full one
"""
from __future__ import annotations

import math

import pytest

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br, market_sweep as msw
from tradingagents.signals_conf import CONF_SIGNALS

SETUPS = ("mom", "donch", "maobv", "triple", "chan",
          "soup", "emarsi", "ttm", "soup1", "eqhl")
HOUR_MS = 3_600_000


def _series(n=900, seed=7):
    """A deterministic pseudo-market: trends, pullbacks and a quiet stretch, so
    every rule has something to find without importing a data file."""
    op, hi, lo, cl, vol, ts = [], [], [], [], [], []
    px, state = 100.0, 0.0
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 180 == 0:
            state = (i // 180 % 3) - 1          # up, flat, down in turn
        drift = 0.0016 * state
        quiet = 0.15 if 400 <= i < 460 else 1.0
        step = px * (drift + 0.006 * r * quiet)
        o = px
        c = px + step
        h = max(o, c) + abs(step) * (0.4 + abs(r))
        low_ = min(o, c) - abs(step) * (0.4 + abs(r))
        op.append(round(o, 4)); cl.append(round(c, 4))
        hi.append(round(h, 4)); lo.append(round(low_, 4))
        vol.append(round(500 + 900 * abs(r) + (1500 if i % 97 == 0 else 0), 2))
        ts.append(1_700_000_000_000 + i * HOUR_MS)
        px = c
    return op, hi, lo, cl, vol, ts


@pytest.fixture(scope="module")
def bars():
    return _series()


def test_all_thirty_are_registered_and_in_the_grid():
    assert len(CONF_SIGNALS) == 30
    for n in SETUPS:
        for key in (f"cf_{n}", f"cf_{n}_l1", f"cf_{n}_l2"):
            assert key in CONF_SIGNALS
            assert key in br.SIGNALS, f"{key} is not in the grid registry"
    assert len(br.SIGNALS) == len(set(br.SIGNALS))


@pytest.mark.parametrize("key", sorted(CONF_SIGNALS))
def test_the_backtest_path_dispatches_every_rule(key, bars):
    op, hi, lo, cl, vol, ts = bars
    dirs = at._dirs_for_backtest(key, hi, lo, cl, opens=op, volume=vol, ts=ts)
    assert len(dirs) == len(cl)
    assert set(dirs) <= {-1, 0, 1}


@pytest.mark.parametrize("key", sorted(CONF_SIGNALS))
def test_the_live_path_agrees_with_the_backtest_on_the_last_bar(key, bars):
    """The grid and the runner must be the same rule. A backtest-only expansion
    is a strategy that trades zero times once deployed (2026-08-19)."""
    op, hi, lo, cl, vol, ts = bars
    dirs = at._dirs_for_backtest(key, hi, lo, cl, opens=op, volume=vol, ts=ts)
    live = at.signal_for(key, hi, lo, cl, opens=op, volume=vol, ts=ts)
    assert live == dirs[-1]


def test_a_longer_name_is_not_swallowed_by_a_shorter_one(bars):
    """`cf_mom_l1_1h` must reach the level-1 rule, not the bare one; and
    `cf_soup1` must not be captured by `cf_soup`."""
    op, hi, lo, cl, vol, ts = bars
    plain = at._dirs_for_backtest("cf_mom_1h", hi, lo, cl, opens=op, volume=vol, ts=ts)
    gated = at._dirs_for_backtest("cf_mom_l1_1h", hi, lo, cl, opens=op, volume=vol, ts=ts)
    assert plain == CONF_SIGNALS["cf_mom"](op, hi, lo, cl, vol, ts)
    assert gated == CONF_SIGNALS["cf_mom_l1"](op, hi, lo, cl, vol, ts)
    assert sum(1 for d in gated if d) < sum(1 for d in plain if d)
    soup = at._dirs_for_backtest("cf_soup_4h", hi, lo, cl, opens=op, volume=vol, ts=ts)
    soup1 = at._dirs_for_backtest("cf_soup1_4h", hi, lo, cl, opens=op, volume=vol, ts=ts)
    assert soup == CONF_SIGNALS["cf_soup"](op, hi, lo, cl, vol, ts)
    assert soup1 == CONF_SIGNALS["cf_soup1"](op, hi, lo, cl, vol, ts)


@pytest.mark.parametrize("name", SETUPS)
def test_each_level_is_a_filter_on_the_one_below(name, bars):
    op, hi, lo, cl, vol, ts = bars
    d0 = CONF_SIGNALS[f"cf_{name}"](op, hi, lo, cl, vol, ts)
    d1 = CONF_SIGNALS[f"cf_{name}_l1"](op, hi, lo, cl, vol, ts)
    d2 = CONF_SIGNALS[f"cf_{name}_l2"](op, hi, lo, cl, vol, ts)
    for i in range(len(cl)):
        if d1[i]:
            assert d1[i] == d0[i], "level 1 invented a signal the setup never gave"
        if d2[i]:
            assert d2[i] == d1[i], "level 2 invented a signal level 1 never gave"
    assert sum(1 for d in d2 if d) <= sum(1 for d in d1 if d) <= sum(1 for d in d0 if d)


@pytest.mark.parametrize("key", sorted(CONF_SIGNALS))
def test_no_rule_reads_the_future(key, bars):
    """Truncate the history and the signals that remain must be unchanged.
    Anything else means a bar was reading bars that had not printed."""
    op, hi, lo, cl, vol, ts = bars
    full = CONF_SIGNALS[key](op, hi, lo, cl, vol, ts)
    cut = 700
    part = CONF_SIGNALS[key](op[:cut], hi[:cut], lo[:cut], cl[:cut], vol[:cut], ts[:cut])
    assert part == full[:cut], f"{key} changed its past when the future was removed"


@pytest.mark.parametrize("key", sorted(CONF_SIGNALS))
def test_a_missing_stream_abstains(key, bars):
    """No opens at all: the rule returns zeros rather than guessing."""
    op, hi, lo, cl, vol, ts = bars
    assert CONF_SIGNALS[key]([], hi, lo, cl, vol, ts) == [0] * len(cl)


def test_level_two_abstains_without_the_clock(bars):
    """Its pivot levels come from the previous day, so no timestamps means no
    level 2 -- said with zeros, not with a guessed bar count."""
    op, hi, lo, cl, vol, ts = bars
    for name in SETUPS:
        assert CONF_SIGNALS[f"cf_{name}_l2"](op, hi, lo, cl, vol, []) == [0] * len(cl)


def test_the_volume_rules_abstain_without_volume(bars):
    op, hi, lo, cl, vol, ts = bars
    for name in ("donch", "maobv", "emarsi"):
        assert CONF_SIGNALS[f"cf_{name}"](op, hi, lo, cl, [], ts) == [0] * len(cl)


def test_no_lookback_exceeds_the_incremental_context():
    """market_sweep hands an incremental pass CONTEXT_BARS of history before the
    first new bar. A rule reaching further would be one rule on a full run and
    a different one on a resumed run, under the same name. The BTC study's
    720-bar and 480-bar trend gates were cut to 200 for exactly this."""
    import re

    src = open("tradingagents/signals_conf.py", encoding="utf-8").read()
    windows = [int(m) for m in re.findall(r"_sma\(close, (\d+)\)", src)]
    windows += [int(m) for m in re.findall(r"_ema\(close, (\d+)\)", src)]
    windows += [int(m) for m in re.findall(r"_roll_(?:max|min)\((?:high|low), (\d+)\)", src)]
    windows += [int(m) for m in re.findall(r"_atr\(high, low, close, (\d+)\)", src)]
    windows += [int(m) for m in re.findall(r"range\((\d+), n\)", src)]
    assert windows, "the lookback windows should be readable from the source"
    assert max(windows) <= msw.CONTEXT_BARS, (
        f"a rule reaches back {max(windows)} bars but an incremental pass only "
        f"gets {msw.CONTEXT_BARS}")


def test_every_rule_actually_fires_on_a_market(bars):
    """A rule that can never signal is a hole in the grid wearing a name.

    Two are exempt on a 900-bar synthetic series because they need a shape it
    does not contain -- a quiet 50-bar channel that then breaks, and a stop pool
    swept before a gap. Both are proved to fire by the constructed tests below,
    and on real BTC 1h they fired 24 and 4 times in a year respectively; level 2
    is deliberately rarer still.
    """
    op, hi, lo, cl, vol, ts = bars
    dead = [k for k in CONF_SIGNALS
            if not any(CONF_SIGNALS[k](op, hi, lo, cl, vol, ts))]
    exempt = ("_l2", "cf_chan", "cf_eqhl")
    assert [k for k in dead if not k.startswith(exempt) and not k.endswith("_l2")] == [], \
        f"never fires: {dead}"


def test_the_quiet_channel_breakout_fires_when_the_shape_exists():
    """250 bars inside a 2% range, then two closes above it."""
    n = 254
    op, hi, lo, cl = [], [], [], []
    px = 100.0
    for i in range(n):
        c = 100.0 + (0.5 if i % 2 else -0.5)          # a tight, quiet range
        if i == n - 2:
            c = 103.0                                  # break out
        if i == n - 1:
            c = 106.0                                  # and hold, clearing that
        op.append(px); cl.append(c)                    # bar's own high, since the
        hi.append(max(px, c) + 0.05)                   # channel excludes only the
        lo.append(min(px, c) - 0.05)                   # current bar
        px = c
    ts = [1_700_000_000_000 + i * HOUR_MS for i in range(n)]
    dirs = CONF_SIGNALS["cf_chan"](op, hi, lo, cl, [1.0] * n, ts)
    assert dirs[-1] == 1, "a held breakout from a quiet channel must fire"


def test_the_stop_pool_sweep_fires_when_the_shape_exists():
    """A swing high is taken by a hair, price closes back under it, and the
    market then gaps away -- the sweep and the gap need not share a bar."""
    n = 246
    op, hi, lo, cl = [], [], [], []
    px = 100.0
    for i in range(n):
        o, c = px, px + (0.25 if i % 3 else -0.2)
        h, l = max(o, c) + 0.15, min(o, c) - 0.15
        if i == n - 8:                       # the swing high to be swept
            h = max(h, c + 3.0)
        if i == n - 3:                       # sweep it, close back below
            h = hi[n - 8] + 0.02
            c = o - 0.4
            l = min(o, c) - 0.2
        if i == n - 1:                       # then gap down away from it
            o = c = px - 4.0
            h, l = o + 0.1, c - 0.4
        op.append(o); cl.append(c); hi.append(h); lo.append(l)
        px = c
    ts = [1_700_000_000_000 + i * HOUR_MS for i in range(n)]
    dirs = CONF_SIGNALS["cf_eqhl"](op, hi, lo, cl, [1.0] * n, ts)
    assert dirs[-1] == -1, "a swept pool followed by a gap down must fire short"


def test_the_engulfing_form_works_on_a_gapless_market():
    """Measured on BTC 1h: 8,757 of 8,759 bars open exactly at the previous
    close, so the textbook engulfing (which needs a gap) fired once in a year.
    A hand-built gapless pair must still count as engulfing."""
    from tradingagents.signals_conf import _level1, _bundle

    n = 260
    op, hi, lo, cl = [], [], [], []
    px = 100.0
    for i in range(n):
        up = 0.5 if i < 240 else 0.0
        o = px
        c = px + (up if i % 2 else up * 0.6)
        if i == n - 2:                     # a red bar
            c = o - 1.2
        if i == n - 1:                     # then a bigger green bar: engulfing
            c = o + 2.4
        op.append(o); cl.append(c)
        hi.append(max(o, c) + 0.1); lo.append(min(o, c) - 0.1)
        px = c                             # next bar opens AT this close
    ts = [1_700_000_000_000 + i * HOUR_MS for i in range(n)]
    assert all(op[i] == cl[i - 1] for i in range(1, n)), "the fixture must be gapless"
    b = _bundle(op, hi, lo, cl, [1.0] * n, ts)
    l1 = _level1(op, hi, lo, cl, b)
    assert l1[-1] == 1, "a gapless bullish engulfing above the SMA200 must count"
