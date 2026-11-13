"""A skill trade's fill pays the app's own recorded order book of its own minute (Nov 13, 2026).

Operator: *"build it, use superpower when bulding"*, to the design of the same day - the five room rule
sets' 707 trades of Oct 17 - Nov 12, 2026 read +$131 as the backtest measured them and -$1,125 at the
order book the app recorded in the same minute. The engine priced a fill at the candle's last price plus
the coin's usual gap; a reversion strategy buys when that last price was a seller hitting the bid, and
that price cannot be bought.

Everything here is hand-made on ONE timeline: 1h candles opening at T0 + k hours, the minutes under
them 60 seconds apart, a reading stamped at the first second of the minute it was recorded in.
"""
import numpy as np
import pandas as pd
import pytest

from tradingagents import skill_bt as sb

pytestmark = pytest.mark.unit

H = 3_600_000
M = 60_000
T0 = 1_793_000_000_000 // H * H          # an hour boundary after the record began (Oct 26, 2026)
FEE, SLIP = 0.00075, 0.0003
APP, RECORD = 3, 1                       # book_history.SOURCES: the app's own reading / the exchange's record

# CATL, Nov 11, 2026 7:00am: the candle's last price 49.34; the book bid 48.97 / ask 49.23 (middle
# 49.10); $100 walked the asks to an average of 49.88
LAST, BID, ASK, MID, WALKED = 49.34, 48.97, 49.23, 49.10, 49.88
BUY = WALKED / MID - 1
SELL = 0.004


class _Sig:
    def __init__(self, entry=False, exit=False, direction="long"):
        self.entry, self.exit, self.direction = entry, exit, direction


