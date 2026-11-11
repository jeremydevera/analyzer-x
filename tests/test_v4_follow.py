"""THE SKILL ROOMS' FOLLOWER (Nov 10, 2026; docs/superpowers/specs/2026-11-10-skill-rooms-design.md,
"3. The follower" and "4. The daily refresh").

The three practice rooms #D7EN8BNV, #RSS7CUKH and #7T3VJU82 trade Backtest v4's Claude-skill
strategies EXACTLY as their backtest did: `tradingagents/v4_follow.py` replays every closed candle
with the backtest's own engine (`skill_bt.step`) and writes the room's trade record and open
positions in the practice runner's shapes. It places no order.

ONE TIMELINE. Every candle, every day list, every funding settlement and every pass clock below is
built from ONE clock, T0 = Nov 01, 2026 12:00am UTC: 1h candle k opens at T0 + k hours, day n's
list is named by T0 + (n - 1) days, and a pass at `now` sees exactly the candles that CLOSED by
`now` - the fake exchange cuts its frames at the pass's own clock, the way the real one serves
closed candles only. Do not "simplify" a fixture onto two clocks: a candle clock and a position
clock that disagree is how RCA-2026-09-12-A passed its tests.

Everything is written under tmp_path: the room files through conftest's sandbox, the day lists and
the follow lock under a Backtest v4 home moved into tmp_path. Nothing reaches the exchange: candles,
funding and the contract list are injected.
"""
from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import tradingagents.auto_trader as at
from tradingagents import profiles, stores
from tradingagents import skill_bt as sb
from tradingagents import v4_follow as vf
from tradingagents.skill_frames import BARS

pytestmark = pytest.mark.unit

T0 = int(dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp())    # day 1's midnight, seconds
H = 3600
DAY = 86400
H_MS = H * 1000
D1, D2, D3, D4 = T0, T0 + DAY, T0 + 2 * DAY, T0 + 3 * DAY
ROOM = "D7EN8BNV"


class Market:
    """The exchange, on the one timeline: frames cut at the pass's clock (`now_ms`), funding every
    8 hours, the contract list with each contract's size, and switches that make one coin's
    candles or funding - or the whole contract list - unreadable."""

    def __init__(self):
        self.frames: dict = {}
        self.now_ms = 0
        self.calls: list = []
        self.fail: dict = {}          # sym -> how many candle reads fail (-1: every one)
        self.fund_fail: dict = {}     # sym -> how many funding reads fail (-1: every one)
        self.listed_fail = False      # the contract list cannot be read (the network is down)
        self.coins: set | None = None
        self.sizes: dict = {}         # sym -> contract size (1.0 when not set)
        self.fund_calls: list = []    # (sym, since_ms, fresh_after_s, the pass's clock in ms)
        self.minute_rows: dict = {}   # sym -> [(open_ms, high, low)]: the minutes, when a test wants them
        self.minute_calls: list = []
        self.fund_cache_s = 0         # > 0: the adapter's own copy, kept this long (gate: 1800 s)
        self._fund_copy: dict = {}

    def add(self, sym: str, closes, first_ms: int, tf: str = "1h") -> None:
        bar = H_MS if tf == "1h" else int({"15m": 900, "30m": 1800, "4h": 14400, "1d": 86400}[tf] * 1000)
        c = np.asarray(closes, dtype=float)
        idx = pd.to_datetime(np.arange(len(c), dtype=np.int64) * bar + first_ms, unit="ms")
        self.frames[(sym, tf)] = pd.DataFrame({"open": c, "high": c, "low": c, "close": c,
                                               "volume": 1.0}, index=idx)

    def fetch(self, sym, tf, bars=None, end_ms=None):
        self.calls.append((sym, tf, bars, end_ms))
        n = self.fail.get(sym, 0)
        if n:
            if n > 0:
                self.fail[sym] = n - 1
            raise ConnectionError(f"{sym} cut")
        df = self.frames[(sym, tf)]
        ms = df.index.as_unit("ms").asi8
        bar = int(ms[1] - ms[0])
        keep = ms + bar <= self.now_ms
        if end_ms is not None:
            keep &= ms < int(end_ms)
        return df[keep].tail(BARS[tf] if bars is None else int(bars))

    def funding(self, sym, since_ms=None, fresh_after_s=None):
        """Settlements every 8 hours. With `fund_cache_s` it behaves as the real adapter does: only
        what was SETTLED by the read is in it, and a read is kept that long - answered again while
        it is fresh enough (made at or after `fresh_after_s`, the pass's own clock)."""
        self.fund_calls.append((sym, since_ms, fresh_after_s, self.now_ms))
        n = self.fund_fail.get(sym, 0)
        if n:
            if n > 0:
                self.fund_fail[sym] = n - 1
            raise ConnectionError(f"{sym} funding cut")
        every = [{"settle_ms": T0 * 1000 + k * 8 * H_MS, "rate": 0.0001 * (1 if k % 3 else -2)}
                 for k in range(-200, 30)]
        if not self.fund_cache_s:
            return every
        now_s = self.now_ms / 1000
        hit = self._fund_copy.get(sym)
        if hit and now_s - hit[0] < self.fund_cache_s and (fresh_after_s is None or hit[0] >= fresh_after_s):
            return list(hit[1])
        rows = [r for r in every if r["settle_ms"] <= self.now_ms]
        self._fund_copy[sym] = (now_s, rows)
        return list(rows)

    def minutes(self, sym, start_s, end_s):
        """The minutes under every candle: NONE by default - the exchange keeps no minutes for the
        coin - so every candle is settled by its close, the rule these tests were written on. A test
        of the minute rule sets `minute_rows`: {sym: [(open_ms, high, low), ...]}."""
        self.minute_calls.append((sym, start_s, end_s))
        rows = self.minute_rows.get(sym) or []
        rows = [r for r in rows if start_s * 1000 <= r[0] and r[0] + 60_000 <= end_s * 1000]
        return pd.DataFrame({"Date": pd.to_datetime([r[0] for r in rows], unit="ms"),
                             "High": [r[1] for r in rows], "Low": [r[2] for r in rows],
                             "Seconds": [60] * len(rows)})

    def listed(self):
        """{symbol: contract size}, the shape `fx.list_contracts()` gives the follower."""
        if self.listed_fail:
            raise ConnectionError("the contract list is unreachable")
        syms = set(self.coins) if self.coins is not None else {s for s, _ in self.frames}
        return {s: self.sizes.get(s, 1.0) for s in syms}


