"""Per-coin verdicts of Backtest v3 (operator, Nov 03, 2026: "tell me which are profitable? even
winrate is low as long as the win ratio is high"): every coin x judged group (family x timeframe x
filter) chooses its setting on THAT COIN'S older days (the best profit a trade with 10+ older
trades, a tie to the simplest) and is PROFITABLE when that setting made money after every fee on
the coin's unseen days with 20+ trades - beside the coin's own 200 random runs (their median
profit, the share that made at least as much, and the share that would be PROFITABLE by the same
rule: added up over the rows, the count luck alone gives). Kept as its own store; the pooled one
is untouched."""
import json

import pytest

import tests.test_v3_proof as tp
import tests.test_v3_verdicts as tv
from tradingagents import (
    backtest_report as br,
    v3_families as vf,
    v3_per_coin as vpc,
    v3_research as vrs,
    v3_verdicts as vv,
)

DAY = tp.DAY


def _rec(coin, older15, older2, unseen2, random2=tp.QUIET, *, unseen15=(), kind="crypto",
         unseen_candles=2160):
    """One coin's record of the snap family on 1h with no filter (`tests/test_v3_proof._coin`),
    as v3_measure writes it."""
    c = tp._coin(coin, older15, older2, unseen2, random2, unseen15)
    c |= {"version": 2, "kind": kind, "plan_id": "p", "plan_end_ms": tp.PLAN_END,
          "risk_usd": 5.0, "runs": 200, "skipped": {}}
    c["windows"]["1h"] |= {"older_candles": 6600, "unseen_candles": unseen_candles}
    return c


def _row(rec, fam="v3_snap", tf="1h", filt="none"):
    return vpc.judge(rec, fam, tf, filt)


def test_the_setting_is_chosen_on_the_coins_own_older_days_with_ten_trades():
    # k2 makes +0.10 a trade on 12 older trades, k1.5 +0.05 on 40: k2 is chosen on this coin
    rec = _rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 12), tp._rows([0.3] * 25))
    r = _row(rec)
    assert r["setting"] == "k2" and r["older"]["k2"] == [12, pytest.approx(0.10)]
    # 9 older trades are too few: k1.5 is chosen though it makes less a trade
    rec = _rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 9), tp._rows([0.3] * 25),
               unseen15=tp._rows([0.2] * 21))
    assert _row(rec)["setting"] == "k1.5"
    # a tie goes to the simplest, the family's first setting
    rec = _rec("AAA_USDT", tp._rows([0.1] * 10), tp._rows([0.1] * 10), [],
               unseen15=tp._rows([0.2] * 21))
    assert _row(rec)["setting"] == "k1.5"


def test_no_setting_with_ten_older_trades_could_not_choose_and_says_why():
    rec = _rec("AAA_USDT", tp._rows([0.05] * 9), tp._rows([0.10] * 3), [])
    r = _row(rec)
    assert r["setting"] is None and r["verdict"] == "could not choose" and not r["profitable"]
    assert r["why"] == "no setting had 10 trades on the older days"
    assert r["trades"] is None and r["profit"] is None and r["luck_profitable"] is None
    assert r["blank"] == "could not choose: no setting had 10 trades on the older days"


def test_profitable_is_money_after_every_fee_with_twenty_unseen_trades():
    older = (tp._rows([0.05] * 40), tp._rows([0.10] * 40))
    win = _row(_rec("AAA_USDT", *older, tp._rows([0.30] * 20)))
    assert win["profitable"] and win["verdict"] == "PROFITABLE" and win["trades"] == 20
    assert win["profit"] == pytest.approx(6.0)
    few = _row(_rec("AAA_USDT", *older, tp._rows([0.30] * 19)))
    assert not few["profitable"] and few["verdict"] == "not profitable: 19 trades, under 20"
    lost = _row(_rec("AAA_USDT", *older, tp._rows([0.30] * 10 + [-0.40] * 20)))
    assert not lost["profitable"] and lost["verdict"] == "not profitable: lost $5.00"
    flat = _row(_rec("AAA_USDT", *older, tp._rows([0.0] * 30)))
    assert not flat["profitable"], "made no money is not profitable"


