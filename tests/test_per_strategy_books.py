"""Per-strategy book selection: each strategy trades REAL, PAPER, both, or off.

The global "Auto Trade" / "Dry run" pair used to decide the book for EVERY
strategy at once, so a strategy the operator wanted to paper-test could not run
beside one trading real money. These tests pin the replacement, and the one
that matters most is `test_paper_only_strategy_is_never_evaluated_live`: a
strategy set to PAPER must never be reachable with dry=False, because that is
the difference between a simulation and an order.
"""
import pytest

import tradingagents.auto_trader as at


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("AUTO_TRADE_DRY", raising=False)
    yield


# --------------------------------------------------------------- books_for

def test_per_strategy_books_are_honoured():
    s = {"strategies": ["a", "b", "c"],
         "strategy_books": {"a": ["real"], "b": ["paper"],
                            "c": ["real", "paper"]}}
    assert at.books_for("a", s) == [False]
    assert at.books_for("b", s) == [True]
    assert sorted(at.books_for("c", s)) == [False, True]


def test_empty_book_list_means_the_strategy_runs_nowhere():
    s = {"strategies": ["a"], "strategy_books": {"a": []}}
    assert at.books_for("a", s) == []


def test_falls_back_to_the_global_switches_when_unconfigured():
    """An existing settings file has no strategy_books; it must keep working
    exactly as before rather than silently trading nothing — or worse,
    silently trading everything live."""
    both = {"strategies": ["a"], "enabled": True, "dry_run": True}
    assert sorted(at.books_for("a", both)) == [False, True]
    live = {"strategies": ["a"], "enabled": True, "dry_run": False}
    assert at.books_for("a", live) == [False]
    paper = {"strategies": ["a"], "enabled": False, "dry_run": True}
    assert at.books_for("a", paper) == [True]
    off = {"strategies": ["a"], "enabled": False, "dry_run": False}
    assert at.books_for("a", off) == []


def test_a_strategy_missing_from_the_map_falls_back_not_forward():
    """Unknown key + a live global must not invent a real book for it beyond
    what the legacy behaviour already granted."""
    s = {"strategies": ["a", "b"], "enabled": True, "dry_run": False,
         "strategy_books": {"a": ["paper"]}}
    assert at.books_for("a", s) == [True]      # explicit wins
    assert at.books_for("b", s) == [False]     # legacy global


def test_env_dry_adds_the_paper_book(monkeypatch):
    """AUTO_TRADE_DRY has always ADDED paper; keep that exact meaning."""
    monkeypatch.setenv("AUTO_TRADE_DRY", "yes")
    s = {"strategies": ["a"], "strategy_books": {"a": ["real"]}}
    assert sorted(at.books_for("a", s)) == [False, True]


# ------------------------------------------------------------ active_modes

def test_active_modes_is_the_union_of_every_strategy_book():
    s = {"strategies": ["a", "b"],
         "strategy_books": {"a": ["real"], "b": ["paper"]}}
    assert sorted(at.active_modes(s)) == [False, True]


def test_active_modes_empty_when_no_strategy_trades_anywhere():
    s = {"strategies": ["a", "b"],
         "strategy_books": {"a": [], "b": []}}
    assert at.active_modes(s) == []


def test_active_modes_ignores_books_of_unarmed_strategies():
    """A strategy that is not in `strategies` is off, whatever its book says."""
    s = {"strategies": ["a"],
         "strategy_books": {"a": ["paper"], "b": ["real"]}}
    assert at.active_modes(s) == [True]


def test_active_modes_keeps_legacy_behaviour():
    s = {"strategies": ["a"], "enabled": True, "dry_run": True}
    assert sorted(at.active_modes(s)) == [False, True]


# ------------------------------------------------- the gate that spends money

def test_paper_only_strategy_is_never_evaluated_live(monkeypatch):
    """The whole point. A PAPER strategy must not appear in the live book."""
    seen = {}

    def fake_strategies(symbol, settings, dry):
        return [k for k in ("live_one", "paper_one")
                if k in settings.get("strategies", [])
                and symbol in at.coins_for(k, settings)
                and dry in at.books_for(k, settings)]

    s = {"strategies": ["live_one", "paper_one"],
         "strategy_coins": {"live_one": ["X_USDT"], "paper_one": ["X_USDT"]},
         "strategy_books": {"live_one": ["real"], "paper_one": ["paper"]}}
    seen[False] = fake_strategies("X_USDT", s, False)
    seen[True] = fake_strategies("X_USDT", s, True)
    assert seen[False] == ["live_one"]
    assert seen[True] == ["paper_one"]


def test_process_symbol_skips_strategies_not_in_this_book(monkeypatch):
    """Drive the real function: a paper-only strategy must not be considered
    when the live book is scanned."""
    considered = []

    real_specs = at.STRATEGY_SPECS

    def spy_klines(symbol, interval, n):
        raise AssertionError("should not fetch — no strategy in this book")

    class FX:
        klines = staticmethod(spy_klines)

    s = {"strategies": ["fvg_1h_w"],
         "strategy_coins": {"fvg_1h_w": ["ALICE_USDT"]},
         "strategy_books": {"fvg_1h_w": ["paper"]}}
    state = {}
    # live book: no strategy qualifies, so it must return before any fetch
    at.process_symbol("ALICE_USDT", s, state, fx=FX(), dry=False)
    assert state == {}
    assert considered == []
    assert real_specs is at.STRATEGY_SPECS


def test_settings_round_trip_keeps_strategy_books(tmp_path, monkeypatch):
    import json
    p = tmp_path / "auto_trade.json"
    monkeypatch.setattr(at, "SETTINGS_PATH", p)
    p.write_text(json.dumps({"strategies": ["a"],
                             "strategy_books": {"a": ["real", "paper"]}}))
    s = at.load_settings()
    assert s["strategy_books"] == {"a": ["real", "paper"]}
    assert sorted(at.books_for("a", s)) == [False, True]
