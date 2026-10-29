"""The Backtest v3 proof test (decisions doc docs/superpowers/specs/2026-10-23-
backtest-v3-part2-decisions.md, "The proof test"): choose on the older days,
judge on the unseen days against the random runs' bar and a day-clustered
bootstrap, at least 300 unseen trades — and every verdict kept with the step
it failed. Rows are the compact trade rows `v3_measure` writes:
[signal_ms, entry_ms, exit_ms, side, pnl, why]."""
import calendar
import math

import pytest

from tradingagents import v3_families as vf, v3_filters as vfl, v3_proof as vp, v3_universe as vu

DAY = 86_400_000
D0 = calendar.timegm((2026, 7, 25, 0, 0, 0)) * 1000        # the unseen days start here
PLAN_END = calendar.timegm((2026, 10, 23, 0, 0, 0)) * 1000  # the plan's end: D0 + 90 days
KEY = vf.combo_key("v3_snap", "k2", "1h", "none")
KEY15 = vf.combo_key("v3_snap", "k1.5", "1h", "none")


def _rows(pnls, per_day=4, why="TP"):
    """One row per pnl, `per_day` of them closing on each UTC day from D0."""
    return [[D0 + (k // per_day) * DAY, D0 + (k // per_day) * DAY + 60_000,
             D0 + (k // per_day) * DAY + 3_600_000, 1, p, why] for k, p in enumerate(pnls)]


def _walk(rows, **extra):
    return {"rows": rows, "counts": {}, "filter": {}, "twins": [0, 0.0], "lev": [20, 20],
            "notional": [50.0, 50.0], "over_book": 0, **extra}


def _coin(name, older15, older2, unseen2, random2, unseen15=()):
    return {"coin": name, "windows": {"1h": {"split": "Jul 25, 2026", "end": "Oct 23, 2026"}},
            "unseen_months": ["2026-07", "2026-08", "2026-09", "2026-10"],
            "combos": {KEY15: {"older": _walk(older15), "unseen": _walk(list(unseen15)),
                               "random": [[0, 0.0]] * 200},
                       KEY: {"older": _walk(older2), "unseen": _walk(unseen2),
                             "random": random2}}}


QUIET = [[100, 0.1 * ((k % 5) - 2)] for k in range(200)]    # a run's profit a trade: +-0.002
LOUD = [[100, 10.0 * ((k % 5) - 2)] for k in range(200)]    # +-0.2


def _two_coins(unseen, random_runs=QUIET):
    """k1.5 makes +0.05 a trade on the older days, k2 +0.10 (40 trades each per coin): k2 is
    chosen. The unseen trades are split between the two coins."""
    half = len(unseen) // 2
    return [_coin(c, _rows([0.05] * 40), _rows([0.10] * 40), part, random_runs)
            for c, part in (("AAA_USDT", unseen[:half]), ("BBB_USDT", unseen[half:]))]


def test_alpha_divides_by_every_combination_measured():
    # 0.05 / 63 = 0.000794; z = the normal curve's 1 - 0.000397 point
    assert vp.TRIED == len(vf.combos()) == 63
    assert round(vp.Z, 4) == 3.355 and round(vp.z_for(1), 5) == 1.95996


def test_the_setting_is_chosen_on_the_older_days_with_30_trades_ties_to_the_simplest():
    older = {"n20": _rows([0.10] * 40), "n50": _rows([0.20] * 35), "n100": _rows([5.0] * 29)}
    chosen, table = vp.choose(older, ["n20", "n50", "n100"])
    # n100 makes far more a trade, but 29 trades are under the 30 a setting needs
    assert chosen == "n50" and table["n100"]["eligible"] is False
    assert table["n50"]["per_trade"] == pytest.approx(0.20) and table["n50"]["trades"] == 35
    tie = {"n20": _rows([0.2] * 30), "n50": _rows([0.2] * 30)}
    assert vp.choose(tie, ["n20", "n50", "n100"])[0] == "n20", "a tie goes to the simplest"
    assert vp.choose({"n20": _rows([1.0] * 29)}, ["n20"])[0] is None


def test_the_random_bar_is_the_normal_curves_point_with_the_best_run_as_its_floor():
    # three runs that traded make +0.1, -0.1 and +0.1 a trade (the run with no trade is left
    # out): mean 0.0333, sample sd sqrt((0.0667^2 + 0.1333^2 + 0.0667^2) / 2) = 0.11547, so
    # the point is 0.0333 + 3.355 x 0.11547 = 0.4207, over the best run's 0.1
    bar = vp.random_bar([(10, 1.0), (10, -1.0), (5, 0.5), (0, 0.0)])
    assert (bar["runs"], bar["traded"]) == (4, 3)
    assert bar["sd"] == pytest.approx(0.11547, abs=1e-5)
    assert bar["bar"] == pytest.approx(0.0333333 + vp.Z * 0.11547, abs=1e-4)
    # 199 runs at 0 and one at +0.5 a trade: mean 0.0025, sd sqrt(0.24875 / 199) = 0.035355,
    # the point 0.0025 + 3.355 x 0.035355 = 0.1211 - under the best run, which is the bar
    bar = vp.random_bar([(10, 0.0)] * 199 + [(10, 5.0)])
    assert bar["normal"] == pytest.approx(0.12112, abs=1e-4) and bar["bar"] == 0.5
    assert vp.random_bar([(10, 1.0), (0, 0.0)]) is None, "one run that traded is no curve"


def test_random_runs_pool_run_by_run_over_the_coins():
    assert vp.pool_random([[[10, 1.0], [5, -1.0]], [[2, 0.5], [0, 0.0]]]) == [(12, 1.5),
                                                                            (5, -1.0)]
    with pytest.raises(ValueError, match="random runs"):
        vp.pool_random([[[1, 1.0]], [[1, 1.0], [1, 1.0]]])


def test_the_bootstrap_draws_whole_days():
    # two days, one trade each, +1 and -1: a draw of 2 days is (+1, +1) a quarter of the time,
    # (-1, -1) a quarter, mixed half - profit a trade +1, -1 or 0: sd sqrt(0.5) = 0.7071
    two = _rows([1.0, -1.0], per_day=1)
    se, days = vp.boot_se(two, seed=1)
    assert days == 2 and se == pytest.approx(math.sqrt(0.5), abs=0.03)
    assert vp.boot_se(two, seed=1) == (se, 2), "seeded: the same every time"
    # two wins on day 1 and a loss on day 2 are 2 clusters, not 3 trades: a draw is +1 (both
    # day 1), -1 (both day 2) or (2 - 1) / 3 = +0.333 (one each), so the sd is
    # sqrt(0.25 + 0.25 + 0.5 x 0.1111 - 0.1667^2) = 0.7265
    se, days = vp.boot_se(_rows([1.0, 1.0, -1.0], per_day=2), seed=1)
    assert days == 2 and se == pytest.approx(0.7265, abs=0.03)
    assert vp.boot_se(_rows([1.0, 2.0], per_day=2), seed=1) == (None, 1)


def test_the_summary_is_the_standard_kits_figures_in_closing_order():
    rows = _rows([1.0, -0.5, -0.7, 2.0, -0.4], per_day=1)
    rows[4][5] = "END"
    s = vp.summary(list(reversed(rows)))                  # handed over in any order
    # wins 1.0 and 2.0 (avg 1.5), losses 0.5, 0.7, 0.4 (avg 0.5333): break-even 0.5333 / 2.0333
    assert (s["trades"], s["wins"], s["losses"]) == (5, 2, 3)
    assert s["profit"] == pytest.approx(1.4) and s["per_trade"] == pytest.approx(0.28)
    assert s["break_even"] == pytest.approx(0.53333 / 2.03333, abs=1e-4)
    assert (s["worst_run_usd"], s["worst_run_trades"]) == (pytest.approx(-1.2), 2)
    assert s["open_at_end"] == 1


STEADY = [1.2, -0.8] * 160                  # 320 trades, +0.20 each on average, every day alike


def test_a_family_that_clears_every_step_passes():
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY)))
    # k2 chosen (+0.10 against +0.05 on the older days); unseen 320 trades at +0.20; QUIET's runs
    # make -0.002..+0.002 a trade (mean 0, sd 0.0014178): the bar 3.355 x 0.0014178 = 0.0048;
    # every day makes the same +0.20, so the bootstrap's error is 0
    assert v["setting"] == "k2" and v["passed"] is True and v["failed"] == ""
    assert v["unseen"]["trades"] == 320 and v["unseen"]["per_trade"] == pytest.approx(0.2)
    assert v["random"]["bar"] == pytest.approx(vp.Z * 0.0014178, abs=1e-5)
    assert v["bootstrap"]["se"] == pytest.approx(0.0, abs=1e-12) and v["bootstrap"]["days"] == 80
    assert v["coins"] == ["AAA_USDT", "BBB_USDT"] and v["id"] == vf.verdict_id("v3_snap", "1h",
                                                                               "none")
    assert v["months"] == ["2026-07", "2026-08", "2026-09", "2026-10"], "the months used"
    assert v["window"] == {"split": "Jul 25, 2026", "end": "Oct 23, 2026",
                           "older_candles": 0, "unseen_candles": 0}


def test_each_step_that_fails_names_the_verdict():
    # the luck bar: LOUD's runs make -0.2..+0.2 a trade (sd 0.14178): 3.355 x 0.14178 = 0.4757
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY), LOUD))
    assert (v["passed"], v["failed"]) == (False, "random") and v["checks"]["profit"] is True
    # losing money: -0.20 a trade
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows([-1.2, 0.8] * 160)))
    assert v["failed"] == "profit"
    # +0.20 a trade, all of it from ONE day: 79 days of 4 losses of 0.1, and one day of 3 losses
    # and a +95.9 win. A draw holds that day K times, K ~ Binomial(80, 1/80): profit a trade
    # (96K - 32) / 320 = 0.3K - 0.1, sd 0.3 x sqrt(0.9875) = 0.298, and 0.2 - 3.355 x 0.298 < 0
    lucky = [-0.1] * 319 + [95.9]
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(lucky)))
    assert v["unseen"]["per_trade"] == pytest.approx(0.2) and v["failed"] == "bootstrap"
    assert v["bootstrap"]["se"] == pytest.approx(0.298, abs=0.03)
    # +0.20 a trade, the days swinging: 40 days of 4 trades at +1.2, 40 of 4 at -0.8. Every day
    # holds 4 trades, so a draw's profit a trade is the mean of 80 drawn days' averages, whose sd
    # is 1.0: the error sqrt(1 / 80) = 0.1118, and 0.2 - 3.355 x 0.1118 = -0.175 - not proven,
    # though 0.2 is 1.8 errors above 0
    swing = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(([1.2] * 4 + [-0.8] * 4) * 40)))
    assert swing["bootstrap"]["se"] == pytest.approx(0.1118, abs=0.01)
    assert swing["failed"] == "bootstrap" and swing["checks"]["random"] is True
    # every check passes but there are 299 trades, not 300
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows([0.2] * 299)))
    assert v["failed"] == "trades" and [v["checks"][k] for k in vp.CHECKS[:3]] == [True] * 3