def test_the_win_and_loss_sizes_and_their_ratio_are_kept():
    # 5 wins of +3.00 and 16 losses of -1.00: 24% won, a win is 3x a loss, -$1.00 overall
    rows = tp._rows([3.0] * 5 + [-1.0] * 16)
    r = _row(_rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40), rows))
    assert (r["wins"], r["losses"]) == (5, 16) and r["win_rate"] == pytest.approx(5 / 21)
    assert r["avg_win"] == pytest.approx(3.0) and r["avg_loss"] == pytest.approx(1.0)
    assert r["win_loss_ratio"] == pytest.approx(3.0)
    assert r["profit"] == pytest.approx(-1.0) and not r["profitable"]
    assert r["worst_run_usd"] == pytest.approx(-16.0) and r["worst_run_trades"] == 16


def test_beside_it_the_coins_own_random_runs_median_and_luck_shares():
    # runs make -0.2 .. +0.2 (100 trades each): 2 of 5 made money with 20+ trades
    r = _row(_rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40),
                  tp._rows([0.30] * 20)))
    assert r["random_median"] == pytest.approx(0.0) and r["random_runs"] == 200
    assert r["luck_share"] == 0.0, "no random run made the real run's +$6.00"
    assert r["luck_profitable"] == pytest.approx(0.4)
    # a run with 19 trades never counts as profitable by the rule, however much it made
    runs = [[19, 50.0]] * 100 + [[25, 1.0]] * 50 + [[25, -1.0]] * 50
    r = _row(_rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40),
                  tp._rows([0.30] * 20), runs))
    assert r["luck_profitable"] == pytest.approx(0.25) and r["luck_share"] == pytest.approx(0.5)


def test_trades_a_day_read_the_coins_own_unseen_days_and_months_green_its_months():
    # a coin listed late: 240 unseen 1h candles = 10 days, 20 trades = 2 a day
    rows = tp._rows([0.3] * 12 + [-0.1] * 8, per_day=1)
    r = _row(_rec("NEW_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40), rows,
                  unseen_candles=240))
    assert r["days"] == pytest.approx(10.0) and r["per_day"] == pytest.approx(2.0)
    assert r["months"] == {"2026-07": pytest.approx(2.1), "2026-08": pytest.approx(0.7)}
    assert r["green"] == [2, 4], "green months of the coin's unseen months (Jul - Oct)"


def test_a_coin_that_never_measured_a_group_has_no_row_for_it():
    rec = _rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40), [])
    assert vpc.judge(rec, "v3_trend", "1d", "none") is None


def test_the_id_is_stable_hashed_from_coin_group_and_setting_and_never_a_pooled_id():
    rec = _rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40), [])
    r = _row(rec)
    assert r["id"] == br.row_code("AAA_USDT", "1h", "v3_snap", 0, 0, 0, "flat",
                                  plan="percoin|none|k2", res="v3")
    assert r["id"] != vf.verdict_id("v3_snap", "1h", "none")
    assert _row(rec)["id"] == r["id"]
    none = _row(_rec("AAA_USDT", [], [], []))
    assert none["id"] == br.row_code("AAA_USDT", "1h", "v3_snap", 0, 0, 0, "flat",
                                     plan="percoin|none|none", res="v3")


