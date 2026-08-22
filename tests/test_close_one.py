"""Closing ONE position from the UI table.

The rule this file exists to enforce: `close_one` may only report success when
the EXCHANGE says the position is gone. "The order was accepted" is not "it is
closed" — a venue can accept a close and still leave size on the book (partial
fill, 2078 refusal near liquidation, a rate limit swallowing the second leg).
Reporting a phantom close would clear the position from the local book, and
nothing would ever retry it: real money left open with no tracker.
"""

import pytest

import tradingagents.auto_trader as at


class FakeFx:
    """A MEXC stand-in that can be told to close, refuse, or lie."""

    SIDE_CLOSE_LONG = 4
    SIDE_CLOSE_SHORT = 2

    def __init__(self, positions, *, submit_raises=None, closes=True,
                 history=None):
        self._positions = list(positions)
        self.submit_raises = submit_raises
        self.closes = closes
        self.submitted = []
        self._history = history or []

    def open_positions(self, symbol=None):
        if symbol is None:
            return list(self._positions)
        return [p for p in self._positions if p["symbol"] == symbol]

    def submit(self, symbol, side, vol, *, leverage, dry_run):
        self.submitted.append((symbol, side, vol))
        if self.submit_raises:
            raise RuntimeError(self.submit_raises)
        if self.closes:
            self._positions = [p for p in self._positions
                               if p["symbol"] != symbol]

    def position_history(self, symbol, n):
        return [h for h in self._history if h["symbol"] == symbol]

    def contract_spec(self, symbol):
        return {"priceScale": 4}

    def last_price(self, symbol):
        return 1.0


def _pos(symbol="PI_USDT", pid=111, side=1, vol=2261):
    return {"symbol": symbol, "positionId": pid,
            "positionType": 1 if side > 0 else 2, "holdVol": vol,
            "unRealizedPnl": 1.2, "liquidatePrice": 0.05}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Keep every test off the operator's real state and ledger."""
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(at, "KILL_PATH", tmp_path / "KILL")
    yield


def test_closes_the_named_position_only():
    fx = FakeFx([_pos("PI_USDT", 111), _pos("RUNE_USDT", 222, side=-1)])
    rep = at.close_one("PI_USDT", fx=fx)
    assert rep["closed"] is True
    assert [s[0] for s in fx.submitted] == ["PI_USDT"]
    assert {p["symbol"] for p in fx.open_positions()} == {"RUNE_USDT"}


def test_uses_the_close_side_that_matches_the_direction():
    long_fx = FakeFx([_pos(side=1)])
    at.close_one("PI_USDT", fx=long_fx)
    assert long_fx.submitted[0][1] == FakeFx.SIDE_CLOSE_LONG
    short_fx = FakeFx([_pos(side=-1)])
    at.close_one("PI_USDT", fx=short_fx)
    assert short_fx.submitted[0][1] == FakeFx.SIDE_CLOSE_SHORT


def test_unknown_symbol_is_not_a_success():
    fx = FakeFx([_pos("PI_USDT")])
    rep = at.close_one("NOPE_USDT", fx=fx)
    assert rep["closed"] is False
    assert "no open position" in rep["error"].lower()
    assert fx.submitted == []


def test_submit_failure_is_reported_and_position_kept():
    fx = FakeFx([_pos()], submit_raises="510 rate limit")
    rep = at.close_one("PI_USDT", fx=fx)
    assert rep["closed"] is False
    assert "510" in rep["error"]
    # the position must still be tracked — nothing may silently drop it
    assert {p["symbol"] for p in fx.open_positions()} == {"PI_USDT"}


def test_a_venue_that_accepts_but_does_not_close_is_NOT_success():
    """The whole point: acceptance is not closure."""
    fx = FakeFx([_pos()], closes=False)   # submit() succeeds, size remains
    rep = at.close_one("PI_USDT", fx=fx)
    assert rep["closed"] is False
    assert "still open" in rep["error"].lower()


def test_books_the_realised_pnl_as_an_exit_row():
    fx = FakeFx([_pos(pid=111)],
                history=[{"symbol": "PI_USDT", "positionId": 111,
                          "realised": -3.25}])
    rep = at.close_one("PI_USDT", fx=fx)
    assert rep["closed"] is True
    assert rep["realised"] == -3.25
    rows = at.ledger_tail(10)
    exits = [r for r in rows if r.get("action") == "exit"]
    assert len(exits) == 1
    # every PnL reader and the loss limit filter on action == "exit"
    assert exits[0]["symbol"] == "PI_USDT"
    assert exits[0]["pnl_est"] == -3.25
    assert exits[0]["dry_run"] is False
    assert exits[0]["why"] == "MANUAL_UI"


def test_clears_the_local_book_entry_on_success():
    at.save_state({"PI_USDT": {"position": {"side": 1, "vol": 2261,
                                            "position_id": 111}}})
    fx = FakeFx([_pos(pid=111)])
    at.close_one("PI_USDT", fx=fx)
    assert at.load_state()["PI_USDT"]["position"] is None


def test_keeps_the_local_book_entry_when_the_close_failed():
    at.save_state({"PI_USDT": {"position": {"side": 1, "vol": 2261,
                                            "position_id": 111}}})
    fx = FakeFx([_pos(pid=111)], closes=False)
    at.close_one("PI_USDT", fx=fx)
    assert at.load_state()["PI_USDT"]["position"] is not None


def test_never_touches_the_paper_book():
    at.save_state({"PI_USDT#paper": {"position": {"side": 1, "vol": 5,
                                                  "position_id": 9}}})
    fx = FakeFx([_pos(pid=111)])
    at.close_one("PI_USDT", fx=fx)
    assert at.load_state()["PI_USDT#paper"]["position"] is not None


def test_does_not_halt_entries_or_stop_the_runner():
    """Closing one position is not a panic stop — the rest keeps trading."""
    fx = FakeFx([_pos(), _pos("RUNE_USDT", 222, side=-1)])
    at.close_one("PI_USDT", fx=fx)
    assert not at.halted()


def test_unreadable_positions_is_an_error_not_a_close():
    class Broken(FakeFx):
        def open_positions(self, symbol=None):
            raise RuntimeError("network down")

    rep = at.close_one("PI_USDT", fx=Broken([]))
    assert rep["closed"] is False
    assert "network down" in rep["error"]
