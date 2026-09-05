"""Adding signals must not re-measure the store.

Aug 27, 2026: registering the five 4-hour confluence setups took the signal
registry from 105 to 120. `market_sweep.run_pair` fingerprinted a pair's
checkpoint with the COUNT (`signals105-th3`), so every pair in the operator's
store — 4,226 pairs, 21.9 million rows — became "stale" the moment the rules
landed, and the next update would have replayed all of it to obtain the new
rules' first pass.

Two things hold that shut:

* the fingerprint is a NAMED SET (`__signals__`) when the state file carries
  one, so a pair is stale only when the registry has a signal the pair has
  never measured;
* `merge=True` walks only the signals it is given, over the whole window, and
  MERGES — rows by combination, states by key, watermark by max — so the
  combinations it never looked at keep both their rows and their resume points.
"""
from __future__ import annotations

import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import market_sweep as msw
from tradingagents.dataflows import mexc_futures as fx

BAR_MS = 4 * 3_600_000


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(msw, "HOME", tmp_path)
    monkeypatch.setattr(msw, "STATES", tmp_path / "state")
    monkeypatch.setattr(msw, "ROWDIR", tmp_path / "rows")
    monkeypatch.setattr(msw, "PROGRESS", tmp_path / "progress.json")
    monkeypatch.setattr(msw, "CANDLES", tmp_path / "candles")
    return tmp_path


