"""The confluence research's building blocks (tradingagents/signals_cq.py),
Oct 21, 2026. Every block and setting is covered:
* a name parses back to exactly its parts, and every other spelling - a part
  twice, two parts of one family, a confirmation alone, an unsorted order -
  is not a name (one combination, one name);
* no candle's decision changes when later candles arrive (cut frames);
* the runner's 299 closed candles decide what the deep window decides;
* the two entry rules refuse exactly the candles they name, and a missing
  calendar refuses every entry;
* the search's space holds only legal combinations; stock tokens trade New
  York's session only; 4h and 1d have no session break;
* the runner and the backtest read one implementation (auto_trader)."""
from __future__ import annotations

import datetime as _dt
import json

import numpy as np
import pytest

from tests.test_pro_strategies import _frame
from tradingagents import signals_cq as sq

DAY = 86_400_000
MON_AUG_31 = 1_788_048_000_000 + DAY       # Mon Aug 31, 2026 00:00 UTC


def _names():
    """Every trigger setting with a confirmation it may take, every
    confirmation setting under a trigger of another family, three pairs of
    confirmations, two existing setups and two random streams."""
    conf = [(b, d) for b in sq.CONFIRM_ORDER for d in sq._digits(b)]
    trig = [(b, d) for b in sq.TRIGGER_ORDER for d in sq._digits(b)]
    out = []
    for t in trig:
        x = next(c for c in conf if sq.BLOCKS[c[0]]["family"] != sq.BLOCKS[t[0]]["family"])
        out.append(sq.name_of(t, [x]))
    for c in conf:
        t = next(t for t in trig if sq.BLOCKS[t[0]]["family"] != sq.BLOCKS[c[0]]["family"])
        out.append(sq.name_of(t, [c]))
    out += ["cq_fl00-ev-vs1", "cq_sb01-rs1-vo0", "cq_sq0-ht1-kp0"]
    out += [sq.name_of(("ex", (sq.EXISTING.index(r),))) for r in ("cf_mom", "cx_maj3")]
    out += ["cq_rn00070", "cq_rn01231"]
    return sorted(set(out))


NAMES = _names()


def _dirs(name, fr):
    return sq.dirs_for(sq.spec_for(name), *fr)


@pytest.mark.parametrize("name", NAMES)
def test_no_candle_reads_the_future(name):
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


def test_every_name_of_the_space_parses_back_and_is_its_only_spelling():
    for tf, kind in (("15m", "crypto"), ("1h", "stocks"), ("4h", "crypto"), ("1d", "metals")):
        for name in sq.entries_for(tf, kind):
            spec = sq.spec_for(name)
            assert spec is not None and spec["name"] == name, name
            assert sq.spec_for(name + "_gh_" + tf)["name"] == name


@pytest.mark.parametrize("bad", [
    "cq_ev", "cq_fl00", "cq_fl00-ht0-ev", "cq_fl00-ev-ev", "cq_ec0-ev", "cq_fl00-kp0",
    "cq_fl0-ev", "cq_fl20-ev", "cq_rn0007", "cq_rn00070-ev", "cq_ex99", "cq_zz0-ev",
    "pt_brk_n0g0c0", "", "cq_fl00-ev-vs1-rs0"])
def test_a_name_that_is_not_ours_is_none(bad):
    assert sq.spec_for(bad) is None


def test_the_space_holds_only_legal_combinations():
    e15 = sq.entries_for("15m", "crypto")
    assert len(e15) == len(set(e15))
    combos = [n for n in e15 if not n.startswith("cq_ex")]
    assert len(combos) == 1116           # 18 trigger settings, parts of different families
    assert sum(n.startswith("cq_ex") for n in e15) == len(sq.EXISTING)
    for n in combos:
        fams = sq.families(n)
        assert len(set(fams)) == len(fams) and 2 <= len(fams) <= 3, n


