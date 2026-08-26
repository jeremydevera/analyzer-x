"""The thirteen added entry rules.

The property that matters most is NO LOOK-AHEAD: bar i may read bars 0..i and
nothing later. A rule that peeks one bar forward invents an edge that cannot be
traded, and it is invisible in a profit column.
"""
import math

import pytest

from tradingagents import signals_ext as sx


def _series(n=400):
    """A wave with a drift, so every rule finds something to fire on."""
    high, low, close = [], [], []
    for i in range(n):
        base = 100 + i * 0.05 + 8 * math.sin(i / 9.0) + 3 * math.sin(i / 2.3)
        close.append(base)
        high.append(base + 0.6 + 0.4 * abs(math.sin(i / 3.0)))
        low.append(base - 0.6 - 0.4 * abs(math.cos(i / 4.0)))
    return high, low, close


ALL = sorted(sx.EXTRA_SIGNALS)


@pytest.mark.parametrize("name", ALL)
def test_shape_and_alphabet(name):
    h, l, c = _series()
    out = sx.EXTRA_SIGNALS[name](h, l, c)
    assert len(out) == len(c), name
    assert set(out) <= {-1, 0, 1}, name


@pytest.mark.parametrize("name", ALL)
def test_no_lookahead(name):
    """Truncating the future must not change the past.

    Computed over the first k bars, the answer for those bars must equal what
    the full-history run produced.
    """
    h, l, c = _series()
    full = sx.EXTRA_SIGNALS[name](h, l, c)
    k = 260
    part = sx.EXTRA_SIGNALS[name](h[:k], l[:k], c[:k])
    assert part == full[:k], f"{name} reads the future"


@pytest.mark.parametrize("name", ALL)
def test_actually_fires(name):
    h, l, c = _series()
    out = sx.EXTRA_SIGNALS[name](h, l, c)
    assert any(out), f"{name} never fires on a moving series"


def test_short_series_never_raises():
    for name, fn in sx.EXTRA_SIGNALS.items():
        for n in (0, 1, 2, 5, 21):
            h = [10.0] * n
            assert len(fn(h, h, h)) == n, f"{name} at n={n}"


def test_bollinger_break_is_the_mirror_of_the_fade():
    h, l, c = _series()
    assert sx.bbbreak(h, l, c) == [-d for d in sx.bb20(h, l, c)]


def test_fib_levels_are_two_different_rules():
    """They must not be the same trade list.

    Which one fires MORE is not a property to assert: a shallower level is
    easier to reach but harder to close back above, and which effect wins
    depends on the series. Measured on PI's real 1h year: 61.8% fired 621 times
    and 38.2% fired 1,021.
    """
    h, l, c = _series()
    a, b = sx.fib618(h, l, c), sx.fib382(h, l, c)
    assert a != b
    assert any(a) and any(b)


def test_dispatcher_routes_every_new_signal():
    from tradingagents import auto_trader as at

    h, l, c = _series()
    for name in ALL:
        key = f"{name}_rpt_1h"
        at.STRATEGY_SPECS[key] = {"interval": "Min60", "bar_seconds": 3600,
                                  "tp": 0.02, "sl": 0.01}
        try:
            routed = at._dirs_for_backtest(key, h, l, c)
        finally:
            at.STRATEGY_SPECS.pop(key, None)
        assert routed == sx.EXTRA_SIGNALS[name](h, l, c), name


def test_signal_list_carries_all_of_them():
    """The shared grid sweeps the 7 originals plus EVERY expansion — the count
    is derived, because pinning it at 22 broke the day the second expansion
    landed, and pinning it at 75 broke the day the confluence set landed
    (2026-08-26, signals_conf: ten researched setups x three levels)."""
    from tradingagents import backtest_report as br
    from tradingagents.signals_conf import CONF_SIGNALS
    from tradingagents.signals_ext2 import EXTRA_SIGNALS2

    assert len(br.SIGNALS) == (7 + len(sx.EXTRA_SIGNALS) + len(EXTRA_SIGNALS2)
                               + len(CONF_SIGNALS))
    assert len(set(br.SIGNALS)) == len(br.SIGNALS)
    for name in ALL:
        assert name in br.SIGNALS