def test_a_family_that_shines_only_on_the_older_days_fails():
    # +0.10 a trade on the older days, +0.001 on the unseen ones: under QUIET's 0.0048 bar
    coins = _two_coins(_rows([0.501, -0.499] * 160))
    v = vp.verdict("v3_snap", "1h", "none", coins)
    assert v["older"]["k2"]["per_trade"] == pytest.approx(0.10)
    assert v["unseen"]["per_trade"] == pytest.approx(0.001) and v["failed"] == "random"


def test_a_group_with_too_few_older_trades_or_no_coin_fails_at_the_choice():
    thin = [_coin("AAA_USDT", _rows([0.1] * 10), _rows([0.1] * 29), _rows(STEADY), QUIET)]
    v = vp.verdict("v3_snap", "1h", "none", thin)
    assert (v["failed"], v["setting"]) == ("choose", None) and "30 trades" in v["why"]
    v = vp.verdict("v3_trend", "1d", "none", thin)
    assert v["failed"] == "choose" and v["why"] == "no coin measured v3_trend on 1d"
    assert v["coins"] == [] and any("survivorship" in n for n in v["notes"])


def test_every_judged_group_gets_a_verdict_and_what_could_not_be_measured_is_summed():
    coins = _two_coins(_rows(STEADY))
    for c in coins:
        c["combos"][KEY]["unseen"].update(counts={"cost_unmeasured": 7, "missed": 2},
                                          filter={"signals": 50}, twins=[2, 0.75], over_book=3,
                                          lev=[12, 20], notional=[40.0, 120.0])
    out = vp.verdicts(coins)
    assert [(v["family"], v["tf"], v["filter"]) for v in out] == vf.judged()
    v = next(v for v in out if (v["family"], v["tf"], v["filter"]) == ("v3_snap", "1h", "none"))
    assert v["counts"] == {"cost_unmeasured": 14, "missed": 4, "signals": 100}
    assert (v["twins"], v["twins_pnl"], v["over_book"]) == (4, pytest.approx(1.5), 6)
    assert v["lev"] == [12, 20] and v["notional"] == [40.0, 120.0]
    assert sum(1 for v in out if v["failed"] == "choose") == 26


