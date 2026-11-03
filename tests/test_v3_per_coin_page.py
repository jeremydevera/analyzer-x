"""The Backtest v3 per-coin results page (tradingagents/v3_per_coin_page.py) carries the standard kit
(CLAUDE.md "Backtest reporting requirements"): one row per coin x idea with every field and its
stable id first, every figure worked out in the page FROM ITS TRADES (so they add up to the row),
the counts above the table - judged, profitable, and what luck alone would make profitable - the
risk box, the last-N-days re-add, the max TP % / max SL % ceilings, a "profitable only" box, and
the trade log with its TOTAL PROFIT. The payload is compressed in its encoding, never by dropping
a field. The page's own JavaScript is run under node, on the payload it embeds."""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

import tests.test_v3_per_coin as tpc
import tests.test_v3_verdicts as tv
from tradingagents import v3_per_coin as vpc, v3_per_coin_page as vpp, v3_research as vrs

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


@pytest.fixture()
def page(monkeypatch, tmp_path):
    run = tv.make_run(monkeypatch, tmp_path)
    monkeypatch.setattr(vpc, "store_path", lambda: tmp_path / "v3" / "verdicts-per-coin.json")
    monkeypatch.setattr(vpc, "history_dir", lambda: tmp_path / "v3" / "verdicts-per-coin")
    # a third coin whose setting could not be chosen: every row is on the page, judged or not
    vrs.save_coin(run.folder, tpc._rec("XPT_USDT", [], [], []) | {
        "plan_id": run.plan["id"], "plan_end_ms": run.plan["end_ms"]})
    store = vpc.build("pilot", now=1_793_000_000.0)
    records = vrs.load_coins(run.folder)
    html = vpp.build(store, records)
    return store, records, html, vpp.payload(store, records), run


