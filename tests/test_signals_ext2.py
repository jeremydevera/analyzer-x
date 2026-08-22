"""The fifty-three researched entry rules (second expansion).

Same discipline as the first expansion, plus the new streams: NO LOOK-AHEAD
holds for volume and timestamps too, a rule whose stream is missing must
abstain (all zeros) rather than guess, and both dispatchers — the backtest's
and the LIVE runner's — must reach every one of them.
"""
import math

import pytest

from tradingagents import signals_ext2 as s2


def _series(n=500):
    """Wave + drift + a volume pulse, so every rule finds something."""
    opens, high, low, close, volume, ts = [], [], [], [], [], []
    prev = 100.0
    for i in range(n):
        base = 100 + i * 0.05 + 8 * math.sin(i / 9.0) + 3 * math.sin(i / 2.3)
        o = prev
        c = base
        hi = max(o, c) + 0.6 + 0.4 * abs(math.sin(i / 3.0))
        lo = min(o, c) - 0.6 - 0.4 * abs(math.cos(i / 4.0))
        # an occasional violent bar so gap/climax/pin rules have material
        if i % 97 == 0 and i:
            hi += 4
            lo -= 4
        opens.append(o)
        high.append(hi)
        low.append(lo)
        close.append(c)
        volume.append(1000 + 900 * math.sin(i / 5.0) ** 2
                      + (5000 if i % 53 == 0 else 0))
        ts.append(1_700_000_000_000 + i * 3_600_000)
        prev = c
    return opens, high, low, close, volume, ts


def _rich():
    """The wave plus scripted segments, so the pattern rules have their
    patterns: a quiet coil then a pop, a volume climax, a double top with
    confirmed swings, a crash, a gap, a pin bar and a pinned close."""
    o, h, l, c, v, t = _series(400)

    def bar(open_, hi, lo, cl, vol=1000.0):
        o.append(open_)
        h.append(hi)
        l.append(lo)
        c.append(cl)
        v.append(vol)
        t.append(t[-1] + 3_600_000)

    p = c[-1]
    for _ in range(26):                      # coil: squeeze arms
        bar(p, p + 0.2, p - 0.2, p)
    bar(p, p + 3.2, p - 0.1, p + 3, 15000)   # pop: squeeze fires, volspike
    p += 3
    for k in (1, 2, 3):                      # three rising closes
        bar(p + k - 1, p + k + 0.1, p + k - 1.2, p + k)
    bar(p + 3, p + 3.1, p + 0.5, p + 0.8, 16000)   # climax reversal
    base = p + 0.8
    for hi_, lo_ in ((1.0, -0.2), (2.0, 0.7), (3.0, 1.7),   # P1 = base+3
                     (2.2, 1.4), (1.8, 1.0),                 # confirms P1
                     (2.0, 1.3), (2.6, 1.8), (3.05, 2.0),    # P2 ~= P1
                     (2.4, 1.6), (1.9, 1.5)):                # confirms P2
        bar(c[-1], base + hi_, base + lo_, base + (hi_ + lo_) / 2)
    bar(c[-1], base + 3.85, base + 1.0, base + 1.2)   # raid: sweep + reject
    for _ in range(10):                      # crash: ultosc pins low
        pc = c[-1]
        bar(pc, pc + 0.1, pc - 2.3, pc - 2)
    pc = c[-1]
    bar(pc + 4, pc + 4.4, pc + 3.4, pc + 3.6)         # gap up, fades
    pc = c[-1]
    bar(pc, pc + 0.3, pc - 6, pc - 0.1)               # pin bar
    pc = c[-1]
    bar(pc, pc + 2.5, pc - 0.2, pc + 2.5)             # close pinned to high
    return o, h, l, c, v, t


ALL = sorted(s2.EXTRA_SIGNALS2)


@pytest.mark.parametrize("name", ALL)
def test_shape_and_alphabet(name):
    o, h, l, c, v, t = _series()
    out = s2.EXTRA_SIGNALS2[name](o, h, l, c, v, t)
    assert len(out) == len(c), name
    assert set(out) <= {-1, 0, 1}, name


@pytest.mark.parametrize("name", ALL)
def test_no_lookahead(name):
    """Truncating the future must not change the past."""
    o, h, l, c, v, t = _series()
    full = s2.EXTRA_SIGNALS2[name](o, h, l, c, v, t)
    k = 320
    part = s2.EXTRA_SIGNALS2[name](o[:k], h[:k], l[:k], c[:k], v[:k], t[:k])
    assert part == full[:k], f"{name} reads the future"


@pytest.mark.parametrize("name", ALL)
def test_actually_fires(name):
    o, h, l, c, v, t = _rich()
    out = s2.EXTRA_SIGNALS2[name](o, h, l, c, v, t)
    assert any(out), f"{name} never fires on a series containing its pattern"


@pytest.mark.parametrize("name", ALL)
def test_short_series_never_raises(name):
    for n in (0, 1, 2, 5, 21):
        o, h, l, c, v, t = _series(400)
        out = s2.EXTRA_SIGNALS2[name](o[:n], h[:n], l[:n], c[:n], v[:n], t[:n])
        assert len(out) == n


@pytest.mark.parametrize("name", ALL)
def test_missing_streams_abstain_not_guess(name):
    """Called without opens/volume/ts a rule must return zeros or work off
    high/low/close alone — never raise, never emit from imagined data."""
    _, h, l, c, _, _ = _series()
    out = s2.EXTRA_SIGNALS2[name]([], h, l, c, [], [])
    assert len(out) == len(c), name
    assert set(out) <= {-1, 0, 1}, name


def test_dispatcher_routes_every_new_signal():
    from tradingagents import auto_trader as at
    o, h, l, c, v, t = _series()
    for name in ALL:
        direct = s2.EXTRA_SIGNALS2[name](o, h, l, c, v, t)
        routed = at._dirs_for_backtest(f"{name}_rpt_1h", h, l, c,
                                       opens=o, volume=v, ts=t)
        assert routed == direct, f"dispatcher missed {name}"


def test_live_signal_for_reaches_both_expansions():
    """The runner's path must speak every rule the grid recommends —
    the first expansion was backtest-only for a day, and a deployed
    fib618 strategy would have emitted 0 forever."""
    from tradingagents import auto_trader as at, signals_ext as s1
    o, h, l, c, v, t = _series()
    hits = 0
    for name in ALL:
        dirs = s2.EXTRA_SIGNALS2[name](o, h, l, c, v, t)
        got = at.signal_for(f"{name}_live", h, l, c, opens=o, volume=v, ts=t)
        assert got == dirs[-1], f"live path disagrees on {name}"
        hits += got != 0
    for name in sorted(s1.EXTRA_SIGNALS):
        dirs = s1.EXTRA_SIGNALS[name](h, l, c)
        got = at.signal_for(f"{name}_live", h, l, c)
        assert got == dirs[-1], f"live path disagrees on {name}"


def test_no_name_collisions_across_registries():
    from tradingagents import signals_ext as s1
    both = set(s1.EXTRA_SIGNALS) & set(s2.EXTRA_SIGNALS2)
    assert not both, f"same name in both registries: {both}"
    # nor may one name prefix-shadow another the dispatcher way
    names = sorted(s1.EXTRA_SIGNALS) + ALL
    for a in names:
        for b in names:
            if a != b:
                assert not b.startswith(a + "_"), f"{a} shadows {b}"


def test_report_signal_list_carries_all_of_them():
    from tradingagents import backtest_report as br
    missing = [n for n in ALL if n not in br.SIGNALS]
    assert not missing, f"not in the shared grid: {missing}"
