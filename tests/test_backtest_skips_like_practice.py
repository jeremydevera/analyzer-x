"""The backtest skips a trade the way practice skips it (operator, Oct 11,
2026: "i said it should behave like practice, meaning backtest should know
wether to skip a trade or not ... that is why I changed fro MEXC to gate
because gate has cost in its api").

Practice's checks after a signal, in the runner's order (auto_trader.
process_symbol): the cost check, the signal's age, the coin's places, then
the "price already ran away" check (`chase_ok`). The backtest asked only the
cost check. Since the move to Gate every minute's order book is recorded, so
the backtest now asks `chase_ok` too, on the SAME minute's best price the
cost check reads - ask for a long, bid for a short - and counts each refusal
(`chase_skip`), exactly as practice writes one.

Measured on room #55D32617 since the move (Oct 10, 2026 3:59am): 15
entries, 10 chase_skip, 6 stale_skip (all six in the minute after a restart).
Every entry with a reading passes the same check on the recorded minute; 5 of
the 7 chase_skips with a reading are refused by it.

Candles and readings share ONE clock here: hour bars from T0, the entry
minute is the entry bar's open, and the book is read there.
"""
import numpy as np
import pandas as pd

from tradingagents import auto_trader as at

T0 = 1791504000           # Oct 09, 2026 00:00 UTC
H = 3600


def frame():
    n = 30
    o = [100.0] * n
    hi = [100.2] * n
    lo = [99.8] * n
    hi[8] = 101.5          # a long's 1% target is touched in bar 8
    lo[8] = 98.5           # and a short's 1% target too
    return pd.DataFrame({"Date": pd.to_datetime([T0 + H * k for k in range(n)], unit="s"),
                         "Open": o, "High": hi, "Low": lo, "Close": o,
                         "Volume": [1.0] * n})


KEY = next(iter(at.STRATEGY_SPECS))


def run(side=1, **kw):
    dirs = [0] * 30
    dirs[5] = side         # signal on bar 5 (close 100) -> entry at bar 6's open
    return at.backtest_strategy(KEY, frame(), 5.0, fee=0.00075, slippage=0.0003,
                                sizing="flat", dirs=dirs, tp=0.01, sl=0.01,
                                keep_log=True, **kw)


def book(bid, ask, at_t=T0 + 6 * H):
    """One cheap reading at the entry minute with this best bid and ask."""
    return {"t": np.asarray([at_t], dtype="int64"), "bid": np.asarray([bid], dtype="float64"),
            "ask": np.asarray([ask], dtype="float64"),
            "spread": np.asarray([(ask - bid) / ((ask + bid) / 2)], dtype="float32"),
            "buy": np.asarray([0.0001], dtype="float32"),
            "sell": np.asarray([0.0001], dtype="float32"),
            "exhausted": np.asarray([False]), "source": np.ones(1, dtype="int8")}


def test_a_long_whose_buy_price_already_ran_away_is_skipped_and_counted():
    """The 1% stop allows 0.10% of drift (MAX_CHASE_FRACTION_OF_STOP). The
    ask 0.15% above the signal's close is the runner's chase_skip."""
    r = run(book=book(100.14, 100.15))
    assert r["trades"] == 0 and r["chase_skip"] == 1 and r["gate_blocked"] == 0


def test_a_long_inside_the_limit_is_taken():
    r = run(book=book(100.04, 100.05))
    assert r["trades"] == 1 and r["chase_skip"] == 0


def test_a_short_reads_the_bid():
    """A short sells at the bid: the bid 0.15% under the close has run away;
    the same book's ask is irrelevant to it."""
    assert run(side=-1, book=book(99.85, 99.86))["chase_skip"] == 1
    r = run(side=-1, book=book(99.95, 99.96))
    assert r["trades"] == 1 and r["chase_skip"] == 0


def test_a_minute_with_no_reading_is_not_judged():
    """No recorded book at the entry minute: the runner would have read a
    live price; the backtest cannot, so it neither skips nor invents a price
    (the trade is counted unmeasured by the cost check, as before)."""
    r = run(book=book(100.14, 100.15, at_t=T0))           # hours too old
    assert r["trades"] == 1 and r["chase_skip"] == 0 and r["cost_unmeasured"] == 1


def test_a_candle_the_room_really_took_is_never_refused_by_a_model():
    """Backtest a room follows the ROOM where it ran: a candle the room
    entered is taken whatever the minute's book says - the record is the
    truth, the book is a model of it (chase and cost alike)."""
    signal_open_ms = (T0 + 5 * H) * 1000
    r = run(book=book(100.14, 100.15), keep=lambda ms: ms == signal_open_ms)
    assert r["trades"] == 1 and r["chase_skip"] == 0
    # 0.8% to get in against a 1% target: only the COST check refuses it
    dear = {**book(99.99, 100.01), "spread": np.asarray([0.016], dtype="float32"),
            "buy": np.asarray([0.008], dtype="float32"),
            "sell": np.asarray([0.008], dtype="float32")}
    assert run(book=dear)["gate_blocked"] == 1
    r = run(book=dear, keep=lambda ms: ms == signal_open_ms)
    assert r["trades"] == 1 and r["gate_blocked"] == 0
    # a keep that names another candle changes nothing
    assert run(book=book(100.14, 100.15), keep=lambda ms: False)["chase_skip"] == 1


