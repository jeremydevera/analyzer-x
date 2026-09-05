"""The five setups that live only in the research ledger's 4-HOUR ranking.

Operator, Aug 27, 2026, reading that artifact against the store: *"have you
also tried this 10 strats to all coins?"* and then *"why di you not build them,
/goal buiild them for all coins"*. They were right: the ledger published TWO
top-tens, the 1-hour list became `signals_conf` and was swept on 1h and 4h, and
five setups from the 4-hour list had never been written at all --

    cf_bosfvg    4h CHoCH/BOS + FVG retrace
    cf_fundfade  funding-extreme fade + trend-failure confirm
    cf_obretest  BOS -> order-block retest
    cf_diadx     DI-cross + ADX(14) > 25 + EMA200 side
    cf_stflip    Supertrend(10,3) flip + RSI 50-70 + ADX > 25

The generic contract (dispatch on both paths, no lookahead, levels are filters,
a missing stream abstains) is enforced for all 45 rules in
tests/test_signals_conf.py, which iterates the registry. This file covers what
is specific to these five:

  * FUNDING is a real input now. `cf_fundfade` reads MEXC's settlement history,
    and no signal function had ever received anything but candles. A rule that
    needs it and does not get it must ABSTAIN -- and every caller that measures
    a grid must pass it, or the sweep and the app's own 1 YEAR button run
    different rules under the same name, which is the divergence CLAUDE.md
    forbids.
  * The DMI arithmetic has ONE implementation (`signals_ext2._dmi`), split out
    of `adx14` rather than copied.
"""
from __future__ import annotations

import inspect

import pytest

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br
from tradingagents.signals_conf import CONF_SIGNALS, NEEDS_FUNDING
from tradingagents.signals_ext2 import EXTRA_SIGNALS2, _dmi

FOUR_HOUR = ("bosfvg", "fundfade", "obretest", "diadx", "stflip")
HOUR_MS = 3_600_000


