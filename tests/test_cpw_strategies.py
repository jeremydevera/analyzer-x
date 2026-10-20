"""The Crypto-Predictor strategies (tradingagents/signals_cpw.py, cpw_rules.py,
cpw_indicators.py) — the seven entry rules of
github.com/jeremydevera/Crypto-Predictor-Web with every combination of their
main switches (operator, Oct 19, 2026: "use the strategy and switches and come
up with best combination for all coins").

The guards, most important first:
* NO BAR READS THE FUTURE. Their own browser backtest did (it judged the
  bigger-timeframe trend on a candle's later close); every bar's decision here
  must be the same whether the frame ends at that bar or runs on past it.
* the names carry the settings, and parse back to exactly them;
* the app's indicators are reproduced to the formula (SMA-seeded EMA, Wilder
  RSI/ATR, JavaScript rounding and NaN);
* the app's own rules that are not switches stay: the 4-hour repeat block,
  the chart pattern's extra signal, FluxGate's preset that lets a pattern
  alone open a trade.
"""
from __future__ import annotations

import math
import random

import pytest

from tradingagents import cpw_indicators as ind
from tradingagents import cpw_rules as rules
from tradingagents import signals_cpw as cp


def _frame(n=900, seed=7, tf_s=900, start_ms=1_788_048_000_000, vol=0.004):
    """A random walk with bursts, so breakouts, flips and patterns happen.
    Times on one 15-minute grid from a UTC midnight."""
    rnd = random.Random(seed)
    o, h, lo, c, v, ts = [], [], [], [], [], []
    px = 100.0
    for i in range(n):
        burst = 3.0 if rnd.random() < 0.04 else 1.0
        op = px
        cl = op * math.exp(rnd.gauss(0, vol * burst))
        hi = max(op, cl) * (1 + abs(rnd.gauss(0, vol / 2)))
        lw = min(op, cl) * (1 - abs(rnd.gauss(0, vol / 2)))
        o.append(op)
        h.append(hi)
        lo.append(lw)
        c.append(cl)
        v.append(1000 * burst * (0.5 + rnd.random()))
        ts.append(start_ms + i * tf_s * 1000)
        px = cl
    return o, h, lo, c, v, ts


def _dirs(name, fr):
    return cp.dirs_for(cp.spec_for(name), *fr)


# ----------------------------------------------------------- the future

CAUSAL_NAMES = [cp.variants([s])[0] for s in cp.NAMES] + [
    "cp_ecb_s1v1o1f0h0r0", "cp_br_e2h1x1u1r1", "cp_cm_w1f1c1o0u0s0",
    "cp_fg_s1x1t1m1u1h1q0", "cp_st_f1u0h0x0i1d1", "cp_bb_z1j1k1c1x1h0",
]


@pytest.mark.parametrize("name", CAUSAL_NAMES)
def test_no_bar_reads_the_future(name):
    """Every bar's decision is the same on the frame cut at that bar as on
    the whole frame — 20 cut points, every bar before each one compared."""
    fr = _frame()
    full = _dirs(name, fr)
    assert len(full) == len(fr[3])
    for cut in range(120, len(fr[3]) + 1, 39):
        part = _dirs(name, tuple(x[:cut] for x in fr))
        assert part == full[:cut], (name, cut, [k for k in range(cut) if part[k] != full[k]][:5])


def _raw_rows(strategy, ctx):
    raw = cp._RAW[strategy](ctx)
    if isinstance(raw, dict):                       # Confirmation Model
        return [tuple(raw[k][i] for k in sorted(raw)) for i in range(ctx.n)]
    return raw