def _book(rows: dict, **kw) -> sb.Book:
    """{minute_ms: (bid, ask, buy, sell[, exhausted[, source]])} -> a Book."""
    keys = sorted(rows)
    col = lambda i, d=None: [rows[k][i] if len(rows[k]) > i else d for k in keys]   # noqa: E731
    return sb.Book({"t": np.array([k // 1000 for k in keys], dtype="int64"),
                    "bid": np.array(col(0), dtype="float64"), "ask": np.array(col(1), dtype="float64"),
                    "buy": np.array(col(2), dtype="float32"), "sell": np.array(col(3), dtype="float32"),
                    "exhausted": np.array(col(4, False), dtype=bool),
                    "source": np.array(col(5, APP), dtype="int8")}, **kw)


def _enter(book, *, close=LAST, direction="long"):
    pos, done = sb.step(None, _Sig(entry=True, direction=direction), close=close, when_ms=T0, bar_ms=H,
                        stop=0.015, fee=FEE, slip=SLIP, book=book)
    assert done is None
    return pos


def _minutes(lows=None, highs=None, flat=100.0, candle=1):
    t = [T0 + candle * H + m * M for m in range(60)]
    return sb.Fine(t, [(highs or {}).get(m, flat) for m in range(60)],
                   [(lows or {}).get(m, flat) for m in range(60)], T0 + candle * H, T0 + (candle + 1) * H)


# ------------------------------------------------------------------ the entry
def test_an_entry_fills_at_the_recorded_walk_not_the_last_price():
    pos = _enter(_book({T0 + H: (BID, ASK, BUY, SELL)}))
    assert pos["px"] == pytest.approx(WALKED, rel=1e-6)        # what $100 really bought
    assert pos["px"] > LAST * (1 + SLIP)                       # the estimate was 49.3548
    assert pos["real"] is True


def test_a_short_entry_sells_at_the_recorded_walk():
    pos = _enter(_book({T0 + H: (BID, ASK, BUY, SELL)}), direction="short")
    assert pos["px"] == pytest.approx(MID / (1 + SELL), rel=1e-6)
    assert pos["real"] is True


def test_no_reading_at_the_minute_is_todays_price_marked_estimated():
    # the reading is one minute LATER than the fill: not this fill's minute
    pos = _enter(_book({T0 + H + M: (BID, ASK, BUY, SELL)}))
    assert pos["px"] == pytest.approx(LAST * (1 + SLIP))
    assert pos["real"] is False


def test_without_a_book_nothing_is_added():
    pos, _ = sb.step(None, _Sig(entry=True), close=LAST, when_ms=T0, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP)
    assert pos == {"t": T0, "dir": "long", "px": LAST * (1 + SLIP), "fill_ms": T0 + H}
    _, trade = sb.step(pos, _Sig(exit=True), close=50.0, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP)
    assert "real" not in trade and trade["exit_px"] == pytest.approx(50.0 * (1 - SLIP))


# ------------------------------------------------------------------ the exits
def test_a_signal_exit_sells_at_the_recorded_walk():
    book = _book({T0 + H: (BID, ASK, BUY, SELL), T0 + 2 * H: (50.0, 50.2, 0.003, 0.002)})
    pos = _enter(book)
    after, trade = sb.step(pos, _Sig(exit=True), close=50.4, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE,
                           slip=SLIP, book=book)
    assert after is None
    assert trade["why"] == "SIGNAL"
    assert trade["exit_px"] == pytest.approx(50.1 / 1.002, rel=1e-6)      # the middle, less the walk down the bids
    assert trade["real"] == 2
    move = trade["exit_px"] / pos["px"] - 1
    assert trade["pnl"] == pytest.approx(100 * move - 100 * FEE - 100 * (trade["exit_px"] / pos["px"]) * FEE, abs=1e-4)


def test_one_fill_real_is_marked_part():
    book = _book({T0 + H: (BID, ASK, BUY, SELL)})                         # the exit minute was not recorded
    pos = _enter(book)
    _, trade = sb.step(pos, _Sig(exit=True), close=50.4, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE,
                       slip=SLIP, book=book)
    assert trade["exit_px"] == pytest.approx(50.4 * (1 - SLIP))
    assert trade["real"] == 1


def test_a_stop_by_the_minute_keeps_its_barrier_and_pays_that_minutes_walk():
    at = T0 + H + 7 * M
    book = _book({T0 + H: (99.9, 100.1, 0.001, 0.001), at: (99.9, 100.1, 0.002, 0.003)})
    pos = _enter(book, close=100.0)                                       # bought at 100 x 1.001 = 100.1
    sl_px = pos["px"] * (1 - 0.015)
    _, trade = sb.step(pos, _Sig(), close=100.0, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP,
                       fine=_minutes(lows={7: 98.0}), book=book)
    assert trade["why"] == "SL" and trade["at"] == at
    assert trade["exit_px"] == pytest.approx(sl_px / 1.003, rel=1e-6)     # the barrier, less THAT minute's walk
    assert trade["real"] == 2


def test_a_stop_the_price_jumped_past_fills_from_where_the_price_was():
    at = T0 + H + 7 * M
    book = _book({T0 + H: (99.9, 100.1, 0.001, 0.001), at: (97.9, 98.1, 0.002, 0.003)})   # middle 98.0
    pos = _enter(book, close=100.0)
    assert pos["px"] * (1 - 0.015) > 98.0                                 # the stop (98.6) is above the middle
    _, trade = sb.step(pos, _Sig(), close=100.0, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP,
                       fine=_minutes(lows={7: 97.5}), book=book)
    assert trade["why"] == "SL"
    assert trade["exit_px"] == pytest.approx(98.0 / 1.003, rel=1e-6)      # never the barrier it could not get


def test_a_shorts_stop_the_price_jumped_past_buys_from_where_the_price_was():
    at = T0 + H + 7 * M
    book = _book({T0 + H: (99.9, 100.1, 0.001, 0.001), at: (102.9, 103.1, 0.002, 0.003)})  # middle 103.0
    pos = _enter(book, close=100.0, direction="short")
    assert pos["px"] * (1 + 0.015) < 103.0
    _, trade = sb.step(pos, _Sig(), close=100.0, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP,
                       fine=_minutes(highs={7: 103.5}), book=book)
    assert trade["why"] == "SL"
    assert trade["exit_px"] == pytest.approx(103.0 * 1.002, rel=1e-6)


def test_a_target_keeps_its_barrier_even_when_the_price_ran_past_it():
    at = T0 + H + 20 * M
    book = _book({T0 + H: (99.9, 100.1, 0.001, 0.001), at: (103.9, 104.1, 0.002, 0.003)})  # middle 104.0
    pos = _enter(book, close=100.0)
    tp_px = pos["px"] * 1.03
    _, trade = sb.step(pos, _Sig(), close=100.0, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP,
                       target=0.03, fine=_minutes(highs={20: 104.5}), book=book)
    assert trade["why"] == "TP"
    assert trade["exit_px"] == pytest.approx(tp_px / 1.003, rel=1e-6)     # never better than its target


def test_the_stop_is_measured_from_the_price_really_paid():
    """Bought at 49.88, a 1.5% stop sits at 49.13: a minute that trades down to 49.12 stops it. From the
    estimate (49.3548) the stop would sit at 48.61 and the same minute would not touch it."""
    lows = {m: 49.12 if m == 0 else 49.30 for m in range(60)}
    fine = sb.Fine([T0 + H + m * M for m in range(60)], [49.40] * 60, [lows[m] for m in range(60)],
                   T0 + H, T0 + 2 * H)
    book = _book({T0 + H: (BID, ASK, BUY, SELL)})
    kw = dict(close=49.30, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP, fine=fine)
    after, trade = sb.step(_enter(book), _Sig(), book=book, **kw)
    assert after is None and trade["why"] == "SL" and trade["at"] == T0 + H
    plain = _enter(None)
    after, trade = sb.step(plain, _Sig(), **kw)
    assert trade is None and after == plain


# ------------------------------------------------------------------ what is not a price
@pytest.mark.parametrize("row", [
    (BID, ASK, BUY, SELL, True),                 # the $100 walk ran out of book
    (BID, ASK, BUY, SELL, False, RECORD),        # the exchange's own record: offers the app cannot take
    (0.0, ASK, BUY, SELL),                       # no bid
    (BID, ASK, float("nan"), SELL),              # a walk that is not a number
    (ASK, BID, BUY, SELL),                       # crossed
    (BID, float("inf"), BUY, SELL),
    (BID, ASK, -0.01, SELL),                     # a walk better than the middle is not a walk
])
def test_a_reading_that_is_not_a_usable_one_of_the_apps_is_not_a_price(row):
    book = _book({T0 + H: row})
    assert book.minutes == 0 and book.at(T0 + H) is None
    pos = _enter(book)
    assert pos["px"] == pytest.approx(LAST * (1 + SLIP)) and pos["real"] is False


def test_an_empty_book_prices_nothing_and_breaks_nothing():
    for book in (sb.Book(None), sb.Book({"t": [], "bid": [], "ask": [], "buy": [], "sell": [],
                                         "exhausted": [], "source": []})):
        assert book.minutes == 0
        assert _enter(book)["real"] is False


# ------------------------------------------------------------------ a reading still on its way
def test_a_reading_on_its_way_raises_and_changes_nothing():
    book = _book({T0 + H: (BID, ASK, BUY, SELL)}, now_ms=T0 + 2 * H + 20_000, wait_ms=600_000)
    pos = _enter(book)
    before, tally = dict(pos), {}
    with pytest.raises(sb.BookNotYet) as e:
        sb.step(pos, _Sig(exit=True), close=50.4, when_ms=T0 + H, bar_ms=H, stop=0.015, fee=FEE, slip=SLIP,
                fine=_minutes(), book=book, tally=tally)
    assert e.value.minute_ms == T0 + 2 * H
    assert pos == before and tally == {}          # nothing moved: the same step can be asked again


def test_after_the_wait_the_fill_is_an_estimate():
    book = _book({T0 + H: (BID, ASK, BUY, SELL)}, now_ms=T0 + 2 * H + 600_000, wait_ms=600_000)
    _, trade = sb.step(_enter(book), _Sig(exit=True), close=50.4, when_ms=T0 + H, bar_ms=H, stop=0.015,
                       fee=FEE, slip=SLIP, book=book)
    assert trade["exit_px"] == pytest.approx(50.4 * (1 - SLIP)) and trade["real"] == 1


def test_a_book_with_no_clock_never_waits():
    assert _book({}).fill(T0 + H, True) is None


# ------------------------------------------------------------------ the walk, the lines, the read
def _frame(closes):
    idx = pd.DatetimeIndex(pd.to_datetime([T0 + k * H for k in range(len(closes))], unit="ms"))
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1.0}, index=idx)