def test_no_book_is_the_engine_of_before():
    a, b = run(), run(book=None, keep=lambda ms: True)
    assert a == b and "chase_skip" not in a


def test_every_v2_row_carries_the_count():
    from pathlib import Path
    src = " ".join((Path(__file__).resolve().parents[1] / ".github/scripts/sweep_shard.py")
                   .read_text(encoding="utf-8").split())
    assert '"chase_skip": int(r.get("chase_skip", 0))' in src


def test_the_trade_list_rebuild_lets_the_room_s_own_candles_through():
    """`trades_for(took=...)` hands the engine a `keep` that answers True for
    exactly the candles the room entered (signal-candle opens: seconds in,
    milliseconds asked), and Backtest a room's rebuild passes them."""
    import re

    from tradingagents import market_sweep as msw
    keep = msw._keep_of({1791504000})
    assert keep(1791504000 * 1000) and not keep(1791507600 * 1000)
    assert msw._keep_of(set()) is None and msw._keep_of(None) is None
    ms_src = Path_src("tradingagents/market_sweep.py")
    call = ms_src[ms_src.index("r = at.backtest_strategy(key, df, base_margin"):]
    assert "keep=_keep_of(took)" in call[:call.index("finally:")]
    rr_src = Path_src("tradingagents/room_replay.py")
    rr_src = rr_src[rr_src.index("def room_lists("):]
    tf_call = rr_src[rr_src.index("got = ms.trades_for(c[\"coin\"]"):]
    tf_call = tf_call[:tf_call.index("except Exception")]
    assert re.search(r"took=took\)", tf_call), "room_lists passes the room's own entries"