def _frame(n=700, seed=5):
    """A deterministic market with enough movement for a rule to trade."""
    rows = []
    px = 100.0
    for i in range(n):
        seed = (1103515245 * seed + 12345) % (1 << 31)
        r = (seed / (1 << 31)) - 0.5
        if i % 90 == 0:
            trend = (i // 90 % 3) - 1
        step = px * (0.004 * trend + 0.012 * r)
        o, c = px, px + step
        rows.append({"Date": pd.Timestamp(1_700_000_000_000 + i * BAR_MS,
                                          unit="ms"),
                     "Open": round(o, 4),
                     "High": round(max(o, c) * 1.004, 4),
                     "Low": round(min(o, c) * 0.996, 4),
                     "Close": round(c, 4), "Volume": 1000.0 + 500 * abs(r)})
        px = c
    return pd.DataFrame(rows)


@pytest.fixture
def offline(monkeypatch):
    """No venue. Candles, funding and the cost model are all local."""
    df = _frame()
    monkeypatch.setattr(msw, "refresh_candles",
                        lambda sym, tf, days=365: (df, 0, "test"))
    monkeypatch.setattr(fx, "funding_history",
                        lambda sym, **k: [{"settle_ms": int(df["Date"].iloc[0]
                                                            .timestamp() * 1000)
                                           + j * 8 * 3_600_000,
                                           "rate": 0.0001}
                                          for j in range(400)])
    monkeypatch.setattr(at, "taker_fee", lambda sym, fx=None: 0.0002)
    monkeypatch.setattr(fx, "liquidation_move_pct", lambda sym, lev: 5.0)
    monkeypatch.setattr(fx, "book_cost",
                        lambda sym, notional: {"spread": 0.0004,
                                               "slippage": 0.0002,
                                               "book_exhausted": False})
    monkeypatch.setattr(msw, "min_trades", lambda tf, days=None: 1)
    return df


def _sigs_of(rows):
    return {r["signal"] for r in rows}


def test_merge_adds_a_signal_and_keeps_the_other_ones_rows(store, offline):
    first = msw.run_pair("TEST_USDT", "4h", days=120, signals=["mom6"],
                         thresholds=1)
    assert first["rows"], "the first pass measured nothing to build on"
    assert _sigs_of(msw.pair_rows("TEST", "4h")) == {"mom6"}
    st1 = msw.load_states("TEST", "4h")
    assert st1["__signals__"] == ["mom6"]
    n1 = len(msw.pair_rows("TEST", "4h"))

    second = msw.run_pair("TEST_USDT", "4h", days=120, signals=["trend50"],
                          thresholds=1, merge=True)
    assert second["rows"], "the added signal measured nothing"
    stored = msw.pair_rows("TEST", "4h")
    assert _sigs_of(stored) == {"mom6", "trend50"}, \
        "merge must not delete the rows it did not measure"
    assert len(stored) > n1
    st2 = msw.load_states("TEST", "4h")
    assert st2["__signals__"] == ["mom6", "trend50"]
    # the first signal's per-combination resume points survived
    kept = [k for k in st1 if not k.startswith("__")]
    assert kept and all(k in st2 for k in kept), \
        "merge dropped the checkpoints of the signals it did not measure"


def test_a_named_set_means_an_addition_is_not_a_reset(store, offline,
                                                      monkeypatch):
    """The pair holds both signals; asking for both again resumes instead of
    replaying. This is the 21.9-million-row question."""
    msw.run_pair("TEST_USDT", "4h", days=120, signals=["mom6"], thresholds=1)
    msw.run_pair("TEST_USDT", "4h", days=120, signals=["trend50"],
                 thresholds=1, merge=True)
    st = msw.load_states("TEST", "4h")
    before = {k: v for k, v in st.items() if not k.startswith("__")}
    again = msw.run_pair("TEST_USDT", "4h", days=120,
                         signals=["mom6", "trend50"], thresholds=1)
    assert again.get("why") == "no new bars" or again.get("incremental"), \
        f"a pair holding every asked-for signal replayed anyway: {again}"
    after = msw.load_states("TEST", "4h")
    assert all(k in after for k in before), "the checkpoints were thrown away"


def test_a_signal_the_pair_has_never_measured_still_resets_it(store, offline):
    """The check must still catch a store that is genuinely behind: rows
    measured with fewer rules must never be served as complete."""
    msw.run_pair("TEST_USDT", "4h", days=120, signals=["mom6"], thresholds=1)
    st = msw.load_states("TEST", "4h")
    assert st["__last_ms__"] > 0
    got = msw.run_pair("TEST_USDT", "4h", days=120,
                       signals=["mom6", "fade15"], thresholds=1)
    assert got.get("why") != "no new bars", \
        "a pair missing fade15 must not report itself up to date"
    assert _sigs_of(msw.pair_rows("TEST", "4h")) == {"mom6", "fade15"}
    assert msw.load_states("TEST", "4h")["__signals__"] == ["fade15", "mom6"]


def test_merge_walks_the_whole_window_not_just_the_new_bars(store, offline):
    """A combination with no state behind it cannot be resumed: starting it at
    the last bar would give it no ladder rung and no running total. The rows the
    merge writes must therefore cover the same trade count as a fresh pass."""
    fresh = msw.run_pair("TEST_USDT", "4h", days=120, signals=["trend50"],
                         thresholds=1, fresh=True)
    fresh_rows = {(r["signal"], r["sl"], r["tp"], r["sizing"]): r["trades"]
                  for r in fresh["rows"]}
    # a different pair, measured with something else first, then merged
    msw.run_pair("OTHER_USDT", "4h", days=120, signals=["mom6"], thresholds=1)
    merged = msw.run_pair("OTHER_USDT", "4h", days=120, signals=["trend50"],
                          thresholds=1, merge=True)
    merged_rows = {(r["signal"], r["sl"], r["tp"], r["sizing"]): r["trades"]
                   for r in merged["rows"]}
    assert merged_rows == fresh_rows, \
        "the merged pass measured a different history from a fresh one"


def test_a_state_file_written_before_the_named_set_is_read_from_its_keys(
        store, offline):
    """Every pair in the operator's store predates `__signals__`.

    The first merged pair proved it: 1000BONK-1h came back with
    `__signals__: ["cf_bosfvg", ...]` -- fifteen names -- beside 17,592 rows
    from 80 other signals, because the previous set was read from a field that
    did not exist yet. The next pass would then have called the pair stale and
    re-measured all of it, which is the exact cost this feature exists to
    avoid. The state's own KEYS carry the answer: one per measured
    combination.
    """
    msw.run_pair("TEST_USDT", "4h", days=120, signals=["mom6", "fade15"],
                 thresholds=1)
    st = msw.load_states("TEST", "4h")
    assert msw.signals_in(st) == {"mom6", "fade15"}
    # forget the named set, exactly as every pair in the store has it
    st.pop("__signals__", None)
    msw.save_states("TEST", "4h", st)

    msw.run_pair("TEST_USDT", "4h", days=120, signals=["trend50"],
                 thresholds=1, merge=True)
    after = msw.load_states("TEST", "4h")
    assert after["__signals__"] == ["fade15", "mom6", "trend50"],         "the merge forgot what the pair had already measured"
    assert after["__version__"].startswith("signals3-"),         "the version must count what the pair HOLDS, not what one pass measured"
    assert _sigs_of(msw.pair_rows("TEST", "4h")) == {"mom6", "fade15",
                                                    "trend50"}


def test_the_persist_step_merges_rather_than_overwriting():
    """Source-level, because this is the line that would silently delete 105
    signals' rows if it were ever changed back."""
    import inspect

    src = inspect.getsource(msw.run_pair)
    assert "if merge:" in src
    i = src.index("if merge:")
    tail = src[i:i + 420]
    assert "merge_pair_rows(coin, tf, out_rows)" in tail
    assert "save_pair_rows(coin, tf, out_rows)" in src, \
        "a full pass still replaces the file"
    assert '"__signals__"' in src, "the named set has to be written"
