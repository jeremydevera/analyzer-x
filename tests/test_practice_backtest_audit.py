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
