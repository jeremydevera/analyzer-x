"""The two orders the screen uses must not disappear during a fill.

Operator, 2026-08-26, after asking three times: "when i clickk winrate header,
the only sorted are the ones on the page. i want you to sort all". The sort IS
global — but `rows_winrate` kept vanishing. The loop:

  * a sweep runs -> the indexer trickles one pair a cycle, no drop
  * the sweep pauses -> the indexer finds 800+ stale pairs, calls it a BULK
    fill, DROPS rows_coin and rows_winrate, loads, and rebuilds at the end
  * anything that interrupts that cycle (an app restart, another sweep
    starting) leaves them dropped, and the screen answers 503 for hours

Measured cost of carrying them instead: an insert with SIX indexes managed 1.5
pairs/min, with none 73. Two more indexes is a middle the incremental path can
afford; losing the operator's ranking is not. A genuinely huge load (a rebuild
from the pair files) still drops them, because there the rebuild is cheaper
than the maintenance.
"""
from tradingagents import rows_index as ri


def test_the_screens_two_orders_are_never_dropped():
    kept = " ".join(ri.KEEP_INDEXES)
    for name in ("rows_pair", "rows_profit", "rows_coin", "rows_winrate"):
        assert name in kept, f"{name} must survive a fill"
    assert not set(ri.FILTER_INDEXES) & {"rows_coin", "rows_winrate"}, \
        "an index the screen needs must not be in the droppable set"


def test_a_normal_fill_drops_nothing(tmp_path, monkeypatch):
    import inspect

    src = inspect.getsource(ri.sync)
    assert "BIG_FILL" in src, "only a huge load may drop the kept indexes"
    assert "len(todo) > BULK_PAIRS" not in src, \
        "an 9-pair fill must not drop the screen's indexes"


def test_not_even_a_huge_load_drops_them():
    """The BIG_FILL exception lasted one evening. At 12:48am on 2026-08-27 the
    indexer finished a 500+ pair fill, dropped rows_profit with it, and the
    Stored strategies page showed nothing at all for the ~25 minutes of
    rebuilds — "why does it not show anything". A slower fill costs the
    operator nothing they can see."""
    import inspect

    src = inspect.getsource(ri.sync)
    assert "DROP INDEX" not in src



def test_the_sort_guard_still_covers_a_missing_index(tmp_path, monkeypatch):
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "x.db")
    ri._ready.discard(str(tmp_path / "x.db"))
    ri.ensure()
    assert ri.has_index("rows_winrate") is True, \
        "ensure() must now create it — it is a kept index"
    assert ri.has_index("rows_coin") is True
