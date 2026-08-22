"""The generated backtest page must carry what CLAUDE.md's kit demands.

These are structural checks on the renderer, not a re-test of the engine: the
page has broken three times in ways a screenshot caught and a unit test would
have caught sooner -- a column reading a field only the re-simulated copy had,
a hardcoded coin list, and a deployed row that was not in the grid at all.
"""
import json

import pytest

from tradingagents import backtest_report as br


def _payload(rows=None, **kw):
    rows = rows if rows is not None else [_row()]
    base = {
        "rows": rows, "meta": {"FOO|1h": {"bars": 500, "days": 120,
                                          "rt": 0.19, "liq": 4.0,
                                          "fee": 0.0004}},
        "series": {}, "months": ["2026-08", "2026-07"], "cur": "2026-08",
        "lev": 20, "slip": 0.0003, "base": 5.0, "ladder": [1, 1, 2, 2, 4, 4, 8],
        "deployed": [], "excluded": [], "days_asked": 365,
        "fetched": "2026-08-19 00:00",
    }
    base.update(kw)
    return base


def _row(**kw):
    r = {"coin": "FOO", "tf": "1h", "signal": "mom6", "th": 0.3, "sl": 1.0,
         "tp": 4.0, "rr": 4.0, "sizing": "flat", "lev": 20, "base": 5.0,
         "notional": 100.0, "trades": 50, "wins": 20, "losses": 30,
         "winrate": 40.0, "profit": 12.34, "h1": 6.0, "h2": 6.34, "green": 2,
         "months": 2, "worst": -3.0, "dd": 8.0, "liqs": 0,
         "stop_reachable": True, "days": 120, "mon": [7.0, 5.34],
         "cost_of_tp": 4.8, "gate": "ok", "id": 1}
    r.update(kw)
    return r


def test_every_mandated_column_is_in_the_page():
    html = br.render(_payload(), title="t")
    for col in ("PROFIT TOTAL $", "TP %", "SL %", "lev", "WINS", "LOSSES",
                "trades", "trades/day", "worst streak $", "streak losses",
                "worst single trade $", "green", "ID"):
        assert f">{col}<" in html, f"missing column {col}"
    assert "combinations</b>" in html          # the count, above the table
    # base margin and notional are CONSTANT across rows: they belong in the
    # provenance line and the detail panel, not in 23,000 identical cells.
    assert "USDT base" in html and "notional)" in html
    for gone in (">base $<", ">notional $<", ">1st half<", ">2nd half<",
                 ">green %<"):
        assert gone not in html, f"{gone} should not be a grid column"


def test_kit_features_are_present():
    html = br.render(_payload(), title="t")
    for feature in ('id="base"', 'id="wallet"', 'id="fwin"', 'id="fprof"',
                    'id="fgreen"', 'id="fdip"', 'id="fid"', 'id="freset"',
                    'id="det"', "TOTAL PROFIT"):
        assert feature in html, f"missing {feature}"


def test_months_green_filter_is_a_count_not_a_percent():
    html = br.render(_payload(), title="t")
    assert "Min months green" in html
    assert "r.green<mnG" in html.replace(" ", "")


def test_coin_and_timeframe_pickers_come_from_the_rows():
    rows = [_row(coin="AAA", tf="1h", id=1), _row(coin="BBB", tf="4h", id=2)]
    html = br.render(_payload(rows), title="t")
    assert '<option value="AAA">AAA</option>' in html
    assert '<option value="BBB">BBB</option>' in html
    assert '<option value="4h">4h</option>' in html
    assert "'PI'" not in html and "'APEX'" not in html   # no hardcoded coins


