"""The 23 flat rows the operator asked for live, as catalog specs (2026-08-27).

The operator pasted 51 rows that were 100.00% over the last 30 days: *"add
those in strategy the ones flat only for live trading"*. 23 cleared the
still-working gate and are here; 28 did not, and 14 of THOSE lose money over
the full window despite the perfect month (SPK elder −$21.21, MERL zscore20
−$16.45, ANIME psar −$15.37, BSV fib382 −$8.18, and ten more).

What these tests hold shut is the part that has burned this project before:

* a spec whose barriers do not match the row that was measured (2026-08-17: a
  config was deployed at a sizing that had never been tested)
* a spec the RUNNER cannot emit a signal for. Every expansion rule was
  backtest-only until 2026-08-19, so a deployed fib618 would have emitted 0
  forever and traded exactly never.
* a key in STRATEGY_SPECS that is not in STRATEGY_ORDER — the UI iterates the
  order, so the strategy would be invisible and unarmable.
"""
import pytest

import tradingagents.auto_trader as at

# coin, timeframe, signal, SL%, TP%, spec key — the six fields of the
# combination that was measured, transcribed from the screen's own output.
SCREENED = [
    ("GLM", "1h", "zscore20", 4.0, 0.6, "zscore20_1h_sl4tp06"),
    ("ORDI", "1h", "fisher", 4.0, 0.6, "fisher_1h_sl4tp06"),
    ("HBAR", "1h", "fvg", 4.0, 0.6, "fvg_1h_sl4tp06"),
    ("NEO", "1h", "killzone", 4.0, 0.6, "killzone_1h_sl4tp06"),
    ("JELLYJELLY", "1h", "rsi2", 4.0, 0.6, "rsi2_1h_sl4tp06"),
    ("HAEDAL", "4h", "ibs", 3.0, 0.6, "ibs_4h_sl3tp06"),
    ("SEI", "1h", "ote", 4.0, 0.4, "ote_1h_sl4tp04"),
    ("FLOKI", "1h", "ote", 4.0, 0.4, "ote_1h_sl4tp04"),
    ("PENDLE", "1h", "ote", 4.0, 0.4, "ote_1h_sl4tp04"),
    ("FET", "1h", "killzone", 4.0, 0.4, "killzone_1h_sl4tp04"),
    ("NEO", "1h", "killzone", 4.0, 0.4, "killzone_1h_sl4tp04"),
    ("LYN", "1h", "psar", 4.0, 0.4, "psar_1h_sl4tp04"),
    ("COMP", "1h", "fisher", 4.0, 0.4, "fisher_1h_sl4tp04"),
    ("BTC", "1h", "fvg", 4.0, 0.4, "fvg_1h_sl4tp04"),
    ("XDC", "1h", "killzone", 2.5, 0.4, "killzone_1h_sl25tp04"),
    ("UMA", "1h", "elder", 4.0, 0.4, "elder_1h_sl4tp04"),
    ("XEC", "1h", "fib382", 4.0, 0.4, "fib382_1h_sl4tp04"),
    ("ARKM", "1h", "sweep30", 4.0, 0.4, "sweep30_1h_sl4tp04"),
    ("COMP", "1h", "hull20", 4.0, 0.4, "hull20_1h_sl4tp04"),
    ("HAEDAL", "4h", "ibs", 3.0, 0.4, "ibs_4h_sl3tp04"),
    ("HAEDAL", "4h", "ibs", 4.0, 0.4, "ibs_4h_sl4tp04"),
    ("PIPPIN", "1h", "lrslope", 4.0, 0.6, "lrslope_1h_sl4tp06"),
    ("LUNANEW", "4h", "pivot", 4.0, 0.4, "pivot_4h_sl4tp04"),
]
KEYS = sorted({k for *_rest, k in SCREENED})
BARS = {"1h": ("Min60", 3600), "4h": ("Hour4", 14400)}