# --- Fix round 1 (ruled Oct 23, 2026): the luck bar is pinned at verdict
# level - its best-run floor, and its pooling run by run over the coins - and a verdict's z
# follows its own count of tries.


def _two_coins_with_runs(unseen, runs_a, runs_b):
    """Two coins that choose k2 on the older days (k1.5 +0.05 a trade, k2 +0.10), each with its
    own random runs; the unseen trades are split between them."""
    half = len(unseen) // 2
    return [_coin("AAA_USDT", _rows([0.05] * 40), _rows([0.10] * 40), unseen[:half], runs_a),
            _coin("BBB_USDT", _rows([0.05] * 40), _rows([0.10] * 40), unseen[half:], runs_b)]


def test_the_luck_bar_is_the_best_run_when_the_best_run_is_above_the_normal_point():
    # 199 runs at 0 and one at +0.5 a trade: mean 0.0025, sd sqrt(0.24875 / 199) = 0.035355, so
    # the normal point is 0.0025 + 3.355 x 0.035355 = 0.1211, and the best run (0.5) is ABOVE it:
    # the bar is the best run
    runs = [[10, 0.0]] * 199 + [[10, 5.0]]
    # a real +0.30 a trade is over the normal point and under the bar: it FAILS the random check
    v = vp.verdict("v3_snap", "1h", "none", _two_coins_with_runs(_rows([0.3] * 320), runs, runs))
    assert v["setting"] == "k2" and v["unseen"]["per_trade"] == pytest.approx(0.3)
    assert v["random"]["normal"] == pytest.approx(0.12112, abs=1e-4)
    assert v["random"]["bar"] == pytest.approx(0.5)
    assert v["checks"]["profit"] is True and v["checks"]["random"] is False
    assert (v["passed"], v["failed"]) == (False, "random")
    # a real +0.60 a trade is over the bar, so it passes the random check
    w = vp.verdict("v3_snap", "1h", "none", _two_coins_with_runs(_rows([0.6] * 320), runs, runs))
    assert w["checks"]["random"] is True and w["passed"] is True


def test_random_runs_pool_run_by_run_across_the_coins_not_strung_together():
    # coin A's two runs make +1.0 and -1.0 over 10 trades each; coin B's make -0.5 and +0.5.
    # Pooled run by run (each run's trades and profit summed over the coins): (20 trades, +0.5)
    # and (20, -0.5), i.e. +0.025 and -0.025 a trade: sd 0.025 x sqrt(2) = 0.035355, normal point
    # 3.355 x 0.035355 = 0.118616, best run 0.025: the bar is 0.118616.
    # Strung together (four runs: +0.1, -0.1, -0.05, +0.05 a trade): sd 0.091287, normal point
    # 0.308919, best run 0.1: the bar would be 0.308919. The pooled bar is the one that holds.
    v = vp.verdict("v3_snap", "1h", "none", _two_coins_with_runs(
        _rows(STEADY), [[10, 1.0], [10, -1.0]], [[10, -0.5], [10, 0.5]]))
    assert v["setting"] == "k2" and (v["random"]["runs"], v["random"]["traded"]) == (2, 2)
    assert v["random"]["best"] == pytest.approx(0.025)
    assert v["random"]["bar"] == pytest.approx(vp.Z * 0.025 * math.sqrt(2), abs=1e-9)
    # the real +0.20 a trade clears the pooled bar (0.1186), not the strung-together one (0.3089)
    assert v["unseen"]["per_trade"] == pytest.approx(0.2) and v["checks"]["random"] is True


