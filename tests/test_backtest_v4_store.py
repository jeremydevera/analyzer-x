"""Backtest v4 (Nov 10, 2026): the Claude skills' strategies with every trade, filed in a database of
their own and read with the filters of Backtest v2 - win rate, profit, TP/SL ceilings, last N days."""
import json
from datetime import datetime, timezone

import pytest

from tradingagents import stores, v4_store as v4

DAY = 86_400_000
END = int(datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp() * 1000)


def _pick(strategy, stop, target, pnls, *, split_back_days=20, end=END, lost=False, gap=DAY):
    """A skill pick whose trades close every `gap` ms ending at `end`."""
    n = len(pnls)
    tr = []
    for i, p in enumerate(pnls):
        ex = end - (n - 1 - i) * gap
        tr.append([ex - 3_600_000, ex, 1, "SL" if p < 0 else "TP", p])
    label = f"{strategy}(period=14) stop {stop * 100:g}%" + (f" target {target * 100:g}%" if target else "")
    return {"label": label, "strategy": strategy, "params": {"period": 14}, "stop": stop, "target": target,
            "older": {}, "newer": {}, "older_lost": lost, "trades": tr}


def _line(coin, tf, picks, end=END, days=60, split_back_days=20):
    return {"coin": coin, "tf": tf, "fee": 0.00075, "slip": 0.001, "bars": 500, "combos": len(picks),
            "split_ms": end - split_back_days * DAY, "start_ms": end - days * DAY, "end_ms": end, "bar": 0.0,
            "picks": picks}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    folder = tmp_path / "acs"
    folder.mkdir()
    lines = {
        "AAA|1h": _line("AAA", "1h", [
            _pick("bf_momentum", 0.015, None, [1, 1, 1, -1, 1, 1] * 5),          # 30 trades, 25 wins
            _pick("ta_ma_pullback", 0.03, 0.06, [-1, -1, -1, 5, -1, -1] * 5),    # a win of 5 splits the runs; the 2 at the end of one block join the 3 at the start of the next: 5 in a row
        ]),
        "BBB|15m": _line("BBB", "15m", [
            _pick("bf_momentum", 0.015, 0.03, [2, -1, 2, -1] * 4),
        ]),
    }
    (folder / "skilltaall.json").write_text(json.dumps({"lines": lines}), encoding="utf-8")
    target = tmp_path / "v4" / "rows.db"
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "rows_db": target}))
    v4.build(folder, target=target, sources=(("skilltaall.json", "technical-analysis"),), log=lambda *_: None)
    return target


def ids(res):
    return {r["id"] for r in res["rows"]}


def test_every_strategy_is_filed_with_every_trade(db):
    m = v4.meta()
    assert m["strategies"] == 3 and m["trades"] == 30 + 30 + 16
    res = v4.query({"limit": 50})
    assert res["total"] == 3 and len(res["rows"]) == 3
    by = {(r["coin"], r["strategy"]): r for r in res["rows"]}
    mom = by[("AAA", "bf_momentum")]
    assert (mom["trades"], mom["wins"], mom["losses"]) == (30, 25, 5) and mom["profit"] == 20.0
    assert mom["win_rate"] == pytest.approx(100 * 25 / 30)


def test_the_id_is_the_all_coins_page_id_and_never_a_position(db):
    from tradingagents import backtest_report as br
    res = v4.query({})
    r = next(r for r in res["rows"] if r["strategy"] == "ta_ma_pullback")
    want = br.row_code("AAA", "1h", "ta_ma_pullback", 0, 3.0, 6.0, "flat", plan=r["label"], res="skill")
    assert r["id"] == want and len(want) == 8


def test_worst_losing_run_is_the_sum_of_the_unbroken_run_and_its_length(db):
    r = next(r for r in v4.query({})["rows"] if r["strategy"] == "ta_ma_pullback")
    assert (r["worst_run"], r["worst_run_n"]) == (-5.0, 5)
    log = v4.trade_log(r["id"])
    assert log["worst_run"] == -5.0 and log["worst_run_n"] == 5


def test_tp_and_sl_are_ceilings_inclusive_and_a_row_with_no_target_is_left_out_by_max_tp(db):
    assert ids(v4.query({"max_tp": 3})) == {r["id"] for r in v4.query({})["rows"]
                                              if r["tp"] == 3.0}              # BBB only: 3% kept, 6% and none out
    assert {r["tp"] for r in v4.query({"max_tp": 6})["rows"]} == {3.0, 6.0}
    assert {r["sl"] for r in v4.query({"max_sl": 1.5})["rows"]} == {1.5}
    assert v4.query({"max_sl": 3})["total"] == 3
    n = v4.query({"max_tp": 3})
    assert any("no target" in x for x in n["notes"])