def test_every_row_carries_every_field_judged_or_not():
    a = _row(_rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40),
                  tp._rows([0.30] * 20)))
    b = _row(_rec("BBB_USDT", [], [], []))
    c = _row(_rec("CCC_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40), []))
    assert set(a) == set(b) == set(c)
    assert c["verdict"] == "not profitable: no trade on the unseen days"
    assert c["blank"] == "no trade on the unseen days"


# ---- the store ---------------------------------------------------------------------------------


@pytest.fixture()
def run(monkeypatch, tmp_path):
    ns = tv.make_run(monkeypatch, tmp_path)
    monkeypatch.setattr(vpc, "store_path", lambda: tmp_path / "v3" / "verdicts-per-coin.json")
    monkeypatch.setattr(vpc, "history_dir", lambda: tmp_path / "v3" / "verdicts-per-coin")
    return ns


def test_publish_keeps_a_row_per_coin_and_group_and_counts_what_luck_would_give(run):
    path = vpc.publish("pilot", now=1_793_000_000.0)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == vpc.VERSION and data["plan_id"] == run.plan["id"]
    assert data["coins"] == ["XAG_USDT", "XAU_USDT"] and data["plan_coins"] == 4
    assert data["not_judged"]["failed"] == ["XPT_USDT: ConnectionError: cut"]
    # make_run's records measured snap 1h with no filter only: one row per coin
    assert [(r["coin"], r["family"], r["tf"], r["filter"]) for r in data["rows"]] == [
        ("XAG_USDT", "v3_snap", "1h", "none"), ("XAU_USDT", "v3_snap", "1h", "none")]
    assert all(r["profitable"] and r["trades"] == 200 for r in data["rows"])
    t = data["totals"]
    assert (t["rows"], t["profitable"], t["could_not_choose"]) == (2, 2, 0)
    assert t["luck_profitable"] == pytest.approx(0.8), "0.4 a row from QUIET's runs, added up"
    assert data["rule"] == vpc.RULE and "10" in vpc.RULE and "20" in vpc.RULE
    assert (data["min_older"], data["min_unseen"]) == (10, 20)
    kept = list((run.tmp / "v3" / "verdicts-per-coin").iterdir())
    assert [p.name for p in kept] == ["pilot-1793000000000.json"]


def test_the_pooled_store_is_untouched_by_a_per_coin_publish(run):
    pooled = run.tmp / "v3" / "verdicts.json"
    vpc.publish("pilot", now=1_793_000_000.0)
    assert not pooled.exists()
    vv.publish("pilot", now=1_793_000_000.0)
    before = pooled.read_bytes()
    vpc.publish("pilot", now=1_793_000_100.0)
    assert pooled.read_bytes() == before


def test_a_redos_name_and_an_uncollected_run_are_refused_as_the_pooled_store_refuses(run):
    with pytest.raises(ValueError, match="publish pilot"):
        vpc.publish("pilot-redo1")
    (run.tmp / "cloud" / "pilot-collected.json").unlink()
    with pytest.raises(ValueError, match="not collected yet"):
        vpc.publish("pilot")


def test_the_cli_prints_the_counts_and_the_profitable_rows(run, capsys):
    assert vpc.main(["publish", "pilot"]) == 0
    out = capsys.readouterr().out
    assert "2 coin x idea rows judged on 2 coins" in out
    assert "2 profitable" in out and "luck alone would make 0.8" in out
    assert out.count("PROFITABLE") >= 2


def test_a_record_left_unjudged_is_named_in_its_bucket(run):
    vrs.save_coin(run.folder, tv._record("XPT_USDT", run.plan, [], risk=1.0))
    data = json.loads(vpc.publish("pilot").read_text(encoding="utf-8"))
    assert data["not_judged"]["other_records"] == ["XPT_USDT: risk $1.00, not $5.00"]


# ---- ruling, Nov 03, 2026: a setting is chosen only when it made money on the older days ---------


def test_a_best_setting_that_lost_on_the_older_days_is_not_chosen():
    # k1.5 -0.05 a trade over 40, k2 -0.02 over 12: k2 is the best, and it lost
    rec = _rec("AAA_USDT", tp._rows([-0.05] * 40), tp._rows([-0.02] * 12), tp._rows([0.3] * 25))
    r = _row(rec)
    assert r["setting"] is None and r["verdict"] == "could not choose" and not r["profitable"]
    assert r["why"] == ("no setting made money on the older days "
                        "(best: k2 -$0.02 a trade over 12 trades)")
    assert r["blank"] == "could not choose: " + r["why"]
    assert r["trades"] is None and r["luck_profitable"] is None and r["luck_share"] is None


def test_a_setting_that_made_money_is_chosen_over_a_better_one_with_too_few_trades():
    # k2 +1.00 a trade over 9 (too few), k1.5 +0.01 over 10: k1.5 made money, it is chosen
    rec = _rec("AAA_USDT", tp._rows([0.01] * 10), tp._rows([1.0] * 9), [],
               unseen15=tp._rows([0.2] * 21))
    assert _row(rec)["setting"] == "k1.5"
    # zero on the older days is not money made
    rec = _rec("AAA_USDT", tp._rows([0.0] * 40), tp._rows([-0.1] * 40), [])
    assert _row(rec)["setting"] is None


def test_the_luck_total_counts_only_the_rows_whose_setting_was_chosen():
    good = _row(_rec("AAA_USDT", tp._rows([0.05] * 40), tp._rows([0.10] * 40),
                     tp._rows([0.30] * 20)))
    # the same random runs, but the coin's settings all lost on the older days
    bad = _row(_rec("BBB_USDT", tp._rows([-0.05] * 40), tp._rows([-0.10] * 40),
                    tp._rows([0.30] * 20)))
    t = vpc.totals([good, bad])
    assert (t["rows"], t["profitable"], t["could_not_choose"]) == (2, 1, 1)
    assert t["luck_profitable"] == pytest.approx(0.4), "BBB's runs are never luck's"