def _js(html: str, data: dict, expr: str):
    logic = re.search(r"/\*LOGIC\*/(.*?)/\*END LOGIC\*/", html, re.S).group(1)
    prog = f"const D={json.dumps(data)};\n{logic}\nconst ROWS=rowsOf(D);\n" \
           f"console.log(JSON.stringify({expr}));"
    out = subprocess.run([NODE], input=prog, capture_output=True, text=True, timeout=60,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_every_coin_x_idea_row_is_on_the_page_with_every_field(page):
    store, _r, _h, data, _run = page
    assert len(data["R"]) == len(store["rows"]) == 3
    assert {len(r) for r in data["R"]} == {len(data["F"])}, "every row carries every field (kit F)"
    assert data["F"][0] == "id" and [r[0] for r in data["R"]] == [r["id"] for r in store["rows"]]
    coins = [r[data["F"].index("coin")] for r in data["R"]]
    assert coins == ["XAG_USDT", "XAU_USDT", "XPT_USDT"]
    blank = data["R"][2][data["F"].index("blank")]
    assert blank.startswith("could not choose") and data["T"][2] == []


def test_the_page_embeds_the_payload_compressed_and_it_comes_back_whole(page):
    _s, _r, html, data, _run = page
    assert vpp.unpack(html) == json.loads(json.dumps(data))
    assert "DecompressionStream" in html and 'const Z="";' not in html


@needs_node
def test_a_rows_figures_add_up_to_the_row_the_store_judged(page):
    store, _r, html, data, _run = page
    got = _js(html, data, "ROWS.map(r=>{const m=measure(r,null,1);return [m.trades,m.profit,"
                          "m.wins,profitable(m,D)]})")
    for (n, profit, wins, ok), row in zip(got[:2], store["rows"][:2], strict=True):
        assert n == row["trades"] == 200 and wins == row["wins"]
        assert profit == pytest.approx(row["profit"], abs=0.01) and ok is True
    assert got[2][0] == 0 and got[2][3] is False


@needs_node
def test_above_the_table_the_counts_are_judged_profitable_and_what_luck_gives(page):
    store, _r, html, data, _run = page
    got = _js(html, data, "tally(ROWS.map(r=>({r,m:measure(r,null,1)})),D)")
    assert got["rows"] == 3 and got["profitable"] == 2
    assert got["luck"] == pytest.approx(store["totals"]["luck_profitable"]) == pytest.approx(0.8)


@needs_node
def test_the_risk_box_rescales_every_dollar_and_the_window_re_adds(page):
    _s, _r, html, data, _run = page
    k = "ROWS.map(r=>measure(r,null,2/D.risk).profit)"     # the box at $2: k = $2 / the $5
    one, two = _js(html, data, "ROWS.map(r=>measure(r,null,1).profit)"), _js(html, data, k)
    assert two[0] == pytest.approx(one[0] * 0.4)            # $2 of the $5 measured
    # the last 10 days of the unseen days: only the trades that closed in them
    got = _js(html, data, "(()=>{const w=windowOf(D,10);return ROWS.map(r=>measure(r,w.from,1)"
                          ".trades)})()")
    assert got[0] < 200 and got[2] == 0


@needs_node
def test_max_tp_and_max_sl_are_inclusive_ceilings_and_profitable_only_is_a_box(page):
    _s, _r, html, data, _run = page
    # XAG trades carry a 1.0% stop and a 1.2% target, XAU 0.4% and 0.6%
    got = _js(html, data, "ROWS.map(r=>{const m=measure(r,null,1);return [fails(m,{sl:1.0},D),"
                          "fails(m,{sl:0.99},D),fails(m,{tp:0.6},D),fails(m,{pass:true},D)]})")
    xag, xau, xpt = got
    assert xag[0] == [] and xag[1] == ["max SL %"] and xag[2] == ["max TP %"]
    assert xau[2] == [] and xau[3] == [] and xpt[3] == ["profitable only"]


@needs_node
def test_the_win_and_loss_sizes_are_worked_out_in_the_page(page):
    _s, _r, html, data, _run = page
    got = _js(html, data, "ROWS.map(r=>{const m=measure(r,null,1);return [m.avgWin,m.avgLoss,"
                          "m.ratio]})")
    assert got[0][0] == pytest.approx(0.30) and got[0][1] is None and got[0][2] is None


def test_the_kit_is_on_the_page(page):
    _s, _r, html, _d, _run = page
    for label in ("PROFIT (total $)", "TP (target rule)", "SL (stop rule)", '"Leverage"',
                  '"W"', '"L"', "W / L a day", "Worst losing run", "Trades a day",
                  "Months green", "Win size ÷ loss size", "Random runs profitable by the rule",
                  "Typical cost (all unseen days)", "f-risk", "f-pass", "f-wr", "f-pr", "f-gm",
                  "f-dd", "f-tp", "f-sl", "f-days", "f-id", "Clear all filters", "TOTAL PROFIT",
                  "combinations tried", "margin = the coin bought ÷ its leverage"):
        assert label in html, label


def test_a_folder_that_no_longer_holds_the_judged_trades_is_refused(page):
    store, records, _h, _d, run = page
    rec = next(r for r in records if r["coin"] == "XAU_USDT")
    key = next(iter(k for k in rec["combos"] if k.endswith("|k2|1h|none")))
    rec["combos"][key]["unseen"]["rows"] = rec["combos"][key]["unseen"]["rows"][:-1]
    with pytest.raises(ValueError, match="publish the per-coin verdicts again"):
        vpp.payload(store, records)


def test_a_store_of_another_shape_is_refused_by_name(page):
    store, records, *_ = page
    with pytest.raises(ValueError, match="per-coin store version"):
        vpp.payload({**store, "version": 9}, records)


def test_write_builds_from_the_newest_kept_copy(page, monkeypatch, tmp_path):
    import dataclasses

    from tradingagents import stores

    _s, _r, _h, _d, run = page
    vpc.publish("pilot", now=1_793_000_000.0)
    monkeypatch.setattr(stores, "V3", dataclasses.replace(stores.V3, home=tmp_path / "v3"))
    out = vpp.write("pilot")
    assert out.name == "pilot-per-coin.html" and out.parent == tmp_path / "v3" / "pages"
    assert len(vpp.unpack(out.read_text(encoding="utf-8"))["R"]) == 3
