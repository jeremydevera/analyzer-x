"""practice_backtest_audit compares a practice trade with its backtest only
when the trade's own STRATEGY closed it (Oct 14, 2026).

The skill's first run reads every practice trade closed since the move to
Gate, `Oct 10, 2026 3:59am`. In that same minute the move itself closed 20
open practice trades at the old exchange's last price (`VENUE_SWITCH`; 91 in
all, at 3:56am, 3:58am and 3:59am): 19 strategies of rooms #CC94D9FB and
#6B08FF64 on ADMSTOCK, AZNSTOCK, AZOSTOCK, DVNSTOCK, FASTSTOCK, GPNSTOCK,
JPY, KIMISTOCK and XLI, opened from Oct 08, 2026 1:45pm. No backtest trade
ends at a switch, so a first run would have looked those ids up and either
listed them as ids with no result or set a switch price against a backtest
exit. A trade closed by hand, by the panic button, or by anything but its
own target or stop is the same case: named, never compared.

The matching rules live in `scripts/match.mjs`, and these tests import that
file, so what is tested is what the audit runs.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = (Path(__file__).resolve().parents[1] / ".claude" / "skills"
           / "practice_backtest_audit" / "scripts")
MATCH = SCRIPTS / "match.mjs"
AUDIT = SCRIPTS / "audit.mjs"


def _node(expr: str):
    """Evaluate `expr` in node with the real match.mjs imported as `m`."""
    node = shutil.which("node")
    if not node:                                     # pragma: no cover
        pytest.skip("node is not on PATH")
    script = (f'import * as m from "{MATCH.as_uri()}";'
              f"console.log(JSON.stringify({expr}));")
    out = subprocess.run([node, "--input-type=module", "-e", script],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# Real practice trades, as the Main tab printed them.
SWITCHED = {"strategy_id": "SHU6ESVA", "coin": "FASTSTOCK", "side": "LONG",
            "closed_by": "VENUE_SWITCH", "profit": -0.43,
            "opened": "Oct 09, 2026 10:00am", "closed": "Oct 10, 2026 3:59am"}
GPS_SHORT = {"strategy_id": "5RKPYVQ7", "coin": "GPS", "side": "SHORT",
             "closed_by": "TP", "profit": 0.79,
             "opened": "Oct 13, 2026 6:45am", "closed": "Oct 13, 2026 7:46am"}
GPS_LONG = {"strategy_id": "5RKPYVQ7", "coin": "GPS", "side": "LONG",
            "closed_by": "SL", "profit": -1.09,
            "opened": "Oct 13, 2026 8:15am", "closed": "Oct 13, 2026 8:19am"}
# #5RKPYVQ7's own trade list for those two minutes, as Stored strategies drew it
GPS_LOG = [
    {"opened": "Oct 13, 2026 6:45am", "closed": "Oct 13, 2026 7:46am",
     "closed_by": "TP", "pnl": 0.79},
    {"opened": "Oct 13, 2026 8:15am", "closed": "Oct 13, 2026 8:19am",
     "closed_by": "SL", "pnl": -1.03},
]


def test_a_trade_the_move_to_gate_closed_is_named_never_compared():
    got = _node(f"m.split({json.dumps([SWITCHED, GPS_SHORT])})")
    assert [t["strategy_id"] for t in got["compared"]] == ["5RKPYVQ7"]
    assert got["ids"] == ["5RKPYVQ7"], \
        "a switch close's id must never be looked up: it would be listed as an id with no result"
    (named,) = got["named"]
    assert named["strategy_id"] == "SHU6ESVA"
    assert named["verdict"] == "closed by the move to Gate, not by its strategy"


def test_a_trade_closed_by_hand_or_the_panic_button_is_named_too():
    for why, said in (("MANUAL_UI", "closed by hand, not by its strategy"),
                      ("PANIC_CLOSE", "closed by the panic button, not by its strategy"),
                      ("RECONCILED", "closed by RECONCILED, not by its strategy"),
                      ("", "closed without a recorded reason, not by its strategy")):
        got = _node(f"m.split([{json.dumps({**GPS_LONG, 'closed_by': why})}])")
        assert got["compared"] == [] and got["ids"] == [], why
        assert got["named"][0]["verdict"] == said, why


def test_its_own_target_or_stop_is_compared_however_it_is_printed():
    trades = [GPS_SHORT, GPS_LONG, {**GPS_LONG, "closed_by": " sl "}]
    got = _node(f"m.split({json.dumps(trades)})")
    assert len(got["compared"]) == 3 and got["named"] == []
    assert got["ids"] == ["5RKPYVQ7"], "an id shared by several trades is looked up once"


def test_the_matching_rules_the_operator_set():
    """Step 12, in their words: 10.6 against 10.8 is close, against 100 it
    is not, and no equivalent trade is reported back."""
    assert _node("m.verdict(10.6, 10.8)") == "close"
    assert _node("m.verdict(10.6, 100)") == "not close"
    assert _node("m.verdict(0.74, -1.20)") == "not close (one won, one lost)"

    got = _node(f"m.compare({json.dumps(GPS_SHORT)}, {json.dumps(GPS_LOG)})")
    assert (got["verdict"], got["difference"]) == ("close", 0)
    got = _node(f"m.compare({json.dumps(GPS_LONG)}, {json.dumps(GPS_LOG)})")
    assert (got["verdict"], got["difference"]) == ("close", 0.06)

    later = {**GPS_LONG, "opened": "Oct 13, 2026 9:00am", "closed": "Oct 13, 2026 9:10am"}
    got = _node(f"m.compare({json.dumps(later)}, {json.dumps(GPS_LOG)})")
    assert got["verdict"] == "no equivalent"
    assert "45 min away" in got["note"]


def test_a_backtest_that_ends_while_the_trade_is_open_is_not_a_miss():
    """XDC 30m #2ZBNSQ5L, Oct 13, 2026: practice +0.74 at its target at
    12:23pm, the backtest's candles ended at 11:30am with the trade +0.12."""
    xdc = {"strategy_id": "2ZBNSQ5L", "coin": "XDC", "side": "LONG", "closed_by": "TP",
           "profit": 0.74, "opened": "Oct 13, 2026 8:30am", "closed": "Oct 13, 2026 12:23pm"}
    log = [{"opened": "Oct 13, 2026 8:30am", "closed": "Oct 13, 2026 11:30am",
            "closed_by": "END", "pnl": 0.12}]
    got = _node(f"m.compare({json.dumps(xdc)}, {json.dumps(log)})")
    assert got["verdict"] == "backtest ends before this trade closed"


