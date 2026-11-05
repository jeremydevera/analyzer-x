"""The all-coins strategies page (tradingagents/acs_page.py): a v2 pick carries GitHub's re-measured
trades, a pick whose trades do not add up to its row is REFUSED, and a pick with no trade list is
NAMED, never dropped (kit F, rule 20)."""
import pytest

from tradingagents import acs_page as ap


def _picks():
    return {"made_s": 1, "rows": 10, "rule": {}, "pairs": {"BTC-1h": {"coin": "BTC", "tf": "1h", "bar": {
        "per_trade": -0.1}, "picks": [
        {"id": "AAAA1111", "signal": "rsi2", "th": 0.0, "sl": 1.0, "tp": 4.0, "t15": 2, "w15": 1, "p15": 1.0,
         "older": {"trades": 6, "wins": 3, "profit": 2.0}},
        {"id": "BBBB2222", "signal": "mom6", "th": 0.2, "sl": 0.3, "tp": 0.4, "t15": 1, "w15": 0, "p15": -1.0,
         "older": {"trades": 6, "wins": 3, "profit": 2.0}}]}}}


def _trades(profit=3.0):
    t = [[1_000_000, 2_000_000, 1, "TP", 3.78, 0.3], [3_000_000, 4_000_000, -1, "SL", -0.78, 0.3]]
    return {"lines": {"BTC|1h|rsi2:0:1:4": {"cfg": "rsi2:0:1:4", "coin": "BTC", "tf": "1h",
                                            "row": {"trades": 2, "profit": profit, "days": 30,
                                                    "last_ms": 5_000_000}, "trades": t}}}


def test_a_pick_carries_its_trades_and_one_without_a_list_is_named():
    rows, tl, missing = ap.v2_rows(_picks(), _trades())
    assert [r["id"] for r in rows] == ["AAAA1111"]
    assert tl[0][0] == [1000, 2000, 1, ap.WHYS.index("TP"), 37800, 1000, 4000]
    assert len(missing) == 1 and "#BBBB2222" in missing[0]


def test_trades_that_do_not_add_up_to_the_row_are_refused():
    with pytest.raises(ValueError, match="AAAA1111"):
        ap.v2_rows(_picks(), _trades(profit=9.0))


def test_the_page_script_parses():
    # Nov 05, 2026: a legend sentence with "double quotes" inside a double-quoted string broke the
    # whole page ("Unexpected identifier 'lost'"); every row test passed, because none runs the script
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    code = ("const s=require('fs').readFileSync(process.argv[1],'utf8');"
            "new Function(s.split('<script>')[1].split('</script>')[0]);")
    r = subprocess.run([node, "-e", code, str(ap._HTML)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _skill_line(strategy, target):
    tr = [[1_000_000, 2_000_000, 1, "TP" if target else "SIGNAL", 2.9]]
    c = {"label": f"{strategy}(lookback=50) stop 1.5%" + (" target 3%" if target else ""),
         "strategy": strategy, "params": {"lookback": 50}, "stop": 0.015, "target": target,
         "older": {"trades": 12, "win_rate": 60.0, "profit": 4.0, "expectancy": 0.33},
         "newer": {"trades": 1, "profit": 2.9}, "older_lost": False, "trades": tr}
    return {"lines": {"BTC|1h": {"coin": "BTC", "tf": "1h", "bars": 2160, "combos": 42, "split_ms": 1_500_000,
                                 "start_ms": 0, "end_ms": 3_000_000, "bar": -0.1, "picks": [c]}}}


def test_a_technical_analysis_row_names_its_skill_and_carries_its_target():
    rows, tl = ap.skill_rows(_skill_line("ta_wyckoff_spring", 0.03))
    assert rows[0]["strategy"].startswith("technical-analysis: ta_wyckoff_spring")
    assert rows[0]["tp_rule"].startswith("3% (2x the stop")
    assert tl[0][0][5:] == [1500, 3000]
    rows, tl = ap.skill_rows(_skill_line("bf_momentum", None))
    assert rows[0]["strategy"].startswith("backtesting-frameworks: bf_momentum")
    assert tl[0][0][6] == -1 and rows[0]["tp_rule"].startswith("none")


def test_the_backtesting_skills_rows_keep_their_old_label_and_id():
    rows, tl = ap.skill_rows(_skill_line("sma_crossover", None))
    from tradingagents import backtest_report as br

    assert rows[0]["strategy"] == "sma_crossover(lookback=50) stop 1.5%"
    assert rows[0]["id"] == br.row_code("BTC", "1h", "sma_crossover", 0, 1.5, 0, "flat",
                                        plan="sma_crossover(lookback=50) stop 1.5%", res="skill")
