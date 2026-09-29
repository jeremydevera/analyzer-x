"""The Trade screen's Watcher panel prints what the watcher did, from its own data.

Operator, Sep 29, 2026: "deploy now the wathcer replay ... the promotion and
demotion". Every word comes from GET /api/trade/watcher; dates go through the
project's one formatter; switching it on asks first.
"""
from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PANEL = (ROOT / "webapp" / "src" / "components" / "trade" / "WatcherPanel.tsx").read_text("utf-8")
SCREEN = (ROOT / "webapp" / "src" / "components" / "trade" / "AutoTradeScreen.tsx").read_text("utf-8")


def test_the_panel_is_on_the_trade_screen():
    assert "<WatcherPanel />" in SCREEN


def test_every_figure_comes_from_the_payload():
    for used in ("w.running", "w.cooling", "fmtWhen(w.last_on_pass)", "fmtWhen(w.next_on_pass)",
                 "fmtWhen(w.last_off_pass)", "w.why", "rules(w.cfg)", "fmtWhen(d.at)", "d.why"):
        assert used in PANEL, used
    assert "c.on_winrate" in PANEL and "c.off_winrate" in PANEL and "c.min_trades" in PANEL


def test_dates_are_printed_by_the_projects_formatter_only():
    assert ".toLocale" not in PANEL and "new Date" not in PANEL


def test_switching_it_on_asks_first_and_names_what_it_touches():
    assert 'mode === "act" && !confirm(' in PANEL
    assert "never touches real money" in PANEL


def test_the_routes_exist():
    api = (ROOT / "tradingagents" / "api.py").read_text("utf-8")
    assert '@app.get("/api/trade/watcher")' in api and '@app.post("/api/trade/watcher")' in api
