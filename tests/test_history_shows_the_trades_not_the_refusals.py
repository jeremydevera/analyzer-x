"""The trade history shows TRADES, however many refusals sit in front of them.

Operator, Sep 09, 2026: *"why is #YDMRLEZ5 has 1 lose and it does not reflect
in demo history trades"*.

The loss was real and the runner had taken it. Row #YDMRLEZ5 is KITE 1h
squeeze, SL 3% / TP 3%, flat, and the demo ledger holds exactly one trade for
that strategy:

    Sep 07, 2026 5:00pm  enter  KITE_USDT  squeeze_1h_sl3tp3  (dry_run=True)
    Sep 07, 2026 5:01pm  exit   SL  -3.19

WHY IT WAS INVISIBLE. The panel asked for the newest 200 LEDGER ROWS and then
filtered to `enter`/`exit` in the browser — after the server had already thrown
the trades away. Measured on the operator's own file that day:

    3,666 ledger rows
      2,868  gate_blocked
        552  blocked
        169  stale_skip
         12  enter + exit          <- the trades
    the newest 200 rows spanned 23 hours and held 2 of the 12
    the KITE exit sat 640 rows from the end

So the filter ran on a window that could not contain the answer. The route
takes an `actions` list now and the panel asks for `enter,exit` by name, so
the 200 it receives are 200 TRADES.

`total` still counts the whole ledger, because the panel prints it as "N lines
on this PC" and that is what it is.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import tradingagents.auto_trader as at
from tradingagents.api import app

# the shape of the operator's file: a few trades buried under refusals
LEDGER = (
    [{"ts": 1000, "action": "exit", "symbol": "KITE_USDT",
      "strategy": "squeeze_1h_sl3tp3", "dry_run": True, "why": "SL",
      "pnl_est": -3.19}]
    + [{"ts": 900 + i, "action": "gate_blocked", "symbol": "X_USDT",
        "strategy": "s", "dry_run": True} for i in range(300)]
    + [{"ts": 800, "action": "enter", "symbol": "KITE_USDT",
        "strategy": "squeeze_1h_sl3tp3", "dry_run": True}]
)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(at, "ledger_tail", lambda n: list(LEDGER))
    return TestClient(app)


def test_asking_for_trades_gets_trades(client):
    """The fix, in one call."""
    got = client.get("/api/ledger?limit=200&actions=enter,exit").json()
    kinds = {r["action"] for r in got["rows"]}
    assert kinds == {"enter", "exit"}, kinds
    assert got["matched"] == 2
    assert len(got["rows"]) == 2


def test_the_kite_loss_is_in_it(client):
    """The operator's actual row — a demo SL of -3.19 on KITE."""
    got = client.get("/api/ledger?limit=200&actions=enter,exit").json()
    loss = [r for r in got["rows"]
            if r["action"] == "exit" and r["symbol"] == "KITE_USDT"]
    assert loss, "the demo loss is missing from the trade history"
    assert loss[0]["why"] == "SL"
    assert loss[0]["pnl_est"] == -3.19
    assert loss[0]["dry_run"] is True, "and it is labelled as the paper book"


def test_asking_for_rows_still_gets_every_action(client):
    """No `actions` = the old behaviour, for any caller that wants the feed."""
    got = client.get("/api/ledger?limit=200").json()
    assert len(got["rows"]) == 200
    assert "gate_blocked" in {r["action"] for r in got["rows"]}
    assert got["matched"] == got["total"] == len(LEDGER)


def test_total_still_counts_the_whole_ledger(client):
    """The panel prints it as "N lines on this PC" — a filter must not shrink
    it, or the caption stops describing the file (label-must-match-data)."""
    got = client.get("/api/ledger?limit=200&actions=enter,exit").json()
    assert got["total"] == len(LEDGER) == 302
    assert got["matched"] == 2, "and `matched` says what the filter left"


def test_refusals_can_never_crowd_the_trades_out(client):
    """The bug's shape: with 300 refusals in front, a 200-row window holds 1
    trade. Asking by action holds both."""
    rows = client.get("/api/ledger?limit=200").json()["rows"]
    unfiltered_trades = [r for r in rows
                         if r["action"] in ("enter", "exit")]
    assert len(unfiltered_trades) < 2, \
        "the fixture must reproduce the crowding, or this proves nothing"
    filtered = client.get("/api/ledger?limit=200&actions=enter,exit").json()
    assert len(filtered["rows"]) == 2


def test_an_unknown_action_returns_nothing_rather_than_everything(client):
    """A typo must not silently hand back the whole feed."""
    got = client.get("/api/ledger?limit=200&actions=entre").json()
    assert got["rows"] == [] and got["matched"] == 0
    assert got["actions"] == ["entre"], "and it says what it was asked for"


# ------------------------------------------------------------ the panel
def test_the_panel_asks_the_server_for_trades():
    """Filtering in the browser cannot recover rows the server never sent."""
    src = open("webapp/src/components/backtest/HistoryPanel.tsx",
               encoding="utf-8").read()
    assert 'api.ledger(200, "enter,exit")' in src, \
        "the panel must name the actions it wants"


def test_the_panel_stopped_hand_rolling_the_date():
    """`new Date(v*1000).toISOString().slice(0,16)` printed `2026-09-07 17:01`
    — the compact stamp CLAUDE.md bans — on every row of this table."""
    src = open("webapp/src/components/backtest/HistoryPanel.tsx",
               encoding="utf-8").read()
    assert "toISOString" not in src
    assert "fmtWhen" in src


def test_no_component_prints_a_timestamp_with_toISOString():
    """The date test scanned for `.toLocale` only, so an ISO stamp walked past
    it. A `Date` built from SECONDS (`* 1000`) is a timestamp being printed;
    `new Date().toISOString().slice(0, 10)` for a date INPUT's value is not.
    """
    import pathlib
    import re

    offenders = []
    for f in (list(pathlib.Path("webapp/src").rglob("*.tsx"))
              + list(pathlib.Path("webapp/src").rglob("*.ts"))):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"new Date\([^)]*\*\s*1000[^)]*\)\.toISOString", line):
                offenders.append(f"{f}:{i}")
    assert not offenders, (
        "a timestamp is being formatted by hand — use fmtWhen/fmtWhenMs: "
        f"{offenders}")
