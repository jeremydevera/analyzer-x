"""The Pro Trader families (tradingagents/signals_pro.py), Oct 20, 2026.

Every test runs over EVERY family, so a family added later is covered the day
it lands:
* no bar's decision changes when later bars arrive (cut frames);
* the runner's 299 closed candles decide exactly what the backtest's deep
  window decides at the same bar (the indicators are fixed-window, and every
  family's lookback fits);
* the runner (`auto_trader.signal_for`) and the backtest
  (`_dirs_for_backtest`) read one implementation;
* every name parses back to its settings, unknown names abstain."""
from __future__ import annotations

import math
import random

import pytest

from tradingagents import pro_indicators as pi, signals_pro as sp


def _frame(n=1500, seed=7, step_s=900, start_ms=1_788_048_000_000, vol=0.006):
    """A random walk with bursts and quiet stretches, so breakouts, trends and
    snap-backs all happen. Times on one grid from a UTC midnight."""
    rnd = random.Random(seed)
    o, h, lo, c, v, ts = [], [], [], [], [], []
    px = 100.0
    regime = 1.0
    for i in range(n):
        if i % 200 == 0:
            regime = rnd.choice((0.4, 1.0, 2.2))
        drift = 0.0015 * math.sin(i / 90.0)
        op = px
        cl = op * math.exp(drift * vol * 50 + rnd.gauss(0, vol * regime))
        o.append(op)
        h.append(max(op, cl) * (1 + abs(rnd.gauss(0, vol / 3))))
        lo.append(min(op, cl) * (1 - abs(rnd.gauss(0, vol / 3))))
        c.append(cl)
        v.append(1000 * regime * (0.5 + rnd.random()))
        ts.append(start_ms + i * step_s * 1000)
        px = cl
    return o, h, lo, c, v, ts


def _one_of_each():
    """Every family's default, and its last setting."""
    out = []
    for fam, f in sp.FAMILIES.items():
        kn = f["knobs"]
        out.append(sp.name_of(fam, [0] * len(kn)))
        out.append(sp.name_of(fam, [len(k[2]) - 1 for k in kn]))
    return out


NAMES = _one_of_each()


def _dirs(name, fr):
    return sp.dirs_for(sp.spec_for(name), *fr)


@pytest.mark.parametrize("name", NAMES)
def test_no_bar_reads_the_future(name):
    fr = _frame()
    full = _dirs(name, fr)
    assert len(full) == len(fr[3])
    for cut in range(300, len(fr[3]) + 1, 137):
        part = _dirs(name, tuple(x[:cut] for x in fr))
        assert part == full[:cut], (name, cut, [k for k in range(cut) if part[k] != full[k]][:5])


@pytest.mark.parametrize("name", NAMES)
def test_the_runners_299_candles_decide_what_the_backtest_decides(name):
    fr = _frame(n=2400, seed=3)
    full = _dirs(name, fr)
    for end in (700, 1333, 1999, 2400):
        tail = tuple(x[end - 299:end] for x in fr)
        assert _dirs(name, tail)[-1] == full[end - 1], (name, end)


def test_every_family_fits_the_runners_candles():
    for fam, f in sp.FAMILIES.items():
        assert f["lookback"] <= pi.MAX_LOOKBACK, fam
        assert len(f["knobs"]) <= 3, fam
        for _letter, _setting, values in f["knobs"]:
            assert 2 <= len(values) <= 4, (fam, _setting)


def test_every_setting_has_one_name_that_parses_back():
    names = sp.variants()
    assert len(names) == len(set(names))
    for nm in names:
        spec = sp.spec_for(nm)
        assert spec is not None and spec["name"] == nm
        assert sp.spec_for(nm + "_gh_1h")["name"] == nm


@pytest.mark.parametrize("bad", ["pt_", "pt_zzz_a0", "pt_rand", "pt_rand_s0", "pt_rand_s9r0",
                                 "pt_rand_x0r0", "cp_rand_s0r0", "trend50"])
def test_a_name_that_is_not_ours_is_none(bad):
    assert sp.spec_for(bad) is None


def test_random_entries_are_the_same_coin_flip_for_the_same_bar_in_any_frame():
    fr = _frame(n=1200, seed=5)
    a = _dirs("pt_rand_s1r1", fr)
    b = _dirs("pt_rand_s1r1", tuple(x[500:] for x in fr))
    assert a[500:] == b
    rate = sum(1 for d in a if d) / len(a)
    assert 0.015 < rate < 0.05
    assert _dirs("pt_rand_s0r1", fr) != a


def test_the_runner_and_the_backtest_read_the_same_signal():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=900, seed=9)
    for name in NAMES[:6]:
        want = _dirs(name, (o, h, lo, c, v, ts))
        got = at._dirs_for_backtest(name + "_gh_15m", h, lo, c, opens=o, volume=v, ts=ts)
        assert list(got) == want, name
        for cut in (400, 777, 900):
            live = at.signal_for(name, h[:cut], lo[:cut], c[:cut], opens=o[:cut],
                                 volume=v[:cut], ts=ts[:cut])
            assert live == want[cut - 1], (name, cut)


def test_an_unknown_pt_name_abstains_everywhere():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=300)
    assert set(at._dirs_for_backtest("pt_zzz_a0_gh_15m", h, lo, c, opens=o,
                                     volume=v, ts=ts)) == {0}
    assert at.signal_for("pt_rand_s9r0", h, lo, c, opens=o, volume=v, ts=ts) == 0


def test_every_stop_target_is_one_the_grid_measures_and_pays_two_to_one_at_the_usual_cost():
    from tradingagents import backtest_report as br

    for tf, pairs in sp.BARRIERS_PCT.items():
        grid = {(round(a * 100, 4), round(b * 100, 4)) for a, b in br.pairs_for(tf)}
        for sl, tp in pairs:
            assert (sl, tp) in grid, (tf, sl, tp)
            assert sl <= 3.0 and tp > sl
            c = 0.23                       # the median round trip paid (Oct 20, 2026)
            assert (tp - c) >= 2 * (sl + c), (tf, sl, tp)