def test_the_default_z_is_the_normal_point_for_the_full_correction():
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY)))
    assert v["z"] == vp.Z and v["alpha"] == pytest.approx(0.05 / vp.TRIED)
    assert v["random"]["normal"] == pytest.approx(v["random"]["mean"] + vp.Z * v["random"]["sd"])


def test_tried_sets_the_z_and_the_alpha_for_the_same_count():
    # 0.05 / 10 = 0.005 a test, so z = z_for(10) = 2.807 - not the 63-count's 3.355
    v = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY)), tried=10)
    assert v["tried"] == 10 and v["alpha"] == pytest.approx(0.05 / 10)
    assert v["z"] == pytest.approx(vp.z_for(10)) and v["z"] != vp.Z
    assert v["random"]["normal"] == pytest.approx(v["random"]["mean"] + v["z"] * v["random"]["sd"])


def test_an_explicit_z_is_used_as_given_and_its_alpha_is_the_one_it_makes():
    coins = _two_coins(_rows(STEADY))
    v = vp.verdict("v3_snap", "1h", "none", coins, z=3.0)
    assert v["z"] == 3.0
    assert v["random"]["normal"] == pytest.approx(v["random"]["mean"] + 3.0 * v["random"]["sd"])
    # 2 x (1 - Phi(3)) = 0.0026998: the two-sided alpha that z = 3.0 is made for
    assert v["alpha"] == pytest.approx(0.0026998, abs=1e-6)
    with pytest.raises(ValueError, match="z must be positive"):
        vp.verdict("v3_snap", "1h", "none", coins, z=-1.0)


# --- Fix round 2 (ruled on the task review of Oct 23, 2026) ----------------------------------
# 1. a pooled verdict's window is the group's; 2. the bootstrap's z, the 300-trade edge and the
# exit-day clustering are pinned; 3. a choose-failed verdict names the filter that blocked it;
# 4. coins pooled twice, or at two risks, plans or run counts, are refused; 5. z and tried are
# refused exactly. Each pin fails on its mutant, and where the behaviour was already right the
# pin passes on the committed code.


def _windowed(coin, start, older, unseen, seconds):
    """A coin whose 1h window is its own: its start, its candle counts and its seconds."""
    coin["windows"] = {"1h": {"start": start, "split": "Jul 25, 2026", "end": "Oct 23, 2026",
                              "older_candles": older, "unseen_candles": unseen,
                              "seconds": seconds}}
    return coin


def _group(name, family, tf, filt, older_by_setting):
    """A coin that measured one group: `older_by_setting` maps each setting to its older walk."""
    combos = {vf.combo_key(family, k, tf, filt): {"older": w, "unseen": _walk([]),
                                                  "random": [[0, 0.0]] * 200}
              for k, w in older_by_setting.items()}
    return {"coin": name, "windows": {tf: {"split": "Jul 25, 2026", "end": "Oct 23, 2026"}},
            "unseen_months": ["2026-07"], "combos": combos}


def test_a_pooled_window_is_the_groups_split_and_end_with_the_candle_counts_summed():
    # NEWCOIN is listed first and is young: its own start (Jun 10, 2026, before the split and later
    # than BTC's) and its seconds must never become the group's, and BTC's candles are added to
    # NEWCOIN's, not used in its place. The 1h counts follow the starts: 45 days from Jun 10 to the
    # split is 1,080 candles; 275 days from Oct 23, 2025 is 6,600
    young = _windowed(_coin("NEWCOIN_USDT", _rows([0.05] * 40), _rows([0.10] * 40),
                            _rows(STEADY)[:160], QUIET), "Jun 10, 2026 12:00am", 1080, 2160, 4.1)
    old = _windowed(_coin("BTC_USDT", _rows([0.05] * 40), _rows([0.10] * 40),
                          _rows(STEADY)[160:], QUIET), "Oct 23, 2025 12:00am", 6600, 2160, 61.0)
    v = vp.verdict("v3_snap", "1h", "none", [young, old])
    assert v["window"] == {"split": "Jul 25, 2026", "end": "Oct 23, 2026",
                           "older_candles": 7680, "unseen_candles": 4320}
    assert v["window"] is not young["windows"]["1h"], "a copy, never a coin's own record"
    assert vp.verdict("v3_snap", "1h", "none", [old, young])["window"] == v["window"]


def test_coins_measured_on_different_splits_are_refused_by_name():
    # a split is the plan's end less 90 days, so coins of two plan ends have two splits - and it is
    # that number, never the date a machine printed for it, that tells the two windows apart
    coins = _two_coins(_rows(STEADY))
    coins[0]["plan_end_ms"], coins[1]["plan_end_ms"] = PLAN_END, PLAN_END + DAY
    coins[1]["windows"]["1h"]["split"] = "Jul 26, 2026"
    with pytest.raises(ValueError, match="coins measured at different plan_end_ms cannot be pooled: "
                                         f"BBB_USDT at {PLAN_END + DAY}, AAA_USDT at {PLAN_END}"):
        vp.verdict("v3_snap", "1h", "none", coins)