def Path_src(rel):
    from pathlib import Path
    return (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")


def test_the_room_replay_keeps_practice_s_same_direction_rule_before_the_room():
    """Practice never opens a trade against the side already open on its coin
    ("netting would cancel them"). Backtest a room applied that only while
    following the room; the days before it opened opposite trades together."""
    from tradingagents import watcher_policy as wp, watcher_replay as wr
    t0 = 1791504000 * 1000
    hr = 3_600_000
    # a won trade at t0 makes each row pass its line at the next midnight;
    # then the LONG opens at t0+30h and the SHORT at t0+31h, on the same coin
    warm = [t0, t0 + 1000, 1.0, 1, t0 + 1000, "TP", "LONG"]
    long_ = {"id": "LONG0001", "coin": "KII", "tf": "1h", "signal": "a", "th": 0.0,
             "sl": 1.0, "tp": 2.0, "group": "classic", "gate": "ok",
             "trades": [warm, [t0 + 30 * hr, t0 + 40 * hr, 0.9, 1, t0 + 40 * hr, "TP", "LONG"]]}
    short = {**long_, "id": "SHRT0002",
             "trades": [warm, [t0 + 31 * hr, t0 + 35 * hr, 0.9, 1, t0 + 35 * hr, "TP", "SHORT"]]}
    cfg = {**wp.DEFAULTS, "on_winrate": 50.0, "off_winrate": 0.0, "min_trades": 1,
           "tp_rule": ">", "max_sl": 2.0, "window_days": 30, "raw": True,
           "max_new_per_day": 0, "max_slots": 0, "max_per_coin": 0, "cooldown_days": 0,
           "coin_slices": 4}
    got = wr.simulate([long_, short], start_ms=t0, end_ms=t0 + 48 * hr, cfg=cfg)
    assert {s["id"] for s in got["slots"]} == {"LONG0001", "SHRT0002"},         "the fixture must switch both on to prove anything"
    took = {s["id"]: len(s["trades"]) for s in got["slots"]}
    assert took.get("LONG0001") == 1 and took.get("SHRT0002", 0) == 0, took


def test_an_old_reading_never_judges_the_price():
    """The cost check takes the newest reading up to an hour old; the price
    is another matter - an ask from 30 minutes before the close says nothing
    about where the market was when the runner looked, ~3 s after it. Only
    the book of the close's OWN minute judges the price, else it does not
    judge (the runner, with no live price, would have looked again; the
    backtest cannot). The minute before the close is inside the signal
    candle, so it is not judged either (review of a1ab2206)."""
    old = book(100.14, 100.15, at_t=T0 + 6 * H - 30 * 60)
    r = run(book=old)
    assert r["trades"] == 1 and r["chase_skip"] == 0
    minute_before = book(100.14, 100.15, at_t=T0 + 6 * H - 60)
    r = run(book=minute_before)
    assert r["trades"] == 1 and r["chase_skip"] == 0
    assert run(book=book(100.14, 100.15))["chase_skip"] == 1


RAN = {"age_s": 0, "bid": 100.14, "ask": 100.15, "spread": 0.0001,
       "buy": 0.0001, "sell": 0.0001, "exhausted": False}
LONG = {"side": 1, "signal_close": 100.0, "tp": 0.01, "sl": 0.01, "fee": 0.00075,
        "hold_s": 3600, "liq": None, "fund_day": 0.0}


def test_a_snapshot_only_hour_never_judges_the_price():
    """Gate publishes only a snapshot for some hours, and `replay_hour`
    stamps that ONE hour-start book on all sixty minutes, each read back
    with age 0 (source 2). This PC's BTC readings, Sep 10, 2026: the ask is
    77142.4 at 10:00, 10:15, 10:30 and 10:45am - the 10:00 book every time
    - and 15,000 of 44,548 BTC readings since Sep 01 are such hours. A 15m
    long closing 0.124% under that stale ask was refused while the next
    minute opened at the close (review of a1ab2206, RCA-2026-10-11-E)."""
    hour = 1789048800                            # Sep 10, 2026 10:00am EDT
    # a snapshot-only hour read at :15 - its book is 15 minutes old
    assert at.entry_refusal({**RAN, "t": hour + 900, "source": 2}, **LONG)[0] == ""
    # the same hour read at :00 IS the snapshot's own minute
    assert at.entry_refusal({**RAN, "t": hour, "source": 2}, **LONG)[0] == "chase_skip"
    # a full replay's :15 is that minute's own book
    assert at.entry_refusal({**RAN, "t": hour + 900, "source": 1}, **LONG)[0] == "chase_skip"


def test_the_engine_reads_a_snapshot_hour_as_old():
    """The same rule through `backtest_strategy`: 15m bars, the entry at
    :15 past an hour that only has a snapshot."""
    n, q = 30, 900
    o = [100.0] * n
    hi, lo = [100.2] * n, [99.8] * n
    hi[8] = 101.5
    df = pd.DataFrame({"Date": pd.to_datetime([T0 + q * k for k in range(n)], unit="s"),
                       "Open": o, "High": hi, "Low": lo, "Close": o,
                       "Volume": [1.0] * n})
    dirs = [0] * n
    dirs[4] = 1                    # signal on bar 4 -> entry at bar 5 = T0 + 1h15m
    entry = T0 + 5 * q
    assert entry % 3600 == 900

    def snap(source):
        b = book(100.14, 100.15, at_t=entry)
        return {**b, "source": np.asarray([source], dtype="int8")}

    def go(b):
        return at.backtest_strategy(KEY, df, 5.0, fee=0.00075, slippage=0.0003,
                                    sizing="flat", dirs=dirs, tp=0.01, sl=0.01,
                                    keep_log=True, book=b)
    r = go(snap(2))
    assert r["trades"] == 1 and r["chase_skip"] == 0, r
    assert go(snap(1))["chase_skip"] == 1


def test_a_row_measured_on_this_pc_carries_the_count_too():
    """UPDATE THIS BACKTEST writes the same fields as a GitHub v2 row
    (RCA-2026-10-10-K): the chase count with the cost check's."""
    src = " ".join(Path_src("tradingagents/market_sweep.py").split())
    assert src.count('"chase_skip": int(r.get("chase_skip", 0))') >= 2,         "both the row writer and the trade-list rebuild carry it"


def test_one_entry_decision_for_the_engine_and_the_replay():
    """at.entry_refusal answers in the runner's order: cost first."""
    dear = {"t": 0, "age_s": 0, "bid": 100.14, "ask": 100.15, "spread": 0.016,
            "buy": 0.008, "sell": 0.008, "exhausted": False, "source": 1}
    why, _ = at.entry_refusal(dear, side=1, signal_close=100.0, tp=0.01, sl=0.01,
                              fee=0.00075, hold_s=3600, liq=None, fund_day=0.0)
    assert why == "gate_blocked"
    cheap = {**dear, "spread": 0.0001, "buy": 0.0001, "sell": 0.0001}
    assert at.entry_refusal(cheap, side=1, signal_close=100.0, tp=0.01, sl=0.01,
                            fee=0.00075, hold_s=3600, liq=None, fund_day=0.0)[0] == "chase_skip"
    assert at.entry_refusal({**cheap, "ask": 100.05}, side=1, signal_close=100.0,
                            tp=0.01, sl=0.01, fee=0.00075, hold_s=3600, liq=None,
                            fund_day=0.0)[0] == ""