def scripted(rises, before: int = 48, after: int = 4 * 24) -> list[float]:
    """Closes for candles k = -before .. after-1 (k = hours from T0): rising 0.1 a candle inside
    each [a, b) of `rises`, flat elsewhere. With bf_momentum lookback 2 (long while a close beats
    the one before), that is ONE long trade per interval: entered on candle a's close, closed on
    candle b's (`why` SIGNAL) - unless its stop is reached first."""
    out, c = [], 100.0
    for k in range(-before, after):
        if any(a <= k < b for a, b in rises):
            c += 0.1
        out.append(c)
    return out


def row(sid: str, coin: str = "AAA", strategy: str = "bf_momentum", params=None, stop: float = 0.03,
        target=None, fee: float = 0.00075, slip: float = 0.0005, tf: str = "1h") -> dict:
    """One strategy as `forecast_v4.switched_on` hands it over (the day list's row)."""
    return {"sid": 1, "id": sid, "coin": coin, "tf": tf, "strategy": strategy, "label": f"{strategy} test",
            "skill": "backtesting-frameworks", "params": params or {"lookback": 2}, "stop": stop,
            "target": target, "fee": fee, "slip": slip, "n": 25, "wins": 24}


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "v4"
    monkeypatch.setattr(stores, "V4", stores.Store(**{**stores.V4.__dict__, "home": home,
                                                      "rows_db": home / "rows.db"}))
    lists = home / "rooms"
    lists.mkdir(parents=True)
    m = Market()

    def run(now_s, **kw):
        m.now_ms = int(now_s * 1000)
        return vf.pass_once(now_s, fetch=m.fetch, funding_of=m.funding, listed=m.listed, lists_dir=lists, minutes=m.minutes, **kw)

    def put(day_s, rooms):
        vf.list_path(day_s, lists).write_text(json.dumps({"day_s": day_s, "made_s": day_s + 300,
                                                          "fallback_from": None, "rooms": rooms}),
                                              encoding="utf-8")

    return SimpleNamespace(m=m, lists=lists, run=run, put=put, home=home)


def ledger(pid: str = ROOM) -> list[dict]:
    with profiles.using(pid):
        return at.ledger_trades(0)


def trades(pid: str = ROOM) -> list[tuple]:
    """(entry candle ms, exit candle ms or None, side, why, pnl) per trade id, in entry order."""
    by: dict = {}
    for r in ledger(pid):
        by.setdefault(r["trade_id"], {})[r["action"]] = r
    out = []
    for tid, p in by.items():
        e, x = p.get("enter"), p.get("exit")
        assert e is not None, f"an exit with no entry: {tid}"
        side = 1 if e["side"] == "LONG" else -1
        out.append((e["entry_ts"] * 1000, None if x is None else x["ts"] * 1000 - H_MS, side,
                    None if x is None else x["why"], None if x is None else round(x["pnl_est"], 4)))
    return sorted(out)


def open_slots(pid: str = ROOM) -> dict:
    with profiles.using(pid):
        st = at.load_state()
    return {k: v["position"] for k, v in st.items()
            if k != "_rev" and isinstance(v, dict) and v.get("position")}


def follow_state(pid: str = ROOM) -> dict:
    with profiles.using(pid):
        return vf.load()


# ------------------------------------------------------------------ the engine's own trades
@pytest.mark.parametrize("strategy,params,stop,target", [
    ("bf_momentum", {"lookback": 10}, 0.015, None),                              # signals_all path
    ("sma_crossover", {"fast_period": 3, "slow_period": 8}, 0.015, 0.01),        # a target
    ("rsi_reversal", {"period": 7, "overbought": 70, "oversold": 30}, 0.02, None),  # shorts, flips
])
def test_follower_trades_equal_the_engines_walk(world, strategy, params, stop, target):
    rng = np.random.default_rng(11)        # every case: a carried trade, and SL plus SIGNAL or TP
    before, after = 400, 3 * 24 + 6
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, before + after)))
    world.m.add("AAA_USDT", closes, (T0 - before * H) * 1000)
    r = row("TESTAAA1", strategy=strategy, params=params, stop=stop, target=target)
    for d in (D1, D2, D3):
        world.put(d, {ROOM: [r]})
    now = T0 + 20
    while now < D4:                     # a pass every 7 hours, across both midnights
        world.run(now)
        now += 7 * H
    world.run(D4 + 20)

    # THE BACKTEST: run() over the same frame - from the warm-up's first candle to the last closed one
    world.m.now_ms = (D4 + 20) * 1000
    warm = world.m.fetch("AAA_USDT", "1h", end_ms=T0 * 1000)
    full = world.m.fetch("AAA_USDT", "1h", bars=10 ** 6)
    ref = full[full.index >= warm.index[0]]
    done, still = sb.run(ref, sb.signals(ref, strategy, params), stop=stop, fee=r["fee"], slip=r["slip"],
                         target=target, funding=sb.Funding(world.m.funding("AAA_USDT")), bar_ms=H_MS)
    want = [(t["entry_ms"], t["exit_ms"], t["side"], t["why"], round(t["pnl"], 4))
            for t in done if t["entry_ms"] >= T0 * 1000]
    if still is not None and still["t"] >= T0 * 1000:
        want.append((still["t"], None, 1 if still["dir"] == "long" else -1, None, None))
    carried = [t for t in done if t["entry_ms"] < T0 * 1000 <= t["exit_ms"]]
    got = trades()
    assert len(want) >= 5 and len(carried) == 1, (want, carried)
    assert got == sorted(want), "the room's trades are the engine's walk, candle for candle"
    assert all(t[0] >= T0 * 1000 for t in got), f"the warm-up's carried trade is never written: {carried}"


