"""The reviewed GitHub repos' strategies on the skill engine (Nov 18, 2026): the gh set's line, the
luck bar, the shard / workflow / collector wiring, the page's words and the summary."""
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents import gh_strats, skill_bt as sb
from tradingagents.gh_strats import baseline

ROOT = Path(__file__).resolve().parents[1]


def _df(n=900, seed=5, freq="1h"):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.012, n)))
    spread = np.abs(rng.normal(0, 0.006, n))
    idx = pd.date_range("2026-01-01", periods=n, freq=freq)
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close * (1 + spread),
                         "low": close * (1 - spread), "close": close,
                         "volume": rng.lognormal(3, 0.6, n)}, index=idx)


def _key(s):
    return None if s is None else (s.entry, s.direction if s.entry else None, s.exit, s.exit_dir)


def _random_combos():
    return [c for c in gh_strats.combos() if c["strategy"] == "gh_random"]


def test_the_luck_bar_is_loaded_and_never_reads_a_later_candle():
    assert "baseline" in gh_strats.LOADED
    df = _df(700)
    for params in baseline.GRID["gh_random"]:
        whole = [_key(s) for s in baseline.RandomEntries().signals_all(df, params)]
        assert sum(1 for k in whole if k and k[0]) > 5
        for cut in (260, 333, 401, 520, 699):
            part = [_key(s) for s in baseline.RandomEntries().signals_all(df.iloc[:cut], params)]
            assert part == whole[:cut], (params, cut)


def test_a_random_entry_is_closed_after_its_hold():
    df = _df(400)
    sigs = baseline.RandomEntries().signals_all(df, {"rate": 0.05, "hold": 7, "seed": 3})
    for i, s in enumerate(sigs):
        if s and s.entry and i + 7 < len(sigs):
            assert sigs[i + 7].exit and sigs[i + 7].exit_dir == s.direction


def test_the_gh_line_keeps_every_combo_split_at_seventy_percent():
    df = _df(900)
    combos = _random_combos()
    x = sb.gh_line("TEST", "1h", df, fee=0.00075, slip=0.0003, combos=combos)
    assert x["combos"] == len(combos) == len(x["picks"])
    assert x["split_ms"] == int(sb._ms(df.index)[int(len(df) * sb.SPLIT)])
    for c in x["picks"]:
        # only the judged newest 30%'s trades are carried; the older part is its statistics
        assert all(t[0] >= x["split_ms"] for t in c["trades"])
        assert c["newer"]["trades"] == len(c["trades"])
        assert round(c["newer"]["profit"], 2) == round(sum(t[4] for t in c["trades"]), 2)
        assert all(t[3] != "END" for t in c["trades"])
        assert c["older_lost"] == (not (c["older"]["trades"] >= sb.MIN_OLDER and c["older"]["profit"] > 0))
    assert sum(c["older"]["trades"] for c in x["picks"]) > 0


def test_a_trade_open_at_the_end_is_counted_never_listed():
    df = _df(300)
    c = {"strategy": "gh_random", "params": {"rate": 0.9, "hold": 1000, "seed": 1}, "stop": 0.5, "target": None}
    x = sb.gh_line("TEST", "1h", df, fee=0.00075, slip=0.0003, combos=[c])
    assert x["open_at_end"] == 1
    assert x["picks"][0]["trades"] == []


def test_a_strategy_that_raises_is_named_and_the_line_goes_on(monkeypatch):
    class Boom:
        name = "gh_boom"

        def signals_all(self, df, params):
            raise RuntimeError("bad window")

    monkeypatch.setitem(gh_strats.STRATEGIES, "gh_boom", Boom())
    combos = [{"strategy": "gh_boom", "params": {}, "stop": 0.015, "target": None}] + _random_combos()
    x = sb.gh_line("TEST", "1h", _df(600), fee=0.00075, slip=0.0003, combos=combos)
    assert x["errors"] == {"gh_boom": "RuntimeError: bad window"}
    assert x["combos"] == len(combos) - 1


def test_the_shard_the_workflow_and_the_collector_know_the_gh_set():
    from tradingagents import acs

    shard = (ROOT / ".github/scripts/skill_shard.py").read_text(encoding="utf-8")
    wf = (ROOT / ".github/workflows/skillbt.yml").read_text(encoding="utf-8")
    assert '"gh": "skillgh"' in shard and 'WALKED = SET in ("daily", "gh")' in shard
    assert "sb.gh_line(" in shard
    assert "out/skillgh-*.jsonl" in wf and "out/skillgh-report-*.json" in wf
    assert "scikit-learn" in wf
    assert acs.SKILL_PREFIX["gh"] == "skillgh"


def _skill():
    df = _df(900)
    x = sb.gh_line("TEST", "1h", df, fee=0.00075, slip=0.0003, combos=_random_combos())
    return {"lines": {"TEST|1h": x}, "failed": [], "skipped": [], "not_reached": [], "collected_s": 1_790_000_000}