def _embedded(html):
    """The payload as the browser sees it, with the wire encoding reversed.

    Rows travel as arrays aligned to `cols` and directions run-length encoded,
    because a 28,600-row year rendered to 28.9 MB against a 16 MB artifact
    ceiling. The rule (kit item F) is to compress the ENCODING and never the
    coverage, so this helper decodes exactly as the template does and every
    assertion below still runs against whole rows.
    """
    blob = json.loads(html.split("const D=", 1)[1].split(", LAD=", 1)[0])
    if blob.get("cols"):
        cols = blob["cols"]
        blob["rows"] = [dict(zip(cols, a, strict=False)) for a in blob["rows"]]
    return blob


def test_payload_is_embedded_as_valid_json():
    p = _payload()
    html = br.render(p, title="t")
    assert _embedded(html)["rows"][0]["coin"] == "FOO"


def test_packing_preserves_every_field_of_every_row():
    """The encoding may shrink; the coverage may not. 22,482 rows once lost
    their month columns to a size cap, and it went unnoticed because the
    default view hid them."""
    rows = [_row(id=1, mon=[1.0, 2.0]), _row(id=2, mon=[None, 3.0])]
    p = _payload(rows)
    before = [dict(r) for r in p["rows"]]
    html = br.render(p, title="t")
    after = _embedded(html)["rows"]
    assert len(after) == len(before)
    for a, b in zip(before, after, strict=False):
        assert set(a) == set(b), "a field went missing in the wire encoding"
        for k in a:
            assert a[k] == b[k], f"{k} changed: {a[k]!r} -> {b[k]!r}"


def test_directions_survive_run_length_encoding():
    """"nnnnnuuu" -> "n5u3" is 32% of the size and must be exactly reversible."""
    import re

    for text in ("nnnnnuuu", "u", "udn", "nnn", "ududud", "", "n" * 1234):
        enc = br._rle(text)
        back = "".join(c * int(n or 1)
                       for c, n in re.findall(r"([udn])(\d*)", enc))
        assert back == text, f"{text!r} -> {enc!r} -> {back!r}"


def test_rle_refuses_an_alphabet_that_would_be_ambiguous():
    """Run lengths are digits, so a digit in the data would encode to itself:
    "u3d" -> "u3d" -> "uuud". Directions are only u/d/n today, and a future
    fourth symbol must fail loudly rather than corrupt the replay."""
    with pytest.raises(ValueError, match="u/d/n"):
        br._rle("u3d")
    with pytest.raises(ValueError):
        br._rle("uxd")


def test_regular_timestamps_ship_as_start_and_step():
    """34,655 sixteen-character stamps per frame is 4.9 MB of a page whose
    bars are perfectly evenly spaced."""
    p = _payload()
    p["series"] = {"FOO|1h": {
        "o": [1.0, 1.0, 1.0], "h": [1.0, 1.0, 1.0], "l": [1.0, 1.0, 1.0],
        "c": [1.0, 1.0, 1.0],
        "t": ["2026-01-01 00:00", "2026-01-01 01:00", "2026-01-01 02:00"],
        "fee": 0.0002, "liq": 4.0, "d": {}, "fund": []}}
    packed = br._pack(p)["series"]["FOO|1h"]
    assert packed["t0"] == "2026-01-01 00:00"
    assert packed["step"] == 3600
    assert "t" not in packed


def test_an_irregular_frame_keeps_its_timestamps():
    """A gap in the bars must not be silently re-timed into a regular grid."""
    p = _payload()
    p["series"] = {"FOO|1h": {
        "o": [1.0, 1.0, 1.0], "h": [1.0, 1.0, 1.0], "l": [1.0, 1.0, 1.0],
        "c": [1.0, 1.0, 1.0],
        "t": ["2026-01-01 00:00", "2026-01-01 01:00", "2026-01-01 09:00"],
        "fee": 0.0002, "liq": 4.0, "d": {}, "fund": []}}
    packed = br._pack(p)["series"]["FOO|1h"]
    assert packed.get("t") is not None, "an irregular grid keeps its stamps"
    assert "t0" not in packed


