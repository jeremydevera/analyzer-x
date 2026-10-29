"""The Backtest v3 Part 2a command (`python -m tradingagents.v3_research`): it
builds the plan, measures a few coins, prints the order books' coverage FIRST
and then every verdict with the standard kit's figures, says every rule and
figure from the code that decides it, and never pools a coin measured under
another plan BUILD, plan end, risk or random-run count."""
import calendar
import json
from pathlib import Path

import pytest

from tradingagents import (
    v3_families as vf,
    v3_measure as vm,
    v3_proof as vp,
    v3_random as vrn,
    v3_research as vr,
    v3_rules,
    v3_universe as vu,
)
from tradingagents.positions_view import fmt_when

DAY = 86_400_000
END = calendar.timegm((2026, 10, 23, 0, 0, 0)) * 1000
D0 = END - 90 * DAY
KEY = vf.combo_key("v3_snap", "k2", "1h", "none")
KEY15 = vf.combo_key("v3_snap", "k1.5", "1h", "none")
TRAIL = "a trailing stop 3 x ATR(20), never loosened"


def _rows(pnls, per_day=4):
    return [[D0 + (k // per_day) * DAY, D0 + (k // per_day) * DAY + 60_000,
             D0 + (k // per_day) * DAY + 3_600_000, 1, p, "TP"] for k, p in enumerate(pnls)]


def _walk(rows, **extra):
    return {"rows": rows, "counts": {"cost_unmeasured": 5}, "filter": {"signal_candles": 9},
            "twins": [1, 0.5], "lev": [20, 20], "notional": [45.0, 130.0], "over_book": 2,
            **extra}


def _plan():
    return {"version": vu.VERSION, "venue": "Gate", "start_ms": END - 365 * DAY, "end_ms": END}


PLAN_ID = vu.plan_id(_plan())


def _record(coin="XAU_USDT", end=END, risk=1.0, runs=200, build=PLAN_ID):
    """A coin whose snap 1h k2 makes +0.10 a trade on 40 older trades and +0.20 on 320 unseen
    ones (1.2 and -0.8 in turn), against random runs of -0.002..+0.002 a trade."""
    quiet = [[100, 0.1 * ((k % 5) - 2)] for k in range(200)]
    return {"coin": coin, "kind": "metals", "plan_id": build, "plan_end_ms": end, "runs": runs,
            "risk_usd": risk, "version": vm.VERSION,
            "pre": {"coverage_older": 0.0, "coverage_unseen": 0.712, "flat_slip": 0.00012,
                    "flat_slip_source": "the median of its 95,012 recorded minutes"},
            "windows": {"1h": {"split": "Jul 24, 2026 8:00pm"}}, "skipped": {},
            "combos": {KEY15: {"older": _walk(_rows([0.05] * 40)), "unseen": _walk([]),
                               "random": [[0, 0.0]] * 200},
                       KEY: {"older": _walk(_rows([0.10] * 40)),
                             "unseen": _walk(_rows([1.2, -0.8] * 160)), "random": quiet}}}


def _verdict(verdicts, family="v3_snap", tf="1h", filt="none"):
    return next(v for v in verdicts if (v["family"], v["tf"], v["filter"]) == (family, tf, filt))


def test_the_report_prints_coverage_first_then_every_verdict_with_the_kits_figures():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    text = "\n".join(lines)
    assert len(verdicts) == 27 and sum(v["passed"] for v in verdicts) == 1
    assert ("63 combinations tried (14 family-setting-timeframes x 5 filter choices, less the 7 "
            "not tried: funding_minutes on 1d), alpha = 0.05 / 63, z = 3.355") in lines[1]
    assert "$1.00 risk a trade" in lines[1]
    cover = next(k for k, ln in enumerate(lines) if ln.startswith("XAU_USDT (metals)"))
    first = next(k for k, ln in enumerate(lines) if ln.startswith("#"))
    assert cover < first, "COVERAGE FIRST"
    assert "71.2% of the unseen days'" in lines[cover] and "0.01200% a side" in lines[cover]
    snap = "\n".join(vr.verdict_lines(next(v for v in verdicts if v["passed"])))
    # 320 trades over the 90 unseen days, 160 won (+1.2) and 160 lost (-0.8): +$64.00
    assert f"#{vf.verdict_id('v3_snap', '1h', 'none')} v3_snap 1h none: setting k2 - PASSED" in snap
    assert "320 trades (3.56 a day), 160 won / 160 lost, 50.0%" in snap
    assert "(break-even 40.0%)" in snap, "0.8 / (1.2 + 0.8)"
    assert "PROFIT +$64.00, +$0.200 a trade" in snap
    assert "worst losing run -$0.80 over 1 trade" in snap and "1 trades" not in snap
    assert "target: the 20-candle average at the signal, resting" in snap
    assert "leverage 20x-20x" in snap
    assert "$45-$130 of coin a trade (2 over the books' $100)" in snap
    assert "exits at a typical cost 5 of 320" in snap and "1 of 27 verdicts passed." in text
    assert "refused signal candles: under one lot 0, no safe leverage 0, the cost check 0" in snap
    assert vr.CRASH_GUARD in text and vr.FEW_COINS in text and vu.SURVIVORSHIP in text


def test_a_chosen_setting_with_no_unseen_trade_says_so_in_one_line():
    rec = _record()
    rec["combos"][KEY]["unseen"] = _walk([])
    lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    snap = _verdict(verdicts)
    assert vr.verdict_lines(snap) == [
        f"#{snap['id']} v3_snap 1h none: setting k2 - FAILED at profit: no trade on the unseen "
        "days (older days: k1.5 +$0.050 a trade over 40 (exits at a typical cost 5 of 40), k2 "
        "+$0.100 a trade over 40 (exits at a typical cost 5 of 40))"]


def test_a_group_no_coin_measured_says_so_in_one_line():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    trend = _verdict(verdicts, "v3_trend", "1d")
    assert vr.verdict_lines(trend) == [
        f"#{trend['id']} v3_trend 1d none: FAILED at choose - no coin measured v3_trend on 1d "
        "(older days: n20 - a trade over 0 (too few), n50 - a trade over 0 (too few), n100 - a "
        "trade over 0 (too few))"]


# --- the pool: one plan BUILD, one plan end, one risk, one run count -------------------------------


def test_differences_names_each_field_that_differs_with_both_values():
    plan = {**_plan(), "id": PLAN_ID}
    assert vr.differences(_record(), plan, 200, 1.0) == []
    assert vr.differences(_record(build="ab12"), plan, 200, 1.0) == [
        f"plan build ab12, not {PLAN_ID}"]
    assert vr.differences(_record(end=END - DAY), plan, 200, 1.0) == [
        f"plan end {fmt_when((END - DAY) / 1000)}, not {fmt_when(END / 1000)}"]
    assert vr.differences(_record(risk=5.0), plan, 200, 1.0) == ["risk $5.00, not $1.00"]
    assert vr.differences(_record(runs=20), plan, 200, 1.0) == ["20 random runs, not 200"]
    # several at once: every one is named
    assert vr.differences(_record(risk=5.0, runs=20), plan, 200, 1.0) == [
        "risk $5.00, not $1.00", "20 random runs, not 200"]
    # a record that does not say is never assumed to fit - least of all to be $1
    assert vr.differences({"coin": "OLD_USDT"}, plan, 200, 1.0) == [
        f"plan build not recorded, not {PLAN_ID}",
        f"plan end not recorded, not {fmt_when(END / 1000)}",
        "no risk recorded", "no run count recorded",
        f"record version not recorded, not {vm.VERSION}"]
    # a record of another version (1: its rows have no stop or target) is named, never pooled
    assert vr.differences({**_record(), "version": 1}, plan, 200, 1.0) == [
        f"record version 1, not {vm.VERSION}"]


def test_judge_pools_only_the_coins_of_this_plan_and_names_every_other_with_its_reason(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    root = tmp_path / "local"
    vr.save_coin(root, _record())
    vr.save_coin(root, _record("OLD_USDT", end=END - DAY))
    vr.save_coin(root, _record("BIG_USDT", risk=5.0))
    vr.save_coin(root, _record("FEW_USDT", runs=20))
    vr.save_coin(root, _record("REBUILT_USDT", build="0123456789abcdef"))
    unstamped, unpriced = _record("UNSTAMPED_USDT"), _record("NORISK_USDT")
    del unstamped["plan_id"], unpriced["risk_usd"]
    vr.save_coin(root, {**_record("V1_USDT"), "version": 1})
    vr.save_coin(root, unstamped)
    vr.save_coin(root, unpriced)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["judge", "--plan", str(plan_path), "--risk", "1"]) == 0
    lines = capsys.readouterr().out.splitlines()
    # the header, then the left-out line - before any coverage line - then the one coin pooled
    assert lines[0].startswith("Backtest v3 Part 2a on Gate: 1 coin(s) measured;")
    assert lines[2].startswith("left out, not measured under this plan build, plan end, risk, "
                               "run count and record version: ")
    assert lines[3].startswith("XAU_USDT (metals)")
    for reason in ("BIG_USDT (risk $5.00, not $1.00)", "FEW_USDT (20 random runs, not 200)",
                   "NORISK_USDT (no risk recorded)",
                   f"OLD_USDT (plan end {fmt_when((END - DAY) / 1000)}, "
                   f"not {fmt_when(END / 1000)})",
                   f"REBUILT_USDT (plan build 0123456789abcdef, not {PLAN_ID})",
                   f"V1_USDT (record version 1, not {vm.VERSION})",
                   f"UNSTAMPED_USDT (plan build not recorded, not {PLAN_ID})"):
        assert reason in lines[2]
    saved = json.loads((root / "verdicts.json").read_text(encoding="utf-8"))["verdicts"]
    snap = next(v for v in saved if v["passed"])
    assert snap["coins"] == ["XAU_USDT"] and snap["unseen"]["trades"] == 320


def test_two_builds_of_one_day_are_never_pooled_and_the_other_is_named(
        monkeypatch, tmp_path, capsys):
    # one UTC day is one end instant: a plan built again after a throttled read ends where the first
    # did, with one coin's group changed. They are two plans, and only their content says so
    first = {**_plan(), "calm": {"2026-10": ["BTC_USDT", "XAU_USDT"]}}
    second = {**_plan(), "calm": {"2026-10": ["BTC_USDT"]}}
    assert first["end_ms"] == second["end_ms"] and vu.plan_id(first) != vu.plan_id(second)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    root = tmp_path / "local"
    vr.save_coin(root, _record("AAA_USDT", build=vu.plan_id(first)))
    vr.save_coin(root, _record("BBB_USDT", build=vu.plan_id(second)))
    for plan, other, kept, left in ((first, second, "AAA_USDT", "BBB_USDT"),
                                    (second, first, "BBB_USDT", "AAA_USDT")):
        path = vu.save(plan, tmp_path / "plan.json")
        assert vr.main(["judge", "--plan", str(path), "--risk", "1"]) == 0
        out = capsys.readouterr().out
        assert "1 coin(s) measured" in out
        assert f"{left} (plan build {vu.plan_id(other)}, not {vu.plan_id(plan)})" in out
        saved = json.loads((root / "verdicts.json").read_text(encoding="utf-8"))["verdicts"]
        assert next(v for v in saved if v["passed"])["coins"] == [kept]


def test_run_measures_each_coin_saves_it_judges_it_and_prints_its_line(
        monkeypatch, tmp_path, capsys):
    from tradingagents import v3_measure

    asked = []

    def fake(sym, plan, *, runs, risk_usd, log=None):
        asked.append((sym, runs, risk_usd))
        return {**_record(sym, risk=risk_usd), "runs": runs, "plan_id": plan["id"]}

    monkeypatch.setattr(v3_measure, "measure_coin", fake)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["run", "xau_usdt", "--plan", str(plan_path), "--runs", "3",
                    "--label", "t"]) == 0
    assert asked == [("XAU_USDT", 3, 5.0)], "the research's $5 unless --risk says otherwise"
    assert vr.coin_file(tmp_path / "t", "XAU_USDT").exists()
    out = capsys.readouterr().out
    assert "XAU_USDT (metals): order books cover 0.0%" in out
    # the command judges what it has just measured: the coin it stamped is pooled, none left out
    assert "1 coin(s) measured" in out and "left out" not in out


def test_the_research_measures_at_5_dollars_a_trade_and_risk_still_overrides(
        monkeypatch, tmp_path, capsys):
    # the operator's pick, Oct 27, 2026: at $1 ETH's daily trend could not take one lot on 228 of
    # 228 signals. The tab's own default ($1) is not the research's
    from tradingagents import v3_measure, v3_rules

    assert v3_rules.RESEARCH_RISK_USD == 5.0 and v3_rules.RISK_USD == 1.0
    asked = []

    def fake(sym, plan, *, runs, risk_usd, log=None):
        asked.append(risk_usd)
        return {**_record(sym, risk=risk_usd), "runs": runs, "plan_id": plan["id"]}

    monkeypatch.setattr(v3_measure, "measure_coin", fake)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    base = ["--plan", str(plan_path), "--runs", "200"]
    assert vr.main(["run", "aaa_usdt", *base]) == 0
    assert "$5.00 risk a trade" in capsys.readouterr().out
    # judge names the same default: a record measured at the research's $5 is pooled, and one at
    # the tab's $1 is left out with both figures
    vr.save_coin(tmp_path / "local", _record("TAB_USDT", risk=1.0))
    assert vr.main(["judge", *base]) == 0
    out = capsys.readouterr().out
    assert "1 coin(s) measured" in out and "TAB_USDT (risk $1.00, not $5.00)" in out
    # --risk wins, on both commands
    assert vr.main(["run", "bbb_usdt", *base, "--risk", "2.5"]) == 0
    assert asked == [5.0, 2.5]
    assert "$2.50 risk a trade" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        vr.main(["run", "--help"])
    assert "default $5.00" in capsys.readouterr().out


def test_a_coin_that_fails_is_named_its_old_record_dropped_and_the_others_still_measured(
        monkeypatch, tmp_path, capsys):
    from tradingagents import v3_measure

    root = tmp_path / "local"
    vr.save_coin(root, _record("BAD_USDT"))        # an earlier measurement of the coin that fails
    asked = []

    def fake(sym, plan, *, runs, risk_usd, log=None):
        asked.append(sym)
        if sym == "BAD_USDT":
            raise RuntimeError("the exchange refused the read")
        return {**_record(sym, risk=risk_usd), "runs": runs, "plan_id": plan["id"]}

    monkeypatch.setattr(v3_measure, "measure_coin", fake)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    code = vr.main(["run", "aaa_usdt", "bad_usdt", "ccc_usdt", "--plan", str(plan_path),
                    "--runs", "200"])
    out = capsys.readouterr().out
    assert code == 1, "a script chain must notice"
    assert asked == ["AAA_USDT", "BAD_USDT", "CCC_USDT"], "the rest go on after the one that failed"
    assert "FAILED BAD_USDT: RuntimeError: the exchange refused the read" in out
    assert not vr.coin_file(root, "BAD_USDT").exists(), "a failed redo leaves no old record to pool"
    assert vr.coin_file(root, "AAA_USDT").exists() and vr.coin_file(root, "CCC_USDT").exists()
    assert "2 coin(s) measured" in out, "what was saved is judged"
    last = out.rstrip().splitlines()[-1]
    assert last == "1 coin(s) failed and were left out: BAD_USDT"


def test_a_run_where_every_coin_is_fine_returns_zero_and_names_no_failure(
        monkeypatch, tmp_path, capsys):
    from tradingagents import v3_measure

    monkeypatch.setattr(v3_measure, "measure_coin", lambda sym, plan, *, runs, risk_usd, log=None:
                        {**_record(sym, risk=risk_usd), "runs": runs, "plan_id": plan["id"]})
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["run", "aaa_usdt", "--plan", str(plan_path), "--runs", "200"]) == 0
    out = capsys.readouterr().out
    # a verdict that failed its checks says "FAILED at ..."; a coin that failed is a line of its own
    assert not any(ln.startswith("FAILED ") for ln in out.splitlines())
    assert "coin(s) failed" not in out


def test_plan_builds_the_universe_and_names_every_coin_it_skipped(monkeypatch, tmp_path, capsys):
    plan = {**_plan(), "start": "Oct 23, 2025 8:00pm", "end": "Oct 22, 2026 8:00pm",
            "months": ["2026-10"], "coins": ["BTC_USDT"], "liquid": {"2026-10": ["BTC_USDT"]},
            "calm": {"2026-10": []}, "skipped": {"BAD_USDT": "RuntimeError: no Day1 candles"},
            "left_out": {"BVOL_USDT": "a volatility index: it jumps by design, so it is never calm"}}
    monkeypatch.setattr(vu, "collect", lambda **k: plan)
    assert vr.main(["plan", "--out", str(tmp_path / "plan.json")]) == 0
    out = capsys.readouterr().out
    assert "1 skipped" in out and "skipped BAD_USDT: RuntimeError: no Day1 candles" in out
    assert "1 left out" in out
    assert "left out BVOL_USDT: a volatility index: it jumps by design, so it is never calm" in out
    assert vu.load(tmp_path / "plan.json")["coins"] == ["BTC_USDT"]


def test_a_coin_named_in_chinese_is_filed_under_plain_ascii(tmp_path):
    # the cost store's rule: "x" + the name's UTF-8 in hex
    assert vr.coin_file(tmp_path, "龙虾_USDT").name == "x" + "龙虾_USDT".encode().hex() + ".json.gz"
    assert vr.coin_file(tmp_path, "BTC_USDT").name == "BTC_USDT.json.gz"
    rec = vr.save_coin(tmp_path, {"coin": "龙虾_USDT", "combos": {}})
    assert vr.load_coins(tmp_path) == [{"coin": "龙虾_USDT", "combos": {}}] and rec.exists()


# --- the label is one plain folder name ------------------------------------------------------------


@pytest.mark.parametrize("label", ["C:\\temp\\x", "/tmp/x", "../x", "..", ".", "a/b", "a\\b", "",
                                   "x y", "x:y", "a..b"])
def test_a_label_is_one_plain_folder_name_and_anything_else_is_refused_by_name(label, capsys):
    # an absolute label would put the records on the system drive, and ".." would leave the store
    with pytest.raises(SystemExit) as refused:
        vr.main(["judge", "--label", label])
    assert refused.value.code == 2
    assert repr(label) in capsys.readouterr().err
    with pytest.raises(ValueError, match="not a plain folder name"):
        vr.home(label)


def test_a_plain_label_is_filed_under_the_stores_research_folder():
    from tradingagents import stores

    for label in ("local", "run-2", "a_b.c", "2026.10"):
        assert vr.home(label) == Path(stores.V3.home) / "research" / label


# --- every printed rule and figure is read from the code that decides it ---------------------------


@pytest.mark.parametrize("family, key, tf, words", [
    ("v3_trend", "n50", "1d", ("none; out on a close past its 50-day average", TRAIL)),
    ("v3_trend", "n50", "4h", ("none; out on a close past its 50-day average", TRAIL)),
    ("v3_breakout", "n20", "1d", ("none", TRAIL)),
    ("v3_strength", "k3", "1d", ("none; out at a Monday 00:00 UTC rank outside the top 6", TRAIL)),
    ("v3_snap", "k1.5", "1h", ("the 20-candle average at the signal, resting; out after 24 "
                               "candles",
                               "an emergency stop 3 x ATR(20) at the market")),
    ("v3_snap", "k2", "4h", ("the 20-candle average at the signal, resting; out after 24 "
                             "candles",
                             "an emergency stop 3 x ATR(20) at the market"))])
def test_each_familys_target_and_stop_are_said_in_words(family, key, tf, words):
    assert vr.exit_words(family, key, tf) == words
    assert vr.exit_words(family, key) == words, "the timeframe changes no word"


def test_the_words_move_with_the_numbers_the_walk_reads(monkeypatch):
    monkeypatch.setattr(v3_rules, "TRAIL_ATR", 2.5)
    monkeypatch.setattr(v3_rules, "ATR_N", 14)
    monkeypatch.setattr(vf, "SNAP_N", 10)
    monkeypatch.setattr(vf, "SNAP_MAX_BARS", 48)
    monkeypatch.setattr(vf, "STRENGTH_KEEP", 3)
    trail = "a trailing stop 2.5 x ATR(14), never loosened"
    assert vr.exit_words("v3_trend", "n20") == ("none; out on a close past its 20-day average",
                                                trail)
    assert vr.exit_words("v3_breakout", "n50") == ("none", trail)
    assert vr.exit_words("v3_strength", "k3") == (
        "none; out at a Monday 00:00 UTC rank outside the top 9", trail)
    assert vr.exit_words("v3_snap", "k2") == (
        "the 10-candle average at the signal, resting; out after 48 candles",
        "an emergency stop 2.5 x ATR(14) at the market")


def test_every_combination_prints_words_that_say_what_its_exit_spec_says():
    for family, key, tf, _filt in vf.combos():
        spec = vf.exit_spec(family, float(key[1:]), tf)
        target, stop = vr.exit_words(family, key, tf)
        if spec["kind"] == "snap":
            assert f"{spec['stop_atr']:g} x ATR({v3_rules.ATR_N}) at the market" in stop
            assert target == (f"the {spec['mean_n']}-candle average at the signal, resting; "
                              f"out after {spec['max_bars']} candles")
        else:
            assert f"{spec['atr_mult']:g} x ATR({v3_rules.ATR_N}), never loosened" in stop
            if spec["ma_n"]:
                assert f"past its {spec['ma_n'] / vf.BARS_PER_DAY[tf]:g}-day average" in target
            else:
                assert target.startswith("none")


def test_an_unknown_family_is_refused_by_name_never_given_the_snaps_words():
    with pytest.raises(ValueError, match="v3_future"):
        vr.exit_words("v3_future", "k1")


def test_the_header_names_the_venue_the_runs_the_risk_the_window_and_the_corrections_figures(
        monkeypatch):
    plan = {**_plan(), "venue": "Other"}
    lines, _ = vr.report([_record(risk=2.5, runs=50)], plan, 50, 2.5)
    start, split, end = vm.windows(plan)
    assert lines[0] == (
        f"Backtest v3 Part 2a on Other: 1 coin(s) measured; the window {fmt_when(start / 1000)} "
        f"to {fmt_when(end / 1000)} - older days to {fmt_when(split / 1000)}, then "
        f"{vm.UNSEEN_DAYS} unseen days; 50 random runs a combination")
    assert "$2.50 risk a trade" in lines[1]
    assert vr.report([_record()], {**_plan(), "venue": ""}, 200, 1.0)[0][0].startswith(
        "Backtest v3 Part 2a on the exchange: ")
    # the correction and the window are the code's own: change them there and the line follows
    monkeypatch.setattr(vp, "ALPHA", 0.01)
    monkeypatch.setattr(vm, "UNSEEN_DAYS", 30)
    lines, _ = vr.report([_record()], _plan(), 200, 1.0)
    assert f"alpha = 0.01 / {vp.TRIED}, z = {vp.z_for(vp.TRIED, 0.01):.3f}" in lines[1]
    assert "then 30 unseen days" in lines[0]
    assert f"older days to {fmt_when((END - 30 * DAY) / 1000)}" in lines[0]


def test_the_books_dollars_in_a_verdict_line_are_the_measures_own(monkeypatch):
    _lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    snap = next(v for v in verdicts if v["passed"])
    assert "(2 over the books' $100)" in "\n".join(vr.verdict_lines(snap))
    monkeypatch.setattr(vm, "BOOK_USD", 250.0)
    assert "(2 over the books' $250)" in "\n".join(vr.verdict_lines(snap))


def test_the_default_run_count_is_the_random_runs_own(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vrn, "RUNS", 7)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    vr.save_coin(tmp_path / "local", _record(runs=7))
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["judge", "--plan", str(plan_path), "--risk", "1"]) == 0
    out = capsys.readouterr().out
    assert "1 coin(s) measured" in out and "7 random runs a combination" in out


# --- what a verdict line says ----------------------------------------------------------------------


def test_a_verdict_whose_random_runs_never_traded_says_how_many_were_made():
    rec = _record()
    rec["combos"][KEY]["random"] = [[0, 0.0]] * 200
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    snap = _verdict(verdicts)
    assert snap["failed"] == "random" and snap["random"] is None
    assert "random runs: median -, bar - (0 of 200 traded)" in "\n".join(vr.verdict_lines(snap))
    rec["combos"][KEY]["random"] = [[10, 1.0]] + [[0, 0.0]] * 199
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    assert "(1 of 200 traded)" in "\n".join(vr.verdict_lines(_verdict(verdicts)))


def test_a_single_trade_or_day_is_not_pluralised():
    rec = _record()
    rec["combos"][KEY]["unseen"] = _walk(_rows([0.5]))
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    text = "\n".join(vr.verdict_lines(_verdict(verdicts)))
    assert "unseen: 1 trade (0.01 a day), 1 won / 0 lost" in text
    assert "bootstrap low - over 1 day;" in text and "worst losing run +$0.00 over 0 trades" in text
    assert "1 trades" not in text and "1 days" not in text


def test_each_verdict_prints_its_filters_note_beneath_it_and_the_survivorship_line_once():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    text = "\n".join(lines)
    for filt, note in vp.NOTES.items():
        group = [v for v in verdicts if v["filter"] == filt]
        assert group, filt
        for v in group:
            assert vr.verdict_lines(v)[-1] == f"   note: {note}", (v["id"], filt)
        assert text.count(f"   note: {note}") == len(group)
    plain = _verdict(verdicts)
    assert not any(ln.startswith("   note:") for ln in vr.verdict_lines(plain))
    # the survivorship line every verdict carries is said once, at the foot, never under each
    assert text.count(vu.SURVIVORSHIP) == 1


def test_the_header_counts_only_the_coins_measured_and_says_how_many_were_in_no_universe():
    idle = {"coin": "AAPL_USDT", "kind": "stocks", "plan_id": PLAN_ID, "plan_end_ms": END,
            "runs": 200, "risk_usd": 1.0, "version": vm.VERSION, "windows": {}, "combos": {}, "skipped": {},
            "why": "in no family's universe in any month of the plan"}
    lines, _ = vr.report([_record(), idle], _plan(), 200, 1.0)
    assert ": 1 coin(s) measured, 1 in no family's universe; the window " in lines[0]
    assert "AAPL_USDT: in no family's universe in any month of the plan" in lines
    lines, _ = vr.report([_record()], _plan(), 200, 1.0)
    assert "in no family's universe" not in lines[0]


def test_a_group_that_failed_at_the_choice_for_want_of_a_lot_says_so_on_its_line():
    # ETH on 1d at $1: every signal candle of every setting was under one lot
    refused = {"older": _walk([], counts={"too_small": 76}, filter={"signal_candles": 76}),
               "unseen": _walk([]), "random": [[0, 0.0]] * 200}
    rec = _record()
    rec["combos"] = {vf.combo_key("v3_trend", k, "1d", "none"): refused
                     for k in ("n20", "n50", "n100")}
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    (line,) = vr.verdict_lines(_verdict(verdicts, "v3_trend", "1d"))
    assert (": FAILED at choose - no setting had 30 trades on the older days: 228 of 228 "
            "signals over the 3 settings (a candle counts once for each setting it signals under) "
            "were under one lot at $1.00 risk (older days: ") in line


# --- the final review's fixes (Oct 27, 2026) -------------------------------------------------------


def test_every_verdict_says_how_far_the_random_runs_trades_fell_short_of_the_real_runs():
    rec = _record()
    rec["combos"][KEY].update(random_short=0, random_in_trade=85,
                              random_refused={"no_levels": 210, "missed": 4})
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    lines = vr.verdict_lines(_verdict(verdicts))
    assert lines[2] == (
        "   random runs traded a median 100 of the real run's 320 trades; over the 200 runs, "
        "entries that never traded: 210 had no target or stop (ATR or the average not ready, or a "
        "snap drawn on the far side of its average), 85 fell inside the run's own open trade, 4 "
        "rested and never filled")
    # every reason the measurement can keep has its words
    assert {k for k, _w in vr.NOT_TRADED_WORDS} == {"short", "in_trade", *vm.DROPS}
    # nothing refused, and a record that did not keep the reasons
    rec["combos"][KEY].update(random_in_trade=0, random_refused={})
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    assert vr.verdict_lines(_verdict(verdicts))[2].endswith(
        "over the 200 runs, every entry they placed traded")
    del rec["combos"][KEY]["random_refused"]
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    assert vr.verdict_lines(_verdict(verdicts))[2] == (
        "   random runs traded a median 100 of the real run's 320 trades; why their other entries "
        "never traded was not recorded")


def test_the_counts_line_names_each_counts_unit_and_the_filters_unjudged_signals():
    # final review M2: funding_estimated counts TRADES, the filters' counts SIGNAL CANDLES
    rec = _record()
    rec["combos"][KEY]["unseen"]["counts"] = {"cost_unmeasured": 5, "funding_estimated": 7}
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    text = "\n".join(vr.verdict_lines(_verdict(verdicts)))
    assert ("funding estimated on 7 of 320 trades; filter blocked 0 of 9 signal candles; refused"
            in text)
    assert "could not judge" not in text and "by the settlement cycle" not in text
    # a filter's unjudged signals are said where there are any, with the filter that counted them
    for filt, count, words in (
            ("funding_side", "funding_unknown",
             "funding_side could not judge 4 of 9 signal candles (they passed)"),
            ("btc_mood", "mood_unknown",
             "btc_mood could not judge 4 of 9 signal candles (they passed)"),
            ("funding_minutes", "settle_by_cycle",
             "funding_minutes judged 4 of 9 signal candles by the settlement cycle "
             "(no recorded settlement)")):
        key = vf.combo_key("v3_snap", "k2", "1h", filt)
        r = _record()
        r["combos"] = {key: {**r["combos"][KEY]},
                       vf.combo_key("v3_snap", "k1.5", "1h", filt): r["combos"][KEY15]}
        r["combos"][key]["unseen"] = _walk(_rows([1.2, -0.8] * 160),
                                           filter={"signal_candles": 9, count: 4})
        _lines, verdicts = vr.report([r], _plan(), 200, 1.0)
        text = "\n".join(vr.verdict_lines(_verdict(verdicts, filt=filt)))
        assert f"filter blocked 0 of 9 signal candles; {words}; refused" in text, filt


def test_a_4h_funding_minutes_group_that_traded_nothing_unseen_still_prints_what_it_blocked():
    # final review I2: on a coin that settles every 4 hours every 4h order goes in on a settlement
    # hour, so funding_minutes blocks them all - the line says how many, and the note says why
    key = vf.combo_key("v3_trend", "n20", "4h", "funding_minutes")
    rec = _record("XAU_USDT")
    rec["windows"] = {"4h": {"split": "Jul 24, 2026 8:00pm"}}
    rec["combos"] = {key: {"older": _walk(_rows([0.10] * 40)),
                           "unseen": _walk([], counts={},
                                           filter={"signal_candles": 12, "blocked": 12}),
                           "random": [[0, 0.0]] * 200}}
    _lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    v = _verdict(verdicts, "v3_trend", "4h", "funding_minutes")
    lines = vr.verdict_lines(v)
    assert lines[0].startswith(f"#{v['id']} v3_trend 4h funding_minutes: setting n20 - FAILED at "
                               "profit: no trade on the unseen days; filter blocked 12 of 12 "
                               "signal candles (older days: ")
    assert lines[-1] == f"   note: {vp.NOTES['funding_minutes']}"
    assert "every 4h order of a coin that settles every 4 hours" in lines[-1]
    # a plain group names no filter count on that line
    plain = _record()
    plain["combos"][KEY]["unseen"] = _walk([])
    _lines, verdicts = vr.report([plain], _plan(), 200, 1.0)
    assert "filter blocked" not in vr.verdict_lines(_verdict(verdicts))[0]


def test_a_coin_whose_every_timeframe_was_skipped_is_not_counted_as_measured():
    # final review M7
    young = {"coin": "NEW_USDT", "kind": "metals", "plan_id": PLAN_ID, "plan_end_ms": END,
             "runs": 200, "risk_usd": 1.0, "version": vm.VERSION, "pre": {}, "windows": {}, "combos": {},
             "skipped": {"1h": "1 older and 40 unseen 1h candles",
                         "4h": "0 older and 10 unseen 4h candles"}}
    lines, _ = vr.report([_record(), young], _plan(), 200, 1.0)
    assert (": 1 coin(s) measured, 1 with every timeframe skipped (its line says why); the "
            in lines[0])
    assert any(ln.startswith("NEW_USDT (metals)") and "1h skipped: 1 older and 40 unseen" in ln
               for ln in lines)


@pytest.mark.parametrize("label", ["CON", "con", "Nul", "PRN", "AUX", "COM1", "com9", "LPT1",
                                   "lpt9", "nul.txt", "CON.x", "x.", "run."])
def test_a_windows_device_name_or_a_label_ending_in_a_dot_is_refused(label, capsys):
    with pytest.raises(SystemExit) as refused:
        vr.main(["judge", "--label", label])
    assert refused.value.code == 2 and repr(label) in capsys.readouterr().err
    with pytest.raises(ValueError, match="not a plain folder name"):
        vr.home(label)


@pytest.mark.parametrize("label", ["COM10", "CONSOLE", "LPT", "com", "x.con", "nul_1", "COM0"])
def test_names_that_only_look_like_a_device_are_still_plain_labels(label):
    from tradingagents import stores

    assert vr.home(label) == Path(stores.V3.home) / "research" / label


def test_an_old_record_that_cannot_be_dropped_is_named_and_never_stops_the_other_coins(
        monkeypatch, tmp_path, capsys):
    from tradingagents import v3_measure

    root = tmp_path / "local"
    vr.save_coin(root, _record("BAD_USDT"))
    asked = []

    def fake(sym, plan, *, runs, risk_usd, log=None):
        asked.append(sym)
        if sym == "BAD_USDT":
            raise RuntimeError("the exchange refused the read")
        return {**_record(sym, risk=risk_usd), "runs": runs, "plan_id": plan["id"]}

    def locked(root_, sym):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(v3_measure, "measure_coin", fake)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    monkeypatch.setattr(vr, "drop_coin", locked)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    code = vr.main(["run", "aaa_usdt", "bad_usdt", "ccc_usdt", "--plan", str(plan_path),
                    "--runs", "200"])
    out = capsys.readouterr().out
    assert code == 1 and asked == ["AAA_USDT", "BAD_USDT", "CCC_USDT"]
    assert ("FAILED BAD_USDT: RuntimeError: the exchange refused the read; its old record "
            f"{vr.coin_file(root, 'BAD_USDT')} could not be dropped (PermissionError: ") in out
    # its old record is still on disk, and is never judged in its place
    assert vr.coin_file(root, "BAD_USDT").exists()
    assert "2 coin(s) measured" in out and "BAD_USDT (metals)" not in out
    saved = json.loads((root / "verdicts.json").read_text(encoding="utf-8"))["verdicts"]
    assert next(v for v in saved if v["passed"])["coins"] == ["AAA_USDT", "CCC_USDT"]


def test_judge_writes_its_verdicts_with_what_they_were_judged_under(monkeypatch, tmp_path, capsys):
    # the parked M-5: a bare list could not say which plan, risk, runs or coins it judged, so the
    # Backtest v3 tab could not label its check card from the file
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    root = tmp_path / "local"
    vr.save_coin(root, _record())
    vr.save_coin(root, _record("OLD_USDT", end=END - DAY))
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    before = __import__("time").time()
    assert vr.main(["judge", "--plan", str(plan_path), "--risk", "1"]) == 0
    capsys.readouterr()
    saved = json.loads((root / "verdicts.json").read_text(encoding="utf-8"))
    assert set(saved) == {"plan_id", "plan_end", "risk_usd", "runs", "coins", "judged_at",
                          "verdicts"}
    assert saved["plan_id"] == PLAN_ID and saved["plan_end"] == END
    assert (saved["risk_usd"], saved["runs"]) == (1.0, 200)
    assert saved["coins"] == ["XAU_USDT"], "only the coins pooled, never the one left out"
    assert before <= saved["judged_at"] <= __import__("time").time()
    assert len(saved["verdicts"]) == len(vf.judged())