def test_two_coins_of_one_plan_pool_whatever_time_zone_their_dates_were_printed_in():
    # one plan: a split of Jul 25, 2026 00:00 UTC and an end of Oct 23, 2026 00:00 UTC. A runner on
    # UTC prints them so; this PC, on New York time (UTC-4 in July and in October), prints the same
    # two instants as the evening before. The plan's end says they are one window; the texts are
    # labels of it and are never compared
    coins = _two_coins(_rows(STEADY))
    for c in coins:
        c["plan_end_ms"] = PLAN_END
    coins[0]["windows"]["1h"].update(split="Jul 25, 2026 12:00am", end="Oct 23, 2026 12:00am")
    coins[1]["windows"]["1h"].update(split="Jul 24, 2026 8:00pm", end="Oct 22, 2026 8:00pm")
    v = vp.verdict("v3_snap", "1h", "none", coins)
    assert v["coins"] == ["AAA_USDT", "BBB_USDT"]
    # the group's label is one coin's text of that one instant: the first coin's
    assert (v["window"]["split"], v["window"]["end"]) == ("Jul 25, 2026 12:00am",
                                                           "Oct 23, 2026 12:00am")
    back = vp.verdict("v3_snap", "1h", "none", coins[::-1])
    assert back["coins"] == ["BBB_USDT", "AAA_USDT"]
    assert (back["window"]["split"], back["window"]["end"]) == ("Jul 24, 2026 8:00pm",
                                                                 "Oct 22, 2026 8:00pm")


def test_the_bootstrap_low_end_uses_the_verdicts_own_z_not_the_63_count_z():
    # days alternate +1.335 and -0.665 a trade (four trades a day, 80 days): profit a trade +0.335;
    # the day averages' sd is 1.0, so the error is about 0.11 (sqrt(1 / 80) = 0.1118, less the
    # sampling noise of 2,000 draws) and 0.335 / 0.11 = 3.0 - between z_for(10) = 2.807 and the
    # 63-count's Z = 3.355
    unseen = []
    for day in range(80):
        unseen += [1.335] * 4 if day % 2 == 0 else [-0.665] * 4
    ten = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(unseen)), tried=10)
    default = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(unseen)))
    se, per_trade = ten["bootstrap"]["se"], ten["unseen"]["per_trade"]
    assert ten["z"] == pytest.approx(vp.z_for(10)) and default["z"] == vp.Z
    assert ten["bootstrap"]["low"] == pytest.approx(per_trade - ten["z"] * se, abs=1e-9)
    assert ten["checks"]["bootstrap"] is True and ten["passed"] is True
    assert default["bootstrap"]["low"] == pytest.approx(per_trade - vp.Z * se, abs=1e-9)
    assert default["checks"]["bootstrap"] is False and default["failed"] == "bootstrap"


def test_exactly_300_unseen_trades_pass_the_trades_check():
    three = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows([0.2] * 300)))
    assert three["unseen"]["trades"] == 300 and three["checks"]["trades"] is True
    assert three["passed"] is True and three["failed"] == ""


def test_the_bootstrap_clusters_trades_by_the_day_they_closed_not_the_day_they_opened():
    # 80 days, four trades closing on each; a day's four sum to +0.8 (+0.2 a trade) in any order,
    # so by CLOSE day every cluster is alike and the error is 0. The first two trades of each day
    # OPENED the day before (across midnight): by OPEN day the clusters differ, and the error is
    # about 0.11
    rows = []
    for j in range(80):
        pnls = [1.2, 1.2, -0.8, -0.8] if j % 2 == 0 else [-0.8, -0.8, 1.2, 1.2]
        close = D0 + j * DAY + 3_600_000
        for q, p in enumerate(pnls):
            opened = close - 3_600_000 - (DAY if q < 2 else 0)
            rows.append([opened - 60_000, opened, close, 1, p, "TP"])
    se, days = vp.boot_se(rows, seed=1)
    assert days == 80, "80 closing days, not the 81 opening days"
    assert se == pytest.approx(0.0, abs=1e-9)


def test_a_filter_that_blocked_every_signal_on_the_older_days_says_so():
    # the real case is funding_minutes on a 4-hour coin's 4h orders (all six a day go in on a
    # settlement hour): the filter blocks every signal of every setting (1,234 and 900 here)
    coin = _group("AAA_USDT", "v3_snap", "1h", "funding_minutes", {
        "k1.5": _walk([], filter={"signal_candles": 1234, "blocked": 1234}),
        "k2": _walk([], filter={"signal_candles": 900, "blocked": 900})})
    v = vp.verdict("v3_snap", "1h", "funding_minutes", [coin])
    assert (v["failed"], v["setting"]) == ("choose", None)
    assert v["why"] == "funding_minutes blocked all 1,234 signals on the older days"


def test_blocked_all_is_not_said_when_one_setting_let_a_signal_through():
    # AAA blocks every signal of both settings; BBB blocks every signal of k1.5 but lets 15 of the
    # 20 signals of k2 through. Pooled, k1.5 is blocked on every signal and k2 is not, so "blocked
    # all" must not be said: an any-setting reading says it, and so does a reading of the first coin
    coins = [
        _group("AAA_USDT", "v3_snap", "1h", "funding_minutes", {
            "k1.5": _walk([], filter={"signal_candles": 50, "blocked": 50}),
            "k2": _walk([], filter={"signal_candles": 40, "blocked": 40})}),
        _group("BBB_USDT", "v3_snap", "1h", "funding_minutes", {
            "k1.5": _walk([], filter={"signal_candles": 30, "blocked": 30}),
            "k2": _walk([], filter={"signal_candles": 20, "blocked": 5})})]
    v = vp.verdict("v3_snap", "1h", "funding_minutes", coins)
    assert v["setting"] is None
    assert v["why"] == "no setting had 30 trades on the older days with funding_minutes"
    assert "blocked all" not in v["why"]