# ------------------------------------------------------------------ the day lists
def test_holds_at_midnight_until_the_list_lands(world):
    world.m.add("AAA_USDT", scripted([(5, 8), (25, 27)]), (T0 - 48 * H) * 1000)
    r = row("TESTAAA1")
    world.put(D1, {ROOM: [r]})
    world.run(T0 + 20)
    world.run(T0 + 12 * H)
    res = world.run(D2 + 5 * H)
    assert res[ROOM]["held_at"] == D2
    st = follow_state()
    assert st["held_at"] == D2
    assert st["strats"]["TESTAAA1"]["last_ms"] == (D2 - H) * 1000, "day 1's last candle, and no further"
    assert trades() == [((T0 + 5 * H) * 1000, (T0 + 8 * H) * 1000, 1, "SIGNAL", trades()[0][4])]
    assert all(e["ts"] <= D2 for e in ledger()), "nothing from a day whose list has not landed"
    st_status = vf.status(ROOM, now_s=D2 + 5 * H, lists_dir=world.lists)
    assert st_status["held_at"] == D2 and "waiting" in st_status["why"]

    world.put(D2, {ROOM: [r]})                     # the list lands late
    res = world.run(D2 + 5 * H + 15 * 60)
    assert res[ROOM]["held_at"] is None
    got = trades()
    assert [t[:4] for t in got] == [((T0 + 5 * H) * 1000, (T0 + 8 * H) * 1000, 1, "SIGNAL"),
                                    ((T0 + 25 * H) * 1000, (T0 + 27 * H) * 1000, 1, "SIGNAL")]
    assert follow_state()["filled_in"] == 1, "the one trade since midnight was filled in"
    assert vf.status(ROOM, now_s=D2 + 5 * H + 15 * 60, lists_dir=world.lists)["filled_in"] == 1
    exit_row = [e for e in ledger() if e["action"] == "exit"][-1]
    assert exit_row["ts"] == T0 + 28 * H, "a late trade keeps its candle's time"
    assert exit_row["written_at"] == D2 + 5 * H + 15 * 60