def test_deployed_threshold_is_zeroed_for_signals_without_one(monkeypatch):
    """sweep30 has no threshold, so a deployed entry naming one would match no
    row and the page would show nothing as DEPLOYED."""

    def fake_klines(*a, **k):
        raise RuntimeError("no network in tests")

    import sys
    import types
    fx = types.SimpleNamespace(
        klines=fake_klines, book_cost=lambda *a, **k: {},
        liquidation_move_pct=lambda *a, **k: 4.0)
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.mexc_futures", fx)
    out = br.run_grid(["FOO_USDT"], ["1h"], deployed=[
        {"coin": "FOO", "tf": "1h", "signal": "sweep30", "th": 0.3,
         "sl": 1.0, "tp": 4.0, "sizing": "martingale"}])
    assert out["deployed"][0]["th"] == 0.0
    assert out["excluded"], "a failed fetch must be recorded, never silent"


def test_row_code_is_stable_across_pages_and_runs():
    """The same combination must carry the same ID on every page. Sequential
    numbering gave the live APEX row three different IDs in three tabs."""
    a = br.row_code("APEX", "1h", "sweep30", 0.0, 1.0, 4.0, "martingale")
    assert a == br.row_code("APEX", "1h", "sweep30", 0.0, 1.0, 4.0,
                            "martingale")
    # a signal with no threshold has been stored as 0.0 and as 0.3; both are
    # the same live strategy and must hash the same
    assert a == br.row_code("APEX", "1h", "sweep30", 0.3, 1.0, 4.0,
                            "martingale")
    # ...but a signal that DOES use a threshold must not collapse them
    assert (br.row_code("PI", "4h", "mom15", 0.6, 2.0, 8.0, "martingale")
            != br.row_code("PI", "4h", "mom15", 0.8, 2.0, 8.0, "martingale"))
    # and every other field still separates rows
    base = {"coin": "X", "tf": "1h", "signal": "fvg", "th": 0.0, "sl": 1.0, "tp": 4.0,
                "sizing": "flat"}
    codes = {br.row_code(**base)}
    for field, other in (("coin", "Y"), ("tf", "4h"), ("signal", "rsi14"),
                         ("sl", 2.0), ("tp", 5.0), ("sizing", "martingale")):
        codes.add(br.row_code(**{**base, field: other}))
    assert len(codes) == 7
    assert len(br.row_code(**base)) == 8


def test_month_columns_are_an_array_on_every_row():
    """Kit item F: never drop a field from a subset of rows."""
    rows = [_row(id=1, mon=[1.0, 2.0]), _row(id=2, mon=[None, 3.0])]
    p = _payload(rows)
    html = br.render(p, title="t")
    blob = _embedded(html)
    for r in blob["rows"]:
        assert len(r["mon"]) == len(blob["months"])


def test_window_control_resimulates_rather_than_filtering():
    """"Last N months" must re-run the strategy, not hide rows: a filtered
    table would keep a year's PROFIT under a three-month label."""
    html = br.render(_payload(), title="t")
    assert 'id="fmon"' in html
    js = html.replace(" ", "").replace("\n", "")
    assert "letWIN_MONTHS=0" in js
    assert "functionwinStart" in js
    # every stat the window changes must come off the replay, not the payload
    for field in ("winrate:+s.winrate", "green:s.green", "months:s.months",
                  "days:s.days", "h1:s.h1", "h2:s.h2"):
        assert field.replace(" ", "") in js, f"{field} not re-simulated"
    # and the verdict is recomputed, or a losing window still reads "survivor"
    assert "functionreverdict" in js
    # a 3-month window shows the 4 calendar months it touches, and no others
    assert "D.months.slice(0,WIN_MONTHS+1)" in js