def test_all_twenty_three_rows_are_reachable_as_specs():
    assert len(SCREENED) == 23
    assert len(KEYS) == 20, KEYS      # three coins share ote_1h; NEO/HAEDAL 2x
    for key in KEYS:
        assert key in at.STRATEGY_SPECS, key
        assert key in at.STRATEGY_ORDER, f"{key} would be invisible in the UI"


@pytest.mark.parametrize("row", SCREENED, ids=lambda r: f"{r[0]}-{r[5]}")
def test_the_spec_carries_the_barriers_that_were_measured(row):
    """Rule 21: the EXACT combination, not a neighbouring one. A spec at 3.0%
    against a row measured at 4.0% is the 2026-08-17 deploy again."""
    _coin, tf, _sig, sl, tp, key = row
    spec = at.STRATEGY_SPECS[key]
    assert spec["tp"] == pytest.approx(tp / 100), (key, spec["tp"])
    assert spec["sl"] == pytest.approx(sl / 100), (key, spec["sl"])
    assert (spec["interval"], spec["bar_seconds"]) == BARS[tf], key


@pytest.mark.parametrize("key", KEYS)
def test_the_runner_can_actually_emit_this_signal(key):
    """A strategy the grid can pick and the runner cannot emit trades zero
    times. signal_for must resolve the key to the SAME rule the backtest used,
    and must not fall through to the `return 0` at the bottom."""
    import random

    rnd = random.Random(7)
    n = 400
    # The close must sit ANYWHERE in its bar, not at a fixed fraction of it:
    # `high = c*1.004, low = c*0.996` puts internal bar strength at exactly
    # 0.50 on all 400 bars, and `ibs` (close pinned to an extreme) then reads
    # as "never signals" when the rule is fine and the fixture is not.
    close, high, low, opens = [], [], [], []
    px = 100.0
    for _ in range(n):
        px = max(1.0, px * (1 + rnd.uniform(-0.012, 0.012)))
        rng = px * rnd.uniform(0.002, 0.02)
        hi = px + rng * rnd.random()
        lo = hi - rng
        close.append(px)
        high.append(max(hi, px))
        low.append(min(lo, px))
        opens.append(min(max(lo, px * (1 + rnd.uniform(-0.004, 0.004))), hi))
    vol = [1000.0 * (1 + rnd.random()) for _ in range(n)]
    ts = [1_700_000_000_000 + i * 3_600_000 for i in range(n)]

    dirs = at._dirs_for_backtest(key, high, low, close, opens=opens,
                                 volume=vol, ts=ts)
    assert len(dirs) == n, key
    assert any(d != 0 for d in dirs), f"{key} never signals on 400 bars"
    live = at.signal_for(key, high, low, close, opens=opens, volume=vol, ts=ts)
    assert live == dirs[-1], (key, live, dirs[-1])


def test_none_of_them_is_armed_by_this_commit():
    """A spec is a rule. Coins and books are assigned in the settings, on the
    machine that holds the keys — rule 22: the operator names the row before
    anything trades."""
    settings = at.load_settings()
    books = settings.get("strategy_books") or {}
    coins = settings.get("strategy_coins") or {}
    for key in KEYS:
        assert not books.get(key), f"{key} has a book in this repo's settings"
        assert not coins.get(key), f"{key} has coins in this repo's settings"


def test_the_colliding_coins_are_named_so_only_one_gets_armed():
    """Two live strategies on one coin+timeframe are locked (timeframe_locks),
    so these three coins can only run ONE of their rows: HAEDAL 4h has three,
    NEO 1h two, COMP 1h two."""
    seen: dict = {}
    for coin, tf, _sig, _sl, _tp, key in SCREENED:
        seen.setdefault((coin, tf), []).append(key)
    clashes = {k: v for k, v in seen.items() if len(v) > 1}
    assert clashes == {
        ("HAEDAL", "4h"): ["ibs_4h_sl3tp06", "ibs_4h_sl3tp04",
                           "ibs_4h_sl4tp04"],
        ("NEO", "1h"): ["killzone_1h_sl4tp06", "killzone_1h_sl4tp04"],
        ("COMP", "1h"): ["fisher_1h_sl4tp04", "hull20_1h_sl4tp04"],
    }, clashes