def test_carried_trade_is_never_written(world):
    world.m.add("AAA_USDT", scripted([(-3, 2), (4, 6)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    s = follow_state()["strats"]["TESTAAA1"]
    assert s["carried"] is True and s["pos"]["t"] == (T0 - 3 * H) * 1000, "the warm-up left it open"
    assert open_slots() == {} and ledger() == [], "a carried trade has no slot and no row"
    world.run(T0 + 3 * H)                          # it closes on candle 2: silently
    assert follow_state()["strats"]["TESTAAA1"]["pos"] is None
    assert ledger() == [] and open_slots() == {}
    world.run(T0 + 8 * H)
    assert [t[:4] for t in trades()] == [((T0 + 4 * H) * 1000, (T0 + 6 * H) * 1000, 1, "SIGNAL")]


def test_switched_off_strategy_finishes_its_trade(world):
    world.m.add("AAA_USDT", scripted([(22, 27), (30, 32)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.put(D2, {ROOM: []})                      # switched off at day 2's midnight
    world.run(T0 + 20)
    world.run(D2 + 20)
    assert list(open_slots()) == ["AAA_USDT#paper#v4_TESTAAA1"], "still holding at midnight"
    world.run(D2 + 12 * H)
    assert [t[:4] for t in trades()] == [((T0 + 22 * H) * 1000, (T0 + 27 * H) * 1000, 1, "SIGNAL")], \
        "the open trade exits by its own rule; the 6:00am signal of day 2 is not taken"
    assert open_slots() == {}


def test_a_strategy_on_two_days_lists_is_followed_once(world):
    world.m.add("AAA_USDT", scripted([(22, 27)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.put(D2, {ROOM: [row("TESTAAA1")]})
    now = T0 + 20
    while now <= D2 + 12 * H:
        world.run(now)
        now += 3 * H
    assert [t[:4] for t in trades()] == [((T0 + 22 * H) * 1000, (T0 + 27 * H) * 1000, 1, "SIGNAL")]
    assert len(ledger()) == 2, "one entry, one exit"
    warms = [c for c in world.m.calls if c[3] is not None]
    assert warms == [("AAA_USDT", "1h", None, T0 * 1000)], "warmed up once, at its first midnight"


def test_catch_up_across_midnight_uses_each_days_list(world):
    world.m.add("AAA_USDT", scripted([(5, 7), (29, 31)]), (T0 - 48 * H) * 1000)
    world.m.add("BBB_USDT", scripted([(5, 7), (29, 31)]), (T0 - 48 * H) * 1000)
    a, b = row("TESTAAA1"), row("TESTBBB1", coin="BBB")
    world.put(D1, {ROOM: [a]})
    world.put(D2, {ROOM: [b]})
    world.run(T0 + 20)
    world.run(D2 + 12 * H)                          # the PC slept through midnight
    by = {}
    for e in ledger():
        by.setdefault(e["strategy"], []).append((e["action"], e["entry_ts"]))
    assert by == {"v4_TESTAAA1": [("enter", T0 + 5 * H), ("exit", T0 + 5 * H)],
                  "v4_TESTBBB1": [("enter", T0 + 29 * H), ("exit", T0 + 29 * H)]}
    assert ("BBB_USDT", "1h", None, D2 * 1000) in world.m.calls, "B warmed up at ITS midnight"


def test_two_strategies_on_one_coin_are_two_trades(world):
    world.m.add("AAA_USDT", scripted([(5, 9)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1", stop=0.03), row("TESTAAA2", stop=0.05)]})
    world.run(T0 + 20)
    world.run(T0 + 7 * H)
    slots = open_slots()
    assert sorted(slots) == ["AAA_USDT#paper#v4_TESTAAA1", "AAA_USDT#paper#v4_TESTAAA2"]
    enters = [e for e in ledger() if e["action"] == "enter"]
    assert len(enters) == 2 and len({e["trade_id"] for e in enters}) == 2
    world.run(T0 + 12 * H)
    assert open_slots() == {} and len([e for e in ledger() if e["action"] == "exit"]) == 2


def test_late_written_exit_counts_on_its_candles_day(world):
    world.m.add("AAA_USDT", scripted([(5, 9)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(D2 + 3 * H)                         # written the next day
    x = [e for e in ledger() if e["action"] == "exit"]
    assert len(x) == 1 and x[0]["ts"] == T0 + 10 * H and x[0]["written_at"] == D2 + 3 * H
    with profiles.using(ROOM):
        that_day = at.pnl_today(now=T0 + 10 * H, dry=True)
        next_day = at.pnl_today(now=T0 + 10 * H + DAY, dry=True)
    assert that_day["trades"] == 1 and that_day["total"] == round(x[0]["pnl_est"], 2)
    assert next_day["trades"] == 0


# ------------------------------------------------------------------ a coin that goes away
def test_a_delisted_coin_closes_its_trade(world):
    world.m.add("AAA_USDT", scripted([(5, 60)]), (T0 - 48 * H) * 1000)
    world.m.add("BBB_USDT", scripted([]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    world.run(T0 + 8 * H)
    assert list(open_slots()) == ["AAA_USDT#paper#v4_TESTAAA1"]
    world.m.coins = {"BBB_USDT"}                   # the exchange no longer trades AAA
    res = world.run(T0 + 10 * H)
    x = [e for e in ledger() if e["action"] == "exit"]
    assert len(x) == 1 and x[0]["why"] == "DELISTED" and x[0]["ts"] == T0 + 10 * H, \
        "closed on the last candle the exchange served"
    assert open_slots() == {}
    assert any("AAA" in e and "delisted" in e for e in res[ROOM]["errors"]), res[ROOM]["errors"]
    assert "TESTAAA1" not in follow_state()["strats"]


def test_failed_candle_reads_never_close_a_trade_only_the_contract_list_does(world):
    """Ruling of the final review (Nov 11, 2026): the record is append-only, and a run of "too many
    requests" answers must never write a false exit - so failed candle reads, however many, are named
    and wait. Only the exchange's own contract list, read successfully, can close a trade DELISTED."""
    world.m.add("CCC_USDT", scripted([(5, 60)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTCCC1", coin="CCC")]})
    world.run(T0 + 20)
    world.run(T0 + 8 * H)
    world.m.fail["CCC_USDT"] = -1
    for k in range(9, 15):                         # six passes in a row, every candle read refused
        res = world.run(T0 + k * H)
        mine = [e for e in res[ROOM]["errors"] if e.startswith("CCC 1h TESTCCC1: ConnectionError")]
        assert mine and "waits" in mine[0] and f"{k - 8} pass" in mine[0], res[ROOM]["errors"]
    assert [e["action"] for e in ledger()] == ["enter"], "no false exit, however many reads failed"
    assert list(open_slots()) == ["CCC_USDT#paper#v4_TESTCCC1"]
    assert follow_state()["strats"]["TESTCCC1"]["last_ms"] == (T0 + 7 * H) * 1000, "state untouched"
    world.m.coins = {"AAA_USDT"}                   # the list, read fine, no longer has CCC
    res = world.run(T0 + 15 * H)
    x = [e for e in ledger() if e["action"] == "exit"]
    assert len(x) == 1 and x[0]["why"] == "DELISTED" and x[0]["ts"] == T0 + 8 * H, \
        "closed at the last candle it read, only once the exchange's list confirmed it"
    assert open_slots() == {}
    assert any("delisted by the exchange" in e for e in res[ROOM]["errors"])


def test_a_funding_read_that_fails_is_not_a_delisting(world):
    """Review, Nov 10, 2026: funding was read in the candles' `try`, so two failed funding reads
    closed every held trade DELISTED - a false exit in an append-only record."""
    world.m.add("AAA_USDT", scripted([(5, 10)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    world.run(T0 + 8 * H)
    world.m.fund_fail["AAA_USDT"] = -1
    for now in (T0 + 9 * H, T0 + 10 * H, T0 + 11 * H):
        res = world.run(now)
        assert any("funding could not be read" in e for e in res[ROOM]["errors"]), res[ROOM]["errors"]
    s = follow_state()["strats"]["TESTAAA1"]
    assert s["last_ms"] == (T0 + 7 * H) * 1000 and s["fails"] == 0, "its candles wait, nothing counted"
    assert list(open_slots()) == ["AAA_USDT#paper#v4_TESTAAA1"]
    assert [e["action"] for e in ledger()] == ["enter"]
    world.m.fund_fail.clear()                      # funding is back: the pass catches up
    world.run(T0 + 12 * H)
    x = [e for e in ledger() if e["action"] == "exit"]
    assert [(e["why"], e["ts"]) for e in x] == [("SIGNAL", T0 + 11 * H)], "at its own candle, by its own rule"
    assert open_slots() == {}


def test_unread_candles_while_the_contract_list_is_unreadable_are_not_counted(world):
    """The network is down: every read fails, which says nothing about one coin."""
    world.m.add("CCC_USDT", scripted([(5, 60)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTCCC1", coin="CCC")]})
    world.run(T0 + 20)
    world.run(T0 + 8 * H)
    world.m.fail["CCC_USDT"] = -1
    world.m.listed_fail = True
    for now in (T0 + 9 * H, T0 + 10 * H, T0 + 11 * H):
        res = world.run(now)
        assert any("contract list could not be read either" in e for e in res[ROOM]["errors"]), \
            res[ROOM]["errors"]
    assert list(open_slots()) == ["CCC_USDT#paper#v4_TESTCCC1"] and len(ledger()) == 1, "no DELISTED"
    world.m.fail.clear()
    world.m.listed_fail = False
    world.run(T0 + 12 * H)
    assert follow_state()["strats"]["TESTCCC1"]["last_ms"] == (T0 + 11 * H) * 1000, "caught up"
    assert len(ledger()) == 1 and list(open_slots()) == ["CCC_USDT#paper#v4_TESTCCC1"]


def _btc(world, size: float) -> dict:
    """BTC at exactly 50,000 when it signals on candle 5, a 10-a-candle rise to candle 8, flat."""
    closes = [49990.0 if k < 5 else 50000.0 + 10 * (min(k, 8) - 5) for k in range(-48, 96)]
    world.m.add("BTC_USDT", closes, (T0 - 48 * H) * 1000)
    world.m.sizes["BTC_USDT"] = size
    world.put(D1, {ROOM: [row("TESTBTC1", coin="BTC", slip=0.0)]})
    world.run(T0 + 20)
    return world.run(T0 + 7 * H)                   # the pass that opens the trade


def test_a_position_is_sized_in_contracts(world):
    """Review, Nov 10, 2026: `vol` was coins while every reader multiplies it by the contract
    size - BTC's 0.0001 put the panel's TP $ / SL $ at about $0."""
    from tradingagents import positions_view as pv

    _btc(world, 0.0001)
    (enter,) = [e for e in ledger() if e["action"] == "enter"]
    pos = open_slots()["BTC_USDT#paper#v4_TESTBTC1"]
    assert enter["entry"] == 50000.0
    assert enter["vol"] == pytest.approx(20.0) and pos["vol"] == pytest.approx(20.0),         "100 / (50,000 x 0.0001) = 20 contracts"
    with profiles.using(ROOM):
        state = at.load_state()
    (r,) = pv.build_rows(state=state, exchange_positions=[], stats={}, dry=True,
                         last_price=lambda s: 50010.0, contract_size=lambda s: 0.0001,
                         taker_fee=lambda s: 0.00075, leverage=20, now=T0 + 7 * H, settings={})
    assert r["notional"] == pytest.approx(100.0), "the panel reads $100 of coin"


def test_an_unknown_contract_size_leaves_the_size_blank_and_says_so(world):
    from tradingagents import positions_view as pv

    res = _btc(world, 0.0)                         # the exchange gave no size
    (enter,) = [e for e in ledger() if e["action"] == "enter"]
    assert enter["vol"] is None and open_slots()["BTC_USDT#paper#v4_TESTBTC1"]["vol"] is None
    assert [e for e in res[ROOM]["errors"] if "no contract size for BTC_USDT" in e] ==         ["BTC 1h TESTBTC1: the exchange gave no contract size for BTC_USDT, so the position's size "
         "(vol) is left blank"]
    with profiles.using(ROOM):
        state = at.load_state()
    rows = pv.build_rows(state=state, exchange_positions=[], stats={}, dry=True,
                         last_price=lambda s: 50010.0, contract_size=lambda s: 0.0001,
                         taker_fee=lambda s: 0.00075, leverage=20, now=T0 + 7 * H, settings={})
    assert len(rows) == 1 and rows[0]["vol"] is None, "the panel reader takes a blank size"


def test_a_failing_read_is_retried_once_in_the_same_pass(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    world.m.fail["AAA_USDT"] = 1                   # the first read fails, the retry works
    res = world.run(T0 + 12 * H)
    assert res[ROOM]["errors"] == [] and len(ledger()) == 2


# ------------------------------------------------------------------ what the screens read
def test_ledger_rows_read_by_every_panel(world, monkeypatch):
    world.m.add("AAA_USDT", scripted([(5, 9)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    world.run(T0 + 7 * H)
    (enter,) = [e for e in ledger() if e["action"] == "enter"]
    pos = open_slots()["AAA_USDT#paper#v4_TESTAAA1"]
    assert at.trade_id_of("AAA_USDT", pos) == enter["trade_id"], "the id the screen computes is the row's"
    assert pos["dry"] is True and pos["margin"] == 5.0 and pos["side"] == 1
    assert enter["margin"] == 5.0 and enter["leverage"] == 20 and enter["dry_run"] is True
    assert enter["ts"] == enter["opened_at"] == T0 + 6 * H and enter["entry_ts"] == T0 + 5 * H
    assert enter["sl"] == pytest.approx(enter["entry"] * 0.97) and enter["tp"] is None
    world.run(T0 + 12 * H)
    rows = ledger()
    x = rows[-1]
    assert x["action"] == "exit" and x["trade_id"] == enter["trade_id"] and "pnl_est" in x
    assert x["pnl_source"] == "v4_engine" and x["held_s"] == x["ts"] - enter["opened_at"]

    from fastapi.testclient import TestClient

    from tradingagents.api import app

    monkeypatch.setattr(profiles, "shown", lambda: ["main", ROOM])
    c = TestClient(app)
    hist = c.get("/api/trade/history?dry=true", headers={"X-TA-Profile": ROOM}).json()["rows"]
    assert [(h["strategy"], h["strategy_id"], h["id"]) for h in hist] == \
        [("v4_TESTAAA1", "TESTAAA1", enter["trade_id"])]
    every = c.get("/api/trade/history/rooms?dry=true").json()["rows"]
    assert [h["strategy"] for h in every] == ["v4_TESTAAA1"]


def test_status_is_a_heartbeat(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 12 * H)
    s = vf.status(ROOM, now_s=T0 + 12 * H + 60, lists_dir=world.lists)
    assert s["last_pass_s"] == T0 + 12 * H and s["why"] is None and s["held_at"] is None
    assert s["last_candle_ms"] == (T0 + 12 * H) * 1000, "the newest candle it read closed at 12:00pm"
    assert [r["id"] for r in s["switched_on"]] == ["TESTAAA1"]
    late = vf.status(ROOM, now_s=T0 + 13 * H, lists_dir=world.lists)
    assert late["why"] and "last pass" in late["why"], "a quiet follower says so"


# ------------------------------------------------------------------ never twice
def test_a_crash_after_writing_never_writes_a_row_twice(world, monkeypatch):
    world.m.add("AAA_USDT", scripted([(5, 9), (12, 14)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)

    class Crash(BaseException):
        """The process dies: no except clause in the follower may swallow it."""

    real = at.append_ledger
    seen = []

    def dies_after_the_first(entry):
        real(entry)
        seen.append(entry)
        raise Crash()

    monkeypatch.setattr(at, "append_ledger", dies_after_the_first)
    with pytest.raises(Crash):
        world.run(T0 + 16 * H)
    assert len(seen) == 1 and follow_state()["strats"]["TESTAAA1"]["last_ms"] < (T0 + 5 * H) * 1000, \
        "the row is on disk, the follower's state is not"
    monkeypatch.setattr(at, "append_ledger", real)
    world.run(T0 + 16 * H)
    world.run(T0 + 17 * H)
    rows = ledger()
    keys = [(e["trade_id"], e["action"]) for e in rows]
    assert len(keys) == len(set(keys)) == 4, rows
    assert open_slots() == {}


def test_tick_does_nothing_under_pytest(monkeypatch):
    monkeypatch.setattr(vf, "pass_once", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert vf.tick() is None


# ------------------------------------------------------------------ final review of the skill rooms (Nov 11, 2026)
def test_a_second_pass_while_the_lock_is_held_writes_nothing_and_says_why(world):
    """CRITICAL: `pass_once` took no lock - only `tick()` did - and the writer reads the room's record
    ONCE when it starts, so a pass run by hand beside the API's thread wrote every enter and exit
    twice, for good. The pass itself now holds `follow.lock`; a second one writes nothing."""
    from tradingagents import portable

    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    with open(world.home / "follow.lock", "a+b") as fh:       # the API's thread is mid-pass
        portable.lock_exclusive(fh, blocking=False)
        try:
            res = world.run(T0 + 12 * H)
        finally:
            portable.unlock(fh)
    assert res[ROOM]["skipped"] is True and res[ROOM]["errors"] == [vf.BUSY]
    assert "another follower pass is running" in vf.BUSY and "wrote nothing" in vf.BUSY
    assert ledger() == [] and follow_state() == {}, "not a row, not a state"
    world.run(T0 + 12 * H)                                    # the lock is free again
    assert [e["action"] for e in ledger()] == ["enter", "exit"]


def test_tick_holds_no_lock_of_its_own_so_its_pass_runs(world, monkeypatch):
    """`tick()` used to take the lock and then call `pass_once`; with the lock in the pass, a tick
    holding it too would find its own pass "busy" for ever."""
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    monkeypatch.setattr(vf, "_fetch_default", world.m.fetch)
    monkeypatch.setattr(vf, "_funding_default", world.m.funding)
    monkeypatch.setattr(vf, "_listed_default", world.m.listed)
    monkeypatch.setattr(vf, "_minutes_default", world.m.minutes)
    monkeypatch.setitem(vf._DONE, "slot", None)
    world.m.now_ms = (T0 + 12 * H) * 1000
    res = vf._tick(T0 + 12 * H)
    assert res is not None and not res[ROOM].get("skipped"), res
    assert [e["action"] for e in ledger()] == ["enter", "exit"]


def test_an_unreadable_follower_record_is_named_and_never_overwritten(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    with profiles.using(ROOM):
        p = vf.state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"strats": {"TESTAAA1": {"pos": {"t": 17', encoding="utf-8")
    before = p.read_bytes()
    res = world.run(T0 + 12 * H)
    (err,) = res[ROOM]["errors"]
    assert "follower record cannot be read" in err and "never overwritten" in err
    assert p.read_bytes() == before, "never overwritten"
    assert ledger() == [] and open_slots() == {}, "nothing is done in that room"
    s = vf.status(ROOM, now_s=T0 + 12 * H + 60, lists_dir=world.lists)
    assert "follower record cannot be read" in s["why"] and s["errors"] == [s["why"]]
    assert "v4_follow.json" not in s["why"] and str(p.parent) not in s["why"], "no file name on screen"


def test_a_room_whose_pass_fails_saves_why_for_the_screen(world, monkeypatch):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    real = vf._Room._follow_all

    def broken(self):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(vf._Room, "_follow_all", broken)
    res = world.run(T0 + 12 * H)
    assert res[ROOM]["errors"] == ["the pass failed: RuntimeError: the disk went away"]
    s = vf.status(ROOM, now_s=T0 + 12 * H + 60, lists_dir=world.lists)
    from tradingagents.positions_view import fmt_when

    assert s["why"] == f"the pass of {fmt_when(T0 + 12 * H)} failed: RuntimeError: the disk went away"
    assert s["errors"][0] == "the pass failed: RuntimeError: the disk went away"
    monkeypatch.setattr(vf._Room, "_follow_all", real)
    world.run(T0 + 12 * H + 15 * 60)                          # the next pass works: the reason goes
    s = vf.status(ROOM, now_s=T0 + 12 * H + 15 * 60 + 60, lists_dir=world.lists)
    assert s["why"] is None and "pass_error" not in follow_state()


def test_a_skipped_entry_marks_the_strategy_cold_so_a_switch_on_rewarms_it(world):
    """Switched off on day 2, a strategy closes its trade on day 2's LAST candle by its target, and
    the same candle signals a new trade the backtest takes. Switched on again at day 3's midnight,
    the follower must know the backtest is holding that trade (warm up again, carry it) - not stand
    flat and buy a candle later, a trade the backtest never had."""
    closes = scripted([(20, 52)])
    c = {k: closes[k + 48] for k in range(-48, 4 * 24)}
    px = c[20] * (1 + 0.0005)
    r46, r47 = (c[46] - px) / px, (c[47] - px) / px
    target = (r46 + r47) / 2                              # reached first on candle 47, day 2's last
    world.m.add("AAA_USDT", closes, (T0 - 48 * H) * 1000)
    # breakout signals an entry on EVERY candle that closes above the last two highs, so the candle
    # that reaches the target also opens the next trade
    r = row("TESTAAA1", strategy="breakout", params={"lookback": 2, "threshold": 0.0}, target=target)
    world.put(D1, {ROOM: [r]})
    world.put(D2, {ROOM: []})                             # switched off for day 2
    world.put(D3, {ROOM: [r]})                            # and on again for day 3
    world.run(T0 + 20)
    world.run(D2 + 20)
    world.run(D3 + 3 * H + 20)
    got = [(e["action"], e["entry_ts"], e.get("why")) for e in ledger()]
    assert got == [("enter", T0 + 20 * H, None), ("exit", T0 + 20 * H, "TP")], got
    s = follow_state()["strats"]["TESTAAA1"]
    assert s["carried"] is True and s["pos"]["t"] == (T0 + 47 * H) * 1000, \
        "the trade the backtest opened on candle 47 is carried, never written"


def test_an_exit_at_a_settlement_is_charged_that_settlement(world):
    """The adapter keeps a funding read for 30 minutes: an exit at 8:00am written from the 7:45am
    read would miss the 8:00am settlement the next day's backtest charges. The follower asks for a
    read made during its own pass."""
    world.m.fund_cache_s = 1800
    world.m.add("AAA_USDT", scripted([(5, 7)]), (T0 - 48 * H) * 1000)   # in at 6:00am, out at 8:00am
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    world.run(T0 + 7 * H + 45 * 60 + 20)            # the 7:45am pass: funding read, settled to 7:45am
    world.run(T0 + 8 * H + 20)                      # the 8:00am pass writes the exit
    (x,) = [e for e in ledger() if e["action"] == "exit"]
    assert x["ts"] == T0 + 8 * H and x["opened_at"] == T0 + 6 * H
    assert x["fund"] == pytest.approx(-0.01), "the 8:00am settlement (0.01%, a long pays) is charged"


def test_funding_is_asked_back_to_the_shards_1d_frame_and_fresh_for_each_pass(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    for now in (T0 + 20, T0 + 7 * H, T0 + 12 * H):
        world.run(now)
    calls = [c for c in world.m.fund_calls if c[0] == "AAA_USDT"]
    assert calls
    for _sym, since, fresh, at_ms in calls:
        start_1d = (at_ms // (DAY * 1000) - BARS["1d"]) * DAY * 1000
        assert since is not None and since <= start_1d, "never later than the shard's 1d frame start"
        assert fresh == at_ms / 1000, "a read made during this pass"
    R = vf._Reads(T0 + 12 * H, None, None, None, world.lists)
    start = (R.now_ms // (DAY * 1000) - BARS["1d"]) * DAY * 1000
    assert R.fund_since(None) == start and R.fund_since(start - 5) == start - 5
    assert R.fund_since(start + 5) == start, "an open trade newer than that still reads from the 1d start"


def test_a_list_that_cannot_be_read_is_named_without_its_file_name(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    vf.list_path(D2, world.lists).write_text('{"rooms": ', encoding="utf-8")
    res = world.run(D2 + 5 * H)
    bad = [e for e in res[ROOM]["errors"] if "cannot be read" in e]
    assert bad and all(".json" not in e and "2026-11-02" not in e for e in res[ROOM]["errors"]), bad
    from tradingagents.positions_view import fmt_when

    assert fmt_when(D2) in bad[0]


def test_status_says_whether_todays_list_has_landed(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(D2 + 5 * H)
    s = vf.status(ROOM, now_s=D2 + 5 * H + 60, lists_dir=world.lists)
    assert s["today_landed"] is False and s["switched_on"] == []
    world.put(D2, {ROOM: [row("TESTAAA1")]})
    s = vf.status(ROOM, now_s=D2 + 5 * H + 60, lists_dir=world.lists)
    assert s["today_landed"] is True and [r["id"] for r in s["switched_on"]] == ["TESTAAA1"]


# ------------------------------------------------------------------ exits settled by the minute (Nov 11, 2026)
# Operator: "okay then change backtest and the practice rooms together, so they keep matching each
# other". A held trade's candle is walked minute by minute by the same skill_bt.step the daily run
# uses; the first minute that touches the stop or target writes the exit at THAT minute (ts), with
# the candle it belongs to beside it (v4_candle).
def _minute_rows(closes, first_ms, wick, seed=5):
    """60 minutes under every 1h candle: a noisy straight line from the previous close to this one,
    each minute's high and low `wick` (a fraction) beyond it."""
    rng = np.random.default_rng(seed)
    rows, prev = [], closes[0]
    for k, c in enumerate(closes):
        for m in range(60):
            p = prev + (c - prev) * (m + 1) / 60
            rows.append((first_ms + k * H_MS + m * 60_000, p * (1 + rng.uniform(0, wick)),
                         p * (1 - rng.uniform(0, wick))))
        prev = c
    return rows


def _exits(pid=ROOM):
    return [r for r in ledger(pid) if r["action"] == "exit"]


@pytest.mark.parametrize("strategy,params,stop,target", [
    ("bf_momentum", {"lookback": 10}, 0.015, None),
    ("sma_crossover", {"fast_period": 3, "slow_period": 8}, 0.015, 0.01),
    ("rsi_reversal", {"period": 7, "overbought": 70, "oversold": 30}, 0.02, None),
])
def test_follower_trades_equal_the_engines_walk_with_the_same_minutes(world, strategy, params, stop, target):
    """The whole point: a room and its backtest settle every stop and target with the same minutes,
    so trade for trade - the minute, the price, the dollars - they are one walk."""
    rng = np.random.default_rng(11)
    before, after = 400, 3 * 24 + 6
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.006, before + after)))
    first_ms = (T0 - before * H) * 1000
    world.m.add("AAA_USDT", closes, first_ms)
    world.m.minute_rows["AAA_USDT"] = _minute_rows(closes, first_ms, wick=0.008)
    r = row("TESTAAA1", strategy=strategy, params=params, stop=stop, target=target)
    for d in (D1, D2, D3):
        world.put(d, {ROOM: [r]})
    now = T0 + 20
    while now < D4:
        world.run(now)
        now += 7 * H
    world.run(D4 + 20)

    world.m.now_ms = (D4 + 20) * 1000
    warm = world.m.fetch("AAA_USDT", "1h", end_ms=T0 * 1000)
    full = world.m.fetch("AAA_USDT", "1h", bars=10 ** 6)
    ref = full[full.index >= warm.index[0]]
    fine = sb.read_fine("AAA_USDT", sb.fine_from_ms(T0 * 1000), minutes=world.m.minutes, now_s=D4 + 20)
    done, _still = sb.run(ref, sb.signals(ref, strategy, params), stop=stop, fee=r["fee"], slip=r["slip"],
                          target=target, funding=sb.Funding(world.m.funding("AAA_USDT")), bar_ms=H_MS, fine=fine)
    want = sorted((t["entry_ms"], t["exit_ms"], t["side"], t["why"], round(t["pnl"], 4), t.get("at"))
                  for t in done if t["entry_ms"] >= T0 * 1000 and t["why"] != "END")
    by_enter = {e["trade_id"]: e for e in ledger() if e["action"] == "enter"}
    got = sorted((by_enter[x["trade_id"]]["entry_ts"] * 1000, x["v4_candle"] * 1000,
                  1 if x["side"] == "LONG" else -1, x["why"], round(x["pnl_est"], 4),
                  x["ts"] * 1000 if x.get("by_minute") else None) for x in _exits())
    assert len(want) >= 4 and got == want, (want, got)
    assert any(w[5] is not None for w in want), "the case must hold a stop or target the minutes settled"
    assert all(x["ts"] >= x["opened_at"] for x in _exits()), "never an exit before its fill"


def test_a_stop_in_minute_twelve_is_written_at_minute_twelve(world):
    closes = scripted([(5, 20)])
    first_ms = (T0 - 48 * H) * 1000
    world.m.add("AAA_USDT", closes, first_ms)
    rows = _minute_rows(closes, first_ms, wick=0.0)
    dip = (T0 + 8 * H) * 1000 + 12 * 60_000                 # candle 8, minute 12: a wick to 90
    rows = [(t, h, 90.0 if t == dip else lo) for t, h, lo in rows]
    world.m.minute_rows["AAA_USDT"] = rows
    world.put(D1, {ROOM: [row("TESTAAA1", stop=0.03, slip=0.0005)]})
    world.run(T0 + 20)
    world.run(T0 + 12 * H)
    (x,) = _exits()
    entry = float(next(e for e in ledger() if e["action"] == "enter")["entry"])
    assert x["why"] == "SL" and x["by_minute"] is True
    assert x["ts"] == T0 + 8 * H + 12 * 60, "the minute the price touched the stop, not the candle's close"
    assert x["v4_candle"] == T0 + 8 * H, "and the candle it belongs to, for the daily check"
    assert x["exit"] == pytest.approx(entry * 0.97 * (1 - 0.0005)), "the stop's price plus the gap"
    assert x["held_s"] == x["ts"] - x["opened_at"] and x["held_s"] > 0
    assert open_slots() == {}, "the position is gone"


def test_it_waits_for_a_candles_last_minute_and_then_for_ten_minutes_no_longer(world):
    """The pass runs 20 seconds after a close; if the exchange's minutes stop short of that candle's
    end, the close must NOT decide (the backtest would settle it by the minute) - the candle waits,
    and only after FINE_WAIT_S does the close decide, as it does where the exchange has no minutes."""
    closes = scripted([(5, 40)])
    first_ms = (T0 - 48 * H) * 1000
    world.m.add("AAA_USDT", closes, first_ms)
    rows = _minute_rows(closes, first_ms, wick=0.0)
    cut = (T0 + 7 * H) * 1000 - 5 * 60_000                  # the last five minutes of candle 6 are missing
    world.m.minute_rows["AAA_USDT"] = [r for r in rows if r[0] < cut]
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 6 * H + 20)                               # candle 5's close is read; the trade is open
    assert open_slots()
    world.run(T0 + 7 * H + 20)                               # candle 6 closed 20 s ago, its last minutes missing
    assert follow_state()["strats"]["TESTAAA1"]["last_ms"] == (T0 + 5 * H) * 1000, "candle 6 waits"
    world.run(T0 + 7 * H + vf.FINE_WAIT_S + 1)               # ten minutes on: the close decides
    assert follow_state()["strats"]["TESTAAA1"]["last_ms"] == (T0 + 6 * H) * 1000


def test_a_coin_with_no_minutes_at_all_is_settled_by_the_close_at_once(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 12 * H)
    (x,) = _exits()
    assert x["why"] == "SIGNAL" and not x.get("by_minute") and x["ts"] == T0 + 9 * H
    assert x["v4_candle"] == T0 + 8 * H


def test_minutes_that_cannot_be_read_hold_the_trade_never_decide_it(world):
    world.m.add("AAA_USDT", scripted([(5, 8)]), (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 6 * H + 20)
    assert open_slots()
    real = world.m.minutes

    def down(*a, **k):
        raise ConnectionError("the minutes are unreachable")
    world.m.minutes = down
    res = world.run(T0 + 12 * H)
    assert _exits() == [] and open_slots(), "no exit written on candles because the minutes were down"
    assert any("the minutes are unreachable" in e for e in res[ROOM]["errors"])
    world.m.minutes = real
    world.run(T0 + 13 * H)
    assert len(_exits()) == 1, "the next pass catches up"


def test_a_warm_up_reads_the_minutes_the_daily_run_reads_for_that_midnight(world):
    """A strategy warmed up at D1 reads minutes from MINUTE_DAYS before D1 - the same stretch the
    GitHub run of D1 reads - so a carried trade is the backtest's carried trade."""
    closes = scripted([(-10, 20)], before=48)
    world.m.add("AAA_USDT", closes, (T0 - 48 * H) * 1000)
    world.put(D1, {ROOM: [row("TESTAAA1")]})
    world.run(T0 + 20)
    starts = [c[1] for c in world.m.minute_calls]
    assert min(starts) == sb.fine_from_ms(T0 * 1000) // 1000
