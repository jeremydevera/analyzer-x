"""Every filter, alone, in pairs, and all at once — against a brute-force oracle.

Operator, 2026-09-06: *"make sure all filters with different combination works
and when i add new filter it will work properly as well"* — asked after their
crypto-only + win % >= 90 + TP >= SL filter sat in a 503 loop for so long they
concluded the crypto filter itself was broken (it was the query PLAN, not the
filter — see WIDEST_WINRATE in rows_index.py).

Two guarantees here:

* every filter `query()` takes is exercised alone, in every PAIR, and all
  together, and the rows that come back match a plain-Python re-filter of the
  same store — so a filter that stops cutting (or cuts the wrong rows) fails
  by name.
* `test_a_new_filter_must_join_this_spec` reads `query()`'s own signature:
  add a parameter without adding it to SPEC (or to the named non-filter list)
  and this file fails, which is the "when i add new filter" half of the ask.
"""
import inspect
import itertools
import json

import pytest

from tradingagents import market_sweep as msw, rows_index as ri


def _row(coin, tf="1h", signal="scalp", sizing="flat", tp=1.0, sl=1.0,
         profit=10.0, trades=120, winrate=60.0):
    wins = round(trades * winrate / 100)
    return {"coin": coin, "tf": tf, "signal": signal, "th": 0.1, "sl": sl,
            "tp": tp, "rr": round(tp / sl, 4), "sizing": sizing, "lev": 20,
            "base": 5.0, "notional": 100.0, "trades": trades, "wins": wins,
            "losses": trades - wins, "winrate": winrate, "profit": profit,
            "funding": -0.2, "h1": profit / 2, "h2": profit / 2, "green": 8,
            "months": 12, "worst": -4.1, "dd": 22.0, "liqs": 0,
            "stop_reachable": True, "days": 360, "bars": 34000,
            "monthly": {"2026-08": profit / 3}, "cost_of_tp": 12.5,
            "rt": 0.04, "gate": "ok"}


# a small store that gives EVERY filter something to cut and something to
# keep: two stocks, three crypto coins, two timeframes, a cf_ signal (the
# preset group), both sizings, tp above/at/below sl, floors both sides
ROWS = [
    _row("GPNSTOCK", tf="1h", signal="scalp", sizing="flat",
         tp=2.0, sl=1.0, profit=50.0, trades=200, winrate=91.0),
    _row("PSXSTOCK", tf="4h", signal="cf_bosfvg", sizing="martingale",
         tp=1.0, sl=2.0, profit=-8.0, trades=15, winrate=40.0),
    _row("KITE", tf="1h", signal="cf_bosfvg", sizing="flat",
         tp=1.0, sl=1.0, profit=30.0, trades=25, winrate=95.0),
    _row("STBL", tf="4h", signal="ema", sizing="martingale",
         tp=0.5, sl=1.5, profit=20.0, trades=500, winrate=55.0),
    _row("KAVA", tf="1h", signal="scalp", sizing="flat",
         tp=4.0, sl=0.5, profit=-2.0, trades=80, winrate=30.0),
]


@pytest.fixture
def store(tmp_path, monkeypatch):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    monkeypatch.setattr(msw, "ROWDIR", rows_dir)
    monkeypatch.setattr(ri, "DB_PATH", tmp_path / "rows.db")
    for r in ROWS:
        (rows_dir / f"{r['coin']}-{r['tf']}.json").write_text(json.dumps([r]))
    import time

    ri.sync(now=time.time() + ri.SETTLE_S + 1)
    return None