def test_the_other_choose_failures_name_the_filter_they_ran_under():
    # signals got through the filter, but too few trades came of them: the filter is named
    coin = _group("AAA_USDT", "v3_snap", "1h", "busy_hours", {
        "k1.5": _walk([], filter={"signal_candles": 50, "blocked": 10}),
        "k2": _walk([], filter={"signal_candles": 40, "blocked": 0})})
    v = vp.verdict("v3_snap", "1h", "busy_hours", [coin])
    assert v["why"] == "no setting had 30 trades on the older days with busy_hours"
    # the plain group blocks nothing and names no filter: its sentences carry no suffix
    plain = _group("AAA_USDT", "v3_snap", "1h", "none", {
        "k1.5": _walk(_rows([0.1] * 10)), "k2": _walk(_rows([0.1] * 29))})
    assert vp.verdict("v3_snap", "1h", "none", [plain])["why"] == \
        "no setting had 30 trades on the older days"
    assert vp.verdict("v3_trend", "1d", "none", [])["why"] == "no coin measured v3_trend on 1d"


def test_verdicts_refuses_the_same_coin_handed_over_twice_by_name():
    coins = _two_coins(_rows(STEADY))
    with pytest.raises(ValueError, match="AAA_USDT is listed twice"):
        vp.verdicts(coins + [_two_coins(_rows(STEADY))[0]])


def test_verdicts_refuses_coins_measured_at_different_risk_runs_or_plan_end_by_name():
    for key, a, b in (("risk_usd", 1.0, 2.0), ("runs", 200, 199), ("plan_end_ms", 1, 2)):
        coins = _two_coins(_rows(STEADY))
        coins[0][key], coins[1][key] = a, b
        with pytest.raises(ValueError, match=f"coins measured at different {key} cannot be pooled"):
            vp.verdicts(coins)


def test_verdicts_refuses_a_version_1_and_a_version_2_record_in_one_pool_by_name():
    # Backtest v3 Part 2b, Task 1: a version 1 coin has 6-wide trade rows and an older walk that
    # paid another flat gap; the two are never one measurement
    coins = _two_coins(_rows(STEADY))
    coins[0]["version"], coins[1]["version"] = 1, 2
    with pytest.raises(ValueError, match="coins measured at different version cannot be pooled: "
                                         "BBB_USDT at 2, AAA_USDT at 1"):
        vp.verdicts(coins)


def test_the_run_count_error_names_the_coin_that_holds_another_number_of_runs():
    coins = [_coin("AAA_USDT", _rows([0.05] * 40), _rows([0.10] * 40), _rows(STEADY)[:160],
                   [[10, 1.0], [10, -1.0]]),
             _coin("BBB_USDT", _rows([0.05] * 40), _rows([0.10] * 40), _rows(STEADY)[160:],
                   [[10, 1.0], [10, -1.0], [10, 0.5]])]
    with pytest.raises(ValueError, match="BBB_USDT holds 3 random runs, AAA_USDT holds 2"):
        vp.verdicts(coins)


def test_z_and_tried_are_refused_by_name_when_they_cannot_make_a_correction():
    coins = _two_coins(_rows(STEADY))
    for z in (float("nan"), 0.0, -1.0):
        with pytest.raises(ValueError, match="z must be positive"):
            vp.verdict("v3_snap", "1h", "none", coins, z=z)
    for tried in (0, -3, 2.5, True, 10.0):
        with pytest.raises(ValueError, match="tried must be a positive whole number"):
            vp.verdict("v3_snap", "1h", "none", coins, tried=tried)
        with pytest.raises(ValueError, match="tried must be a positive whole number"):
            vp.verdict("v3_snap", "1h", "none", coins, z=3.0, tried=tried)


# --- Fix round 1 of Task 9 (ruled Oct 24, 2026) ----------------------------------------------
# 1. coins pool only when they were measured under one plan BUILD, not only one plan end;
# 2. a verdict says how many random runs were made and how many traded, whether or not a bar came
#    of them; 3. a group that failed at the choice says when its signals were refused as under one
#    lot (the engine's own counts, summed over the older walks); 4. every filter that can surprise
#    has its note, and each note is true of the filter's code.


def test_coins_of_two_builds_of_one_plan_end_are_refused_and_unstamped_ones_pool_alone():
    coins = _two_coins(_rows(STEADY))
    for c in coins:
        c["plan_end_ms"] = PLAN_END                                  # one end, one split
    # two records written before builds were stamped pool with each other (None is None) ...
    assert vp.verdict("v3_snap", "1h", "none", coins)["coins"] == ["AAA_USDT", "BBB_USDT"]
    # ... but never with a stamped one
    coins[0]["plan_id"] = "0123456789abcdef"
    with pytest.raises(ValueError, match="coins measured at different plan_id cannot be pooled: "
                                         "BBB_USDT at None, AAA_USDT at '0123456789abcdef'"):
        vp.verdict("v3_snap", "1h", "none", coins)
    # two stamped builds of the same day never pool; one build does
    coins[1]["plan_id"] = "fedcba9876543210"
    with pytest.raises(ValueError, match="coins measured at different plan_id cannot be pooled: "
                                         "BBB_USDT at 'fedcba9876543210', "
                                         "AAA_USDT at '0123456789abcdef'"):
        vp.verdicts(coins)
    coins[1]["plan_id"] = "0123456789abcdef"
    assert vp.verdict("v3_snap", "1h", "none", coins)["coins"] == ["AAA_USDT", "BBB_USDT"]