def test_stock_tokens_trade_new_yorks_session_and_4h_1d_have_no_session_break():
    for n in sq.entries_for("15m", "stocks"):
        spec = sq.spec_for(n)
        for b, d in [spec["trigger"], *spec["confirms"]]:
            if b in ("sb", "vs"):
                assert sq._settings(b, d)["session"] == "ny", n
    for tf in ("4h", "1d"):
        e = sq.entries_for(tf, "crypto")
        assert not any(n.startswith("cq_sb") for n in e)
        assert not any("-vs1" in n for n in e)          # one rolling VWAP: vs0 only


def test_neighbours_are_one_step_away_and_inside_the_space():
    pool = set(sq.entries_for("1h", "crypto"))
    name = "cq_fl00-ev-vs1"
    nb = sq.neighbours(name, pool)
    assert nb and all(x in pool and x != name for x in nb)
    assert {"cq_fl10-ev-vs1", "cq_fl01-ev-vs1", "cq_fl00-ev-vs0"} <= set(nb)   # one setting
    assert {"cq_fl00-ev", "cq_fl00-vs1"} <= set(nb)                           # one dropped
    assert "cq_fl00-ev-vo0" in nb and "cq_fl00-ht0-vs1" in nb                 # one swapped
    assert "cq_ec0-rs0-vo1" in sq.neighbours("cq_ec0-vo1", pool)              # one added
    assert sq.neighbours("cq_rn00070", set(sq.random_entries())) == \
        ["cq_rn00060", "cq_rn00080", "cq_rn00071"]
    mom = sq.name_of(("ex", (sq.EXISTING.index("cf_mom"),)))
    assert sorted(sq.EXISTING[sq.spec_for(x)["trigger"][1][0]]
                  for x in sq.neighbours(mom, pool)) == ["cf_mom_l1", "cf_mom_l2"]


def _day():
    """Mon Aug 31, 2026 (UTC), 96 candles of 15m: a flat first hour whose high
    is 100.8, a close above it inside the first hour (no entry), then two
    breaks after it."""
    c = [100.0] * 96
    h = [100.5] * 96
    lo = [99.5] * 96
    c[3], h[3] = 100.7, 100.8
    c[4], h[4], lo[4] = 100.4, 100.45, 100.0
    c[5], h[5], lo[5] = 101.0, 101.1, 100.4
    c[6], h[6], lo[6] = 100.2, 100.6, 100.1
    c[7], h[7], lo[7] = 102.0, 102.1, 100.2
    for i in range(8, 96):
        c[i], h[i], lo[i] = 101.5, 101.6, 101.4
    o = [100.0] + c[:-1]
    ts = [MON_AUG_31 + i * 900_000 for i in range(96)]
    return o, h, lo, c, [1000.0] * 96, ts


def test_the_session_break_waits_for_the_first_hour_and_first_means_first():
    fr = _day()
    first = list(sq.part_dirs("sb00", *fr))
    every = list(sq.part_dirs("sb01", *fr))
    assert [i for i, x in enumerate(first) if x] == [5]
    assert [i for i, x in enumerate(every) if x] == [5, 7]
    assert first[5] == every[5] == every[7] == 1