def test_a_backtest_already_in_its_own_trade_is_named_not_left_as_no_equivalent():
    """CLANKER 15m choch #WVUWQDBP in #55D32617 (Oct 15, 2026): switched on at
    Oct 10, 2026 9:56am, practice bought at 10:45am (L6XSRUW3, TP +0.96). The
    stored backtest walks without switch-ons: it had been short since Oct 09,
    2026 11:45pm and stayed in until 12:40pm, so it could not open practice's
    trade. Same for ALAB #R2RLBEME and ANKR #U9DUR9HV on Oct 12, 2026. The
    audit names WHY, with the backtest's own trade, instead of a bare "no
    equivalent"."""
    clanker = {"strategy_id": "WVUWQDBP", "coin": "CLANKER", "side": "LONG",
               "closed_by": "TP", "profit": 0.96,
               "opened": "Oct 10, 2026 10:45am", "closed": "Oct 10, 2026 12:39pm"}
    log = [{"opened": "Oct 09, 2026 11:45pm", "closed": "Oct 10, 2026 12:40pm",
            "side": "SHORT", "closed_by": "SL", "pnl": -1.28},
           {"opened": "Oct 10, 2026 6:30pm", "closed": "Oct 10, 2026 11:24pm",
            "side": "SHORT", "closed_by": "TP", "pnl": 0.95}]
    got = _node(f"m.compare({json.dumps(clanker)}, {json.dumps(log)})")
    assert got["verdict"] == "backtest already in its own trade"
    assert got["note"] == ("the backtest held a SHORT from Oct 09, 2026 11:45pm to "
                           "Oct 10, 2026 12:40pm, so it could not open this one")
    assert got["backtest"]["opened"] == "Oct 09, 2026 11:45pm"
    # a trade nobody was in the way of stays "no equivalent"
    free = {**clanker, "opened": "Oct 10, 2026 1:00pm", "closed": "Oct 10, 2026 2:00pm"}
    assert _node(f"m.compare({json.dumps(free)}, {json.dumps(log)})")["verdict"] == "no equivalent"