def test_a_verdict_says_how_many_random_runs_were_made_and_how_many_traded():
    # 200 runs that never traded: no bar, and the count says why, from the data
    def made(v):
        return {k: v["random_runs"][k] for k in ("runs", "traded")}

    never = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY), [[0, 0.0]] * 200))
    assert never["random"] is None and made(never) == {"runs": 200, "traded": 0}
    # one run that traded is no curve either
    one = vp.verdict("v3_snap", "1h", "none",
                     _two_coins(_rows(STEADY), [[10, 1.0]] + [[0, 0.0]] * 199))
    assert one["random"] is None and made(one) == {"runs": 200, "traded": 1}
    # runs pooled over the coins are still 200 runs, not 400
    some = vp.verdict("v3_snap", "1h", "none", _two_coins(_rows(STEADY)))
    assert made(some) == {"runs": 200, "traded": 200}
    assert (some["random"]["runs"], some["random"]["traded"]) == (200, 200)


def _trend_1d(counts, *, filt="none", signals=76, blocked=0, risk=1.0):
    """ETH-like: the older walk of every setting of v3_trend on 1d signalled `signals` times,
    `blocked` of them stopped by the filter, and the engine counted `counts` for the rest."""
    def walk():
        flt = {"signal_candles": signals, **({"blocked": blocked} if blocked else {})}
        return _walk([], counts=dict(counts), filter=flt)

    coin = _group("ETH_USDT", "v3_trend", "1d", filt, {k: walk() for k in ("n20", "n50", "n100")})
    if risk is not None:
        coin["risk_usd"] = risk
    return coin


def test_a_group_whose_signals_were_under_one_lot_says_so_at_the_risk_the_records_name():
    # ETH on 1d at $1: every signal candle of every setting was under one lot (76 of 76 on the
    # unseen days; here the older ones, three settings: 228 of 228)
    v = vp.verdict("v3_trend", "1d", "none", [_trend_1d({"too_small": 76})])
    assert (v["failed"], v["setting"]) == ("choose", None)
    # three settings' counts summed: a candle that signals under all three is three signals, and
    # the words say so (never "228 signal candles" for 76 candles)
    assert v["why"] == ("no setting had 30 trades on the older days: 228 of 228 signals over the 3 settings (a candle counts once for each setting it signals under) "
                        "were under one lot at $1.00 risk")
    # the risk is the records', never typed
    v = vp.verdict("v3_trend", "1d", "none", [_trend_1d({"too_small": 76}, risk=2.5)])
    assert v["why"].endswith("were under one lot at $2.50 risk")
    # a record that names no risk says none
    v = vp.verdict("v3_trend", "1d", "none", [_trend_1d({"too_small": 76}, risk=None)])
    assert v["why"].endswith("228 of 228 signals over the 3 settings (a candle counts once for each setting it signals under) were under one lot")
    # the counts are kept on the verdict: the older walks', every setting, every coin, the
    # filter's beside the engine's
    assert v["older_counts"] == {"too_small": 228, "signal_candles": 228}
    assert vp.verdict("v3_trend", "1d", "none", [])["older_counts"] == {}


def test_a_filtered_group_counts_the_signals_the_filter_let_through_and_names_the_filter():
    # 76 signals, 21 stopped by busy_hours, the 55 that got through were all under one lot
    v = vp.verdict("v3_trend", "1d", "busy_hours",
                   [_trend_1d({"too_small": 55}, filt="busy_hours", blocked=21)])
    assert v["why"] == ("no setting had 30 trades on the older days with busy_hours: 165 of 228 "
                        "signals over the 3 settings (a candle counts once for each setting it signals under) were under one lot at $1.00 risk")


def test_the_dominant_refusal_is_the_one_said_and_each_has_its_own_words():
    counts = {"too_small": 10, "unsafe_stop": 30, "gate_blocked": 5}
    v = vp.verdict("v3_trend", "1d", "none", [_trend_1d(counts, signals=100)])
    assert v["why"] == ("no setting had 30 trades on the older days: 90 of 300 signals over the 3 settings (a candle counts once for each setting it signals under) "
                        "had no safe leverage")
    counts = {"too_small": 10, "unsafe_stop": 3, "gate_blocked": 40}
    v = vp.verdict("v3_trend", "1d", "none", [_trend_1d(counts, signals=100)])
    assert v["why"] == ("no setting had 30 trades on the older days: 120 of 300 signals over the 3 settings (a candle counts once for each setting it signals under) "
                        "were turned away by the cost check")
    # a tie goes to the first of the three (under one lot), so the sentence never flips between runs
    v = vp.verdict("v3_trend", "1d", "none",
                   [_trend_1d({"too_small": 7, "unsafe_stop": 7}, signals=100)])
    assert "were under one lot" in v["why"]
    # signals the engine never refused add nothing to the sentence
    v = vp.verdict("v3_trend", "1d", "none", [_trend_1d({"missed": 12}, signals=100)])
    assert v["why"] == "no setting had 30 trades on the older days"


