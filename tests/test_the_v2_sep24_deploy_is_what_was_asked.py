"""The operator's Sep 24, 2026 deploy is exactly the rows they pasted.

Operator: *"undeploy all deployed ids in strategies deployed / then deploy
these ids"* — 1,473 Backtest v2 row ids. `presets/v2-sep24.json` is that
arming. These tests hold the four checks of `.claude/skills/deploy-by-id`
against the preset itself, so the file in git cannot drift from what was
asked: every id resolves to the combination it was hashed from, the count
survives the round trip (1,473 = armed + refused BY ID), every armed slot
prints the id it runs as, and replacing arms nothing on real money.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradingagents import api, auto_trader as at, backtest_report as br
from tradingagents import deploy_preset as dp
from tradingagents.local_history import _sig_of

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "presets" / "v2-sep24.json"
TF_IV = {"15m": ("Min15", 900), "30m": ("Min30", 1800), "1h": ("Min60", 3600),
         "4h": ("Hour4", 14400), "1d": ("Day1", 86400)}


@pytest.fixture(scope="module")
def preset():
    return dp.load(PRESET)


def _slots(preset):
    for key, one in preset["strategies"].items():
        for coin in one["coins"]:
            yield key, coin, one["measured"][coin.replace("_USDT", "")]


def test_the_ids_add_up_to_what_was_pasted(preset):
    armed = [i for _, _, m in _slots(preset) for i in m["given"]]
    refused = [i for r in preset["refused"] for i in r["given"]]
    assert len(armed) == 1049 and len(refused) == 424
    assert len(set(armed) | set(refused)) == 1473 == len(armed) + len(refused), \
        "every pasted id is armed or refused by name, once"
    assert sum(1 for _ in _slots(preset)) == 537 and len(preset["refused"]) == 215
    assert len(preset["strategies"]) == 326


def test_every_pasted_id_is_the_combination_it_was_hashed_from(preset):
    """Check 1 of deploy-by-id: an id names ONE combination including its
    coin. Re-hash each pasted id from the fields it is armed with."""
    rows = list(_slots(preset)) + [(None, r["coin"], r) for r in preset["refused"]]
    for key, coin, m in rows:
        c = coin.replace("_USDT", "")
        codes = {br.row_code(c, m["tf"], m["signal"], m["th"], m["sl_pct"],
                             m["tp_pct"], sz, res="1m"): sz
                 for sz in ("flat", "martingale")}
        for given in m["given"]:
            assert given in codes, (coin, m["tf"], m["signal"], given)
        assert codes.get(m["runs_as"]) == "flat", "the runner stakes the FLAT twin"


def test_every_armed_key_is_the_spec_its_rows_were_measured_with(preset):
    for key, coin, m in _slots(preset):
        spec = at.STRATEGY_SPECS[key]
        assert key in at.STRATEGY_ORDER, f"{key} is armed and never walked"
        iv, secs = TF_IV[m["tf"]]
        assert (spec["interval"], spec["bar_seconds"]) == (iv, secs), key
        assert spec["tp"] == pytest.approx(m["tp_pct"] / 100), key
        assert spec["sl"] == pytest.approx(m["sl_pct"] / 100), key
        if m["signal"] in ("mom6", "mom15", "fade15"):
            assert spec["threshold"] == pytest.approx(m["th"] / 100), key
        else:
            assert not spec.get("threshold") and not m["th"], key
        assert _sig_of(key) == m["signal"], key
        assert spec["tp"] >= spec["sl"], "the pasted filter was TP >= SL"


def test_every_armed_slot_prints_the_id_it_runs_as(preset):
    """Checks 2 and 3: after the replace, the id on the screen for each slot
    is the flat v2 id — the one pasted, or the flat twin of a pasted
    martingale id (27 slots were pasted as martingale only)."""
    settings = dp.merged({**preset, "replace": True}, {})
    twin_only = pasted_martingale_only = 0
    for key, coin, m in _slots(preset):
        assert api.row_id_for(key, coin, settings) == m["runs_as"], (key, coin)
        twin_only += m["runs_as"] not in m["given"]
        mart = br.row_code(coin.replace("_USDT", ""), m["tf"], m["signal"],
                           m["th"], m["sl_pct"], m["tp_pct"], "martingale",
                           res="1m")
        pasted_martingale_only += m["given"] == [mart]
    assert twin_only == pasted_martingale_only == 21, \
        "the screen names the flat twin exactly where only the martingale id was pasted"


def test_the_refused_are_the_stops_past_the_liquidation_wall(preset):
    armed = {(k, c) for k, c, _ in _slots(preset)}
    for r in preset["refused"]:
        assert "liquidation" in r["why"] and "whole margin" in r["why"], r
        # at 20x the wall is 1/20 minus the maintenance rate (at most 5%),
        # and the gate refuses a stop 80% of the way there: 2.4% on a 2%
        # rate contract, 3.6% on a 0.5% one
        assert r["sl_pct"] >= 0.8 * 3.0 - 1e-9, r
        assert not any(c == r["coin"] + "_USDT" for _, c in armed
                       if at.STRATEGY_SPECS.get(_)
                       and at.STRATEGY_SPECS[_]["sl"] == pytest.approx(r["sl_pct"] / 100)
                       and _sig_of(_) == r["signal"]
                       and at.STRATEGY_SPECS[_]["tp"] == pytest.approx(r["tp_pct"] / 100)
                       and at.STRATEGY_SPECS[_]["interval"] == TF_IV[r["tf"]][0]), r


def test_one_key_is_one_combination(preset):
    for key, one in preset["strategies"].items():
        shapes = {(m["tf"], m["signal"], m["th"], m["tp_pct"], m["sl_pct"])
                  for m in one["measured"].values()}
        assert len(shapes) == 1, (key, shapes)


def test_replacing_disarms_the_old_rows_and_arms_only_the_practice_book(preset):
    old = {"strategies": ["bb20_15m_sl15tp06", "keltner_30m_sl2tp2"],
           "strategy_coins": {"bb20_15m_sl15tp06": ["FASTSTOCK_USDT"],
                              "keltner_30m_sl2tp2": ["KITE_USDT"]},
           "strategy_books": {"bb20_15m_sl15tp06": ["real"],
                              "keltner_30m_sl2tp2|KITE_USDT": ["real"]},
           "strategy_labels": {"bb20_15m_sl15tp06": "old"},
           "martingale_demo": True, "enabled": False, "dry_run": True}
    out = dp.merged({**preset, "replace": True}, old)
    assert set(out["strategies"]) == set(preset["strategies"])
    assert "bb20_15m_sl15tp06" not in out["strategy_coins"]
    assert "keltner_30m_sl2tp2|KITE_USDT" not in out["strategy_books"], \
        "a per-coin REAL switch from the old config must not survive"
    assert "KITE_USDT" not in at.coins_for("keltner_30m_sl2tp2", out)
    for key, coin, _ in _slots(preset):
        assert at.book_names(out, key, coin) == ["paper"], (key, coin)
        assert out["strategy_res"][at.book_slot(key, coin)] == "1m"
    assert out["enabled"] is False and out["martingale_demo"] is True
    assert not out.get("strategy_labels")


# ------------------------------------------------ the first DAILY rows
# 76 of the armed keys are Day1 — the first daily strategies this runner has
# ever held. Drive the function the runner calls, `process_symbol`, with the
# staleness guard ON (the state it runs in) and one clock for candles and
# position (CLAUDE.md, Sep 12, 2026).
DAILY = "cf_mom_l1_1d_sl3tp12p0"          # DASH 1d, one of the operator's rows
MIDNIGHT = 1790208000                    # a UTC midnight: the daily close


def _daily_bars(n=300):
    import pandas as pd

    opens = [MIDNIGHT - (n - i) * 86400 for i in range(n)]
    closes = [100.0] * n
    return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"),
                         "Open": closes, "High": [101.0] * n,
                         "Low": [99.0] * n, "Close": closes,
                         "Volume": [1.0] * n})


@pytest.fixture
def runner(tmp_path, monkeypatch):
    for name in ("SETTINGS_PATH", "STATE_PATH", "LEDGER_PATH", "PID_PATH",
                 "KILL_PATH"):
        monkeypatch.setattr(at, name, tmp_path / f"{name.lower()}.json")
    for cache in ("_BAR_CACHE", "_GATE_CACHE", "_GATE_LOGGED",
                  "_CYCLE_PRICES", "_CYCLE_GATES"):
        getattr(at, cache, {}).clear()
    monkeypatch.setattr(at, "signal_for",
                        lambda key, *a, **k: 1 if key == DAILY else 0)
    return tmp_path


def _one_cycle(monkeypatch, hours_after_close):
    from tests.test_auto_trader import FakeFx

    monkeypatch.setattr(at.time, "time",
                        lambda: MIDNIGHT + hours_after_close * 3600.0)
    fx = FakeFx(_daily_bars())
    settings = {"strategies": [DAILY], "strategy_coins": {DAILY: ["DASH_USDT"]},
                "strategy_books": {DAILY: ["paper"]}, "margin": 5.0,
                "martingale_demo": True, "enabled": False, "dry_run": True}
    state: dict = {}
    at.process_symbol("DASH_USDT", settings, state, fx=fx, dry=True)
    ledger = [json.loads(x) for x in
              at.LEDGER_PATH.read_text().strip().splitlines()] \
        if at.LEDGER_PATH.exists() else []
    return fx, state, ledger


def test_a_daily_row_enters_on_the_runner_after_the_daily_close(runner, monkeypatch):
    fx, state, ledger = _one_cycle(monkeypatch, 1)
    assert [o["dry_run"] for o in fx.orders] == [True], "practice only"
    pos = state[at.state_key("DASH_USDT", True, DAILY)]["position"]
    assert pos["strategy"] == DAILY and pos["side"] == 1
    assert pos["tp"] == pytest.approx(pos["entry"] * 1.12)
    assert pos["sl"] == pytest.approx(pos["entry"] * 0.97)
    assert ledger[-1]["action"] == "enter"


def test_a_daily_signal_half_a_day_old_is_not_traded(runner, monkeypatch):
    """12 hours after the close (8:00pm in Manila) the bar is no longer the
    trade that was measured — the same half-a-bar rule as every frame."""
    fx, state, ledger = _one_cycle(monkeypatch, 13)
    assert fx.orders == []
    assert any(r["action"] == "stale_skip" for r in ledger), ledger