def test_win_rate_and_profit_floors_take_the_units_the_columns_print(db):
    assert v4.query({"min_winrate": 80})["total"] == 1                   # 83.3% only
    assert v4.query({"min_winrate": 50})["total"] == 2                   # 83.3% and 50% (inclusive)
    assert v4.query({"min_profit": 10})["total"] == 1
    assert v4.query({"min_profit": 10, "base_margin": 10})["total"] == 2  # at $10 margin a row shows 2x


def test_the_base_margin_rescales_every_dollar(db):
    a = next(r for r in v4.query({})["rows"] if r["strategy"] == "bf_momentum" and r["coin"] == "AAA")
    b = next(r for r in v4.query({"base_margin": 10})["rows"] if r["id"] == a["id"])
    assert b["profit"] == a["profit"] * 2 and b["worst_run"] == a["worst_run"] * 2
    log = v4.trade_log(a["id"], base_margin=10)
    assert log["total_profit"] == b["profit"] and log["notional"] if "notional" in log else True


def test_last_n_days_re_adds_every_row_over_that_slice(db):
    # one trade a day: the last 10 days hold exactly the 10 newest trades of each row
    res = v4.query({"days": 10})
    for r in res["rows"]:
        assert r["trades"] == 10
        assert r["wins"] + r["losses"] == 10
    assert res["window"]["days"] == 10
    r = next(r for r in res["rows"] if r["strategy"] == "bf_momentum" and r["coin"] == "AAA")
    newest = ([1, 1, 1, -1, 1, 1] * 5)[-10:]
    assert (r["wins"], r["profit"]) == (sum(1 for p in newest if p > 0), float(sum(newest)))
    # and the win-rate floor is then the WINDOW's own
    assert all(x["win_rate"] >= 70 for x in v4.query({"days": 10, "min_winrate": 70})["rows"])


def test_a_window_row_count_names_the_windows_dates_and_drops_rows_with_no_trade(db):
    res = v4.query({"days": 1})
    assert res["window"]["to_s"] - res["window"]["from_s"] == 86_400
    assert all(r["trades"] >= 1 for r in res["rows"])


def test_unseen_counts_only_trades_that_opened_after_the_split(db):
    res = v4.query({"unseen": True})
    for r in res["rows"]:
        assert r["trades"] == r["newer_trades"] and r["profit"] == r["newer_profit"]


def test_the_id_search_overrides_every_other_filter_and_opens_its_row(db):
    r0 = v4.query({"coin": "BBB"})["rows"][0]
    got = v4.query({"row_id": "#" + r0["id"].lower(), "min_winrate": 99, "coin": "AAA", "days": 5})
    assert [r["id"] for r in got["rows"]] == [r0["id"]]


def test_the_trade_log_adds_up_to_its_rows_total_profit(db):
    for r in v4.query({})["rows"]:
        log = v4.trade_log(r["id"])
        assert round(sum(t["pnl"] for t in log["log"]), 2) == log["total_profit"] == r["profit"]
        assert len(log["log"]) == r["trades"]
        assert log["log"][-1]["running"] == log["total_profit"]
    w = v4.trade_log(r["id"], days=3)
    assert len(w["log"]) == 3 and w["window"]["days"] == 3


def test_sorting_and_paging_are_the_servers(db):
    first = v4.query({"sort": "profit", "desc": True, "limit": 1})
    second = v4.query({"sort": "profit", "desc": True, "limit": 1, "offset": 1})
    assert first["rows"][0]["profit"] >= second["rows"][0]["profit"] and first["total"] == 3
    assert v4.query({"limit": 10_000})["limit"] == v4.PAGE_MAX


def test_an_empty_store_says_why_instead_of_an_empty_table(tmp_path, monkeypatch):
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "rows_db": tmp_path / "none.db"}))
    res = v4.query({})
    assert res["ready"] is False and "build" in res["why"]


def test_a_build_with_nothing_to_file_refuses_to_replace_the_store(tmp_path):
    (tmp_path / "x").mkdir()
    with pytest.raises(RuntimeError, match="nothing was filed"):
        v4.build(tmp_path / "x", target=tmp_path / "out" / "rows.db", log=lambda *_: None)
    assert not (tmp_path / "out" / "rows.db").exists()