def test_every_filter_that_can_surprise_has_its_note_and_each_note_is_true_of_the_filter():
    assert set(vp.NOTES) == {"btc_mood", "busy_hours", "funding_side", "funding_minutes"}
    # the notes ride on the verdict, beside the survivorship line every verdict carries
    for filt, note in vp.NOTES.items():
        assert vp.verdict("v3_snap", "1h", filt, [])["notes"] == [vu.SURVIVORSHIP, note]
    assert vp.verdict("v3_snap", "1h", "none", [])["notes"] == [vu.SURVIVORSHIP]
    # funding_minutes: the gap is read off the filter's own constant; orders go in on the hour, so
    # every order on a settlement hour is blocked - recorded (stamped a few seconds late, as Gate
    # does) or by the cycle. Each figure the note says is the filter's own answer:
    minutes = vfl.SETTLE_GAP_MS // 60_000
    assert vp.NOTES["funding_minutes"] == (
        f"No order within {minutes} minutes of a funding settlement. Orders go in on the hour, so "
        "every order that goes in on a settlement hour is blocked: every 4h order of a coin that "
        "settles every 4 hours, half the 4h orders of an 8-hour coin, and 6 or 3 of the 24 1h "
        "orders of a 4- or an 8-hour coin (all of a 1-hour coin's). It is not tried on 1d, where "
        "it would block every order (00:00 UTC is a settlement on every cycle). The filter's "
        "blocked count is on the verdict.")
    hour = 3_600_000

    def blocked(step_h, n, cycle, recorded=False):
        orders = [PLAN_END + k * step_h * hour for k in range(n)]
        funding = ([{"settle_ms": PLAN_END + k * cycle * hour + 3000, "rate": 0.0001,
                     "cycle_h": cycle} for k in range(n * step_h // cycle + 1)]
                   if recorded else None)
        ok, short, flag = vfl.funding_minutes(orders, funding, cycle)
        assert ok == short and set(flag) == ({""} if recorded else {"settle_by_cycle"})
        return ok.count(False)

    for recorded in (False, True):
        # 1d: every order, whatever the cycle
        assert [blocked(24, 5, c, recorded) for c in (8, 4, 1)] == [5, 5, 5]
        # 4h: all six of a 4-hour coin's orders a day, half of an 8-hour coin's
        assert blocked(4, 6, 4, recorded) == 6 and blocked(4, 6, 8, recorded) == 3
        assert blocked(4, 6, 1, recorded) == 6
        # 1h: 6 of 24 on a 4-hour coin, 3 of 24 on an 8-hour coin, all 24 on a 1-hour coin
        assert [blocked(1, 24, c, recorded) for c in (4, 8, 1)] == [6, 3, 24]
    # funding_side: where the history cannot judge, the signal passes and is counted funding_unknown
    midnights = [PLAN_END + k * DAY for k in range(5)]
    long_ok, short_ok, flag = vfl.funding_side(midnights, None)
    assert (long_ok, short_ok, flag) == ([True] * 5, [True] * 5, ["funding_unknown"] * 5)
    assert vp.NOTES["funding_side"] == ("A signal the funding history cannot judge passes and is "
                                        "counted funding_unknown.")


def test_a_verdict_shows_how_far_the_random_runs_trades_fell_short_of_the_real_runs():
    # final review I1: the bar is kept as drawn - stricter than "as many trades" - and every verdict
    # says by how much: the real run's 320 unseen trades against the runs' median 100, and why the
    # other entries never traded, summed over both coins and every run
    coins = _two_coins(_rows(STEADY))
    for c, (short, inside, refused) in zip(coins, ((3, 40, {"no_levels": 150, "too_small": 2}),
                                                   (0, 45, {"no_levels": 60})), strict=True):
        c["combos"][KEY].update(random_short=short, random_in_trade=inside,
                                random_refused=refused)
    v = vp.verdict("v3_snap", "1h", "none", coins)
    made = v["random_runs"]
    assert made["real_trades"] == v["unseen"]["trades"] == 320
    assert made["median_trades"] == 200, "100 trades a run on each of the two coins, pooled run by run"
    assert made["not_traded"] == {"short": 3, "in_trade": 85, "no_levels": 210, "too_small": 2}
    # counts that are 0 are not kept, and a record measured before the counts were kept says
    # "not recorded" (None), never a zero nobody counted
    coins[1]["combos"][KEY].update(random_short=0, random_in_trade=0, random_refused={})
    assert vp.verdict("v3_snap", "1h", "none", coins)["random_runs"]["not_traded"] == {
        "short": 3, "in_trade": 40, "no_levels": 150, "too_small": 2}
    del coins[1]["combos"][KEY]["random_refused"]
    assert vp.verdict("v3_snap", "1h", "none", coins)["random_runs"]["not_traded"] is None
    assert vp.verdict("v3_snap", "1h", "none",
                      _two_coins(_rows(STEADY)))["random_runs"]["not_traded"] is None


def test_the_older_figures_carry_how_many_exits_paid_a_typical_cost():
    # final review M1: the evidence the setting was chosen on says how much of it paid an estimate
    coins = _two_coins(_rows(STEADY))
    for c in coins:
        c["combos"][KEY]["older"]["counts"] = {"cost_unmeasured": 30}
        c["combos"][KEY15]["older"]["counts"] = {"cost_unmeasured": 40, "unclear": 2}
    v = vp.verdict("v3_snap", "1h", "none", coins)
    assert (v["older"]["k2"]["trades"], v["older"]["k2"]["cost_unmeasured"]) == (80, 60)
    assert (v["older"]["k1.5"]["trades"], v["older"]["k1.5"]["cost_unmeasured"]) == (80, 80)