def test_the_app_grid_contains_every_row_the_analysis_publishes():
    """One grid, shared. The button and the artifact must not disagree.

    They did once: the analysis recommended 1h SL 1.50 / TP 2.00 and the app's
    six-pair grid had never tested it, so the operator could not find a single
    recommended row in their own app.
    """
    published = [("1h", 1.50, 2.00), ("4h", 1.00, 3.00), ("4h", 1.50, 3.00),
                 ("1h", 4.00, 2.00), ("1h", 3.00, 3.00), ("1h", 1.00, 4.00)]
    for tf, sl, tp in published:
        assert any(abs(a * 100 - sl) < 1e-6 and abs(b * 100 - tp) < 1e-6
                   for a, b in br.BARRIERS[tf]), f"{tf} {sl}/{tp} not tested"
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        assert len(br.BARRIERS[tf]) >= 100, f"{tf} grid too narrow"
    assert br.MIN_TRADES >= 30


def test_deployed_barriers_are_injected_even_when_off_the_grid():
    """XAUT runs SL 0.80 / TP 2.40, which is in no grid of round numbers. The
    page must still contain it, or the DEPLOYED row cannot be marked."""
    live = {"coin": "XAUT", "tf": "1h", "signal": "mom15", "th": 0.3,
            "sl": 0.80, "tp": 2.40, "sizing": "martingale"}
    assert (0.008, 0.024) not in br.BARRIERS["1h"]
    assert (0.008, 0.024) in br.pairs_for("1h", [live])
    assert (0.008, 0.024) not in br.pairs_for("4h", [live])   # its own tf only
    assert br.pairs_for("1h", []) == sorted(set(br.BARRIERS["1h"]))


def test_row_code_is_seeded_from_the_SHORT_coin_name():
    """A grid row stores `coin` as "APEX", so that is what the ID hashes. Passing
    "APEX_USDT" returns a code that appears on no page — which is the same class
    of confusion ("#05146 / #02054 / not there") the hashed ID exists to end. The
    deployed live rows and their codes, as of 2026-08-19:"""
    assert br.row_code("APEX", "1h", "sweep30", 0.0, 3.0, 3.0,
                       "martingale") == "VB4SNUHQ"
    assert br.row_code("PI", "30m", "trend50", 0.0, 2.0, 2.5,
                       "martingale") == "3M3CRXP8"
    assert br.row_code("XAUT", "1h", "mom6", 0.2, 1.5, 2.0,
                       "martingale") == "CZ7THVJW"
    assert br.row_code("APEX_USDT", "1h", "sweep30", 0.0, 3.0, 3.0,
                       "martingale") != "VB4SNUHQ", \
        "the long name must not silently produce a different-looking ID"


def test_every_row_id_in_the_repo_matches_row_code():
    """Codes quoted in comments and UI notes are how the operator finds a row.
    A stale one sends them to a page that does not contain it."""
    import pathlib
    import re
    # `#232326` is a CSS colour, not a row ID. A real code always carries at
    # least one character outside the hex alphabet, because it is base-32 over
    # `br._CODE_ALPHABET`.
    non_hex = set(br._CODE_ALPHABET) - set("0123456789ABCDEF")
    quoted = set()
    for f in ("app.py", "tradingagents/auto_trader.py"):
        for m in re.finditer(r"#([2-9A-Z]{8})\b",
                             pathlib.Path(f).read_text(encoding="utf-8")):
            code = m.group(1)
            if set(code) & non_hex:
                quoted.add(code)
    live = {
        br.row_code("APEX", "1h", "sweep30", 0.0, 3.0, 3.0, "martingale"),
        br.row_code("APEX", "1h", "sweep30", 0.0, 3.0, 3.0, "flat"),
        br.row_code("APEX", "1h", "sweep30", 0.0, 1.0, 4.0, "martingale"),
        br.row_code("APEX", "1h", "sweep30", 0.0, 1.0, 4.0, "flat"),
        br.row_code("APEX", "1h", "sweep30", 0.0, 3.0, 3.0, "flat"),
        br.row_code("PI", "30m", "trend50", 0.0, 2.0, 2.5, "martingale"),
        br.row_code("XAUT", "1h", "mom6", 0.2, 1.5, 2.0, "martingale"),
        # PROVE fade15, added 2026-08-19. The spec comment cites all three
        # thresholds on purpose, because they are what separates the row the
        # operator picked from its two near-identical twins.
        br.row_code("PROVE", "1h", "fade15", 0.2, 0.3, 8.0, "martingale"),
        br.row_code("PROVE", "1h", "fade15", 0.3, 0.3, 8.0, "martingale"),
        br.row_code("PROVE", "1h", "fade15", 0.5, 0.3, 8.0, "martingale"),
    }
    unknown = quoted - live
    assert not unknown, (
        f"row IDs in the source that row_code does not produce for any "
        f"deployed combination: {sorted(unknown)}")