def test_a_trade_still_open_at_the_end_keeps_its_entrys_mark_and_an_estimated_close():
    book = _book({T0 + H: (99.9, 100.1, 0.001, 0.001), T0 + 3 * H: (99.9, 100.1, 0.001, 0.001)})
    got = sb.walk(_frame([100.0, 100.0, 100.0]), [_Sig(entry=True), _Sig(), _Sig()], stop=0.015, fee=FEE,
                  slip=SLIP, bar_ms=H, book=book)
    assert [t["why"] for t in got] == ["END"]
    assert got[0]["real"] == 1 and got[0]["exit_px"] == pytest.approx(100.0 * (1 - SLIP))


def test_walk_with_a_book_that_holds_nothing_is_the_walk_of_before_plus_the_mark():
    df = _frame([100.0, 101.0, 99.0, 102.0, 100.0])
    sigs = [_Sig(entry=True), _Sig(), _Sig(exit=True), _Sig(entry=True, direction="short"), _Sig()]
    kw = dict(stop=0.015, fee=FEE, slip=SLIP, bar_ms=H)
    plain = sb.walk(df, sigs, **kw)
    marked = sb.walk(df, sigs, book=sb.Book(None), **kw)
    assert [{k: v for k, v in t.items() if k != "real"} for t in marked] == plain
    assert [t["real"] for t in marked] == [0] * len(plain) and len(plain) == 2


