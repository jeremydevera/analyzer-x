"""Every candle the cost check refuses is COUNTED; only the log LINE is
rate-limited (docs/RCA.md RCA-2026-10-02-C).

The `gate_blocked` row used to sit inside the hourly log limit, so a 15-minute
strategy refused for a whole hour left one row for four candles. On Sep 30,
2026 at 9:00pm #4FC03172's FASTSTOCK prank_15m sells were refused — round trip
3.71% against a 2% target, the night-time gap between buy and sell — with no
row at all, and 6,254 of the room's 6,612 missed backtest trades that night
read as "no practice trade and no refusal".

ONE TIMELINE: the candles, the cost check's 5-minute memory, the hourly log
limit and the rows' stamps all run on one fake clock, the one a running runner
sees, moved forward candle by candle. Driven through `process_symbol`, the
path the runner takes; the counts live in the slot's saved state, so a
restart (on Windows always an instant kill) is a JSON round trip of it.
"""
import json
import logging
import time

import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import feedcheck, portfolio_replay

KEY, SYM = "fade15_15m", "WIDE_USDT"
SETTINGS = {"strategies": [KEY], "strategy_coins": {KEY: [SYM]},
            "strategy_margins": {KEY: 5.0}}
T0 = 1790812800          # Sep 30, 2026 8:00pm New York, on a 15-minute line (and a 4-hour one)
STEP = {"Min15": 900, "Min30": 1800, "Min60": 3600, "Hour4": 14400, "Day1": 86400}


class Clock:
    def __init__(self, t):
        self.t = float(t)

    def __call__(self):
        return self.t


class FX:
    """Flat candles of the asked size up to the clock (the forming one
    included, as MEXC sends it), and a book that is wide (refused) or tight
    (let through)."""

    def __init__(self, clock):
        self.clock, self.wide = clock, True

    def klines(self, symbol, interval, n):
        step = STEP.get(interval, 900)
        last = int(self.clock()) // step * step
        opens = [last - step * i for i in range(n)][::-1]
        return pd.DataFrame({"Date": pd.to_datetime(opens, unit="s"), "Open": 50.0,
                             "High": 50.0, "Low": 50.0, "Close": 50.0, "Volume": 10.0})

    def open_positions(self, symbol=None):
        return []

    def contract_spec(self, symbol):
        return {"priceScale": 4, "contractSize": 1, "volUnit": 1, "minVol": 1,
                "maxVol": 25000, "maintenanceMarginRate": 0.005}

    def last_price(self, symbol):
        return 50.0

    def funding_now(self, symbol):
        # read, so a 4-hour hold is refused for the gap, never for an unknown rate
        return {"per_day": 0.0003, "cycle_h": 8}

    def book_cost(self, symbol, notional_usd=200.0):
        # 3.5% gap at night, like FASTSTOCK's 3.512% at Sep 30, 2026 9:00pm
        return ({"spread": 0.035, "slippage": 0.001, "book_exhausted": False} if self.wide
                else {"spread": 0.0002, "slippage": 0.0002, "book_exhausted": False})


class Runner:
    def __init__(self, tmp_path, monkeypatch):
        self.clock = Clock(T0 + 10)
        monkeypatch.setattr(time, "time", self.clock)
        monkeypatch.setattr(at, "LEDGER_PATH", tmp_path / "ledger.jsonl")
        for name in ("_GATE_CACHE", "_GATE_LOGGED", "_BAR_CACHE", "_FUNDING_CACHE"):
            monkeypatch.setattr(at, name, {}, raising=False)
        self.path = tmp_path / "ledger.jsonl"
        self.fx, self.state = FX(self.clock), {}

    def cycle(self, t, settings=SETTINGS):
        self.clock.t = float(t)
        at.process_symbol(SYM, settings, self.state, fx=self.fx, dry=True)

    def restart(self):
        """An instant kill and a fresh start: only what was SAVED survives."""
        self.state = json.loads(json.dumps(self.state))
        at._GATE_LOGGED.clear()
        at._GATE_CACHE.clear()
        at._BAR_CACHE.clear()

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text(encoding="utf-8").splitlines()]

    def refusals(self):
        return [r for r in self.rows() if r.get("action") == "gate_blocked"]


@pytest.fixture
def runner(tmp_path, monkeypatch):
    return Runner(tmp_path, monkeypatch)