def test_round_trip_cost_does_not_charge_the_spread_twice():
    """`book_cost` reports slippage measured against MID, so half the spread is
    already inside it. The old formula added spread/2 on top: APEX printed a
    round trip of 0.376% (12.5% of its 3% target) when the measured cost was
    0.130% (4.3%) — and rule 11 asks the operator to judge a strategy by that
    ratio."""
    import inspect
    src = inspect.getsource(br.run_grid)
    assert 'rt = 2 * (fee + float(book.get("slippage") or 0))' in src
    assert 'spread' not in src.split("rt = 2 *")[1][:200], \
        "the spread is being charged on top of slippage again"


def test_the_deployed_row_survives_the_trade_floor():
    """Rule 21: the page must contain the exact combination that is running.
    The 30-trade floor was deleting it — on the 19-day August sweep all five
    live rows took fewer than 30 trades, so the page badged nothing as deployed
    and the operator could not find their own strategy in their own results."""
    dep = [{"coin": "X", "tf": "1h", "signal": "mom6", "th": 0.3,
            "sl": 2.5, "tp": 4.0, "sizing": "martingale"}]
    assert br._is_deployed("X", "1h", "mom6", 0.3, 2.5, 4.0, "martingale", dep)
    # every field has to match, with the same tolerance the page's isDep uses
    assert not br._is_deployed("Y", "1h", "mom6", 0.3, 2.5, 4.0, "martingale", dep)
    assert not br._is_deployed("X", "4h", "mom6", 0.3, 2.5, 4.0, "martingale", dep)
    assert not br._is_deployed("X", "1h", "fvg", 0.3, 2.5, 4.0, "martingale", dep)
    assert not br._is_deployed("X", "1h", "mom6", 0.5, 2.5, 4.0, "martingale", dep)
    assert not br._is_deployed("X", "1h", "mom6", 0.3, 3.0, 4.0, "martingale", dep)
    assert not br._is_deployed("X", "1h", "mom6", 0.3, 2.5, 5.0, "martingale", dep)
    assert not br._is_deployed("X", "1h", "mom6", 0.3, 2.5, 4.0, "flat", dep)
    assert not br._is_deployed("X", "1h", "mom6", 0.3, 2.5, 4.0, "martingale", [])

    import inspect
    src = inspect.getsource(br.run_grid)
    assert "if r[\"trades\"] < min_trades and not _is_deployed(" in src, \
        "the floor must exempt the deployed combination"


def test_the_page_announces_and_scrolls_to_the_deployed_row():
    """"when i backtest a strategy, highlight it in the results" — the row was
    tinted and pinned, but nothing told the operator where it was."""
    from tradingagents import report_template as rt
    tpl = rt.TEMPLATE if hasattr(rt, "TEMPLATE") else "".join(
        v for v in vars(rt).values() if isinstance(v, str))
    assert 'id="depbar"' in tpl
    assert "announceDeployed" in tpl
    assert "scrollIntoView" in tpl
    assert "No row on this page is the deployed one" in tpl, \
        "and it must say so when there is none, rather than showing nothing"