def test_measure_writes_seven_items_with_a_book_and_the_old_shape_without():
    rng = np.random.default_rng(7)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, 600)))
    df = pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close * 1.002, "low": close * 0.998,
                       "close": close, "volume": 500.0},
                      index=pd.DatetimeIndex(pd.to_datetime([T0 + k * H for k in range(600)], unit="ms")))
    name = next(iter(sb.GRID))
    combo = [{"strategy": name, "params": sb.GRID[name][0], "stop": 0.015, "target": None}]
    old = sb.measure(df, combo, fee=FEE, slip=SLIP, bar_ms=H)[0]["trades"]
    new = sb.measure(df, combo, fee=FEE, slip=SLIP, bar_ms=H, book=sb.Book(None))[0]["trades"]
    assert len(old) > 3 and all(len(t) == 5 for t in old)
    assert all(len(t) == 7 and t[5] is None and t[6] == 0 for t in new)
    assert [t[:5] for t in new] == old


def test_daily_line_says_how_many_readings_it_was_priced_from():
    df = _frame([100.0 + (k % 7) for k in range(400)])
    book = _book({T0 + H: (99.9, 100.1, 0.001, 0.001), T0 + 2 * H: (99.9, 100.1, 0.001, 0.001)})
    line = sb.daily_line("AAA", "1h", df, None, fee=FEE, slip=SLIP, funding=None, bar_ms=H, book=book)
    assert line["book"] == {"minutes": 2, "from_s": sb.REAL_FROM_S}
    assert all(len(t) == 7 for p in line["picks"] for t in p["trades"])
    plain = sb.daily_line("AAA", "1h", df, None, fee=FEE, slip=SLIP, funding=None, bar_ms=H)
    assert "book" not in plain


def test_the_record_begins_on_oct_17_2026():
    import calendar

    assert sb.REAL_FROM_S == calendar.timegm((2026, 10, 17, 0, 0, 0))


def test_read_book_never_reads_before_the_record_began(monkeypatch):
    asked = []

    def reader(sym, a, b):
        asked.append((sym, a, b))
        return None

    day = 86_400
    sb.read_book("AAA_USDT", sb.REAL_FROM_S - 90 * day, sb.REAL_FROM_S + 5 * day, reader=reader)
    assert asked == [("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 5 * day)]
    asked.clear()
    assert sb.read_book("AAA_USDT", sb.REAL_FROM_S - 9 * day, sb.REAL_FROM_S, reader=reader).minutes == 0
    assert asked == []                             # nothing was recorded before it: nothing is asked


def test_read_book_is_empty_and_never_waits_while_the_apps_books_are_switched_out(monkeypatch):
    from tradingagents import app_books

    monkeypatch.setattr(app_books, "IN_BACKTEST", False)
    book = sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 86_400, now_ms=(sb.REAL_FROM_S + 86_400) * 1000,
                        wait_ms=600_000, reader=lambda *a: pytest.fail("read while switched out"))
    assert book.minutes == 0
    assert book.fill((sb.REAL_FROM_S + 86_400) * 1000, True) is None      # an estimate at once, no wait


def test_read_book_asks_the_recorder_for_published_days_by_default(monkeypatch):
    from tradingagents import app_books

    seen = {}

    def book_for(sym, a, b, *, published_only=True):
        seen.update(sym=sym, published_only=published_only)
        return None

    monkeypatch.setattr(app_books, "book_for", book_for)
    sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 86_400)
    assert seen == {"sym": "AAA_USDT", "published_only": True}
    sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 86_400, published_only=False)
    assert seen["published_only"] is False


