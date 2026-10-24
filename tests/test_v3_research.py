"""The Backtest v3 Part 2a command (`python -m tradingagents.v3_research`): it
builds the plan, measures a few coins, prints the order books' coverage FIRST
and then every verdict with the standard kit's figures, and never pools a
coin measured under another plan."""
import calendar
import json

import pytest

from tradingagents import v3_families as vf, v3_research as vr, v3_universe as vu

DAY = 86_400_000
END = calendar.timegm((2026, 10, 23, 0, 0, 0)) * 1000
D0 = END - 90 * DAY
KEY = vf.combo_key("v3_snap", "k2", "1h", "none")
KEY15 = vf.combo_key("v3_snap", "k1.5", "1h", "none")


def _rows(pnls, per_day=4):
    return [[D0 + (k // per_day) * DAY, D0 + (k // per_day) * DAY + 60_000,
             D0 + (k // per_day) * DAY + 3_600_000, 1, p, "TP"] for k, p in enumerate(pnls)]


def _walk(rows):
    return {"rows": rows, "counts": {"cost_unmeasured": 5}, "filter": {"signal_candles": 9},
            "twins": [1, 0.5], "lev": [20, 20], "notional": [45.0, 130.0], "over_book": 2}


def _record(coin="XAU_USDT", end=END, risk=1.0):
    """A coin whose snap 1h k2 makes +0.10 a trade on 40 older trades and +0.20 on 320 unseen
    ones (1.2 and -0.8 in turn), against random runs of -0.002..+0.002 a trade."""
    quiet = [[100, 0.1 * ((k % 5) - 2)] for k in range(200)]
    return {"coin": coin, "kind": "metals", "plan_end_ms": end, "runs": 200, "risk_usd": risk,
            "pre": {"coverage_older": 0.0, "coverage_unseen": 0.712, "flat_slip": 0.00012,
                    "flat_slip_source": "the median of its 95,012 recorded minutes"},
            "windows": {"1h": {"split": "Jul 24, 2026 8:00pm"}}, "skipped": {},
            "combos": {KEY15: {"older": _walk(_rows([0.05] * 40)), "unseen": _walk([]),
                               "random": [[0, 0.0]] * 200},
                       KEY: {"older": _walk(_rows([0.10] * 40)),
                             "unseen": _walk(_rows([1.2, -0.8] * 160)), "random": quiet}}}


def _plan():
    return {"version": vu.VERSION, "venue": "Gate", "start_ms": END - 365 * DAY, "end_ms": END}


def test_the_report_prints_coverage_first_then_every_verdict_with_the_kits_figures():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    text = "\n".join(lines)
    assert len(verdicts) == 30 and sum(v["passed"] for v in verdicts) == 1
    assert "70 combinations tried (14 family-setting-timeframes x 5 filter choices)" in lines[1]
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
    assert "worst losing run -$0.80 over 1 trades" in snap
    assert "target: the 20-candle average, resting" in snap and "leverage 20x-20x" in snap
    assert "$45-$130 of coin a trade (2 over the books' $100)" in snap
    assert "exits at a typical cost 5 of 320" in snap and "1 of 30 verdicts passed." in text
    assert "refused signal candles: under one lot 0, no safe leverage 0, the cost check 0" in snap
    assert vr.CRASH_GUARD in text and vr.FEW_COINS in text and vu.SURVIVORSHIP in text


def test_a_chosen_setting_with_no_unseen_trade_says_so_in_one_line():
    rec = _record()
    rec["combos"][KEY]["unseen"] = _walk([])
    lines, verdicts = vr.report([rec], _plan(), 200, 1.0)
    snap = next(v for v in verdicts if (v["family"], v["tf"], v["filter"]) ==
                ("v3_snap", "1h", "none"))
    assert vr.verdict_lines(snap) == [
        f"#{snap['id']} v3_snap 1h none: setting k2 - FAILED at profit: no trade on the unseen "
        "days (older days: k1.5 +$0.050 a trade over 40, k2 +$0.100 a trade over 40)"]


def test_a_group_no_coin_measured_says_so_in_one_line():
    lines, verdicts = vr.report([_record()], _plan(), 200, 1.0)
    trend = next(v for v in verdicts if (v["family"], v["tf"], v["filter"]) ==
                 ("v3_trend", "1d", "none"))
    assert vr.verdict_lines(trend) == [
        f"#{trend['id']} v3_trend 1d none: FAILED at choose - no coin measured v3_trend on 1d "
        "(older days: n20 - a trade over 0 (too few), n50 - a trade over 0 (too few), n100 - a "
        "trade over 0 (too few))"]


def test_judge_pools_only_the_coins_measured_under_this_plan_and_names_the_rest(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    vr.save_coin(tmp_path / "local", _record())
    vr.save_coin(tmp_path / "local", _record("OLD_USDT", end=END - DAY))
    vr.save_coin(tmp_path / "local", _record("BIG_USDT", risk=5.0))
    vr.save_coin(tmp_path / "local", {**_record("FEW_USDT"), "runs": 20})
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["judge", "--plan", str(plan_path)]) == 0
    out = capsys.readouterr().out
    # a coin measured at another risk is not the same trades, and runs of another count cannot
    # be pooled run by run: never pooled, always named
    assert ("left out, measured under another plan, at another risk than $1.00 or with other "
            "than 200 random runs: BIG_USDT, FEW_USDT, OLD_USDT") in out
    saved = json.loads((tmp_path / "local" / "verdicts.json").read_text(encoding="utf-8"))
    snap = next(v for v in saved if v["passed"])
    assert snap["coins"] == ["XAU_USDT"] and snap["unseen"]["trades"] == 320


def test_run_measures_each_coin_saves_it_and_prints_its_line(monkeypatch, tmp_path, capsys):
    from tradingagents import v3_measure

    asked = []

    def fake(sym, plan, *, runs, risk_usd, log=None):
        asked.append((sym, runs, risk_usd))
        return _record(sym, risk=risk_usd)

    monkeypatch.setattr(v3_measure, "measure_coin", fake)
    monkeypatch.setattr(vr, "home", lambda label="local": tmp_path / label)
    plan_path = vu.save(_plan(), tmp_path / "plan.json")
    assert vr.main(["run", "xau_usdt", "--plan", str(plan_path), "--runs", "3",
                    "--label", "t"]) == 0
    assert asked == [("XAU_USDT", 3, 1.0)], "the spec's $1 unless --risk says otherwise"
    assert vr.coin_file(tmp_path / "t", "XAU_USDT").exists()
    assert "XAU_USDT (metals): order books cover 0.0%" in capsys.readouterr().out


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


@pytest.mark.parametrize("family, key, words", [
    ("v3_trend", "n50", ("none; out on a close past its 50-day average",
                         "a trailing stop 3 x ATR(20), never loosened")),
    ("v3_strength", "k3", ("none; out at a Monday 00:00 UTC rank outside the top 6",
                           "a trailing stop 3 x ATR(20), never loosened")),
    ("v3_snap", "k1.5", ("the 20-candle average, resting; out after 24 candles",
                         "an emergency stop 3 x ATR(20) at the market"))])
def test_each_familys_target_and_stop_are_said_in_words(family, key, words):
    assert vr.exit_words(family, key) == words
