"""A measured set of strategies must travel to another machine (2026-08-27).

Operator: *"push those strategies to github so i can use it to my machine"*.

The catalog travels in the repo; the ARMING does not — which coin a strategy
trades, its margin, its sizing and its book live in
`~/.tradingagents/auto_trade.json`, which is the operator's own file. So the
Mac had the 20 specs and an empty "Strategies you have deployed" table.

A preset is that arming, in git. What these tests hold shut is the damage a
preset could do on the machine it lands on:

* it must MERGE. Overwriting `auto_trade.json` would delete whatever that
  machine is really trading.
* it must not arm a coin another strategy already holds on that timeframe.
  MEXC nets two positions on one contract into one, so the second entry
  resizes the first and either stop closes part of a trade it does not own.
* it must not turn anything live. `enabled` stays off and the book stays what
  the preset asked for — going live is a click on the machine with the keys.
* sizing must be what the rows were MEASURED at. All 23 were measured flat and
  the shipped default is martingale; a flat-measured row deployed laddered is
  the 2026-08-17 incident (+$141 flat became −$21 with a $339 drawdown).
"""
import json

import pytest

from tradingagents import auto_trader as at, deploy_preset as dp

PRESET = dp.PRESET_DIR / "win30-flat-23.json"


def test_the_preset_in_this_repo_is_readable_and_names_real_specs():
    got = dp.load(PRESET)
    assert len(got["strategies"]) == 17, sorted(got["strategies"])
    for key, one in got["strategies"].items():
        assert key in at.STRATEGY_SPECS, key
        assert one["coins"] and all(c.endswith("_USDT") for c in one["coins"])
        assert one["sizing"] == "flat", key
        assert one["book"] == ["paper"], key
        assert len(one["rows"]) == len(one["coins"]), key


def test_every_row_carries_the_numbers_it_was_measured_with():
    """A key and a coin do not tell the other machine what it is arming."""
    got = dp.load(PRESET)
    for key, one in got["strategies"].items():
        for coin in one["coins"]:
            m = one["measured"][coin.replace("_USDT", "")]
            assert m["trades_full"] >= 8 and m["profit_full"] > 0, (key, coin)
            assert m["profit_1mo"] > 0 and m["gate"] in ("ok", "warn")
            assert "/" in m["green"] and m["window_days"] >= 60
    # and the shape warning travels with it
    assert "SIXTEEN wins" in got["measured"]["shape"]
    assert "not a year" in got["measured"]["depth"]


def test_it_merges_and_never_deletes_what_the_machine_already_runs():
    mine = {
        "strategies": ["mom6_1h_pv4"],
        "strategy_coins": {"mom6_1h_pv4": ["APEX_USDT"]},
        "strategy_books": {"mom6_1h_pv4": ["real"]},
        "strategy_margins": {"mom6_1h_pv4": 12.0},
        "strategy_sizing": {"mom6_1h_pv4": "martingale"},
        "enabled": True,
    }
    out = dp.merged(dp.load(PRESET), mine)
    assert "mom6_1h_pv4" in out["strategies"]
    assert out["strategy_coins"]["mom6_1h_pv4"] == ["APEX_USDT"]
    assert out["strategy_books"]["mom6_1h_pv4"] == ["real"]
    assert out["strategy_margins"]["mom6_1h_pv4"] == 12.0
    assert out["strategy_sizing"]["mom6_1h_pv4"] == "martingale", \
        "another strategy's sizing is not the preset's business"
    assert out["strategy_coins"]["zscore20_1h_sl4tp06"] == ["GLM_USDT"]


THIS_MONTH = dp.PRESET_DIR / "this-month-15.json"


def test_a_coin_another_strategy_trades_LIVE_is_refused_not_taken():
    """A REAL holder blocks the coin — per coin, whatever the bar size, because
    MEXC nets every order on a contract into one position. LYN is wanted live
    by cci20_4h_sl3tp3 in this preset."""
    mine = {"strategy_coins": {"mom15_1h": ["LYN_USDT"]},
            "strategy_books": {"mom15_1h": ["real"]}}
    got = dp.plan(dp.load(THIS_MONTH), mine)
    assert "cci20_4h_sl3tp3" not in got["arm"]
    why = " ".join(b["why"] for b in got["refused"])
    assert "LYN_USDT" in why and "mom15_1h" in why, why
    # the rest still arm
    assert "ibs_4h_sl3tp3" in got["arm"]
    # and a DEMO holder blocks nothing at all
    mine["strategy_books"]["mom15_1h"] = ["paper"]
    assert not dp.plan(dp.load(THIS_MONTH), mine)["refused"]


def test_one_coin_of_several_can_be_refused_without_losing_the_others():
    """rsi14_30m_sl2tp2 carries SAPIEN and G on the real book. Taking G away
    must not cost SAPIEN its slot."""
    mine = {"strategy_coins": {"mom15_1h": ["G_USDT"]},
            "strategy_books": {"mom15_1h": ["real"]}}
    got = dp.plan(dp.load(THIS_MONTH), mine)
    armed = got["arm"]["rsi14_30m_sl2tp2"]["coins"]
    assert armed == ["SAPIEN_USDT"], armed
    why = " ".join(b["why"] for b in got["refused"])
    assert "G_USDT" in why, why