def test_no_entry_from_30_minutes_before_to_30_minutes_after_a_us_release():
    ev = json.loads(sq.NEWS_PATH.read_text(encoding="utf-8"))["events"]
    first = next(e for e in ev if e["date"] >= "2026-09-01")
    t_ms = int(_dt.datetime.fromisoformat(f"{first['date']}T{first['time']}")
               .replace(tzinfo=sq.NY).timestamp() * 1000)
    start = (t_ms // DAY) * DAY - 2 * DAY
    fr = _frame(n=4 * 96, seed=5, start_ms=start)
    sq.reset()
    ok = sq.entry_allowed(*fr)
    closes = np.asarray(fr[5], dtype=np.int64) + 900_000
    near = np.abs(closes - t_ms) <= 30 * 60_000
    assert near.sum() == 5                     # closes at -30, -15, 0, +15, +30 minutes
    assert not ok[near].any()
    weekday = ((closes // DAY) + 3) % 7 < 5
    assert ok[~near & weekday].all()


def test_a_quiet_weekend_candle_is_never_bought_and_a_busy_one_is():
    o, h, lo, c, v, ts = _frame(n=3 * 96, seed=6, start_ms=MON_AUG_31 - 2 * DAY)   # Sat
    v = [1000.0] * len(v)
    v[50], v[60], v[200] = 5000.0, 100.0, 100.0       # Saturday busy, Saturday quiet, Monday quiet
    sq.reset()
    ok = sq.entry_allowed(o, h, lo, c, v, ts)
    assert ok[50] and not ok[60] and ok[200]


def test_without_the_calendar_no_entry_is_allowed(monkeypatch, tmp_path):
    monkeypatch.setattr(sq, "NEWS_PATH", tmp_path / "missing.json")
    sq.reset()
    try:
        fr = _frame(n=600, seed=8)
        assert not any(_dirs("cq_rn00071", fr))
        assert not sq.entry_allowed(*fr).any()
    finally:
        sq.reset()


def test_a_candle_after_the_calendar_ends_is_never_bought():
    sq.reset()
    start = int(_dt.datetime(2026, 12, 31, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    fr = _frame(n=400, seed=2, start_ms=start)
    ok = sq.entry_allowed(*fr)
    closes = np.asarray(fr[5], dtype=np.int64) + 900_000
    end = sq.news_times()[1][1]
    assert (closes >= end).any() and not ok[closes >= end].any()


def test_every_trigger_setting_fires_both_ways_somewhere():
    fr = _frame(n=6000, seed=12)
    for b in sq.TRIGGER_ORDER:
        for d in sq._digits(b):
            got = np.asarray(sq.part_dirs(sq.code_of(b, d), *fr))
            assert (got == 1).any() and (got == -1).any(), (b, d)


def test_every_confirmation_setting_lets_some_candles_through_and_stops_others():
    fr = _frame(n=3000, seed=13)
    for b in sq.CONFIRM_ORDER:
        for d in sq._digits(b):
            ok_long, ok_short = sq.part_dirs(sq.code_of(b, d), *fr)
            assert ok_long.any() and (~ok_long).any() and ok_short.any(), (b, d)


def test_an_existing_setup_is_its_own_rule_under_the_entry_rules():
    from tradingagents.signals_conf import CONF_SIGNALS

    fr = _frame(n=1500, seed=4)
    ok = sq.entry_allowed(*fr)
    for rule in ("cf_mom", "cx_maj3"):
        want = CONF_SIGNALS[rule](*fr)
        name = sq.name_of(("ex", (sq.EXISTING.index(rule),)))
        assert _dirs(name, fr) == [int(x) if a else 0 for x, a in zip(want, ok, strict=True)]


def test_random_entries_fire_at_their_rate():
    fr = _frame(n=6000, seed=1)
    ok = sq.entry_allowed(*fr)
    for name, rate in (("cq_rn00070", 0.01), ("cq_rn00071", 0.03)):
        d = np.asarray(_dirs(name, fr))
        assert 0.5 * rate < (d != 0).sum() / ok.sum() < 1.6 * rate, name


def test_every_name_reads_in_plain_words():
    for n in NAMES:
        assert sq.words(n), n
    assert sq.words("pt_brk_n0g0c0") == ""


def test_the_runner_and_the_backtest_read_the_same_signal():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=900, seed=9)
    for name in NAMES[::4]:
        want = _dirs(name, (o, h, lo, c, v, ts))
        got = at._dirs_for_backtest(name + "_gh_15m", h, lo, c, opens=o, volume=v, ts=ts)
        assert list(got) == want, name
        for cut in (400, 777, 900):
            live = at.signal_for(name, h[:cut], lo[:cut], c[:cut], opens=o[:cut],
                                 volume=v[:cut], ts=ts[:cut])
            assert live == want[cut - 1], (name, cut)


def test_an_unknown_cq_name_abstains_everywhere():
    from tradingagents import auto_trader as at

    o, h, lo, c, v, ts = _frame(n=400, seed=2)
    assert at.signal_for("cq_zz0-ev", h, lo, c, opens=o, volume=v, ts=ts) == 0
    assert not any(at._dirs_for_backtest("cq_fl00_gh_15m", h, lo, c, opens=o, volume=v, ts=ts))
