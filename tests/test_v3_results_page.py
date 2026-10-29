"""The Backtest v3 results page (tradingagents/v3_results_page.py, Part 2b)
carries the standard kit (CLAUDE.md "Backtest reporting requirements"): every
judged group a row with every field and its stable id first, the row's figures
worked out in the page FROM ITS TRADES (so they add up to the verdict), the
risk box rescaling every dollar, the window re-adding every row over the
trades that closed in it and dropping the months outside it, the max TP % and
max SL % boxes as inclusive ceilings, and the trade log with its TOTAL PROFIT.
The page's own JavaScript is run under node, on the payload it embeds."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess

import pytest

import tests.test_v3_verdicts as tv
from tradingagents import v3_page as vpg, v3_results_page as vrp, v3_verdicts as vv
from tradingagents.positions_view import fmt_when

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture()
def page(monkeypatch, tmp_path):
    run = tv.make_run(monkeypatch, tmp_path)
    store = vv.build("pilot", now=1_793_000_000.0)
    records = vv_records(run)
    return store, records, vrp.build(store, records), vrp.payload(store, records)


def vv_records(run):
    from tradingagents import v3_research as vrs

    return vrs.load_coins(run.folder)


def _js(html: str, data: dict, expr: str):
    logic = re.search(r"/\*LOGIC\*/(.*?)/\*END LOGIC\*/", html, re.S).group(1)
    prog = f"const D={json.dumps(data)};\n{logic}\nconsole.log(JSON.stringify({expr}));"
    # the program on stdin: a payload of thousands of trades is past Windows' command-line limit
    out = subprocess.run([NODE], input=prog, capture_output=True, text=True, timeout=60,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def _snap(data):
    return next(i for i, r in enumerate(data["rows"]) if r["family"] == "v3_snap"
                and r["tf"] == "1h" and r["filter"] == "none")


def test_every_judged_group_is_a_row_with_every_field(page):
    store, _records, html, data = page
    assert len(data["rows"]) == len(store["verdicts"]) == 27
    keys = {frozenset(r) for r in data["rows"]}
    assert len(keys) == 1, "every row carries every field (kit F)"
    chose = next(r for r in data["rows"] if r["failed"] == "choose")
    assert chose["t"] == [] and chose["blank"] == "not judged: no setting was chosen"
    embedded = json.loads(re.search(r"const D = (\{.*?\});\n", html).group(1))
    assert embedded == json.loads(json.dumps(data))


def test_a_rows_trades_are_its_chosen_settings_unseen_trades_in_closing_order(page):
    _store, records, _html, data = page
    row = data["rows"][_snap(data)]
    assert row["setting"] == "k2" and len(row["t"]) == 400
    assert [t[2] for t in row["t"]] == sorted(t[2] for t in row["t"])
    # coin index, entry and exit seconds, side, profit x 10,000, exit kind, stop and target x 100,000
    first = row["t"][0]
    assert data["coins"][first[0]] in ("XAG_USDT", "XAU_USDT") and first[3] == 1
    assert first[4] == 3000 and data["whys"][first[5]] == "TP" and first[6] in (400, 1000)


@needs_node
def test_the_row_adds_up_to_its_verdict_and_its_trades(page):
    store, _records, html, data = page
    i = _snap(data)
    m = _js(html, data, f"measure(D.rows[{i}],null,1)")
    v = next(x for x in store["verdicts"] if x["id"] == data["rows"][i]["id"])
    assert m["trades"] == v["unseen"]["trades"] == 400
    assert m["wins"] + m["losses"] == m["trades"] and m["wins"] == v["unseen"]["wins"]
    assert m["profit"] == pytest.approx(v["unseen"]["profit"], abs=0.005)
    assert (round(m["worst"], 2), m["worstN"]) == vpg.worst_run([t[4] / 1e4 for t in m["t"]])
    # 200 trades at a 0.4% stop / 0.6% target and 200 at 1.0% / 1.2%: the boxes read the WIDEST
    # of every trade's own, in percent, and the row shows the least beside it
    assert m["stop"] == pytest.approx(1.0) and m["target"] == pytest.approx(1.2)
    assert m["stopLeast"] == pytest.approx(0.4) and m["targetLeast"] == pytest.approx(0.6)


@needs_node
def test_the_risk_box_rescales_every_dollar(page):
    _store, _records, html, data = page
    i = _snap(data)
    one, two = _js(html, data, f"[measure(D.rows[{i}],null,1),measure(D.rows[{i}],null,2)]")
    assert two["profit"] == pytest.approx(2 * one["profit"])
    assert two["per"] == pytest.approx(2 * one["per"]) and two["trades"] == one["trades"]


@needs_node
def test_the_window_re_adds_each_row_and_drops_the_months_outside_it(page):
    _store, _records, html, data = page
    i = _snap(data)
    end = data["end"] // 1000
    got = _js(html, data, f"[measure(D.rows[{i}],{end - 30 * 86400},1),"
                          f"monthsIn(monthList(D),{end},30),monthsIn(monthList(D),{end},null)]")
    m, months30, every = got
    closed = [t for t in data["rows"][i]["t"] if t[2] >= end - 30 * 86400]
    # the fixture's trades close one day after another to Oct 12, 2026: some in the last 30
    # days, most before them
    assert 0 < len(closed) < 400
    assert m["trades"] == len(closed)
    assert m["profit"] == pytest.approx(sum(t[4] for t in closed) / 1e4)
    assert set(data["months"]) <= set(every) and set(months30) <= set(every)
    assert all(mk >= months30[0] for mk in months30) and len(months30) <= 2


@needs_node
def test_max_tp_and_max_sl_are_inclusive_ceilings_and_a_trail_has_no_target(page):
    _store, _records, html, data = page
    m = {"win": 100.0, "profit": 120.0, "green": 2, "worst": 0, "stop": 0.7, "target": 0.9}
    trail = {**m, "target": None}
    got = _js(html, data, f"[fails({json.dumps(m)},{{sl:0.7,tp:0.9}}),"
                          f"fails({json.dumps(m)},{{sl:0.69}}),"
                          f"fails({json.dumps(m)},{{tp:0.89}}),"
                          f"fails({json.dumps(trail)},{{tp:50}}),"
                          f"fails({json.dumps(m)},{{gm:2}}),fails({json.dumps(m)},{{gm:3}})]")
    assert got == [[], ["max SL %"], ["max TP %"], ["max TP %"], [], ["min months green"]]


def test_the_kit_is_on_the_page(page):
    _store, _records, html, _data = page
    cols = re.search(r"const COLS=\[(.*?)\];\n", html, re.S).group(1)
    assert cols.startswith('["id","ID",1]'), "a stable id first (kit H)"
    for label in ("PROFIT (total $)", "TP (target rule)", "TP %", "SL (stop rule)", "SL %",
                  "Leverage", '"W"', '"L"', "Worst losing run", "Trades a day", "Months green"):
        assert label in cols, label
    for box in ("f-risk", "f-wr", "f-pr", "f-gm", "f-dd", "f-tp", "f-sl", "f-days", "f-id",
                "clear"):
        assert f'id="{box}"' in html, box
    assert "TOTAL PROFIT" in html and "margin = the coin bought ÷ its leverage" in html
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    assert 2 <= len(title.split()) <= 4


@needs_node
def test_the_pages_date_format_is_the_projects(page):
    _store, _records, html, _data = page
    js = re.search(r"(const MON=.*?\nfunction fmtWhen\(ms\)\{.*?\n.*?\})\n", html, re.S).group(1)
    moments = [dt.datetime(2026, 8, 3, 20, 3), dt.datetime(2026, 9, 1, 0, 0),
               dt.datetime(2026, 9, 12, 12, 0)]
    ms = [int(x.timestamp() * 1000) for x in moments]
    out = subprocess.run([NODE, "-e", js + f"\nfor (const m of {ms}) console.log(fmtWhen(m));"],
                         capture_output=True, text=True, timeout=60).stdout.split("\n")
    assert out[:3] == [fmt_when(x / 1000) for x in ms]


def test_the_page_is_built_from_the_newest_kept_verdicts(monkeypatch, tmp_path):
    from tradingagents import stores

    tv.make_run(monkeypatch, tmp_path)
    vv.publish("pilot", now=1_793_000_000.0)
    vv.publish("pilot", now=1_793_000_100.0)
    monkeypatch.setattr(stores, "V3", stores.Store(**{**stores.V3.__dict__,
                                                      "home": tmp_path / "v3"}))
    out = vrp.write("pilot")
    data = json.loads(re.search(r"const D = (\{.*?\});\n", out.read_text(encoding="utf-8"))
                      .group(1))
    assert data["judged_at"] == 1_793_000_100.0 and out.parent == tmp_path / "v3" / "pages"
    with pytest.raises(ValueError, match="no verdicts kept for other"):
        vrp.write("other")


def test_a_store_of_another_version_is_refused_by_name(page):
    store, records, _html, _data = page
    from tradingagents import v3_verdicts as vv

    assert store["version"] == vv.VERSION == vrp.STORE_VERSION == 3
    with pytest.raises(ValueError, match=r"verdict store version 2.*reads version 3"):
        vrp.payload({**store, "version": 2}, records)
    with pytest.raises(ValueError, match="verdict store version None"):
        vrp.build({k: v for k, v in store.items() if k != "version"}, records)


@needs_node
def test_the_heading_says_pilot_only_for_a_run_sent_fewer_coins_than_the_plan(page):
    _store, _records, html, data = page
    assert data["dispatched"] == 3 and data["plan_coins"] == 4 and len(data["coins"]) == 2
    pilot, full, whole = _js(
        html, data, "[heading(D),heading({...D,dispatched:4}),"
                    "heading({...D,dispatched:4,plan_coins:2})]")
    assert pilot == "Pilot — 2 of the plan's 4 coins, not the proof"
    assert full == "Full run — 2 of 4 coins not judged"
    assert whole == "Every idea's verdict — 2 coins"


@needs_node
def test_every_coin_not_judged_is_named_once_with_its_bucket_and_the_accounts_beside(page):
    store, _records, html, data = page
    assert data["not_judged"] == store["not_judged"] and data["accounts"] == store["accounts"]
    lines = _js(html, {**data, "accounts": {"downloads_failed": ["a/x run 11: cut"]}},
                "notJudged(D)")
    by = {x["key"]: x for x in lines}
    assert by["failed"]["items"] == ["XPT_USDT: ConnectionError: cut"]
    assert by["failed"]["label"] == "failed"
    assert by["not_dispatched"]["items"] == ["EURUSD_USDT"]
    assert by["not_dispatched"]["label"] == "not sent (a pilot)"
    assert by["downloads_failed"]["items"] == ["a/x run 11: cut"]
    assert by["downloads_failed"]["account"] is True
    # a bucket with no coin in it prints nothing, and no coin is named in two
    assert not [k for k, x in by.items() if not x["items"]]
    names = [i.split(":")[0] for x in lines if not x["account"] for i in x["items"]]
    assert len(names) == len(set(names)) == 2
    assert sum(len(x["items"]) for x in lines if not x["account"]) \
        + len(data["coins"]) == data["plan_coins"], "judged + named is the whole plan"


def test_the_page_is_from_the_kept_copy_with_the_newest_stamp_and_counter(monkeypatch, tmp_path):
    tv.make_run(monkeypatch, tmp_path)
    for now in (1_793_000_000.0, 1_793_000_100.0, 1_793_000_100.0):
        vv.publish("pilot", now=now)
    d = vv.history_dir()
    (d / "pilot-2-1793999999999.json").write_text("{}", encoding="utf-8")   # another run's
    assert sorted(p.name for p in d.iterdir()) == [
        "pilot-1793000000000.json", "pilot-1793000100000-1.json", "pilot-1793000100000.json",
        "pilot-2-1793999999999.json"]
    assert vrp.newest_kept("pilot").name == "pilot-1793000100000-1.json"


# ------------------------------------------------------------------ fix round 1 (task review)
def _land_again(run, coin, unseen, risk=5.0):
    from tradingagents import v3_research as vrs

    vrs.save_coin(run.folder, tv._record(coin, run.plan, unseen, risk=risk))


def _v3_home(tmp_path, monkeypatch):
    from tradingagents import stores

    monkeypatch.setattr(stores, "V3", stores.Store(**{**stores.V3.__dict__,
                                                      "home": tmp_path / "v3"}))


def test_the_page_refuses_when_the_run_folder_now_holds_other_trades_than_the_verdicts(
        monkeypatch, tmp_path):
    import tests.test_v3_proof as tp

    run = tv.make_run(monkeypatch, tmp_path)
    vv.publish("pilot", now=1_793_000_000.0)
    _v3_home(tmp_path, monkeypatch)
    assert vrp.write("pilot").exists(), "the folder still agrees: the page is built"
    # a coin landed again with 100 unseen trades instead of 200: its rows are not the verdict's
    _land_again(run, "XAU_USDT", tv._eight(tp._rows([0.30] * 100, per_day=5), 0.004, 0.006))
    with pytest.raises(ValueError, match=r"[0-9A-Z]{8}: the run folder now holds trades the "
                                         r"verdicts were not judged on .*publish the verdicts "
                                         r"again"):
        vrp.write("pilot")


def test_the_page_refuses_when_a_judged_coin_was_landed_again_under_another_risk(
        monkeypatch, tmp_path):
    import tests.test_v3_proof as tp

    run = tv.make_run(monkeypatch, tmp_path)
    vv.publish("pilot", now=1_793_000_000.0)
    _v3_home(tmp_path, monkeypatch)
    _land_again(run, "XAU_USDT", tv._eight(tp._rows([0.30] * 200, per_day=5), 0.004, 0.006),
                risk=1.0)
    with pytest.raises(ValueError, match=r"XAU_USDT: .*no longer .*publish the verdicts again"):
        vrp.write("pilot")


def test_a_record_the_verdicts_never_judged_is_left_out_of_the_page(monkeypatch, tmp_path):
    import tests.test_v3_proof as tp

    run = tv.make_run(monkeypatch, tmp_path)
    vv.publish("pilot", now=1_793_000_000.0)
    _v3_home(tmp_path, monkeypatch)
    _land_again(run, "XPT_USDT", tv._eight(tp._rows([0.30] * 50, per_day=5), 0.004, 0.006))
    data = json.loads(re.search(r"const D = (\{.*?\});\n",
                                vrp.write("pilot").read_text(encoding="utf-8")).group(1))
    assert data["coins"] == ["XAG_USDT", "XAU_USDT"], "the coins the verdicts judged, no others"


@needs_node
def test_a_window_longer_than_the_data_starts_where_the_data_starts(page):
    _store, _records, html, data = page
    end, split = data["end"] / 1000, data["split"] / 1000
    long_, short, none = _js(html, data, "[windowOf(D,1000),windowOf(D,30),windowOf(D,null)]")
    assert long_["start"] == split and long_["clamped"] is True
    assert long_["span"] == pytest.approx((end - split) / 86400) == pytest.approx(90)
    assert short["start"] == end - 30 * 86400 and short["clamped"] is False
    assert short["span"] == pytest.approx(30)
    assert none["start"] == split and none["span"] == pytest.approx(90) and not none["clamped"]
    # 400 trades over the 90 days the data covers, never over the 1,000 typed
    assert _js(html, data, "perDay(400,windowOf(D,1000).span)") == "4.44"
    assert "all unseen days" in html


@needs_node
def test_max_sl_and_max_tp_are_ceilings_on_every_trades_own_stop_and_target(page):
    _store, _records, html, data = page
    i = _snap(data)
    # the snap row's median stop is 0.7% but half of its trades risk 1.0%: it passes max SL
    # 1.0 and fails 0.99; the same for the target (median 0.9%, widest 1.2%)
    got = _js(html, data, f"(()=>{{const m=measure(D.rows[{i}],null,1);"
                          "return [fails(m,{sl:1.0,tp:1.2}),fails(m,{sl:0.99}),fails(m,{tp:1.19}),"
                          "fails(m,{sl:0.7})]})()")
    assert got == [[], ["max SL %"], ["max TP %"], ["max SL %"]]
    for text in ("stop at most", "target at most", "on every trade"):
        assert text in html


@needs_node
def test_a_row_with_no_trade_has_no_numbers_and_never_passes_a_dip_or_a_green_box(page):
    _store, _records, html, data = page
    chose = next(i for i, r in enumerate(data["rows"]) if r["failed"] == "choose")
    m = _js(html, data, f"measure(D.rows[{chose}],null,1)")
    assert m["trades"] == 0 and m["green"] is None and m["win"] is None and m["per"] is None
    got = _js(html, data, f"[fails(measure(D.rows[{chose}],null,1),{{dd:50}}),"
                          f"fails(measure(D.rows[{chose}],null,1),{{gm:0}})]")
    assert got == [["max worst dip $"], ["min months green"]]


@needs_node
def test_blank_rows_sort_last_both_ways(page):
    _store, _records, html, data = page
    xs = [{"id": "A", "m": {"profit": None}, "r": {"random": [None, None]}},
          {"id": "B", "m": {"profit": 5}, "r": {"random": [None, None]}},
          {"id": "C", "m": {"profit": 9}, "r": {"random": [None, None]}}]
    up, down = _js(html, {**data, "xs": xs},
                   "[sortRows(D.xs,'profit',1).map(x=>x.id),sortRows(D.xs,'profit',-1).map(x=>x.id)]")
    assert up == ["B", "C", "A"] and down == ["C", "B", "A"]


@needs_node
def test_the_filters_are_named_in_the_words_a_reader_expects(page):
    _store, _records, html, data = page
    names = _js(html, data, "filterNames({wr:60,pr:5,gm:10,dd:10,tp:3,sl:1})")
    assert names == ["win at least 60%", "profit at least +$5.00", "10 or more months green",
                     "worst dip no worse than −$10.00", "target at most 3% on every trade",
                     "stop at most 1% on every trade"]
    assert _js(html, data, "[levWords([20,20]),levWords([10,20]),levWords(null)]") == [
        "20x", "10x-20x", None]


@needs_node
def test_month_columns_use_the_clock_of_the_printed_times(page):
    _store, _records, html, data = page
    # a trade printed Oct 31 9:00pm local is in the October column, whatever UTC says
    got = _js(html, data, "[monthKey(new Date(2026,9,31,21,0).getTime()/1000),"
                          "monthKey(new Date(2026,10,1,0,30).getTime()/1000),"
                          "monthList(D).length,"
                          "D.rows.every(r=>r.t.every(x=>monthList(D).includes(monthKey(x[2]))))]")
    assert got[0] == "2026-10" and got[1] == "2026-11" and got[2] >= 4 and got[3] is True
    assert "calendar months of your own time zone" in html


def test_the_log_is_paged_and_the_provenance_follows_the_risk_box(page):
    _store, _records, html, _data = page
    assert "const LOG_PAGE=" in html and "log-next" in html
    assert "function drawProv" in html and "no row has #" in html


# ---- the final fix wave (Oct 29, 2026) ---------------------------------------------------------

def _counted_run(monkeypatch, tmp_path):
    """make_run's pilot with XAU's chosen unseen walk counting 20 exits at a usual cost and 10
    orders placed with no book, 4 of which never filled."""
    import tests.test_v3_proof as tp
    from tradingagents import v3_research as vrs

    run = tv.make_run(monkeypatch, tmp_path)
    rec = next(r for r in vrs.load_coins(run.folder) if r["coin"] == "XAU_USDT")
    rec["combos"][tp.KEY]["unseen"]["counts"] = {"cost_unmeasured": 20,
                                                 "placement_unmeasured": 10, "missed": 4}
    vrs.save_coin(run.folder, rec)
    return run


def test_every_verdict_carries_its_typical_cost_share_and_page_and_tab_print_it(monkeypatch,
                                                                              tmp_path):
    """I3: COVERAGE FIRST beside every verdict - kept in the store, a column on the page, a
    column on the tab. 400 unseen trades are 800 entries and exits: 20 exits at a usual cost,
    and 6 to 10 of the 10 orders placed with no book were filled entries (4 never filled)."""
    run = _counted_run(monkeypatch, tmp_path)
    store = vv.build("pilot", now=1_793_000_000.0)
    snap = next(v for v in store["verdicts"] if v["family"] == "v3_snap" and v["tf"] == "1h"
                and v["filter"] == "none")
    u = snap["costs"]["unseen"]
    assert (u["legs"], u["typical_low"], u["typical_high"]) == (800, 26, 30)
    assert snap["costs"]["older"]["legs"] == 320, "both settings the choice compared, 2 coins"
    assert "unseen days 3.2%-3.8% of 800 entries and exits" in snap["costs"]["words"]
    assert all("costs" in v for v in store["verdicts"]), "beside EVERY verdict"
    records = vv_records(run)
    data = vrp.payload(store, records)
    row = data["rows"][_snap(data)]
    assert row["cost"] == {"unseen": "3.2%-3.8% of 800 entries and exits",
                           "older": "0.0% of 320 entries and exits", "share": 0.0325}
    chose = next(r for r in data["rows"] if r["failed"] == "choose")
    assert chose["cost"]["unseen"] == "no setting chosen"
    html = vrp.build(store, records)
    assert '["cost","Typical cost (all unseen days)"]' in html
    assert "settled without their own minute's order book" in html
    tab = vpg.check_row(snap)
    assert tab["cost_unseen"] == "3.2%-3.8% of 800 entries and exits"
    assert tab["cost_older"] == "0.0% of 320 entries and exits" and tab["cost_share"] == 0.0325


def test_wins_and_losses_a_day_and_one_leverage_as_one_number(page):
    """M12 (kit item 6: wins and losses a day for intraday) and M6 (the tab prints one leverage
    as "20x", like the page)."""
    from tradingagents.v3_measure import UNSEEN_DAYS

    store, _records, html, _data = page
    snap = next(v for v in store["verdicts"] if v["family"] == "v3_snap" and v["tf"] == "1h"
                and v["filter"] == "none")
    tab = vpg.check_row(snap)
    s = snap["unseen"]
    assert tab["wins_per_day"] == round(s["wins"] / UNSEEN_DAYS, 2)
    assert tab["losses_per_day"] == round(s["losses"] / UNSEEN_DAYS, 2)
    assert tab["lev"] == "20x"
    assert vpg.check_row({**snap, "lev": [12, 20]})["lev"] == "12x-20x"
    assert '["wlday","W / L a day"]' in html and "won and" in html and "lost a day" in html


def test_the_window_says_on_the_page_why_it_is_a_re_add_not_a_new_walk(page):
    """Task 7 review Minor 4: the reason ("no minutes ride in a page") is printed beside the
    count, not only in the module's docstring."""
    _store, _records, html, _data = page
    assert ("every row re-added from its trades that closed in it: no minutes ride in a page, so "
            "it is not a new walk") in html