def test_the_same_strategy_keeping_its_own_coin_is_not_a_clash():
    """Applying twice must be a no-op, not a refusal."""
    once = dp.merged(dp.load(PRESET), {})
    twice = dp.merged(dp.load(PRESET), once)
    assert twice["strategy_coins"] == once["strategy_coins"]
    assert not dp.plan(dp.load(PRESET), once)["refused"]


def test_a_preset_never_turns_the_live_switch_on():
    out = dp.merged(dp.load(PRESET), {})
    assert out["enabled"] is False and out["dry_run"] is True
    for key in dp.load(PRESET)["strategies"]:
        assert out["strategy_books"][key] == ["paper"], key


def test_the_account_default_sizing_follows_the_preset():
    """A row armed by hand later must not silently ladder: these were measured
    flat and the shipped default is martingale."""
    out = dp.merged(dp.load(PRESET), {"sizing": "martingale"})
    assert out["sizing"] == "flat"
    assert at.sizing_for(out) == "flat"
    for key in dp.load(PRESET)["strategies"]:
        assert at.sizing_for(out, key) == "flat", key


def test_a_key_this_repo_does_not_have_is_refused_by_name():
    bad = {"name": "x", "strategies": {"nosuch_1h_sl4tp04": {"coins": ["A_USDT"]}}}
    got = dp.plan(bad, {})
    assert got["arm"] == {}
    assert "STRATEGY_SPECS" in got["refused"][0]["why"]


def test_a_preset_with_no_coins_is_refused_before_anything_is_decided(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"strategies": {"fvg_1h_sl4tp06": {"coins": []}}}),
                 encoding="utf-8")
    with pytest.raises(ValueError, match="no coins"):
        dp.load(p)
    p.write_text(json.dumps({"strategies": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="no strategies"):
        dp.load(p)


def test_the_dry_run_writes_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "SETTINGS_PATH", tmp_path / "auto_trade.json")
    dp.apply(PRESET, write=False)
    assert not (tmp_path / "auto_trade.json").exists()
    dp.apply(PRESET, write=True)
    got = json.loads((tmp_path / "auto_trade.json").read_text(encoding="utf-8"))
    assert got["strategy_coins"]["zscore20_1h_sl4tp06"] == ["GLM_USDT"]
    assert got["enabled"] is False


def test_the_unarmed_rows_are_named_with_the_row_that_beat_them():
    """Four rows share a coin+timeframe with a better one and are recorded, so
    the other machine can swap rather than wonder."""
    got = dp.load(PRESET)
    assert len(got["not_armed"]) == 4, got["not_armed"]
    for one in got["not_armed"]:
        assert one["row"] and one["coin"] and "holds" in one["why"]
    assert {o["coin"] for o in got["not_armed"]} == {"NEO", "COMP", "HAEDAL"}


def test_demo_claims_nothing_and_locks_nobody():
    """`timeframe_locks` locks REAL books only — "for demo it can have multiple
    strategies so i can see if its working" — and a preset must agree, per COIN
    whatever the bar size. `_claims` keyed on (coin, interval) and counted demo
    rows, so applying `this-month-15` twice refused four of its own strategies
    against the demo rows it had just written."""
    mine = {
        "strategy_coins": {"stoch14_1h_sl3tp3": ["LYN_USDT"]},
        "strategy_books": {"stoch14_1h_sl3tp3": ["paper"]},
    }
    got = dp.plan(dp.load(dp.PRESET_DIR / "this-month-15.json"), mine)
    assert not got["refused"], got["refused"]
    assert "cci20_4h_sl3tp3" in got["arm"]

    # a REAL holder on the same coin DOES block, even at another timeframe
    mine["strategy_books"]["stoch14_1h_sl3tp3"] = ["real"]
    got = dp.plan(dp.load(dp.PRESET_DIR / "this-month-15.json"), mine)
    why = " ".join(b["why"] for b in got["refused"])
    assert "LYN_USDT" in why and "stoch14_1h_sl3tp3" in why, why
    assert "cci20_4h_sl3tp3" not in got["arm"]
    # and a row that only wants the DEMO book is never blocked by it
    assert "cci20_4h_sl25tp4" in got["arm"], "that LYN row asks for paper"


def test_this_months_preset_records_what_it_is():
    """Thirteen of its fifteen rows fail the screen. The file has to SAY so, or
    the next machine arms nine live strategies on faith."""
    got = dp.load(dp.PRESET_DIR / "this-month-15.json")
    assert "FAIL" in got["why"] or "fail" in got["why"]
    assert "cannot win" in got["measured"]["warning"]
    assert "one_live_per_coin" in got["measured"]
    ids, failing, real = set(), 0, 0
    for key, one in got["strategies"].items():
        assert key in at.STRATEGY_SPECS, key
        for coin, m in one["measured"].items():
            ids.add(m["row"])
            failing += 0 if m["still_working"] else 1
            real += 1 if m["book"] == "real" else 0
            assert m["days"] >= 22 and m["trades_full"] > 0
            assert "green" in m and m["gate"] in ("ok", "warn")
            if not m["still_working"]:
                assert m["why_not"], (key, coin)
    assert len(ids) == 15, sorted(ids)
    assert failing == 13, failing
    assert real == 10, f"{real} coins on the real book"