# ------------------------------------------------------------------ a machine that cannot read them (final review)
def _machine(monkeypatch, answers):
    """A GitHub machine: no recorder folder, every download answered by `answers(url)`."""
    from tradingagents import app_books as ab, cost_store as cs

    assert not ab.HOME.exists()
    for name in ("_REMOTE", "_REMOTE_DAYS", "_BUNDLES", "_UNREAD"):
        monkeypatch.setattr(ab, name, {})
    asked = []

    def fetch(u):
        asked.append(u)
        return answers(u)

    monkeypatch.setattr(cs, "_fetch", fetch)
    return ab, cs, asked


def _day_file(cs, day_s):
    return cs.to_bytes({"t": np.array([day_s + 60], dtype="int64"), "bid": np.array([99.9]), "ask": np.array([100.1]),
                        "spread": np.array([0.002], dtype="float32"), "buy": np.array([0.001], dtype="float32"),
                        "sell": np.array([0.001], dtype="float32"), "exhausted": np.array([False]),
                        "source": np.array([3], dtype="int8")})


def test_a_machine_that_cannot_read_the_published_list_fails_the_coin_instead_of_estimating(monkeypatch):
    """NEVER HAPPENED YET (found by the final review): a machine whose downloads all fail read 0 readings
    and raised nothing, so its coins would have been priced by the usual gap all night with nothing
    saying so. The nightly run reads strictly: the coin FAILS (and is redone alone)."""
    ab, _cs, asked = _machine(monkeypatch, lambda u: (0, b""))
    with pytest.raises(RuntimeError, match="recorded order books could not be read") as e:
        sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 2 * 86_400, strict=True)
    assert "list of published days" in str(e.value) and asked
    # not strict (a caller that only wants what there is): empty, as before
    assert sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 2 * 86_400).minutes == 0


def test_a_coin_day_that_cannot_be_downloaded_fails_the_coin_and_is_asked_again(monkeypatch):
    import json

    state = {"up": False}

    def answers(u):
        if u.endswith("days.json"):
            return 200, json.dumps({"days": ["20261017"], "partial": {}}).encode()
        return (200, _day_file(cs, sb.REAL_FROM_S)) if state["up"] else (503, b"")

    ab, cs, asked = _machine(monkeypatch, answers)
    with pytest.raises(RuntimeError, match="could not be downloaded") as e:
        sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 3600, strict=True)
    assert "Oct 16, 2026" in str(e.value) or "Oct 17, 2026" in str(e.value), "the day, in the one date format"
    assert "20261017" not in str(e.value)
    state["up"] = True                              # the coin is redone: the file is asked for again
    book = sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 3600, strict=True)
    assert book.minutes == 1 and book.at((sb.REAL_FROM_S + 60) * 1000) is not None
    assert ab.unread("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 3600) == []


def test_a_coin_day_that_was_never_recorded_is_not_a_failure(monkeypatch):
    import json

    def answers(u):
        if u.endswith("days.json"):
            return 200, json.dumps({"days": ["20261017"], "partial": {}}).encode()
        return 404, b""

    _machine(monkeypatch, answers)
    assert sb.read_book("NEW_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 3600, strict=True).minutes == 0


def test_an_hourly_bundle_that_cannot_be_downloaded_fails_the_coin(monkeypatch):
    import json

    def answers(u):
        if u.endswith("days.json"):
            return 200, json.dumps({"days": [], "partial": {"20261017": {"asset": "partial-20261017-05.npz",
                                                                        "through": 0}}}).encode()
        return 0, b""

    _machine(monkeypatch, answers)
    with pytest.raises(RuntimeError, match="could not be downloaded"):
        sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 3600, strict=True)


def test_on_the_recorders_own_pc_nothing_is_unread(monkeypatch):
    from tradingagents import app_books as ab

    ab.HOME.mkdir(parents=True)
    monkeypatch.setattr(ab, "_REMOTE_DAYS", {})
    assert ab.unread("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 86_400) == []
    assert sb.read_book("AAA_USDT", sb.REAL_FROM_S, sb.REAL_FROM_S + 86_400, strict=True).minutes == 0
