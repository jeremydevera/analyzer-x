"""One reading of the order book can no longer re-price a coin's whole history.

Sep 25, 2026 5:19pm — 5:19am in New York, the US stock market shut — the
operator pressed UPDATE THIS BACKTEST on #9GNPMXFF (KKRSTOCK 15m macddiv,
TP 1.2% / SL 1.2%). The job read KKRSTOCK's book at 1.22% a side and charged it
to all 71 trades of the last 38 days: $2.60 a $100 trade against the $0.18 the
coin's other 11,785 rows were charged. Every +$1.20 win booked -$1.40, and the
row went from 94% to 0 wins. #7X9R59U8 (GPNSTOCK 30m prank) the same minute:
$3.59 against $0.20, 0 wins of 75, "-140.43 USDT" on a row that said +$102.80.
The same press wrote the spike into the coin's cost file, which every "last 30
days" re-check of that coin reads. docs/RCA.md RCA-2026-09-25-H.
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FEE = 0.0008
SPIKE = 0.012193859525671202          # KKRSTOCK's book at 5:19pm, per side
USUAL = 0.001803 / 2 - FEE            # what its 11,785 GitHub rows were charged


def test_one_spike_is_not_charged_but_a_repeated_one_is():
    from tradingagents import backtest_report as br

    assert br.charged_slippage([USUAL, SPIKE]) == pytest.approx(USUAL)
    # HOWEVER MANY TIMES the closed-market book is read (the first version
    # believed it on the second press — found by the browser test, 6:36pm)
    assert br.charged_slippage([USUAL] + [SPIKE] * 9) == pytest.approx(USUAL)
    # a coin that is expensive in EVERY reading pays it
    assert br.charged_slippage([SPIKE, SPIKE * 1.1]) == pytest.approx(SPIKE)
    # ordinary variation is not a spike: the middle of the ordinary readings
    assert br.charged_slippage([0.0001, 0.0002, 0.00025]) == pytest.approx(0.0002)
    assert br.charged_slippage([]) is None
    assert br.charged_slippage([None, 0.0003]) == pytest.approx(0.0003)


def test_the_screen_says_in_dollars_why_the_reading_was_not_charged():
    from tradingagents import backtest_report as br

    said = br.cost_note(FEE, SPIKE, USUAL)
    assert "$2.60" in said and "$0.18" in said, said
    assert "not charged" in said
    assert br.cost_note(FEE, USUAL * 1.2, USUAL) == "", "close readings say nothing"


@pytest.fixture
def kkr(tmp_path, monkeypatch):
    """KKRSTOCK exactly as it stood after the press: the pair file's rows
    (the GitHub cost on almost all of them, the spike on the five the press
    rewrote) and a cost file holding nothing but the spike."""
    from tradingagents import market_sweep as msw

    costs, rows = tmp_path / "costs", tmp_path / "rows"
    costs.mkdir()
    rows.mkdir()
    monkeypatch.setattr(msw, "COSTS", costs)
    monkeypatch.setattr(msw, "ROWDIR", rows)
    pair = ([{"id": f"R{i}", "rt": 0.1803, "fee": FEE} for i in range(200)]
            + [{"id": f"S{i}", "rt": 2.5988, "fee": FEE} for i in range(5)])
    (rows / "KKRSTOCK-15m.json").write_text(json.dumps(pair), encoding="utf-8")
    (costs / "KKRSTOCK_USDT.json").write_text(json.dumps(
        {"symbol": "KKRSTOCK_USDT", "fee": FEE, "liq": 3.0, "slippage": SPIKE,
         "funding": []}), encoding="utf-8")
    return msw


def test_the_press_that_failed_now_charges_the_coins_usual_cost(kkr):
    msw = kkr
    charged, readings = msw.charge_cost("KKRSTOCK_USDT", SPIKE, fee=FEE,
                                        coin="KKRSTOCK", tf="15m")
    assert charged == pytest.approx(USUAL, abs=1e-9)
    # seeded from the ROWS, never from the lone spike already in the file
    assert [r["from"] for r in readings] == ["stored rows", "the exchange"]
    from tradingagents import backtest_report as br

    assert br.round_trip_cost(FEE, {"slippage": charged}) * 100 == pytest.approx(0.1803)


def _press(msw, fresh=SPIKE):
    charged, readings = msw.charge_cost("KKRSTOCK_USDT", fresh, fee=FEE,
                                        coin="KKRSTOCK", tf="15m")
    msw.save_costs("KKRSTOCK_USDT", fee=FEE, liq=3.0, funding=[],
                   slippage=charged, readings=readings)
    return charged


def test_pressing_again_in_the_same_quiet_hour_stays_right(kkr):
    """The browser test's own sequence: UPDATE at 6:15pm, UPDATE again at
    6:36pm, both while New York was shut. The first version of the rule
    charged the spike on the second press and #9GNPMXFF read 0 wins of 71."""
    msw = kkr
    for _ in range(6):
        assert _press(msw) == pytest.approx(USUAL, abs=1e-9)
    saved = msw.load_costs("KKRSTOCK_USDT")
    assert len(saved["readings"]) == 7, "every reading is kept, only not charged"
    assert saved["slippage"] == pytest.approx(USUAL, abs=1e-9)