def _series(n=1200, seed=11):
    """A deterministic pseudo-market with trends, ranges and pullbacks."""
    op, hi, lo, cl, vol, ts = [], [], [], [], [], []
    px, state = 100.0, 0.0
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 150 == 0:
            state = (i // 150 % 3) - 1
        step = px * (0.0018 * state + 0.007 * r)
        o, c = px, px + step
        hi.append(round(max(o, c) + abs(step) * (0.5 + abs(r)), 4))
        lo.append(round(min(o, c) - abs(step) * (0.5 + abs(r)), 4))
        op.append(round(o, 4))
        cl.append(round(c, 4))
        vol.append(round(600 + 800 * abs(r), 2))
        ts.append(1_700_000_000_000 + i * 4 * HOUR_MS)
        px = c
    return op, hi, lo, cl, vol, ts


def _funding(ts, spike_every=30, rate=0.0012):
    out, t, k = [], ts[0], 0
    while t <= ts[-1]:
        r = 0.0001 * (1 if k % 3 else -1)
        if k % spike_every == 0:
            r = rate
        elif k % spike_every == spike_every // 2:
            r = -rate
        out.append({"settle_ms": t, "rate": r})
        t += 8 * HOUR_MS
        k += 1
    return out


@pytest.fixture(scope="module")
def bars():
    return _series()


def test_the_five_are_registered_at_three_levels_each():
    for name in FOUR_HOUR:
        for key in (f"cf_{name}", f"cf_{name}_l1", f"cf_{name}_l2"):
            assert key in CONF_SIGNALS, f"{key} is not a rule"
            assert key in br.SIGNALS, f"{key} is not in the grid registry"
    assert len(br.SIGNALS) == 120, "105 signals + the 4-hour five at 3 levels"


def _uptrend(n=900, pull=60, up=0.004, dn=0.004):
    """A steady uptrend with a pullback every `pull` bars: price stays above a
    long EMA while +DI and -DI cross back and forth. The pseudo-random series
    above is a sawtooth that never holds a trend long enough to put price above
    its own EMA200 during an up-leg, so the LONG side of a trend-following rule
    needs a series that actually trends."""
    op, hi, lo, cl, vol, ts = [], [], [], [], [], []
    px = 100.0
    for i in range(n):
        step = px * (-dn if i % pull < pull // 5 else up)
        o, c = px, px + step
        hi.append(round(max(o, c) * 1.002, 4))
        lo.append(round(min(o, c) * 0.998, 4))
        op.append(round(o, 4))
        cl.append(round(c, 4))
        vol.append(1000.0)
        ts.append(1_700_000_000_000 + i * 4 * HOUR_MS)
        px = c
    return op, hi, lo, cl, vol, ts


@pytest.mark.parametrize("name", [n for n in FOUR_HOUR if n != "fundfade"])
def test_each_candle_setup_fires(name, bars):
    op, hi, lo, cl, vol, ts = bars
    d = CONF_SIGNALS[f"cf_{name}"](op, hi, lo, cl, vol, ts)
    assert any(d), f"cf_{name} never fires at all"


@pytest.mark.parametrize("name,side", [("bosfvg", "both"), ("obretest", "both"),
                                       ("diadx", "long"), ("stflip", "long")])
def test_each_candle_setup_can_take_the_side_it_claims(name, side, bars):
    """Both sides, measured. The two trend-following rules take their long side
    on a series that trends (see _uptrend); the two structure rules take both on
    the sawtooth. On the real market all four take both sides -- measured on
    2026-08-27 over stored candles, e.g. BTC 1h cf_diadx 23 long / 34 short,
    cf_stflip 38 / 36, cf_obretest 55 / 56, cf_bosfvg 118 / 49."""
    op, hi, lo, cl, vol, ts = bars
    fn = CONF_SIGNALS[f"cf_{name}"]
    d = fn(op, hi, lo, cl, vol, ts)
    if side == "both":
        assert any(v > 0 for v in d), f"cf_{name} never goes long"
        assert any(v < 0 for v in d), f"cf_{name} never goes short"
        return
    up = fn(*_uptrend())
    assert any(v > 0 for v in up), f"cf_{name} never goes long, even in a trend"
    assert any(v < 0 for v in d), f"cf_{name} never goes short"


def test_the_funding_fade_abstains_without_the_funding_history(bars):
    """No settlements, no signal -- never a guess from price alone.

    This is the contract every rule in the library follows for a missing
    stream, and it is what keeps a caller that cannot supply funding (a skill
    script, an old notebook) honest instead of silently wrong.
    """
    op, hi, lo, cl, vol, ts = bars
    for key in ("cf_fundfade", "cf_fundfade_l1", "cf_fundfade_l2"):
        assert CONF_SIGNALS[key](op, hi, lo, cl, vol, ts) == [0] * len(cl)
        assert CONF_SIGNALS[key](op, hi, lo, cl, vol, ts, []) == [0] * len(cl)


def test_the_funding_fade_fires_when_the_crowd_is_paying(bars):
    op, hi, lo, cl, vol, ts = bars
    d = CONF_SIGNALS["cf_fundfade"](op, hi, lo, cl, vol, ts, _funding(ts))
    assert any(v for v in d), "an extreme funding series produced no signal"
    # it FADES: a positive extreme (longs paying) can only produce a short
    fund = [{"settle_ms": t, "rate": 0.002} for t in
            range(ts[0], ts[-1] + 1, 8 * HOUR_MS)]
    only_up = CONF_SIGNALS["cf_fundfade"](op, hi, lo, cl, vol, ts, fund)
    assert all(v <= 0 for v in only_up), \
        "funding at a positive extreme must never produce a long"
    assert any(v < 0 for v in only_up)


def test_only_the_rules_that_need_funding_are_given_it(bars):
    """A candle rule must not change because funding was passed -- if it did,
    the sweep (which passes funding) and a script that does not would measure
    two different rules under one name."""
    op, hi, lo, cl, vol, ts = bars
    fund = _funding(ts)
    assert NEEDS_FUNDING == ("fundfade",)
    for key, fn in CONF_SIGNALS.items():
        if getattr(fn, "needs_funding", False):
            assert "fundfade" in key
            continue
        assert fn(op, hi, lo, cl, vol, ts) == fn(op, hi, lo, cl, vol, ts, fund), \
            f"{key} changed when funding was supplied"


def test_both_dispatchers_carry_funding_to_the_rule(bars):
    """The backtest path and the LIVE path. A rule the grid can pick and the
    runner cannot emit is a strategy that trades zero times once deployed."""
    op, hi, lo, cl, vol, ts = bars
    fund = _funding(ts)
    iv, bs, _cap = br.TFS["4h"]
    key = "cf_fundfade_bt_4h"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02,
                              "sl": .01, "threshold": .003}
    try:
        with_f = at._dirs_for_backtest(key, hi, lo, cl, opens=op, volume=vol,
                                       ts=ts, funding=fund)
        without = at._dirs_for_backtest(key, hi, lo, cl, opens=op, volume=vol,
                                        ts=ts)
        assert any(with_f), "the backtest path dropped the funding history"
        assert not any(without), "no funding must mean no signal"
        assert with_f == CONF_SIGNALS["cf_fundfade"](op, hi, lo, cl, vol, ts,
                                                    fund)
        live = at.signal_for(key, hi, lo, cl, opens=op, volume=vol, ts=ts,
                             funding=fund)
        assert live == with_f[-1], "the live path and the grid disagree"
    finally:
        at.STRATEGY_SPECS.pop(key, None)


def test_every_grid_that_measures_rows_passes_funding():
    """CLAUDE.md: the app's 1 YEAR button and any analysis run the SAME grid.
    A call site that forgets funding makes cf_fundfade abstain there and trade
    in the sweep -- the same divergence that once hid a strategy from its own
    app."""
    for path in ("tradingagents/market_sweep.py",
                 "tradingagents/backtest_report.py",
                 ".github/scripts/sweep_shard.py"):
        src = open(path, encoding="utf-8").read()
        calls = src.count("_dirs_for_backtest(")
        passes = src.count("funding=fund")
        assert calls and passes >= calls, \
            f"{path}: {calls} dispatch call(s) but funding passed {passes} time(s)"


def test_the_dmi_has_one_implementation():
    """`adx14` and the two 4-hour rules that read ADX share `_dmi`; a second
    copy is a second indicator the moment one of them is edited."""
    src = inspect.getsource(EXTRA_SIGNALS2["adx14"])
    assert "_dmi(" in src, "adx14 must call the shared _dmi"
    assert "pdms" not in src, "the DMI arithmetic should live in _dmi only"
    conf = open("tradingagents/signals_conf.py", encoding="utf-8").read()
    assert "_dmi(high, low, close, 14)" in conf
    assert conf.count("def _dmi") == 0, "no second copy in signals_conf"


def test_the_dmi_series_are_sane(bars):
    _op, hi, lo, cl, _v, _t = bars
    pdi, ndi, adx = _dmi(hi, lo, cl, 14)
    assert len(pdi) == len(ndi) == len(adx) == len(cl)
    vals = [v for v in adx if v == v]                       # drop the NaNs
    assert vals, "ADX never became readable"
    assert min(vals) >= 0 and max(vals) <= 100
    for a, b in zip(pdi, ndi, strict=False):
        if a == a and b == b:
            assert 0 <= a <= 100 and 0 <= b <= 100


@pytest.mark.parametrize("name", FOUR_HOUR)
def test_the_new_rules_read_only_the_past(name, bars):
    """Truncating the future must not change the past. The three retrace rules
    carry state across bars (a pending zone), which is exactly where a
    lookahead hides."""
    op, hi, lo, cl, vol, ts = bars
    fund = _funding(ts)
    fn = CONF_SIGNALS[f"cf_{name}"]
    args = (op, hi, lo, cl, vol, ts)
    full = fn(*args, fund) if name == "fundfade" else fn(*args)
    cut = 900
    part_args = (op[:cut], hi[:cut], lo[:cut], cl[:cut], vol[:cut], ts[:cut])
    part = (fn(*part_args, fund) if name == "fundfade" else fn(*part_args))
    assert part == full[:cut], f"cf_{name} changed its past"