def test_every_refused_candle_lands_in_exactly_one_row(runner, caplog):
    caplog.set_level(logging.ERROR, logger=at.logger.name)
    runner.cycle(T0 + 10)            # 8:00:10pm: the 7:45pm candle — refused, the hour's row
    runner.cycle(T0 + 910)           # 8:15pm: the 8:00 candle — refused, no row of its own
    runner.cycle(T0 + 970)           # the same candle a minute later: never counted twice
    runner.cycle(T0 + 1810)          # 8:30pm: the 8:15 candle
    runner.cycle(T0 + 2710)          # 8:45pm: the 8:30 candle
    runner.cycle(T0 + 3620)          # 9:00:20pm: the 8:45 candle — an hour on: the next row
    runner.cycle(T0 + 4510)          # 9:15pm: the 9:00 candle — refused
    runner.fx.wide = False
    runner.cycle(T0 + 5410)          # 9:30pm: let through — nothing written for that, the
    runner.cycle(T0 + 5470)          # 9:00 candle waits (a coin at the line would otherwise
    #                                  write a row nearly every candle)
    assert [r.get("candles") for r in runner.refusals()] == [1, 4]
    at._flush_stale_refusals(runner.state, T0 + 3600 + 2 * 3600 - 1)   # not two hours yet
    at._flush_stale_refusals(runner.state, T0 + 3600 + 2 * 3600 + 1)   # the 9:00 candle, written
    got = runner.refusals()
    assert [r.get("candles") for r in got] == [1, 4, 1], got
    refused = [b for r in got for b in r.get("bars", [])]
    want = [T0 - 900 + 900 * i for i in range(6)]          # 7:45pm .. 9:00pm, six candles
    assert sorted(refused) == want and len(set(refused)) == len(refused), \
        "every refused candle in exactly one row"
    assert got[2]["late"] is True and not portfolio_replay._GATE_RE.search(got[2]["why"]), \
        "a late row carries no cost figure for the account replay to misplace"
    assert "round-trip cost" in got[2]["refused_why"]
    # the LINE stays one an hour, and says how many it stands for
    lines = [r.getMessage() for r in caplog.records if "LIQUIDITY GATE" in r.getMessage()]
    assert len(lines) == 2 and "(3 earlier candle(s) refused since the last line" in lines[1]


def test_the_count_survives_a_restart(runner):
    """A runner stop on Windows is an instant kill: a count kept in memory
    would die with it. It lives in the slot's saved state instead."""
    runner.cycle(T0 + 10)            # row: the 7:45pm candle
    runner.cycle(T0 + 910)           # the 8:00 candle, counted, waiting
    runner.cycle(T0 + 1810)          # the 8:15 candle, counted, waiting
    runner.restart()                 # killed, and started again from the saved state
    runner.cycle(T0 + 1870)          # the first refusal after a start is written at once
    got = runner.refusals()
    assert [r.get("candles") for r in got] == [1, 2], got
    assert got[1]["bars"] == [T0, T0 + 900], "the two waiting candles, not three (8:15 once)"


def test_a_candle_refused_only_for_an_unreadable_book_is_taken_back(runner):
    """An unreadable book leaves the candle UNSEEN, so the next cycle tries it
    again; when that try lets it through, it was never refused in the end."""
    runner.cycle(T0 + 10)                         # the 7:45pm candle: refused, the hour's row
    runner.fx.book_cost = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("510 too frequent"))
    runner.cycle(T0 + 910)                        # the 8:00 candle: the book cannot be read
    del runner.fx.book_cost                       # back to the class's book
    runner.fx.wide = False
    runner.cycle(T0 + 1210)                       # the same 8:00 candle, now let through
    at._flush_stale_refusals(runner.state, T0 + 900 + 3 * 3600)
    assert [r.get("candles") for r in runner.refusals()] == [1]


def test_a_switched_off_strategy_loses_no_count_and_old_entries_go(runner):
    runner.cycle(T0 + 10)                         # row: the 7:45pm candle
    runner.cycle(T0 + 910)                        # the 8:00pm candle, waiting
    at._flush_stale_refusals(runner.state, T0 + 900 + 3600)        # an hour on: still waiting
    assert len(runner.refusals()) == 1
    changed = at._flush_stale_refusals(runner.state, T0 + 900 + 2 * 3600 + 1)
    late = [r for r in runner.rows() if r.get("late")]
    assert len(late) == 1 and late[0]["candles"] == 1 and "since its last refusal row" in late[0]["why"]
    assert changed, "the slot it cleared is saved"
    at._flush_stale_refusals(runner.state, T0 + 900 + 2 * 3600 + 2)    # nothing written twice
    assert len([r for r in runner.rows() if r.get("late")]) == 1
    at._flush_stale_refusals(runner.state, T0 + 900 + at.REFUSED_STATE_KEEP_S + 1)
    assert not any("gate_pending" in st for st in runner.state.values() if isinstance(st, dict)), \
        "a day-old entry with nothing waiting is forgotten"
    # on the runner's own path every cycle, before the save
    import inspect

    src = inspect.getsource(at.run_cycle)
    assert src.index("_flush_stale_refusals(state, time.time())") < src.index("save_state(state, keys=touched)")