def test_the_page_names_a_gh_row_by_its_repo_and_says_exits_are_by_the_minute():
    from tradingagents import acs_page

    rows, tl = acs_page.skill_rows(_skill())
    assert rows and all(r["strategy"].startswith("luck-bar/random-entries: ") for r in rows)
    assert all("settled by the minute" in r["sl_rule"] for r in rows)
    assert len(rows) == len(tl)


def test_the_summary_adds_up_to_the_trades_it_read():
    from tradingagents import gh_results

    sk = _skill()
    sm = gh_results.summary(lines=list(sk["lines"].values()))
    x = sk["lines"]["TEST|1h"]
    new = [t for c in x["picks"] for t in c["trades"] if t[0] >= x["split_ms"]]
    r = sm["strategies"]["gh_random"]
    assert r["trades"] == len(new)
    assert r["wins"] + r["losses"] == r["trades"]
    assert r["profit"] == round(sum(t[4] for t in new), 2)
    assert sm["luck_per_trade"]["1h"] == r["per_trade"]


def test_the_worst_run_walks_trades_in_closing_order():
    from tradingagents import gh_results

    trades = [[0, 30, 1, "SL", -1.0], [0, 10, 1, "SL", -2.0], [0, 20, 1, "TP", 3.0], [0, 40, 1, "SL", -0.5]]
    assert gh_results._worst_run(trades) == (-2.0, 1)
    trades.append([0, 35, 1, "SL", -4.0])
    assert gh_results._worst_run(trades) == (-5.5, 3)


def _fake_run(tmp_path, monkeypatch, runs):
    """`runs` {run id: [(line, report entries)]}: acs._gh's download writes them where -D points."""
    import json as _j

    from tradingagents import acs

    monkeypatch.setattr(acs, "home", lambda: tmp_path)

    def gh(*args, timeout=None):
        assert args[:2] == ("run", "download")
        run, dest = int(args[2]), Path(args[args.index("-D") + 1])
        lines, report = runs[run]
        (dest / "skill-lines-0").mkdir(parents=True)
        (dest / "skill-lines-0" / "skillgh-0.jsonl").write_text(
            "".join(_j.dumps(x) + "\n" for x in lines), encoding="utf-8")
        (dest / "skill-lines-0" / "skillgh-report-0.json").write_text(_j.dumps(report), encoding="utf-8")
        return ""

    monkeypatch.setattr(acs, "_gh", gh)


def test_collect_files_lines_by_timeframe_a_redo_replaces_and_gaps_are_named(tmp_path, monkeypatch):
    import json as _j

    from tradingagents import gh_results

    a = sb.gh_line("AAA", "1h", _df(600, seed=1), fee=0.00075, slip=0.0003, combos=_random_combos())
    b = sb.gh_line("BBB", "4h", _df(600, seed=2, freq="4h"), fee=0.00075, slip=0.0003, combos=_random_combos())
    b2 = dict(b, bars=599)
    _fake_run(tmp_path, monkeypatch, {
        1: ([a, b], [{"coin": "AAA", "tf": "1h"}, {"coin": "BBB", "tf": "4h"},
                     {"coin": "BBB", "tf": "1d", "error": "ValueError: boom"}]),
        2: ([b2], [{"coin": "BBB", "tf": "4h"}])})
    (tmp_path / "skillgh-state.json").write_text(_j.dumps({"runs": {"o/r": {"run": 1, "coin_list": ["AAA_USDT", "BBB_USDT", "CCC_USDT"]}}}))
    (tmp_path / "skillgh-redo-state.json").write_text(_j.dumps({"runs": {"o/r": {"run": 2, "coin_list": ["BBB_USDT"]}}}))
    m = gh_results.collect()
    assert m["pairs"] == 2 and m["not_reached"] == ["CCC"]
    assert m["failed"] == ["BBB 1d: ValueError: boom"]
    got = {tf: list(gh_results.lines_of(tf)) for tf in gh_results.TFS}
    assert [x["coin"] for x in got["1h"]] == ["AAA"] and got["4h"][0]["bars"] == 599
    root = gh_results.write_page()
    assert (root / "index.html").exists() and "GitHub Repo Strategies" in (root / "index.html").read_text(encoding="utf-8")
    assert sorted(p.name.split("-")[0] for p in root.glob("*.txt")) == ["1h", "4h", "ids"]
    monkeypatch.setattr(gh_results, "NOTE", tmp_path / "RESULTS.md")
    note = gh_results.write_note().read_text(encoding="utf-8")
    assert "| gh_random | luck-bar/random-entries |" in note and "failed: BBB 1d: ValueError: boom" in note
    assert "not reached: CCC" in note