@pytest.mark.parametrize("strategy", list(cp.NAMES))
def test_no_reading_of_any_bar_changes_when_later_bars_arrive(strategy):
    """Stronger than the decisions above: EVERY fact a strategy reads at a
    bar — swings, grades, the bigger-timeframe trend and structure, zones,
    the FluxGate score — is the same whether the frame ends at a cut or runs
    on past it. A planted peek at the forming bigger candle's FINAL values
    flipped no decision in the test above (0 of 13 names) and is caught here."""
    fr = _frame(n=700, seed=5)
    full = _raw_rows(strategy, rules.Ctx(*fr))
    ctx_full = rules.Ctx(*fr)
    for cut in range(130, 700, 57):
        cut_fr = tuple(x[:cut] for x in fr)
        part = _raw_rows(strategy, rules.Ctx(*cut_fr))
        bad = [i for i in range(cut) if part[i] != full[i]]
        assert not bad, (strategy, cut, bad[:5])
        htf_cut = rules.Ctx(*cut_fr).htf()
        htf_full = ctx_full.htf()
        assert all(htf_cut.part[i] == htf_full.part[i] and
                   htf_cut.closed[i] == htf_full.closed[i] for i in range(cut)), (strategy, cut)


def test_the_bigger_candle_is_only_what_had_happened():
    """At a bar inside a 1h candle (15m frame), the forming bigger candle's
    high is the high SO FAR, its close the bar's close — never the hour's
    final values; at the hour's last bar it is finished and a new, flat one
    is forming."""
    fr = _frame(n=200)
    ctx = rules.Ctx(*fr)
    htf = ctx.htf()
    assert htf.per == 3600
    i = next(k for k in range(100, 200) if (fr[5][k] // 1000) % 3600 == 900)   # 2nd bar
    first = i - 1
    o, hi, low, cl = htf.part[i]
    assert o == fr[0][first]
    assert hi == max(fr[1][first:i + 1]) and low == min(fr[2][first:i + 1])
    assert cl == fr[3][i]
    last = i + 2                                                            # 4th bar
    assert htf.closed[last] == htf.pidx[last] + 1
    assert htf.part[last] == (fr[3][last],) * 4


# ----------------------------------------------------------- the names

def test_every_setting_has_one_name_that_parses_back():
    names = cp.variants()
    assert len(names) == len(set(names)) == 96 + 64 + 48 + 64 + 128 + 64 + 64
    for nm in names:
        spec = cp.spec_for(nm)
        assert spec is not None and spec["name"] == nm
        assert cp.spec_for(nm + "_gh_15m")["name"] == nm
    preset = cp.spec_for("cp_ecb_s0v0o0f0h0r0")["switches"]
    assert preset == {"session": True, "vol": "medium", "ob": True, "fvg": False,
                      "htfema": False, "retest": False}


@pytest.mark.parametrize("bad", ["cp_ecb", "cp_zzz_s0", "cp_ecb_s0v0o0f0h0", "cp_ecb_s0v9o0f0h0r0",
                                 "cp_ecb_x0v0o0f0h0r0", "lx_ecb_s0v0o0f0h0r0", "trend50"])
def test_a_name_that_is_not_ours_is_none(bad):
    assert cp.spec_for(bad) is None


# ------------------------------------------------------- the app's math

def test_ema_is_seeded_with_the_sma_like_the_app():
    data = [1.0, 2, 3, 4, 5, 6]
    e = ind.ema(data, 3)
    assert e[:2] == [None, None] and e[2] == 2.0
    assert e[3] == pytest.approx(4 * 0.5 + 2.0 * 0.5)
    closed = data[:5]
    assert ind.ema_last_with(ind.ema(closed, 3), closed, 6.0, 3) == pytest.approx(e[5])


def test_rsi_and_atr_follow_the_apps_wilder_formulas():
    c = [10, 11, 10.5, 11.5, 12, 11.8, 12.5]
    r = ind.rsi(c, 3)
    gains, losses = 1 + 1, 0.5
    assert r[3] == pytest.approx(100 - 100 / (1 + (gains / 3) / (losses / 3)))
    h = [11, 12, 11, 12, 13]
    lo = [9, 10, 10, 11, 11]
    a = ind.atr(h, lo, [10, 11, 10.5, 11.5, 12], 3)
    trs = [2, 2, 1, 1.5, 2]
    assert a[2] == pytest.approx(sum(trs[:3]) / 3)
    assert a[3] == pytest.approx((a[2] * 2 + trs[3]) / 3)


def test_a_flat_stretch_gives_an_adx_that_fails_every_comparison_like_javascript():
    flat = [1.0] * 60
    a = ind.adx(flat, flat, flat, 14)
    assert a[30] is not None and math.isnan(a[30])
    assert not (a[30] >= 22) and not (a[30] > 22)


def test_pattern_confidence_rounds_halves_up_like_javascript():
    assert ind._jsround(66.5) == 67 and ind._jsround(2.4) == 2


# --------------------------------------------- the app's rules that stay

def test_a_signal_repeats_no_sooner_than_four_hours():
    fr = _frame(n=40)
    ctx = rules.Ctx(*fr)
    dirs = [0] * 40
    dirs[5] = dirs[6] = dirs[21] = dirs[22] = 1
    dirs[7] = -1
    out = rules.dedup_4h(ctx, dirs)
    assert out[5] == 1 and out[6] == 0           # 15 minutes later: blocked
    assert out[7] == -1                          # the other side is its own
    assert out[21] == 1 and out[22] == 0         # 16 bars = 4 hours later: again


def test_fluxgates_preset_lets_a_chart_pattern_alone_open_a_trade():
    """The app's FluxGate preset is min quality 0, so a detected chart
    pattern (quality 4) opens a trade even when no FluxGate gate passed; the
    'q1' setting (min quality 5) does not."""
    fr = _frame(n=900, seed=11)
    ctx = rules.Ctx(*fr)
    raw = rules.raw_fg(ctx)
    sw = dict(cp.spec_for("cp_fg_s0x0t0m0u0h0q0")["switches"])
    sw.update(session=True, adx=True, structure=True, momentum=True, volume=True, htf=True)
    pats = [i for i in range(len(raw)) if raw[i] is not None and ctx.pattern(i) is not None]
    assert pats, "the frame must hold a chart pattern"
    loose = rules.decide_fg(ctx, raw, sw)
    strict = rules.decide_fg(ctx, raw, {**sw, "minq": 5})
    fired = [i for i in pats if loose[i] != 0]
    assert fired, "a pattern alone opened nothing under the preset"
    assert all(strict[i] == 0 for i in fired
               if not (raw[i]["lx"] or raw[i]["sx"]))


def test_the_session_switch_decides_whether_off_hours_breakouts_count():
    """The Elite rules trade only 08:00-11:00 and 13:00-17:00 UTC with the
    session switch on; off, the same frame can trade at any hour, and every
    preset signal is still there."""
    fr = _frame(n=1500, seed=3)
    on = _dirs("cp_ecb_s0v1o1f0h0r0", fr)
    off = _dirs("cp_ecb_s1v1o1f0h0r0", fr)
    ctx = rules.Ctx(*fr)
    assert all(ctx.elite_session(i) for i, d in enumerate(on) if d)
    assert sum(1 for d in off if d) >= sum(1 for d in on if d)


# ------------------------------------------- one implementation, every door

def test_the_runner_and_the_backtest_read_the_same_signal():
    """The live runner asks the LAST bar (auto_trader.signal_for); the grid
    asks every bar (auto_trader._dirs_for_backtest, called with the grid's
    `<name>_gh_<tf>` key). Both go through signals_cpw.dirs_for."""
    from tradingagents import auto_trader as at

    fr = _frame(n=600, seed=9)
    o, h, lo, c, v, ts = fr
    for name in ("cp_st_f1u0h0x0i0d0", "cp_fg_s1x1t1m1u1h1q0", "cp_bb_z1j1k1c1x1h0"):
        want = _dirs(name, fr)
        got = at._dirs_for_backtest(name + "_gh_15m", h, lo, c, opens=o, volume=v, ts=ts)
        assert list(got) == want
        for cut in (300, 451, 600):
            live = at.signal_for(name, h[:cut], lo[:cut], c[:cut], opens=o[:cut],
                                 volume=v[:cut], ts=ts[:cut])
            assert live == want[cut - 1], (name, cut)


def test_an_unknown_cp_name_abstains_everywhere():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=200)
    assert set(at._dirs_for_backtest("cp_zzz_q0_gh_15m", h, lo, c, opens=o,
                                     volume=v, ts=ts)) == {0}
    assert at.signal_for("cp_ecb_s9", h, lo, c, opens=o, volume=v, ts=ts) == 0