def test_a_coin_that_really_went_thin_pays_once_its_cheap_readings_age_out(kkr):
    import time

    from tradingagents import backtest_report as br

    msw = kkr
    _press(msw)                                        # seeds USUAL + one spike
    saved = msw.load_costs("KKRSTOCK_USDT")
    old = time.time() - br.COST_WINDOW_S - 3600        # both past the window
    # and the stored rows themselves measured before it: a year-old cost
    # must not outvote today's book (the seed is dated by the rows' last bar)
    rows = json.loads((msw.ROWDIR / "KKRSTOCK-15m.json").read_text(encoding="utf-8"))
    (msw.ROWDIR / "KKRSTOCK-15m.json").write_text(
        json.dumps([{**r, "last_ms": int(old * 1000)} for r in rows]), encoding="utf-8")
    msw.save_costs("KKRSTOCK_USDT", fee=FEE, liq=3.0, funding=[],
                   slippage=saved["slippage"],
                   readings=[{**r, "at": old} for r in saved["readings"]])
    assert _press(msw) == pytest.approx(SPIKE), \
        "fourteen days of nothing but a thin book is the coin, not the hour"


def test_the_cost_file_every_30_day_recheck_reads_holds_the_charged_cost(kkr):
    msw = kkr
    charged, readings = msw.charge_cost("KKRSTOCK_USDT", SPIKE, fee=FEE,
                                        coin="KKRSTOCK", tf="15m")
    msw.save_costs("KKRSTOCK_USDT", fee=FEE, liq=3.0, funding=[],
                   slippage=charged, readings=readings)
    assert msw.load_costs("KKRSTOCK_USDT")["slippage"] == pytest.approx(USUAL)


def _funcs_calling(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            calls = {getattr(c.func, "attr", getattr(c.func, "id", ""))
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            if name in calls:
                yield node, calls


@pytest.mark.parametrize("path", ["tradingagents/market_sweep.py",
                                  ".github/scripts/sweep_shard.py"])
def test_every_measurement_that_reads_the_book_charges_through_the_rule(path):
    """ONE RULE, EVERY DOOR: the button, the local sweep and the GitHub run.
    A function that reads the book must pick the charge with the rule, and
    must never score the row with the raw book (round_trip_cost(fee, book))."""
    src = (REPO / path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = list(_funcs_calling(tree, "book_cost"))
    assert found, "no measurement reads the book any more?"
    for fn, calls in found:
        assert calls & {"charge_cost", "charged_slippage"}, \
            f"{path}:{fn.name} reads the book and charges it raw"
        body = ast.get_source_segment(src, fn) or ""
        assert "round_trip_cost(fee, book)" not in body, \
            f"{path}:{fn.name} scores rows with the raw book"


def test_github_keeps_the_readings_in_the_saved_position(tmp_path, monkeypatch):
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "sweep_shard_under_test", REPO / ".github/scripts/sweep_shard.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "sweep_shard_under_test", mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "STATE_OUT", str(tmp_path))
    mod.write_state("KKRSTOCK", "15m", {}, last_ms=1, first_ms=1, bars=1,
                    fee=FEE, slips=[USUAL, SPIKE])
    got = mod.rs.unpack((tmp_path / "KKRSTOCK-15m.json.gz").read_bytes())
    assert got["__slips__"] == [USUAL, SPIKE]
    src = (REPO / ".github/scripts/sweep_shard.py").read_text(encoding="utf-8")
    assert src.count('prior.get("__slips__")') >= 2, \
        "the no-new-bars path and the continuation must both carry the readings"


def test_the_update_job_hands_the_note_to_the_screen():
    src = (REPO / "tradingagents/db_jobs.py").read_text(encoding="utf-8")
    start = src.index("\ndef _run_pairbt")
    body = src[start:src.index("\ndef ", start + 10)]      # to the next top-level def
    assert 'res.get("cost_note")' in body
    assert "cost_note=cost_said" in body


def test_the_finished_line_says_why_the_row_did_not_move(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    sentence = REPO / "webapp/src/lib/rowUpdate.ts"
    cases = {
        "note": {"pair": "KKRSTOCK 15m", "signal": "macddiv", "rows": 5,
                 "indexed": 90, "cost_note": "the exchange's cost right now is $2.60"},
        "failed": {"pair": "KKRSTOCK 15m", "error": "RuntimeError: x",
                   "cost_note": "should not show"},
        "plain": {"pair": "KKRSTOCK 15m", "rows": 5, "indexed": 90},
    }
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        f'import {{ rowUpdateSentence }} from "{sentence.as_uri()}";\n'
        f"const cases = {json.dumps(cases)};\nconst out = {{}};\n"
        'for (const [k, j] of Object.entries(cases)) out[k] = rowUpdateSentence(j, "Sep 25, 2026 5:19pm");\n'
        "console.log(JSON.stringify(out));\n", encoding="utf-8")
    got = subprocess.run([node, str(probe)], capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    said = json.loads(got.stdout.strip().splitlines()[-1])
    assert said["note"]["text"].startswith("Done at Sep 25, 2026 5:19pm")
    assert "$2.60" in said["note"]["text"]
    assert "should not show" not in said["failed"]["text"]
    assert "cost" not in said["plain"]["text"]