def test_a_4h_candle_refused_all_evening_is_one_refusal(runner, monkeypatch):
    """A 4-hour candle stays the newest for four hours, so three hourly rows
    in four repeat a candle an earlier row counted. A repeat says 0 — with no
    count at all it read as a row from before the counts, which stands for
    one (Oct 02, 2026: 27 such rows by 3:45pm, every one a 4h strategy)."""
    key = "ibs_4h_sl03tp04"
    four = {"strategies": [key], "strategy_coins": {key: [SYM]}, "strategy_margins": {key: 5.0}}
    for h in range(5):               # 8:00pm .. midnight, a cycle an hour
        runner.cycle(T0 + 10 + 3600 * h, four)
    got = runner.refusals()
    # 8:00pm: the 4pm-8pm candle; 9, 10, 11pm: the same candle again; midnight: 8pm-12am
    assert [r.get("candles") for r in got] == [1, 0, 0, 0, 1], got
    assert [b for r in got for b in r["bars"]] == [T0 - 14400, T0]
    monkeypatch.setattr(feedcheck, "load_rows", runner.rows)
    monkeypatch.setattr(feedcheck, "window_since_last_run", lambda r, now=None: 0.0)
    assert feedcheck.report(now=T0 + 5 * 3600)["refused_total"] == 2, "two candles, five rows"


def test_the_feed_check_counts_candles_not_rows(runner, monkeypatch):
    for t in (T0 + 10, T0 + 910, T0 + 1810, T0 + 2710, T0 + 3620):
        runner.cycle(t)
    monkeypatch.setattr(feedcheck, "load_rows", runner.rows)
    monkeypatch.setattr(feedcheck, "window_since_last_run", lambda r, now=None: 0.0)
    got = feedcheck.report(now=T0 + 3700)
    assert got["refused_total"] == 5, got["refused"]       # five candles, two rows


def test_backtest_a_room_reads_the_counted_candles(runner, monkeypatch):
    """The runner's own rows, read by Forecast -> Backtest a room: a backtest
    trade whose signal candle the cost check counted is "fees too high" for
    certain, and a `late` row's own time — two hours after its candles — is
    never taken for a refusal of the trade entering then."""
    runner.cycle(T0 + 10)            # row: the 7:45pm candle
    runner.cycle(T0 + 910)           # the 8:00 candle, waiting
    runner.cycle(T0 + 1810)          # the 8:15 candle, waiting
    runner.fx.wide = False
    runner.cycle(T0 + 2710)          # let through from 8:30pm on
    late_at = T0 + 900 + 2 * 3600 + 1
    runner.clock.t = late_at         # 10:15:01pm: the waiting two, in a late row
    at._flush_stale_refusals(runner.state, late_at)
    assert [r.get("late", False) for r in runner.refusals()] == [False, True]
    entries = [T0, T0 + 900, T0 + 1800, late_at // 900 * 900]   # signal candle + one bar
    d = _backtest_the_room(monkeypatch, runner.path, entries)
    got = {k: v for k, v in d["reasons"].items() if v}
    assert got == {"gate_blocked": 3, "none": 1}, got


def test_backtest_a_room_answers_for_a_room_with_no_trade_record_yet(tmp_path, monkeypatch):
    """A room deployed a minute ago has no trade record file until its runner
    writes its first line. The page read that as ONE empty answer where it
    unpacked two, so it would have shown "not enough values to unpack
    (expected 2, got 0)" instead of the room's backtest (NEVER HAPPENED YET:
    every room shown on Oct 02, 2026 had a trade record; RCA-2026-10-02-C)."""
    d = _backtest_the_room(monkeypatch, tmp_path / "not-written-yet.jsonl", [T0])
    assert d["backtest"]["trades"] == 1 and d["practice"]["trades"] == 0
    assert {k: v for k, v in d["reasons"].items() if v} == {"none": 1}


def _backtest_the_room(monkeypatch, ledger, entries):
    """Forecast -> Backtest a room over one strategy on one coin, its trade
    record at `ledger`, its backtest trades entering at `entries`."""
    from tradingagents import local_history as lh, rolling30 as r30, room_backtest as rb

    slot = f"{KEY}|{SYM}"
    ms = lambda s: int(s * 1000)     # noqa: E731
    rec = {"slot": slot, "bar_s": 900, "end_ms": ms(T0 + 43200),
           "trades": [[ms(e), ms(e + 900), 0.3] for e in entries]}
    settings = {"strategies": [KEY], "strategy_coins": {KEY: [SYM]},
                "watcher_slots": {slot: {"on_at": T0 - 3600}}}
    monkeypatch.setattr(rb.profiles, "shown", lambda: ["main", "TESTROOM"])
    monkeypatch.setattr(rb.profiles, "valid", lambda pid: True)
    monkeypatch.setattr(rb.profiles, "get", lambda pid: {"id": pid, "name": pid})
    monkeypatch.setattr(at, "load_settings", lambda: settings)
    monkeypatch.setattr(at, "_pp", lambda p: ledger if p == at.LEDGER_PATH else p)
    monkeypatch.setattr(lh, "deployed_at", lambda: {})
    monkeypatch.setattr(r30, "_load", lambda s: rec if s == slot else None)
    rb._LEDGER.clear()
    try:
        return rb.compare("TESTROOM", T0 - 3600, T0 + 43200)
    finally:
        rb._LEDGER.clear()