def test_two_rooms_trades_with_one_id_are_two_trades():
    """Rooms running the same strategy get the same trade id: AZOSTOCK
    #MRTZALF8 closed Oct 10, 2026 3:59am in #CC94D9FB AND #6B08FF64, and
    BIIBSTOCK #2KTWTS3E (-1.08) Oct 09, 2026 10:10am in #55D32617 AND
    #B2404C0B — 593 such pairs among 4,000 practice trades. Keyed without the
    room, the second of each was dropped as the list "refreshing"."""
    a = {"room": "#CC94D9FB", "trade_id": "MRTZALF8", "closed": "Oct 10, 2026 3:59am"}
    b = {**a, "room": "#6B08FF64"}
    keys = _node(f"[m.tradeKey({json.dumps(a)}), m.tradeKey({json.dumps(b)}), m.tradeKey({json.dumps(a)})]")
    assert keys[0] != keys[1], "one id in two rooms is two trades"
    assert keys[0] == keys[2], "the same row read twice is one trade"
    src = AUDIT.read_text(encoding="utf-8")
    assert "tradeKey(" in src and "`${tradeId}|${closed}`" not in src


def test_the_audit_runs_these_rules_and_keeps_no_copy_of_its_own():
    """A second copy inside audit.mjs would be the one that runs while this
    file tests the other."""
    src = AUDIT.read_text(encoding="utf-8")
    assert re.search(r'import \{[^}]*\bsplit\b[^}]*\} from "\./match\.mjs"', src)
    assert re.search(r'import \{[^}]*\bcompare\b[^}]*\} from "\./match\.mjs"', src)
    for name in ("compare", "verdict", "split", "parseWhen"):
        assert not re.search(rf"\bfunction {name}\s*\(", src), \
            f"audit.mjs defines its own {name}()"


def test_the_apps_answer_for_an_id_is_read_even_when_it_names_the_room():
    """Oct 17, 2026 6:21am: all 23 ids came back "Stored strategies did not
    answer within 3 minutes". The page HAD answered, inside 10 s: "#L8XAJAWT
    is FORM 15m lrslope, TP 1% / SL 0.8%: #55D32617 switched it on ... this
    list shows only strategies whose win pays at least two losses after fees".
    The script took any OTHER 8-character #name in that sentence for the
    previous search's leftover — and a room's id (#55D32617) is one. An answer
    is this id's when it names this id; only one that does not is stale."""
    now = ("#L8XAJAWT is FORM 15m lrslope, TP 1% / SL 0.8%: #55D32617 switched it on while "
           "the app traded on Gate (last change Oct 16, 2026 6:51pm); this list shows only "
           "strategies whose win pays at least two losses after fees")
    stale = "#82LGV9W9 is GPS 15m tsi: #55D32617 switched it on while the app traded on Gate"
    assert _node(f"m.idAnswer({json.dumps(now)}, 'L8XAJAWT')") == now
    assert _node(f"m.idAnswer({json.dumps(stale)}, 'L8XAJAWT')") is None
    assert _node("m.idAnswer('no row #L8XAJAWT in the store. An id names one exact combination', "
                 "'L8XAJAWT')").startswith("no row #L8XAJAWT")
    audit = (MATCH.parent / "audit.mjs").read_text(encoding="utf-8")
    assert "m.idAnswer(t, id)" in audit or "idAnswer(t, id)" in audit
    assert "named.some((x) => x !== id)" not in audit


def test_a_replayed_trade_log_reads_like_the_row_clicks_table():
    """A strategy the list hides is read from its stored row's trade log
    (/api/v2/strategies/trades-by-id): each trade becomes exactly what the
    audit reads off the table a row click draws — opened = entry time, closed
    = exit time, closed by = why, profit to the cent as fmtMoney prints it."""
    log = [{"entry time": "Oct 16, 2026 4:45pm", "exit time": "Oct 16, 2026 7:03pm",
            "held": "2h 18m", "side": "LONG", "why": "TP", "pnl $": 0.7712}]
    got = _node(f"m.fromReplay({json.dumps(log)})")
    assert got == [{"opened": "Oct 16, 2026 4:45pm", "closed": "Oct 16, 2026 7:03pm",
                    "held": "2h 18m", "side": "LONG", "closed_by": "TP", "pnl": 0.77,
                    "opened_ms": _node("m.parseWhen('Oct 16, 2026 4:45pm')"),
                    "closed_ms": _node("m.parseWhen('Oct 16, 2026 7:03pm')")}]
    # ...and the practice trade it was paired with comes out the way it did by hand
    t = {"opened": "Oct 16, 2026 4:45pm", "closed": "Oct 16, 2026 7:03pm", "profit": 0.8}
    assert _node(f"m.compare({json.dumps(t)}, m.fromReplay({json.dumps(log)})).verdict") == "close"


