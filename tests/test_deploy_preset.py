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


def test_a_coin_another_strategy_trades_LIVE_is_SHARED_not_refused():
    """It was refused until 2026-09-04. The operator then armed 35 rows over
    9 coins (20 on GPNSTOCK) and asked for the runtime rule — one OPEN
    POSITION per coin, first signal wins — so the coin is SHARED and the plan
    SAYS who else is on it, because 20 rows on one contract is worth seeing
    before applying."""
    mine = {"strategy_coins": {"mom15_1h": ["LYN_USDT"]},
            "strategy_books": {"mom15_1h": ["real"]}}
    got = dp.plan(dp.load(THIS_MONTH), mine)
    assert "cci20_4h_sl3tp3" in got["arm"]
    assert "LYN_USDT" in got["arm"]["cci20_4h_sl3tp3"]["coins"]
    assert not got["refused"], got["refused"]
    shared = " ".join(f"{b['key']} {b['with']}" for b in got["shared"])
    assert "LYN_USDT" in shared and "mom15_1h" in shared, shared
    assert "signals first" in shared, "and it says how the tie is settled"
    # a DEMO holder is not even worth mentioning: nothing nets on paper
    mine["strategy_books"]["mom15_1h"] = ["paper"]
    assert not dp.plan(dp.load(THIS_MONTH), mine)["shared"]


def test_a_multi_coin_row_keeps_every_coin_and_names_the_shared_one():
    """rsi14_30m_sl2tp2 carries SAPIEN and G on the real book. G is also
    traded by another row here: both coins stay armed, and G is named."""
    mine = {"strategy_coins": {"mom15_1h": ["G_USDT"]},
            "strategy_books": {"mom15_1h": ["real"]}}
    got = dp.plan(dp.load(THIS_MONTH), mine)
    armed = sorted(got["arm"]["rsi14_30m_sl2tp2"]["coins"])
    assert armed == ["G_USDT", "SAPIEN_USDT"], armed
    shared = " ".join(b["with"] for b in got["shared"])
    assert "G_USDT" in shared, shared


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

    # a REAL holder on the same coin is NAMED (not blocked) since 2026-09-04
    mine["strategy_books"]["stoch14_1h_sl3tp3"] = ["real"]
    got = dp.plan(dp.load(dp.PRESET_DIR / "this-month-15.json"), mine)
    shared = " ".join(f"{b['key']} {b['with']}" for b in got["shared"])
    assert "LYN_USDT" in shared and "stoch14_1h_sl3tp3" in shared, shared
    assert "cci20_4h_sl3tp3" in got["arm"], "named, not blocked"
    assert not got["refused"], got["refused"]
    # and a row that only wants the DEMO book is never even mentioned by it
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


# ---------------------------------------------------------------------------
# REPLACE, not merge.
#
# Operator, 2026-09-04: *"REMOVE THE EXISTING AUTO TRADE STRATEGIES
# COMPLIETELY AND ADD THESE IDS"* — 35 of them, by id.

LIVE35 = dp.PRESET_DIR / "live-35.json"


def test_replace_disarms_everything_the_preset_does_not_name():
    mine = {
        "strategies": ["mom6_1h_g", "cci20_4h_sl3tp3"],
        "strategy_coins": {"mom6_1h_g": ["G_USDT"],
                           "cci20_4h_sl3tp3": ["LYN_USDT"]},
        "strategy_books": {"mom6_1h_g": ["real"],
                           "cci20_4h_sl3tp3": ["real"]},
        "strategy_margins": {"mom6_1h_g": 5.0, "cci20_4h_sl3tp3": 5.0},
        "strategy_sizing": {"mom6_1h_g": "martingale"},
        "strategy_loss_limits": {"mom6_1h_g": 8.0},
        "strategy_labels": {"mom6_1h_g": "old"},
    }
    out = dp.merged(dp.load(LIVE35), mine)
    named = set(dp.load(LIVE35)["strategies"])
    assert set(out["strategies"]) == named
    for field in ("strategy_coins", "strategy_books", "strategy_margins",
                  "strategy_sizing"):
        assert set(out[field]) == named, field
    # a limit or a label for a row nobody arms would come back the moment that
    # row is armed by hand again
    assert out["strategy_loss_limits"] == {}
    assert out["strategy_labels"] == {}
    # and the live switch is STILL not turned on by a preset
    assert out["enabled"] is False and out["dry_run"] is True


def test_merge_is_still_the_default():
    mine = {"strategies": ["mom6_1h_g"],
            "strategy_coins": {"mom6_1h_g": ["G_USDT"]},
            "strategy_books": {"mom6_1h_g": ["real"]}}
    out = dp.merged(dp.load(PRESET), mine)
    assert "mom6_1h_g" in out["strategies"], "a merge touches nothing else"


def test_the_35_rows_are_all_real_flat_and_one_id_each():
    preset = dp.load(LIVE35)
    assert preset["replace"] is True
    assert len(preset["strategies"]) == 35
    coins = set()
    for key, one in preset["strategies"].items():
        assert one["book"] == ["real"], key
        assert one["sizing"] == "flat", key
        assert one["margin"] == 5.0, key
        assert len(one["rows"]) == 1, key
        assert len(one["coins"]) == 1, key
        coins.add(one["coins"][0])
        # the KEY has to say the same barriers as the measurement, or the
        # runner trades a combination nobody measured (rule 21)
        got = list(one["measured"].values())[0]
        assert f"_{got['tf']}_" in key, (key, got["tf"])
        assert key.startswith(got["signal"] + "_"), (key, got["signal"])
    assert len(coins) == 9, sorted(coins)
    # 20 rows on one contract is the case the runtime rule exists for
    per = {}
    for one in preset["strategies"].values():
        per[one["coins"][0]] = per.get(one["coins"][0], 0) + 1
    assert per["GPNSTOCK_USDT"] == 20, per


def test_every_key_in_the_preset_is_a_spec_the_runner_can_trade():
    """A key whose rule the runner cannot emit trades exactly never — the
    rsi14_30m lesson."""
    from tradingagents import auto_trader as at
    from tradingagents.signals_conf import CONF_SIGNALS
    from tradingagents.signals_ext import EXTRA_SIGNALS
    from tradingagents.signals_ext2 import EXTRA_SIGNALS2

    known = set(CONF_SIGNALS) | set(EXTRA_SIGNALS) | set(EXTRA_SIGNALS2)
    for key, one in dp.load(LIVE35)["strategies"].items():
        spec = at.STRATEGY_SPECS.get(key)
        assert spec, f"{key} is not in STRATEGY_SPECS"
        assert key in at.STRATEGY_ORDER, f"{key} is not in STRATEGY_ORDER"
        got = list(one["measured"].values())[0]
        assert abs(spec["tp"] * 100 - got["tp_pct"]) < 1e-9, (key, spec)
        assert abs(spec["sl"] * 100 - got["sl_pct"]) < 1e-9, (key, spec)
        assert key.split("_")[0] in known, key


def test_the_preset_says_how_thin_the_evidence_is():
    """Every row has 18-48 trades over 1-3 months. A file that armed 35 live
    rows without saying so would be the still-working rule quietly skipped."""
    preset = dp.load(LIVE35)
    why = preset["why"] + json.dumps(preset["measured"])
    assert "THIN" in why
    assert "still-working" in why
    assert "one_position_per_coin" in json.dumps(preset["measured"])
    for one in preset["strategies"].values():
        got = list(one["measured"].values())[0]
        assert got["trades"] >= 1 and got["profit"] is not None
        assert "/" in got["green"], got