# filter name -> (a value that cuts this store, the row predicate it PROMISES)
# — the oracle each combination is checked against. A new filter joins this
# dict with its own promise, and the pairwise sweep below covers it at once.
SPEC = {
    "coin": ("KITE", lambda r, v: r["coin"] == v),
    "tf": ("1h", lambda r, v: r["tf"] == v),
    "signal": ("cf_bosfvg", lambda r, v: r["signal"] == v),
    "group": ("preset", lambda r, v: r["signal"].startswith("cf_")
              if v == "preset" else not r["signal"].startswith("cf_")),
    "sizing": ("flat", lambda r, v: r["sizing"] == v),
    "profitable": (True, lambda r, v: r["profit"] > 0),
    "min_trades": (20, lambda r, v: r["trades"] >= v),
    "min_winrate": (50, lambda r, v: r["winrate"] >= v),
    "max_tp": (2.0, lambda r, v: r["tp"] <= v),
    "min_tp": (1.0, lambda r, v: r["tp"] >= v),
    "max_sl": (1.5, lambda r, v: r["sl"] <= v),
    "min_sl": (1.0, lambda r, v: r["sl"] >= v),
    "tp_over_sl": (True, lambda r, v: r["tp"] >= r["sl"]),
    "asset": ("crypto", lambda r, v: r["coin"].endswith("STOCK")
              if v == "stocks" else not r["coin"].endswith("STOCK")),
}

# query() parameters that are NOT row filters: paging, ordering, the months/
# days windows (they restate figures, they do not cut rows) and the id lookup
# (it OVERRIDES the filters — pinned separately below).
NOT_FILTERS = {"limit", "offset", "sort", "months", "days", "desc", "row_id"}


def _expect(active) -> set:
    keep = set()
    for r in ROWS:
        if all(SPEC[k][1](r, v) for k, v in active.items()):
            keep.add(r["coin"])
    return keep


def _check(active, ctx):
    """The rows must equal the oracle's exactly; the count must equal it too
    UNLESS the store said out loud that it capped the count (a GROUP count is
    bounded by design and prints as '5,000+')."""
    got = ri.query(**active)
    want = _expect(active)
    coins = {r["coin"] for r in got["rows"]}
    assert coins == want, (ctx, coins, want)
    if not got["total_capped"]:
        assert got["total"] == len(want), (ctx, got["total"], want)


def test_every_filter_alone_matches_the_oracle(store):
    for name, (value, _) in SPEC.items():
        _check({name: value}, name)


def test_every_pair_of_filters_ANDs(store):
    """78 pairs as of 2026-09-06. The tp_over_sl checkbox shipped with a count
    that ignored it, and asset+winrate shipped with a plan that could not
    reach the data — pairs are where these break."""
    for a, b in itertools.combinations(SPEC, 2):
        _check({a: SPEC[a][0], b: SPEC[b][0]}, (a, b))


def test_all_filters_at_once(store):
    active = {k: v for k, (v, _) in SPEC.items()
              # coin/signal name one row's own values; the sweep above covers
              # them — here everything ELSE stacks on the operator's shape
              if k not in ("coin", "signal", "group")}
    _check(active, "all")


def test_the_operators_own_2026_09_06_filter(store):
    """crypto only + win % >= 90 + 20+ trades + TP >= SL — the exact boxes
    from the screenshot that started this file. KITE (95%, 25 trades,
    TP 1 = SL 1, crypto) is the one row that passes; GPNSTOCK (91%) is a
    stock and must be cut."""
    got = ri.query(asset="crypto", min_winrate=90, min_trades=20,
                   tp_over_sl=True)
    assert [r["coin"] for r in got["rows"]] == ["KITE"]
    assert got["total"] == 1


def test_row_id_overrides_every_filter(store):
    rid = ri.query(coin="GPNSTOCK")["rows"][0]["id"]
    got = ri.query(row_id=rid, asset="crypto", min_winrate=99.9)
    assert [r["id"] for r in got["rows"]] == [rid]


def test_a_new_filter_must_join_this_spec(store):
    """Add a parameter to query() and this fails until the filter has an
    oracle here — which puts it through the alone/pairs/all sweeps above."""
    params = set(inspect.signature(ri.query).parameters)
    unnamed = params - set(SPEC) - NOT_FILTERS
    assert not unnamed, (
        f"query() grew {sorted(unnamed)} — add each to SPEC with the row "
        f"predicate it promises (or to NOT_FILTERS if it does not cut rows), "
        f"so every combination is tested")