def test_the_next_run_never_starts_past_a_trade_that_was_not_checked():
    """Oct 17, 2026 6:21am checked none of its 60 trades and still saved
    "Oct 16, 2026 7:03pm" as where the next run starts — so the next ordinary
    run would have skipped all 60 for good. The saved point stops a minute
    before the oldest trade that was not checked (the window keeps a trade
    that closed at or after the saved point plus one minute)."""
    oct = lambda d, h: _node(f"m.parseWhen('Oct {d:02d}, 2026 {h}:00am')")   # noqa: E731
    trades = [{"closed_ms": oct(12, 1), "verdict": "close"},
              {"closed_ms": oct(13, 1), "verdict": "id not in Stored strategies"},
              {"closed_ms": oct(14, 1), "verdict": "not checked (its trade list did not load)"},
              {"closed_ms": oct(15, 1), "verdict": "closed by the move to Gate, not by its strategy"}]
    assert _node(f"m.nextWatermark({json.dumps(trades)})") == oct(13, 1) - 60_000
    checked = [t for t in trades if not t["verdict"].startswith(("id not", "not checked"))]
    assert _node(f"m.nextWatermark({json.dumps(checked)})") == oct(15, 1)
    assert _node("m.nextWatermark([])") is None
    # an id NO stored row makes is settled (it will never be found); only a
    # list or a replay that did not answer keeps the trade for the next run
    gone = [{"closed_ms": oct(12, 1), "verdict": "no stored backtest makes this id"}]
    assert _node(f"m.nextWatermark({json.dumps(gone)})") == oct(12, 1)


def test_the_audit_reads_a_hidden_strategy_through_its_stored_row():
    audit = (MATCH.parent / "audit.mjs").read_text(encoding="utf-8")
    assert "/api/v2/strategies/trades-by-id?" in audit
    # straight to the back end: the page's /api proxy gives up at 30 s
    assert "${API}/api/v2/strategies/trades-by-id?" in audit and 'arg("api", "http://localhost:8787")' in audit
    assert "fromReplay(" in audit and "nextSaved(st.last_closed_ms ?? null, report.trades)" in audit
    # every such line says where it came from, and the summary counts them apart
    assert "compared from its stored backtest" in audit and "counts_not_on_list" in audit


def test_a_saved_start_point_moves_back_for_a_trade_left_unchecked():
    """The saved point is where the next ordinary run starts. Oct 17, 2026's
    run pushed it to Oct 16, 2026 7:03pm over 60 trades it never checked;
    moving only forward, nothing could ever bring them back. A run that leaves
    a trade unchecked moves it back to before that trade; a run that checked
    everything only moves it forward (an old day run again never rewinds it)."""
    oct = lambda d, h: _node(f"m.parseWhen('Oct {d:02d}, 2026 {h}:00pm')")   # noqa: E731
    left = [{"closed_ms": oct(12, 1), "verdict": "id not in Stored strategies"},
            {"closed_ms": oct(14, 1), "verdict": "close"}]
    assert _node(f"m.nextSaved({oct(16, 7)}, {json.dumps(left)})") == oct(12, 1) - 60_000
    done = [{"closed_ms": oct(14, 1), "verdict": "close"}]
    assert _node(f"m.nextSaved({oct(16, 7)}, {json.dumps(done)})") == oct(16, 7)
    assert _node(f"m.nextSaved({oct(10, 1)}, {json.dumps(done)})") == oct(14, 1)
    assert _node(f"m.nextSaved(null, {json.dumps(done)})") == oct(14, 1)
    assert _node("m.nextSaved(5, [])") == 5
    audit = (MATCH.parent / "audit.mjs").read_text(encoding="utf-8")
    assert "nextSaved(st.last_closed_ms ?? null, report.trades)" in audit
