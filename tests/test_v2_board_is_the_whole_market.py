"""A Backtest v2 press with nothing picked measures the exchange's WHOLE
market - never the coins that happen to sit in this PC's 1-minute folder.

Oct 11, 2026 4:32am: the daily UPDATE (runs 38125155535 and 38125162569)
sent 2 coins, BTC and SKY, instead of Gate's ~1,027. The board was
`stored_symbols(store="v2")`, this PC's 1-minute candle folder. The move to
Gate (Oct 10, 2026) moved MEXC's minutes aside, and the GitHub machines
download their own minutes, so nothing fills that folder any more except a
test download (BTC, Oct 10 6:50am) and one other coin's minutes (SKY,
Oct 11 12:01am). The Oct 10 fix named the market only when the folder was
EMPTY; two files were enough to narrow the whole update to two coins, and
the BACKTEST button's v2 press had no fallback at all (RCA-2026-10-11-D).
"""
import pytest

from tradingagents import cloud_sweep as cs, db_jobs as dj
from tradingagents.dataflows import mexc_futures as mf

MARKET = ["AAA_USDT", "BTC_USDT", "SKY_USDT", "ZZZ_USDT"]


@pytest.fixture
def fleet(monkeypatch):
    """GitHub usable, every dispatch captured, the PC's minute folder holding
    the two coins it held on Oct 11, 2026, the exchange trading four."""
    sent = {}
    monkeypatch.setattr(dj, "stored_symbols", lambda store="v1": ["BTC_USDT", "SKY_USDT"])
    monkeypatch.setattr(mf, "trading_symbols", lambda: list(MARKET))
    monkeypatch.setattr(cs, "available", lambda: (True, ""))
    monkeypatch.setattr(cs, "remember", lambda d: None)

    def across(**kw):
        sent.update(kw)
        n = len(kw.get("coin_list") or [])
        return {"runs": [{"id": 1, "url": "u1", "coins": n}],
                "why": f"1 account(s) x 20 machines = 20; {n} coins dealt {n}"}
    monkeypatch.setattr(cs, "dispatch_across", across)
    return sent


def test_the_daily_update_measures_the_whole_market_not_the_pcs_minute_folder(
        fleet, monkeypatch, capsys):
    written = {}
    monkeypatch.setattr(dj, "_write", lambda path, d: written.__setitem__(str(path), d))
    dj._run_btupdate_v2({"coins": [], "tfs": ["15m", "30m", "1h", "4h"], "days": 30,
                         "base": 5.0, "label": "daily"})
    assert fleet["coin_list"] == ["AAA", "BTC", "SKY", "ZZZ"], fleet.get("coin_list")
    # and every sentence about it counts what was SENT (label-must-match-data):
    # the log printed "continuing every v2 pair: 2 contract(s)" on Oct 11
    out = capsys.readouterr().out
    assert "2 contract(s)" not in out, out
    assert "4 contract(s)" in out, out
    plan = next(d for p, d in written.items() if p.endswith("db_btupdate_v2.plan.json"))
    assert plan["coins"] == 4
    note = next(d["note"] for d in written.values() if d.get("note"))
    assert "over 4 contract(s)" in note, note


def test_a_pick_is_still_only_the_pick(fleet, monkeypatch):
    def no_market():
        raise AssertionError("a press that picked coins never reads the market")
    monkeypatch.setattr(mf, "trading_symbols", no_market)
    monkeypatch.setattr(dj, "_write", lambda path, d: None)
    dj._run_btupdate_v2({"coins": ["KITE"], "tfs": ["1h"]})
    assert fleet["coin_list"] == ["KITE"]


def test_an_unreadable_market_measures_nothing_and_says_why(fleet, monkeypatch):
    """Never a narrower board in its place: a market that cannot be read is
    a dispatch that did not happen, named, so the daily update tries again."""
    written = {}

    def down():
        raise RuntimeError("venue down")
    monkeypatch.setattr(mf, "trading_symbols", down)
    monkeypatch.setattr(dj, "_write", lambda path, d: written.__setitem__(str(path), d))
    dj._run_btupdate_v2({"coins": [], "tfs": ["15m"]})
    assert "coin_list" not in fleet, "nothing was sent"
    note = next(d["note"] for d in written.values() if d.get("note"))
    assert note.startswith("NOTHING was measured") and "venue down" in note, note


def test_a_market_that_names_nothing_is_a_failure_not_one_account(fleet, monkeypatch):
    """An empty list would reach ONE account, whose machines work out the
    market themselves - 20 machines of 40. An empty answer is a failed read."""
    written = {}
    monkeypatch.setattr(mf, "trading_symbols", lambda: [])
    monkeypatch.setattr(dj, "_write", lambda path, d: written.__setitem__(str(path), d))
    dj._run_btupdate_v2({"coins": [], "tfs": ["15m"]})
    assert "coin_list" not in fleet, "nothing was sent"
    note = next(d["note"] for d in written.values() if d.get("note"))
    assert note.startswith("NOTHING was measured") and "no contract" in note, note


def test_the_v2_backtest_button_with_nothing_picked_names_the_whole_market(fleet):
    from tradingagents import api as api_mod

    api_mod.cloud_dispatch({"res": "1m", "timeframes": "15m,30m"})
    assert fleet["coin_list"] == ["AAA", "BTC", "SKY", "ZZZ"], fleet.get("coin_list")


def test_the_v1_backtest_button_is_unchanged(fleet):
    from tradingagents import api as api_mod

    api_mod.cloud_dispatch({"timeframes": "15m"})
    assert fleet["coin_list"] == ["BTC", "SKY"], "v1 still names its own store"


def test_the_v2_button_names_an_unreadable_market(fleet, monkeypatch):
    from fastapi import HTTPException

    from tradingagents import api as api_mod

    def down():
        raise RuntimeError("venue down")
    monkeypatch.setattr(mf, "trading_symbols", down)
    with pytest.raises(HTTPException) as got:
        api_mod.cloud_dispatch({"res": "1m", "timeframes": "15m"})
    assert "venue down" in str(got.value.detail)
    assert "coin_list" not in fleet, "nothing was sent"
