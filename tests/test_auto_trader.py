"""The Auto Trade runner: signals, ladder, and a full dry-run cycle.

The signal functions must match the 13-month backtest that justified the tab,
and the trade loop must honour the safety model: dry by default, SL-first
worst-case fills, ladder resets on a win.
"""

from __future__ import annotations

import json
import time
from unittest import mock

import pandas as pd
import pytest

from tradingagents import auto_trader as at


# --------------------------------------------------------------- signals
def test_fvg_bullish_gap_fill_goes_long():
    # Gap up (bar 2 low > bar 0 high), then price falls to the gap's midpoint.
    high = [10.0, 10.5, 12.0, 12.1, 11.0]
    low = [9.0, 10.2, 11.5, 11.6, 10.2]
    close = [9.5, 10.4, 11.8, 11.9, 10.2]   # last close ≤ (11.5+10)/2 = 10.75
    assert at.sig_ict_fvg(high, low, close) == 1


def test_fvg_bearish_gap_fill_goes_short():
    high = [12.0, 11.5, 10.0, 9.9, 11.2]     # bar-2 high < bar-0 low
    low = [11.0, 10.8, 9.0, 9.1, 10.5]
    close = [11.5, 11.0, 9.5, 9.4, 11.2]     # last close ≥ (11+10)/2 = 10.5
    assert at.sig_ict_fvg(high, low, close) == -1


def test_fvg_no_gap_no_signal():
    n = 10
    assert at.sig_ict_fvg([10.0] * n, [9.0] * n, [9.5] * n) == 0


def test_mom6_direction_and_threshold():
    up = [100, 100, 100, 100, 100, 100, 101]        # +1% > 0.6% threshold
    down = [100, 100, 100, 100, 100, 100, 99]
    flat = [100, 100, 100, 100, 100, 100, 100.1]
    assert at.sig_mom6(up) == 1
    assert at.sig_mom6(down) == -1
    assert at.sig_mom6(flat) == 0


def test_trend50_follows_the_average():
    rising = list(range(100, 160))
    falling = list(range(160, 100, -1))
    assert at.sig_trend50([float(x) for x in rising]) == 1
    assert at.sig_trend50([float(x) for x in falling]) == -1


# ---------------------------------------------------------------- ladder
def test_ladder_multiples_and_cap():
    assert [at.ladder_margin(10, s) for s in range(9)] == \
        [10, 10, 20, 20, 40, 40, 80, 80, 80]


def test_bracket_prices_both_sides():
    tp, sl = at._bracket(1, 100.0, 0.045, 0.015)
    assert tp == pytest.approx(104.5) and sl == pytest.approx(98.5)
    tp, sl = at._bracket(-1, 100.0, 0.045, 0.015)
    assert tp == pytest.approx(95.5) and sl == pytest.approx(101.5)


def test_dry_fill_is_stop_first_when_both_barriers_sit_in_one_bar():
    pos = {"side": 1, "tp": 104.5, "sl": 98.5}
    assert at._dry_fill(pos, high=[105.0], low=[98.0]) == "SL"
    assert at._dry_fill(pos, high=[105.0], low=[99.0]) == "TP"
    assert at._dry_fill(pos, high=[104.0], low=[99.0]) is None


# ------------------------------------------------------- dry-run trade loop
class FakeFx:
    """Just enough exchange for a cycle: canned candles, records orders."""

    SIDE_OPEN_LONG = 1
    SIDE_CLOSE_SHORT = 2
    SIDE_OPEN_SHORT = 3
    SIDE_CLOSE_LONG = 4
    TYPE_LIMIT = 1

    def __init__(self, df):
        self.df = df
        self.orders = []
        self.stops = []

    def klines(self, symbol, interval, limit):
        return self.df.copy()

    max_vol = 0                       # 0 = venue imposes no per-order cap

    def contracts_for(self, symbol, notional, price=None):
        return int(notional)          # one contract ≈ 1 USDT, plenty of vol

    def contract_spec(self, symbol):
        return {"priceScale": 2, "maxVol": self.max_vol}

    def position_history(self, symbol=None, page_size=20):
        return getattr(self, "history", [])

    def submit(self, symbol, side, vol, *, leverage, dry_run=True):
        self.orders.append({"symbol": symbol, "side": side, "vol": vol,
                            "leverage": leverage, "dry_run": dry_run})
        return {"dry_run": dry_run}

    def open_positions(self, symbol=None):
        return []

    def last_price(self, symbol):
        return float(self.df["Close"].iloc[-1])

    def place_position_stop(self, *a, **kw):
        self.stops.append(kw)
        return {"dry_run": kw.get("dry_run", True)}

    def verify_position_stop(self, symbol, position_id):
        # Default fake venue confirms what it accepted; tests that care about
        # the accepted-but-inert case override this.
        return {"protected": True}


# Fixed origin so appending a bar yields a NEW timestamp: with a per-call
# origin of now-(n+2) bars, a 61-bar and a 62-bar series END on the same
# timestamp and the runner rightly refuses to act on the "same" candle twice.
_T0 = int(time.time()) - 400 * at.BAR_SECONDS


def _bars(closes, *, spread=0.001):
    """Closed 4h bars ending well in the past so none is 'in progress'."""
    n = len(closes)
    dates = pd.to_datetime([_T0 + i * at.BAR_SECONDS for i in range(n)], unit="s")
    return pd.DataFrame({
        "Date": dates,
        "Open": closes, "High": [c * (1 + spread) for c in closes],
        "Low": [c * (1 - spread) for c in closes], "Close": closes,
        "Volume": [1.0] * n,
    })


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for name in ("SETTINGS_PATH", "STATE_PATH", "LEDGER_PATH",
                 "PID_PATH", "KILL_PATH"):
        monkeypatch.setattr(at, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.delenv("AUTO_TRADE_DRY", raising=False)
    # Module-level caches are shared state; a test must never inherit another
    # test's candles or liquidity verdicts.
    at._BAR_CACHE.clear()
    at._GATE_CACHE.clear()
    at._GATE_LOGGED.clear()
    # _bars() builds candles well in the past so their timestamps are stable.
    # Real operation acts on a candle seconds old, so disable the staleness
    # guard here; test_a_stale_candle_is_not_traded exercises it directly.
    monkeypatch.setattr(at, "MAX_SIGNAL_AGE_FRACTION", float("inf"))
    return tmp_path


def test_dry_cycle_enters_on_signal_and_stays_dry(sandbox):
    closes = [100.0] * 60 + [102.0]          # +2% jump: mom6 fires long
    fx = FakeFx(_bars(closes))
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                "margin": 10.0, "enabled": True}
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert len(fx.orders) == 1
    order = fx.orders[0]
    assert order["dry_run"] is True, "unarmed must never send a live order"
    assert order["side"] == FakeFx.SIDE_OPEN_LONG
    assert order["leverage"] == at.LEVERAGE
    assert fx.stops == [], "dry run must not rest a live stop"
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    assert pos["strategy"] == "mom6" and pos["side"] == 1
    assert pos["margin"] == 10.0
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert entries[-1]["action"] == "enter" and entries[-1]["dry_run"] is True


def test_same_bar_is_not_traded_twice(sandbox):
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    state[at.state_key("BTC_USDT", True)]["position"] = None       # pretend it closed elsewhere
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert len(fx.orders) == 1, "one candle, one decision"


def test_stop_loss_advances_the_ladder_and_win_resets_it(sandbox):
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    # Price then crashes through the stop on the next bar.
    crash = closes + [pos["sl"] * 0.99]
    fx2 = FakeFx(_bars(crash))
    at.process_symbol("BTC_USDT", settings, state, fx=fx2, dry=True)
    assert state[at.state_key("BTC_USDT", True)]["position"] is None
    assert state[at.state_key("BTC_USDT", True)]["step"] == 1, "a stop-out must move the ladder"
    # Next entry sizes at the same rung value (ladder step 1 = 1× base).
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    exit_row = [e for e in entries if e["action"] == "exit"][-1]
    assert exit_row["why"] == "SL" and exit_row["pnl_est"] < 0


def test_kill_file_blocks_new_entries(sandbox):
    at.KILL_PATH.write_text("stop")
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    at.process_symbol("BTC_USDT", settings, {}, fx=fx, dry=True)
    assert fx.orders == []


def test_run_cycle_does_nothing_when_disabled(sandbox):
    at.SETTINGS_PATH.write_text(json.dumps(
        {"strategies": ["mom6"], "coins": ["BTC_USDT"], "enabled": False}))
    at.run_cycle(fx=None if False else FakeFx(_bars([100.0] * 61)))
    assert not at.LEDGER_PATH.exists()


def test_dry_position_exits_on_live_tick_not_just_closed_bars(sandbox):
    """A simulated fill must not wait up to 4 hours for the bar to close —
    the live tick against the bracket is the real-time exit."""
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    # Same candles (no new closed bar), but the live tick is through the stop.
    fx.last_price = lambda symbol: pos["sl"] * 0.999
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert state[at.state_key("BTC_USDT", True)]["position"] is None
    assert state[at.state_key("BTC_USDT", True)]["step"] == 1


def test_next_sleep_wakes_just_after_the_4h_boundary(sandbox):
    # 10 seconds before a boundary → sleep lands ENTRY_LAG past it.
    boundary = (int(time.time()) // at.BAR_SECONDS + 1) * at.BAR_SECONDS
    s = at.next_sleep_seconds(boundary - 10)
    assert s == pytest.approx(10 + at.ENTRY_LAG_SECONDS)
    # Mid-candle with nothing open → plain heartbeat.
    s = at.next_sleep_seconds(boundary + 100)
    assert s == at.POLL_SECONDS


def test_next_sleep_polls_fast_only_for_a_paper_position(sandbox):
    """A LIVE position's exit is handled by the exchange-side bracket, so
    polling fast for it only burns the rate limit that protects candle data.
    Only an open PAPER trade justifies the 5-second loop."""
    boundary = (int(time.time()) // at.BAR_SECONDS + 1) * at.BAR_SECONDS
    at.STATE_PATH.write_text(json.dumps(
        {"BTC_USDT": {"step": 0, "last_ts": 1,
                      "position": {"side": 1, "dry": False}}}))
    assert at.next_sleep_seconds(boundary + 100) == at.POLL_SECONDS, \
        "a live position must not trigger the fast poll"
    at.STATE_PATH.write_text(json.dumps(
        {"BTC_USDT#paper": {"step": 0, "last_ts": 1,
                            "position": {"side": 1, "dry": True}}}))
    assert at.next_sleep_seconds(boundary + 100) == at.DRY_EXIT_POLL_SECONDS


def test_sweep_signal_fades_the_reclaimed_extreme():
    n = 31
    high = [101.0] * n
    low = [100.0] * n
    close = [100.5] * n
    # Last bar pierces the 30-bar low then closes back above it → long.
    high2, low2, close2 = high[:], low[:], close[:]
    low2[-1] = 99.0
    close2[-1] = 100.2
    assert at.sig_sweep(high2, low2, close2) == 1
    # Mirror: pierce the high, close back below → short.
    high3, low3, close3 = high[:], low[:], close[:]
    high3[-1] = 102.0
    close3[-1] = 100.8
    assert at.sig_sweep(high3, low3, close3) == -1
    assert at.sig_sweep(high, low, close) == 0


def test_every_strategy_has_a_timeframe_and_bracket():
    """Both barriers real, and the target at least as far as the stop.

    Equal barriers (1:1) are allowed: a strategy wins either by being paid
    more than it risks OR by being right more often than it is wrong. APEX
    runs sweep30 at 3.00/3.00 and wins 56.8% of 243 trades, comfortably past
    the ~51.5% break-even once costs are paid. A target INSIDE the stop is
    still refused -- that needs a win rate the search has never produced.
    """
    for key in at.STRATEGY_ORDER:
        spec = at.STRATEGY_SPECS[key]
        assert spec["interval"] and spec["bar_seconds"] > 0
        assert 0 < spec["sl"] <= spec["tp"], key


def test_realtime_sweep_enters_on_its_own_1m_timeframe(sandbox):
    """The signal defines the rhythm: sweep_rt must be evaluated on 1m bars
    and bracketed with ITS barriers (1.8%/0.6%), not the 4h ones."""
    closes = [100.0] * 40
    df = _bars(closes)
    # Sweep on the last bar: pierce the prior 30-bar low, close back above.
    df.loc[df.index[-1], "Low"] = 99.0
    df.loc[df.index[-1], "Close"] = 100.0
    fx = FakeFx(df)
    seen = []
    real_klines = fx.klines
    fx.klines = lambda s, interval, n: seen.append(interval) or real_klines(s, interval, n)
    settings = {"strategies": ["sweep_rt"], "coins": ["BTC_USDT"], "margin": 10.0}
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert seen == ["Min1"], "realtime sweep must fetch 1-minute candles"
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    assert pos["strategy"] == "sweep_rt" and pos["side"] == 1
    assert pos["tp"] == pytest.approx(100.0 * 1.018)
    assert pos["sl"] == pytest.approx(100.0 * 0.994)


def test_next_sleep_follows_the_finest_enabled_timeframe(sandbox):
    at.SETTINGS_PATH.write_text(json.dumps(
        {"strategies": ["ict_fvg", "sweep_rt"], "enabled": True}))
    boundary = (int(time.time()) // 60 + 1) * 60
    s = at.next_sleep_seconds(boundary - 10)
    assert s == pytest.approx(10 + at.ENTRY_LAG_SECONDS), \
        "with the 1m strategy on, wakes align to 1m closes"


def test_strategy_only_trades_its_own_coins(sandbox):
    """Per-strategy coin lists: a strategy must not fire on a coin assigned
    to a different strategy."""
    closes = [100.0] * 60 + [102.0]          # mom6 long signal
    fx = FakeFx(_bars(closes))
    settings = {"strategies": ["mom6"],
                "strategy_coins": {"mom6": ["ETH_USDT"]},
                "coins": ["ETH_USDT"], "margin": 10.0}
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert fx.orders == [], "BTC is not in mom6's coin list"
    at.process_symbol("ETH_USDT", settings, state, fx=fx, dry=True)
    assert len(fx.orders) == 1 and fx.orders[0]["symbol"] == "ETH_USDT"


def test_coins_for_falls_back_to_the_legacy_global_list():
    legacy = {"coins": ["BTC_USDT"]}
    assert at.coins_for("ict_fvg", legacy) == ["BTC_USDT"]
    scoped = {"strategy_coins": {"ict_fvg": ["SOL_USDT"]}, "coins": ["BTC_USDT"]}
    assert at.coins_for("ict_fvg", scoped) == ["SOL_USDT"]


def test_backtest_strategy_wins_a_clean_take_profit():
    """mom6 fires on the +2% bar, enters the next open at 102, and the later
    rally through 106.59 (TP 4.5%) must land as one winning trade."""
    closes = [100.0] * 60 + [102.0] + [102.0] * 5 + [107.0] * 5
    df = _bars(closes)
    r = at.backtest_strategy("mom6", df, base_margin=10.0)
    assert r["trades"] >= 1
    assert r["wins"] >= 1
    assert r["profit"] > 0
    assert r["wins"] + r["losses"] == r["trades"]
    # First trade: (4.5% − 2×(0.02% fee + 0.03% slippage)) × 200 USDT
    # notional = +$8.80; a trailing flat END trade pays costs only (−$0.20).
    assert r["profit"] >= 8.5


def test_backtest_dirs_match_the_live_signal():
    """Differential, randomized, EVERY bar — not one fixture's last bar.

    The live `sig_*` rule and the vectorised `_dirs_for_backtest` rule are two
    implementations of one strategy. When they drift, the backtest measures a
    strategy that never trades: trend50 shipped with the live average
    INCLUDING the current bar and the backtest EXCLUDING it, and a last-bar-
    only check could not see it.
    """
    import random
    mismatches = []
    for seed in range(12):
        rng = random.Random(seed)
        closes = [100.0]
        for _ in range(260):
            closes.append(closes[-1] * (1 + rng.uniform(-0.012, 0.012)))
        high = [c * (1 + rng.uniform(0, 0.006)) for c in closes]
        low = [c * (1 - rng.uniform(0, 0.006)) for c in closes]
        for key in at.STRATEGY_ORDER:
            dirs = at._dirs_for_backtest(key, high, low, closes)
            # Walk every bar: the live function sees history up to that bar.
            for i in range(60, len(closes)):
                live = at.signal_for(key, high[:i + 1], low[:i + 1],
                                     closes[:i + 1])
                if dirs[i] != live:
                    mismatches.append((key, seed, i, dirs[i], live))
    # FVG and sweep carry state across bars by design (a gap is consumed once),
    # so a truncated-history replay legitimately differs; the stateless rules
    # must agree on every bar.
    # Every rule whose signal depends only on the visible window. FVG and
    # sweep carry state across bars, so a truncated replay differs by design.
    stateful = ("ict_fvg", "fvg_1h", "fvg_4h", "fvg_4h_b",
                "sweep_1h", "sweep_rt", "sweep30_4h")
    stateless = [m for m in mismatches if m[0] not in stateful]
    {m[0] for m in mismatches}
    import app as _app
    for _k, *_ in _app.AUTO_STRATEGIES:
        if _k in stateful:
            continue
        assert _k in at.STRATEGY_ORDER, f"{_k} not covered by this test"
    assert not stateless, f"{len(stateless)} live/backtest mismatches: {stateless[:5]}"


def test_daily_loss_limit_trips_only_past_the_threshold(sandbox):
    at.append_ledger({"action": "exit", "why": "SL", "pnl_est": -12.0})
    assert at.loss_limit_hit({"loss_limit": 10}) is True
    assert at.loss_limit_hit({"loss_limit": 15}) is False, \
        "−12 has not reached a −15 limit"
    assert at.loss_limit_hit({"loss_limit": 0}) is False, "0 means off"
    assert at.loss_limit_hit({}) is False


def test_per_strategy_loss_limit_pauses_only_that_strategy(sandbox):
    at.append_ledger({"action": "exit", "strategy": "fade15_1m",
                      "pnl_est": -11.0})
    at.append_ledger({"action": "exit", "strategy": "ict_fvg",
                      "pnl_est": 5.0})
    settings = {"strategy_loss_limits": {"fade15_1m": 10, "ict_fvg": 10}}
    tripped = at.tripped_strategies(settings)
    assert tripped == {"fade15_1m"}, \
        "only the strategy past ITS limit pauses; the winner keeps running"
    # And a tripped strategy takes no new entries even on a fresh signal.
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0},
                      {}, fx=fx, dry=True, tripped=frozenset({"mom6"}))
    assert fx.orders == []


def test_tripped_strategy_still_tracks_its_open_position_exit(sandbox):
    """Pausing entries must NOT orphan an open position: the exit check runs
    even when the strategy is tripped."""
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    assert pos is not None
    fx.last_price = lambda sym: pos["sl"] * 0.999   # tick through the stop
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True,
                      tripped=frozenset({"mom6"}))
    assert state[at.state_key("BTC_USDT", True)]["position"] is None, \
        "exit must be detected even while the strategy is paused"


def test_per_strategy_margin_overrides_the_global(sandbox):
    assert at.margin_for("ict_fvg", {"margin": 10.0}) == 10.0
    assert at.margin_for("ict_fvg", {"margin": 10.0,
                                     "strategy_margins": {"ict_fvg": 25}}) == 25
    assert at.margin_for("ict_fvg", {"margin": 10.0,
                                     "strategy_margins": {"ict_fvg": 0}}) == 10.0
    # And the entry actually sizes with it.
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    state = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0, "strategy_margins": {"mom6": 25}},
                      state, fx=fx, dry=True)
    assert state[at.state_key("BTC_USDT", True)]["position"]["margin"] == 25


def test_manual_close_records_the_exchanges_real_pnl(sandbox):
    """A position that vanished without its bracket being crossed must be
    ledgered with MEXC's realized PnL, not the TP-price estimate."""
    fx = FakeFx(_bars([100.0] * 61))
    fx.history = [{"positionId": 42, "realised": -1.23,
                   "closeAvgPrice": 99.5}]
    state = {"BTC_USDT": {"step": 0, "last_ts": {}, "position": {
        "side": 1, "vol": 50, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "mom6", "entry_ts": _T0 + 3600,
        "position_id": 42, "bracket": True}}}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=False)
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    exit_row = [e for e in entries if e["action"] == "exit"][-1]
    assert exit_row["why"] == "MANUAL/EXCHANGE"
    assert exit_row["pnl_est"] == -1.23, "real PnL from MEXC, not estimate"
    assert state["BTC_USDT"]["step"] == 1, "a real loss moves the ladder"


def test_exchange_exit_label_names_the_barrier_the_fill_landed_on():
    """Replays of real fills from 2026-08-19. Every bracket fill used to be
    ledgered MANUAL/EXCHANGE because the stop fills intrabar, before the
    candle check sees the cross."""
    # ALICE long: stop 0.1321 filled at exactly 0.1321.
    long_pos = {"side": 1, "tp": 0.1387, "sl": 0.1321}
    assert at._exchange_exit_label(long_pos, 0.1321) == "SL"
    # ALICE long TP 0.1386 filled 0.15% shy at 0.1384 — still the TP.
    assert at._exchange_exit_label(
        {"side": 1, "tp": 0.1386, "sl": 0.132}, 0.1384) == "TP"
    # ALICE short: stop 0.1396 slipped THROUGH to 0.1407 — still the stop.
    short_pos = {"side": -1, "tp": 0.1327, "sl": 0.1396}
    assert at._exchange_exit_label(short_pos, 0.1407) == "SL"
    assert at._exchange_exit_label(short_pos, 0.1327) == "TP"
    # Mid-range fills, clear of both barriers, are genuinely manual.
    assert at._exchange_exit_label(long_pos, 0.1350) == "MANUAL/EXCHANGE"
    assert at._exchange_exit_label(short_pos, 0.1360) == "MANUAL/EXCHANGE"


def test_bracket_fill_is_ledgered_as_its_barrier_not_manual(sandbox):
    """Position gone from the venue, fill price at the stop: the ledger row
    must say SL (with MEXC's real PnL), not MANUAL/EXCHANGE."""
    fx = FakeFx(_bars([100.0] * 61))
    fx.history = [{"positionId": 42, "realised": -3.10,
                   "closeAvgPrice": 98.4}]     # through the 98.5 stop
    state = {"BTC_USDT": {"step": 0, "last_ts": {}, "position": {
        "side": 1, "vol": 50, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "mom6", "entry_ts": _T0 + 3600,
        "position_id": 42, "bracket": True}}}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=False)
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    exit_row = [e for e in entries if e["action"] == "exit"][-1]
    assert exit_row["why"] == "SL"
    assert exit_row["pnl_est"] == -3.10, "real PnL from MEXC, not estimate"


# ------------------------------------------------- liquidity / edge gate
class BookFx(FakeFx):
    """FakeFx plus a measurable order book."""
    cost = {"spread": 0.0001, "slippage": 0.0001, "book_exhausted": False}

    def book_cost(self, symbol, notional_usd=200.0):
        return {"symbol": symbol, "mid": 100.0, "notional_tested": notional_usd,
                **self.cost}


def test_edge_gate_blocks_when_cost_eats_the_target(sandbox):
    """BDX: 1.56% spread against a 0.36% take-profit. No edge survives that."""
    fx = BookFx(_bars([100.0] * 61))
    fx.cost = {"spread": 0.0156, "slippage": 0.00854, "book_exhausted": False}
    r = at.edge_check("fade15_1m", "BDX_USDT", 10.0, fx=fx)
    assert r["verdict"] == "block"
    assert r["cost_ratio"] > 1.0, "cost exceeds the entire take-profit"


def test_edge_gate_passes_a_deep_book(sandbox):
    """BTC: 0.000% spread against a 4.5% take-profit."""
    fx = BookFx(_bars([100.0] * 61))
    fx.cost = {"spread": 0.0, "slippage": 0.0, "book_exhausted": False}
    assert at.edge_check("ict_fvg", "BTC_USDT", 10.0, fx=fx)["verdict"] == "ok"


def test_edge_gate_blocks_when_the_book_cannot_fill_the_deepest_rung(sandbox):
    fx = BookFx(_bars([100.0] * 61))
    fx.cost = {"spread": 0.0001, "slippage": 0.0001, "book_exhausted": True}
    assert at.edge_check("ict_fvg", "BTC_USDT", 10.0, fx=fx)["verdict"] == "block"


def test_runner_places_no_order_on_a_blocked_pair(sandbox):
    """The gate must stop the ORDER, not merely warn about it."""
    at._GATE_CACHE.clear(); at._GATE_LOGGED.clear()
    fx = BookFx(_bars([100.0] * 60 + [102.0]))
    fx.cost = {"spread": 0.02, "slippage": 0.01, "book_exhausted": False}
    state = {}
    at.process_symbol("BDX_USDT",
                      {"strategies": ["fade15_1m"], "coins": ["BDX_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=False)
    assert fx.orders == [], "a blocked pair must never reach the exchange"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert any(e["action"] == "gate_blocked" for e in entries)


def test_edge_gate_survives_an_unreadable_book(sandbox):
    class Broken(FakeFx):
        def book_cost(self, symbol, notional_usd=200.0):
            raise RuntimeError("depth endpoint down")
    r = at.edge_check("ict_fvg", "BTC_USDT", 10.0, fx=Broken(_bars([100.0]*61)))
    assert r["verdict"] == "unknown", "an outage must not silently read as ok"


def test_force_close_limit_sits_inside_liquidation_both_directions(sandbox):
    """2078 fallback: the limit must be placeable AND fillable.

    Closing a SHORT rests a BUY; if that buy sits below a rising market it can
    never fill — which is exactly the market a 2078 refusal implies. The first
    version of this code had both ternary branches identical and would have
    guaranteed the liquidation it existed to prevent.
    """
    class Liq(FakeFx):
        last = 100.0
        liq = 0.0
        def submit(self, symbol, side, vol, *, leverage, order_type=None,
                   price=None, dry_run=True):
            if order_type is None:                     # market attempt
                raise RuntimeError("code 2078: Fill price exceeds the "
                                   "liquidation price. Use a limit order")
            self.orders.append({"price": price, "side": side})
            return {}
        def last_price(self, symbol): return self.last
        def contract_spec(self, symbol): return {"priceScale": 2, "maxVol": 0}
        def open_positions(self, symbol=None):
            return [{"positionId": 9, "liquidatePrice": self.liq}]

    # SHORT near liquidation ABOVE the market: buy-limit must be just BELOW
    # liq (so the venue accepts it) and ABOVE the last price (so it fills).
    fx = Liq(_bars([100.0] * 61)); fx.last, fx.liq = 100.0, 100.5
    at._force_close("X_USDT", {"side": -1, "vol": 10, "position_id": 9}, fx=fx)
    px = fx.orders[-1]["price"]
    assert px < fx.liq, "must be inside liquidation or the venue refuses it"
    assert px > fx.last, "a buy-limit below a rising market never fills"

    # LONG near liquidation BELOW the market: sell-limit just ABOVE liq and
    # BELOW the last price.
    fx = Liq(_bars([100.0] * 61)); fx.last, fx.liq = 100.0, 99.5
    at._force_close("Y_USDT", {"side": 1, "vol": 10, "position_id": 9}, fx=fx)
    px = fx.orders[-1]["price"]
    assert px > fx.liq and px < fx.last


def test_bracket_is_only_trusted_when_the_exchange_confirms_it(sandbox):
    """A 200 OK is not protection — MEXC accepts TP/SL records that never
    rest (errorCode 8912, vol 0). The runner must read it back."""
    class Ver(FakeFx):
        protected = True
        def verify_position_stop(self, symbol, pid):
            return {"protected": self.protected}
    fx = Ver(_bars([100.0] * 61))
    pos = {"side": 1, "vol": 10, "tp": 104.5, "sl": 98.5, "position_id": 5}
    assert at._rest_bracket("X_USDT", pos, fx=fx) is True and pos["bracket"]

    fx.protected = False                       # accepted but not resting
    pos2 = {"side": 1, "vol": 10, "tp": 104.5, "sl": 98.5, "position_id": 6}
    assert at._rest_bracket("X_USDT", pos2, fx=fx) is False
    assert pos2["bracket"] is False, "unverified must not read as protected"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert any(e["action"] == "bracket_unverified" for e in entries)


def test_taker_fee_is_per_contract_and_never_assumes_btc(sandbox):
    class Spec(FakeFx):
        rates = {"CHEEMS_USDT": 0.0004, "BTC_USDT": 0.0002,
                 "MCDSTOCK_USDT": 0}          # spec lies; real fee is higher
        def contract_spec(self, symbol):
            return {"takerFeeRate": self.rates.get(symbol, 0), "priceScale": 2}
    fx = Spec(_bars([100.0] * 61))
    assert at.taker_fee("CHEEMS_USDT", fx=fx) == 0.0004
    assert at.taker_fee("BTC_USDT", fx=fx) == 0.0002
    assert at.taker_fee("MCDSTOCK_USDT", fx=fx) == at.FEE_FALLBACK, \
        "a zero/missing spec fee must fall back to the worst observed, not 0"


def test_daily_pnl_buckets_by_local_day_and_splits_books(sandbox):
    """The calendar reads in the operator's timezone, so a close at 8am local
    belongs to that local day — not the UTC one."""
    import time as _t
    day = _t.strftime("%Y-%m-%d")
    now = _t.time()
    for row in (
            {"action": "exit", "symbol": "PI_USDT", "pnl_est": 2.0,
             "dry_run": False, "ts": now},
            {"action": "exit", "symbol": "PROVE_USDT", "pnl_est": -1.0,
             "dry_run": False, "ts": now},
            {"action": "exit", "symbol": "PI_USDT", "pnl_est": 9.0,
             "dry_run": True, "ts": now},
            {"action": "gate_blocked", "symbol": "BDX_USDT", "ts": now}):
        at.append_ledger(row)
    real = at.daily_pnl(dry=False)
    assert real[day]["pnl"] == 1.0
    assert real[day]["wins"] == 1 and real[day]["losses"] == 1
    assert real[day]["trades"] == 2
    assert real[day]["coins"] == ["PI", "PROVE"]
    paper = at.daily_pnl(dry=True)
    assert paper[day]["pnl"] == 9.0, "paper must not leak into the real book"
    assert at.daily_pnl()[day]["trades"] == 3, "dry=None counts both"


def test_coin_stats_splits_the_books_and_keys_by_contract(sandbox):
    """Per-coin PnL: the operator must be able to see WHICH contract is
    losing. Real and paper must never be blended into one record."""
    for row in (
            {"action": "exit", "symbol": "PROVE_USDT", "strategy": "trend50_4h",
             "pnl_est": 2.71, "dry_run": False},
            {"action": "exit", "symbol": "PROVE_USDT", "strategy": "trend50_4h",
             "pnl_est": -1.0, "dry_run": False},
            {"action": "exit", "symbol": "BDX_USDT", "strategy": "fade15_1m",
             "pnl_est": -42.93, "dry_run": False},
            {"action": "exit", "symbol": "PROVE_USDT", "strategy": "trend50_4h",
             "pnl_est": 4.5, "dry_run": True},
            {"action": "gate_blocked", "symbol": "BDX_USDT"}):
        at.append_ledger(row)
    real = at.coin_stats(dry=False)
    assert set(real) == {"PROVE_USDT", "BDX_USDT"}
    assert real["PROVE_USDT"]["pnl"] == 1.71
    assert real["PROVE_USDT"]["wins"] == 1 and real["PROVE_USDT"]["losses"] == 1
    assert real["PROVE_USDT"]["trades"] == 2
    assert real["PROVE_USDT"]["winrate"] == 50.0
    assert real["PROVE_USDT"]["strategies"] == "trend50_4h"
    assert real["BDX_USDT"]["pnl"] == -42.93
    paper = at.coin_stats(dry=True)
    assert set(paper) == {"PROVE_USDT"}, "paper must not contain real coins"
    assert paper["PROVE_USDT"]["pnl"] == 4.5
    both = at.coin_stats()
    assert both["PROVE_USDT"]["trades"] == 3, "dry=None counts both books"


def test_paper_bracket_catches_an_intrabar_wick(sandbox):
    """A real bracket rests at the exchange and fills the instant price prints
    through it — including a wick that immediately retraces. The demo owns no
    order, so it used to see only the last PRICE and missed every wick; the
    miss surfaced hours later when the strategy's own bar closed (measured:
    90th percentile 60 minutes late, worst 206). It must read 1-minute RANGES."""
    import pandas as _pd
    fx = FakeFx(_bars([100.0] * 60 + [102.0]))
    state = {}
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    st = state[at.state_key("BTC_USDT", True)]
    pos = st["position"]
    assert pos and pos["side"] == 1

    # A 1-minute bar that WICKS through the take-profit and closes back below.
    n, now = 5, int(time.time())
    mins = _pd.DataFrame({
        "Date": _pd.to_datetime([now - (n - i) * 60 for i in range(n)], unit="s"),
        "Open": [pos["entry"]] * n,
        "High": [pos["entry"]] * (n - 1) + [pos["tp"] * 1.001],   # the wick
        "Low":  [pos["entry"] * 0.999] * n,
        "Close": [pos["entry"]] * n,                # closes back at entry
        "Volume": [1.0] * n})
    real_klines = fx.klines
    fx.klines = lambda s, interval, limit: (
        mins.copy() if interval == "Min1" else real_klines(s, interval, limit))
    # the last price shows NOTHING wrong — only the range reveals the fill
    fx.last_price = lambda s: pos["entry"]

    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert st["position"] is None, "the wick filled the bracket; demo must exit"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert [e for e in entries if e["action"] == "exit" and e["why"] == "TP"]


def test_zero_price_never_books_a_paper_exit(sandbox):
    """THE PROVE BUG. MEXC answers a rate limit with HTTP 200 and no data, so
    last_price used to hand back 0.0. Zero is below every short's take-profit
    and below every long's stop, so the paper book recorded PROVE_USDT as
    three take-profit wins (+$13.50) while the market never came within 4% of
    the target. An unreadable price must book NOTHING."""
    for side, closes in ((-1, [100.0] * 60 + [98.0]),   # short signal
                         (1, [100.0] * 60 + [102.0])):  # long signal
        at.LEDGER_PATH.write_text("")
        at._BAR_CACHE.clear()          # else round 2 replays round 1's candles
        fx = FakeFx(_bars(closes))
        state = {}
        settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                    "margin": 10.0}
        at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
        st = state[at.state_key("BTC_USDT", True)]
        assert st["position"] and st["position"]["side"] == side
        # now the ticker goes dark exactly the way MEXC does under a 510
        fx.last_price = lambda s: (_ for _ in ()).throw(
            RuntimeError("ticker carried no lastPrice (code=510)"))
        at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
        assert st["position"] is not None, \
            "an unreadable price must never close a paper position"
        entries = [json.loads(x) for x in
                   at.LEDGER_PATH.read_text().strip().splitlines()]
        assert not [e for e in entries if e.get("action") == "exit"], \
            "no exit may be booked without a real price"


def test_last_price_refuses_to_return_zero():
    """The root cause: a sentinel 0.0 wearing a price's clothes."""
    import pytest as _pt

    from tradingagents.dataflows import mexc_futures as mf
    for payload in ({"success": False, "code": 510, "message": "rate limit"},
                    {"data": {}},
                    {"data": {"lastPrice": 0}},
                    {"data": [{"lastPrice": "0.0"}]}):
        with mock.patch.object(mf, "_get_public", return_value=payload):
            with _pt.raises(mf.MexcFuturesError):
                mf.last_price("PROVE_USDT")
    with mock.patch.object(mf, "_get_public",
                           return_value={"data": {"lastPrice": "0.1508"}}):
        assert mf.last_price("PROVE_USDT") == 0.1508


def test_chase_guard_refuses_entry_when_price_unreadable(sandbox):
    """A guard that switches itself off on an API hiccup is not a guard."""
    fx = FakeFx(_bars([100.0] * 60 + [102.0]))
    fx.last_price = lambda s: (_ for _ in ()).throw(RuntimeError("510"))
    state = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=False)
    assert fx.orders == [], "no live entry without a readable price"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert any(e["action"] == "no_price_skip" for e in entries)


def test_a_stale_candle_is_not_traded(sandbox, monkeypatch):
    """A newly enabled book must not act on a candle that closed hours ago.
    The live book did exactly that on 2026-08-13 — entering PROVE on a signal
    5h41m old — because the chase guard only measures PRICE drift."""
    import pandas as _pd
    monkeypatch.setattr(at, "MAX_SIGNAL_AGE_FRACTION", 0.5)
    closes = [100.0] * 60 + [102.0]
    n = len(closes)
    old_start = int(time.time()) - 3 * at.BAR_SECONDS      # closed ~2 bars ago
    dates = _pd.to_datetime(
        [old_start - (n - 1 - i) * at.BAR_SECONDS for i in range(n)], unit="s")
    df = _pd.DataFrame({"Date": dates, "Open": closes,
                        "High": [c * 1.001 for c in closes],
                        "Low": [c * 0.999 for c in closes],
                        "Close": closes, "Volume": [1.0] * n})
    fx = FakeFx(df)
    state = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=True)
    assert fx.orders == [], "a stale signal must not be traded"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert any(e["action"] == "stale_skip" for e in entries)
    # and it must not be reconsidered on the next cycle either
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=True)
    assert fx.orders == []


def test_chase_guard_scales_with_the_stop(sandbox):
    """The tolerance is a fraction of the stop, not a flat percentage — a 4h
    strategy with a 1.5% stop may drift further than a 15m one with 0.3%."""
    ok, drift, limit = at.chase_ok(1, 100.0, 100.1, 0.015)   # +0.10% vs 1.5%
    assert ok and limit == pytest.approx(0.0015)
    ok, drift, limit = at.chase_ok(1, 100.0, 100.3, 0.015)   # +0.30% — too far
    assert not ok
    # Same absolute drift, tighter stop → refused sooner.
    ok, _, _ = at.chase_ok(1, 100.0, 100.1, 0.003)
    assert not ok
    # A move in the FAVOURABLE direction never blocks the entry: a long that
    # can now buy cheaper, or a short that can now sell higher.
    ok, _, _ = at.chase_ok(1, 100.0, 99.0, 0.015)
    assert ok
    ok, _, _ = at.chase_ok(-1, 100.0, 101.0, 0.015)
    assert ok, "selling higher than the signal is better, not a chase"
    # The chase for a SHORT is price having already fallen — the move you
    # wanted to catch has partly happened without you.
    ok, _, _ = at.chase_ok(-1, 100.0, 99.7, 0.015)
    assert not ok


def test_runner_skips_an_entry_that_ran_away(sandbox):
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    fx.last_price = lambda sym: 103.5          # +1.47% past the 102 signal
    state = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=False)
    assert fx.orders == [], "a stale signal must not be chased"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert any(e["action"] == "chase_skip" for e in entries)


def test_precomputed_dirs_match_recomputed(sandbox):
    """A sweep may pass the per-bar signal array in to avoid recomputing it
    six times per coin. Passing it must not change a single number."""
    df = _bars([100.0 + (i % 7) - 3 for i in range(400)])
    high = [float(x) for x in df["High"]]
    low = [float(x) for x in df["Low"]]
    close = [float(x) for x in df["Close"]]
    for key in ("mom6", "mom15_4h", "trend50_4h", "fvg_4h", "sweep30_4h"):
        d = at._dirs_for_backtest(key, high, low, close)
        for sizing in ("martingale", "flat"):
            a = at.backtest_strategy(key, df, 5.0, sizing=sizing)
            b = at.backtest_strategy(key, df, 5.0, sizing=sizing, dirs=d)
            assert a["profit"] == b["profit"], f"{key}/{sizing} profit drifted"
            assert a["trades"] == b["trades"] and a["wins"] == b["wins"]
            assert a["monthly"] == b["monthly"]


def test_flat_sizing_never_ladders(sandbox):
    """Flat is how a signal is measured; the runner must be able to run it.
    With sizing=flat every trade stakes the base margin no matter how many
    losses precede it. Martingale stays the default so an existing config is
    unchanged by this setting existing."""
    s_flat = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 5.0,
              "sizing": "flat"}
    s_mart = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 5.0}
    assert at.sizing_for(s_flat) == "flat"
    assert at.sizing_for(s_mart) == "martingale", "default must not change"
    assert at.sizing_for({"sizing": "MARTINGALE"}) == "martingale"
    for step in range(0, 8):
        assert at.staked_margin("mom6", s_flat, step) == 5.0, \
            "flat must ignore the ladder step entirely"
    assert at.staked_margin("mom6", s_mart, 0) == 5.0
    assert at.staked_margin("mom6", s_mart, 6) == 5.0 * at.LADDER[6]
    # and end to end: a flat book sizes the order off the base margin
    fx = FakeFx(_bars([100.0] * 60 + [102.0]))
    state = {at.state_key("BTC_USDT", True): {"step": 6, "last_ts": {},
                                              "position": None}}
    at.process_symbol("BTC_USDT", s_flat, state, fx=fx, dry=True)
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    assert pos and pos["margin"] == 5.0, \
        "deep in the ladder, flat still stakes the base"


def test_demo_runs_the_same_entry_gates_as_live(sandbox):
    """The demo exists to predict what live will do. It used to skip BOTH the
    liquidity gate and the chase guard (`if not dry:`), so it would happily
    show a tidy profit on a BDX-class contract live would never touch, and
    would take entries live refuses as too far past the signal. Same gates,
    both books — the ONLY thing dry-run may change is whether an order is
    actually sent to the exchange."""
    # 1. liquidity gate
    at._GATE_CACHE.clear(); at._GATE_LOGGED.clear()
    fx = BookFx(_bars([100.0] * 60 + [102.0]))
    fx.cost = {"spread": 0.02, "slippage": 0.01, "book_exhausted": False}
    state = {}
    at.process_symbol("BDX_USDT",
                      {"strategies": ["fade15_1m"], "coins": ["BDX_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=True)
    assert state.get(at.state_key("BDX_USDT", True), {}).get("position") is None, \
        "the demo must refuse a pair whose cost exceeds its target"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    blocked = [e for e in entries if e["action"] == "gate_blocked"]
    assert blocked and blocked[-1]["dry_run"] is True, \
        "the skip row must say which book it came from"

    # 2. chase guard
    at.LEDGER_PATH.write_text(""); at._BAR_CACHE.clear()
    fx2 = FakeFx(_bars([100.0] * 60 + [102.0]))
    fx2.last_price = lambda sym: 103.5         # +1.47% past the 102 signal
    state2 = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state2, fx=fx2, dry=True)
    assert state2.get(at.state_key("BTC_USDT", True), {}).get("position") is None, \
        "the demo must not chase an entry live would decline"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    chase = [e for e in entries if e["action"] == "chase_skip"]
    assert chase and chase[-1]["dry_run"] is True


def test_gate_warning_is_not_swallowed_by_the_other_book(sandbox):
    """Both books run the gate now; a dedupe key without the book let
    whichever ran first silence the other's warning entirely."""
    at._GATE_LOGGED.clear()
    assert at._gate_should_log("BDX_USDT", "fade15_1m", False) is True
    assert at._gate_should_log("BDX_USDT", "fade15_1m", False) is False
    assert at._gate_should_log("BDX_USDT", "fade15_1m", True) is True, \
        "the paper pass must not mute the live warning"


def test_position_on_a_removed_coin_is_still_settled(sandbox):
    """Dropping a strategy must not strand its open position in the book:
    the UI would keep showing money at risk the exchange already closed."""
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: []          # exchange is flat
    fx.history = [{"positionId": 77, "realised": -1.62}]
    state = {"OLDCOIN_USDT": {"step": 0, "last_ts": {}, "position": {
        "side": 1, "vol": 10, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "gone", "entry_ts": 1,
        "position_id": 77, "dry": False, "bracket": True}}}
    at.reconcile_unconfigured({"strategies": ["mom6"],
                               "strategy_coins": {"mom6": ["BTC_USDT"]}},
                              state, fx=fx)
    assert state["OLDCOIN_USDT"]["position"] is None
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    row = [e for e in entries if e["why"] == "RECONCILED"][-1]
    assert row["pnl_est"] == -1.62, "must book the exchange's real PnL"


def test_reconcile_leaves_a_position_that_is_still_open(sandbox):
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: [{"symbol": "OLDCOIN_USDT"}]
    state = {"OLDCOIN_USDT": {"step": 0, "last_ts": {}, "position": {
        "side": 1, "vol": 10, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "gone", "entry_ts": 1,
        "position_id": 77, "dry": False, "bracket": True}}}
    at.reconcile_unconfigured({"strategies": []}, state, fx=fx)
    assert state["OLDCOIN_USDT"]["position"] is not None, \
        "a genuinely open position must never be erased from the book"


def test_candles_are_cached_between_fast_wakes(sandbox):
    """A 5-second exit check must not re-download candles: the bar has not
    changed, and hammering MEXC returns truncated history."""
    at._BAR_CACHE.clear()
    fx = FakeFx(_bars([100.0] * 61))
    calls = []
    real = fx.klines
    fx.klines = lambda s, i, n: (calls.append(i) or real(s, i, n))
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    state = {}
    for _ in range(6):                       # six fast wakes inside one bar
        at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert len(calls) == 1, f"candles downloaded {len(calls)} times in one bar"


def test_book_is_never_flushed_while_the_exchange_says_open(sandbox):
    """The surviving BDX hole: a bracket that verified ONCE and later
    vanished let a barrier cross book a phantom exit. The exchange's answer
    must win over our own candles, always."""
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    state = {}
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=False)
    pos = state["BTC_USDT"]["position"]
    assert pos["bracket"] is True                 # verified at entry
    # Exchange still holds it; our candles cross the stop; closes all fail.
    fx.open_positions = lambda sym=None: [{"symbol": "BTC_USDT"}]
    def refuse(*a, **k):
        raise RuntimeError("exchange down")
    fx.submit = refuse
    crash = closes + [pos["sl"] * 0.99]
    fx2 = FakeFx(_bars(crash))
    fx2.open_positions = fx.open_positions
    fx2.submit = refuse
    at._BAR_CACHE.clear()      # new candles arrived; bypass the intra-bar cache
    at.process_symbol("BTC_USDT", settings, state, fx=fx2, dry=False)
    assert state["BTC_USDT"]["position"] is not None, \
        "must NOT book an exit the exchange has not confirmed"
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    assert any(e["action"] in ("close_failed", "close_unconfirmed")
               for e in entries)


def test_adopted_orphan_is_marked_real_so_a_demo_cannot_erase_it(sandbox):
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: [{
        "symbol": "BTC_USDT", "positionType": 1, "holdVol": 50,
        "holdAvgPrice": 100.0, "positionId": 777, "updateTime": 1}]
    state = {}
    at.adopt_orphans({"strategies": ["mom6"], "coins": ["BTC_USDT"],
                      "margin": 10.0}, state, fx=fx, dry=False)
    assert state["BTC_USDT"]["position"]["dry"] is False, \
        "an adopted position is real money and must be marked so"


def test_loss_limit_sees_the_whole_day_however_busy_the_log(sandbox):
    """The limit read a fixed tail of a log shared with skip/error rows, so a
    busy day hid every exit and it reported 0.00 while losing."""
    for _ in range(2500):
        at.append_ledger({"action": "gate_blocked", "why": "noise"})
    at.append_ledger({"action": "exit", "pnl_est": -500.0, "dry_run": False})
    for _ in range(2500):
        at.append_ledger({"action": "chase_skip", "why": "noise"})
    assert at.pnl_today(dry=False)["total"] == -500.0
    assert at.loss_limit_hit({"loss_limit": 50}) is True


def test_orphan_rescue_runs_when_both_books_are_on(sandbox):
    """The seam that mattered most: rescue was gated on dry_mode(), which
    ignores the Auto Trade switch — so with BOTH switches ticked (the mode the
    UI recommends) no real position was ever rescued."""
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: [{
        "symbol": "BTC_USDT", "positionType": 1, "holdVol": 50,
        "holdAvgPrice": 100.0, "positionId": 777, "updateTime": 1}]
    fx.contract_spec = lambda sym: {"priceScale": 2, "maxVol": 0,
                                    "contractSize": 1.0}
    at.SETTINGS_PATH.write_text(json.dumps(
        {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0,
         "enabled": True, "dry_run": True}))
    at.save_state({})
    at.run_cycle(fx=fx)
    assert at.load_state()["BTC_USDT"]["position"] is not None, \
        "a real orphan must be rescued even while the paper book also runs"


def test_unknown_exit_is_never_booked_as_a_win(sandbox):
    """An exit with no known price fell through to the TAKE-PROFIT, so a
    liquidation was recorded as a win and the ladder reset."""
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: []       # vanished
    fx.history = []                               # no realised figure either
    fx.last_price = lambda sym: 97.0              # it clearly went DOWN
    state = {"BTC_USDT": {"step": 3, "last_ts": {}, "position": {
        "side": 1, "vol": 10, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "mom6", "entry_ts": _T0,
        "position_id": 42, "dry": False, "bracket": True}}}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=False)
    entries = [json.loads(x) for x in
               at.LEDGER_PATH.read_text().strip().splitlines()]
    row = [e for e in entries if e["action"] == "exit"][-1]
    assert row["pnl_est"] < 0, f"a losing exit must not book a profit: {row}"
    assert state["BTC_USDT"]["step"] == 4, "a loss must advance the ladder"


def test_panic_keeps_positions_it_could_not_close(sandbox):
    class Stubborn(FakeFx):
        def submit(self, *a, **k):
            raise RuntimeError("MEXC error 2078")
        def last_price(self, symbol):
            return 100.0
        def contract_spec(self, symbol):
            return {"priceScale": 2}
        def open_positions(self, symbol=None):
            return [{"symbol": "A_USDT", "positionType": 1, "holdVol": 10,
                     "positionId": 1, "liquidatePrice": 95.0}]
    fx = Stubborn(_bars([100.0] * 61))
    at.save_state({"A_USDT": {"step": 2, "position": {
        "side": 1, "vol": 10, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "mom6", "position_id": 1,
        "dry": False, "bracket": True}}})
    rep = at.panic_stop(fx=fx)
    assert rep["failed"], "the failure must be reported"
    assert at.load_state()["A_USDT"]["position"] is not None, \
        "a position that could NOT be closed must stay tracked, not forgotten"


def test_panic_books_the_loss_where_the_limits_can_see_it(sandbox):
    class Closer(FakeFx):
        def submit(self, *a, **k):
            return {}
        def position_history(self, symbol=None, page_size=20):
            return [{"positionId": 1, "realised": -31.50}]
        def open_positions(self, symbol=None):
            return [{"symbol": "A_USDT", "positionType": 1, "holdVol": 10,
                     "positionId": 1}]
    fx = Closer(_bars([100.0] * 61))
    at.save_state({"A_USDT": {"step": 2, "position": {
        "side": 1, "vol": 10, "entry": 100.0, "tp": 104.5, "sl": 98.5,
        "margin": 10.0, "strategy": "mom6", "position_id": 1,
        "dry": False, "bracket": True}}})
    at.panic_stop(fx=fx)
    assert at.pnl_today(dry=False)["total"] == -31.50, \
        "a panic close must land where every PnL reader and limit can see it"


def test_panic_stop_closes_everything(sandbox):
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: [
        {"symbol": "A_USDT", "positionType": 1, "holdVol": 10, "positionId": 1},
        {"symbol": "B_USDT", "positionType": 2, "holdVol": 20, "positionId": 2}]
    at.save_state({"A_USDT": {"step": 3, "position": {"side": 1}},
                   "A_USDT#paper": {"step": 1, "position": {"side": 1}}})
    rep = at.panic_stop(fx=fx)
    assert rep["halted"] and set(rep["closed"]) == {"A_USDT", "B_USDT"}
    assert len(fx.orders) == 2, "every real position must get a close order"
    after = at.load_state()
    assert after["A_USDT"]["position"] is None, "live book cleared"
    assert after["A_USDT#paper"]["position"] is not None, \
        "paper book is not real money and must be left alone"


def test_capped_order_rewrites_its_margin(sandbox):
    """A venue-capped order kept the full ladder margin, inflating every
    number downstream — including what the loss limit reads."""
    fx = FakeFx(_bars([100.0] * 60 + [102.0]))
    fx.max_vol = 50                       # ladder wants 200
    state = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=True)
    pos = state[at.state_key("BTC_USDT", True)]["position"]
    assert pos["vol"] == 50
    assert pos["margin"] == pytest.approx(2.5), \
        "margin must match the size that actually went to market"


def test_a_paper_loss_never_halts_real_trading(sandbox):
    """Introduced when paper and real were split into two books: the account
    circuit breaker summed BOTH, so a losing demo could stop live trading —
    and a winning demo could mask a real drawdown."""
    at.append_ledger({"action": "exit", "pnl_est": -99.0, "dry_run": True})
    assert at.loss_limit_hit({"loss_limit": 50}) is False, \
        "a demo loss is not real money and must not trip the account breaker"
    at.append_ledger({"action": "exit", "pnl_est": -60.0, "dry_run": False})
    assert at.loss_limit_hit({"loss_limit": 50}) is True


def test_per_strategy_limits_are_evaluated_per_book(sandbox):
    at.append_ledger({"action": "exit", "strategy": "mom6",
                      "pnl_est": -11.0, "dry_run": True})
    limits = {"strategy_loss_limits": {"mom6": 10}}
    assert at.tripped_strategies(limits, dry=True) == {"mom6"}
    assert at.tripped_strategies(limits, dry=False) == set(), \
        "the live book keeps trading when only the demo lost"


def test_the_two_checkboxes_are_independent_switches(sandbox):
    """Auto Trade runs the live book. Dry run runs the paper book. Ticking
    both runs BOTH at once, in separate books."""
    assert at.active_modes({"enabled": True, "dry_run": False}) == [False]
    assert at.active_modes({"enabled": False, "dry_run": True}) == [True]
    assert at.active_modes({"enabled": True, "dry_run": True}) == [False, True]
    assert at.active_modes({"enabled": False, "dry_run": False}) == []


def test_running_both_books_keeps_them_completely_separate(sandbox):
    """One signal, both switches on: a real order AND a paper order, each
    tracked in its own book with its own ladder."""
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    state = {}
    for dry in at.active_modes({"enabled": True, "dry_run": True}):
        at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=dry)
    live = state["BTC_USDT"]["position"]
    paper = state[at.state_key("BTC_USDT", True)]["position"]
    assert live and paper, "both books must hold a position"
    assert live["dry"] is False and paper["dry"] is True
    assert [o["dry_run"] for o in fx.orders] == [False, True], \
        "exactly one real order and one simulated order"
    # A loss on the paper book must not move the live book's ladder.
    state[at.state_key("BTC_USDT", True)]["step"] = 4
    assert state["BTC_USDT"]["step"] == 0


def test_paper_and_real_pnl_are_never_summed_together(sandbox):
    at.append_ledger({"action": "exit", "pnl_est": 5.0, "dry_run": True})
    at.append_ledger({"action": "exit", "pnl_est": -2.0, "dry_run": False})
    assert at.pnl_today(dry=True)["total"] == 5.0
    assert at.pnl_today(dry=False)["total"] == -2.0
    assert at.pnl_today()["total"] == 3.0, "unfiltered still reports both"


def test_position_records_its_own_mode_and_keeps_it(sandbox):
    """Flipping the Dry-run checkbox must not change how an OPEN position is
    managed — a live position kept alive by a simulated exit is money lost."""
    closes = [100.0] * 60 + [102.0]
    fx = FakeFx(_bars(closes))
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    state = {}
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=False)
    pos = state["BTC_USDT"]["position"]
    assert pos["dry"] is False, "a live entry must be marked live"

    # Now the operator ticks Dry run. The open position is still REAL, so the
    # runner must not fabricate its exit from candles.
    fx.last_price = lambda sym: pos["sl"] * 0.999   # would trigger a dry exit
    fx.open_positions = lambda sym=None: [{"symbol": "BTC_USDT"}]
    at.process_symbol("BTC_USDT", settings, state, fx=fx, dry=True)
    assert state["BTC_USDT"]["position"] is not None, \
        ("a real position must not be closed by the simulator — the live "
         "book is separate and the paper run never touches it")


def test_closed_bars_drops_the_forming_candle(sandbox):
    """The in-progress bar must never reach a signal.

    Regression for the pandas-3 dtype bug: `to_datetime(unit="s")` yields
    datetime64[s], so `.astype("int64") // 10**9` collapsed every timestamp to
    1 and the filter kept EVERY bar — the live bot signalled mid-candle and
    traded a rule no backtest measured. Built the way the exchange helper
    builds it, so a dtype change breaks this test instead of the account.
    """
    now = int(time.time())
    start = now - now % 3600                       # current 1h bar, still open
    times = [start - 3600 * k for k in range(5, -1, -1)]
    df = pd.DataFrame({
        "Date": pd.to_datetime(times, unit="s"),   # same call as fx.klines
        "Open": [100.0] * 6, "High": [101.0] * 6,
        "Low": [99.0] * 6, "Close": [100.0] * 6, "Volume": [1.0] * 6,
    })
    out = at._closed_bars(df, 3600)
    assert len(out) == len(df) - 1, \
        f"forming bar not dropped ({len(out)} of {len(df)} kept)"
    assert int(out["Date"].iloc[-1].timestamp()) == start - 3600


def test_order_size_is_capped_at_the_venue_maximum(sandbox):
    """MEXC rejects an order above the contract's maxVol (code 2051) — the
    runner must size down instead of losing the trade."""
    fx = FakeFx(_bars([100.0] * 60 + [102.0]))
    fx.max_vol = 150                   # ladder wants 200 (10 margin × 20x)
    state = {}
    at.process_symbol("BTC_USDT",
                      {"strategies": ["mom6"], "coins": ["BTC_USDT"],
                       "margin": 10.0}, state, fx=fx, dry=True)
    assert fx.orders[0]["vol"] == 150, "sized down to the venue cap"


def test_orphan_position_is_adopted_and_bracketed(sandbox):
    """An exchange position on a bot coin with no book entry must be adopted:
    tracked under its strategy and given that strategy's bracket."""
    fx = FakeFx(_bars([100.0] * 61))
    fx.open_positions = lambda sym=None: [{
        "symbol": "BTC_USDT", "positionType": 1, "holdVol": 50,
        "holdAvgPrice": 100.0, "positionId": 777, "updateTime": 1}]
    fx.contract_spec = lambda sym: {"priceScale": 2}
    settings = {"strategies": ["mom6"], "coins": ["BTC_USDT"], "margin": 10.0}
    state = {}
    at.adopt_orphans(settings, state, fx=fx, dry=False)
    pos = state["BTC_USDT"]["position"]
    assert pos is not None and pos["position_id"] == 777
    assert pos["strategy"] == "mom6"
    assert pos["tp"] == pytest.approx(104.5) and pos["sl"] == pytest.approx(98.5)
    assert len(fx.stops) == 1, "the adopted orphan must get its bracket"
    assert pos["bracket"] is True


def test_backtest_charges_slippage_on_top_of_fees():
    closes = [100.0] * 60 + [102.0] + [102.0] * 5 + [107.0] * 5
    df = _bars(closes)
    with_slip = at.backtest_strategy("mom6", df, base_margin=10.0)
    frictionless = at.backtest_strategy("mom6", df, base_margin=10.0,
                                        slippage=0.0)
    assert with_slip["profit"] < frictionless["profit"], \
        "slippage must cost money, or the backtest flatters live"


def test_checkbox_is_the_live_switch_and_dry_run_is_the_opt_in(monkeypatch):
    """Operator's directive: 'if i check auto trade, do auto trade, period'.
    Enabled settings without the dry_run flag mean REAL orders; the dry_run
    flag (or AUTO_TRADE_DRY env) forces simulation."""
    monkeypatch.delenv("AUTO_TRADE_DRY", raising=False)
    assert at.dry_mode({"enabled": True}) is False          # live, period
    assert at.dry_mode({"enabled": True, "dry_run": True}) is True
    monkeypatch.setenv("AUTO_TRADE_DRY", "yes")
    assert at.dry_mode({"enabled": True}) is True           # env failsafe


def _flat_bars(n=40, price=100.0):
    import pandas as pd
    return pd.DataFrame({
        "Date": pd.date_range("2026-01-01", periods=n, freq="h"),
        "Open": [price] * n, "High": [price] * n,
        "Low": [price] * n, "Close": [price] * n})


def test_funding_is_charged_per_settlement_inside_the_trade():
    """Holding a perpetual costs money every few hours. A backtest that only
    charges entry and exit overstates profit by however long it holds."""
    df = _flat_bars()
    at.STRATEGY_SPECS["_fund_t"] = {"interval": "Min60", "bar_seconds": 3600,
                                    "tp": 0.10, "sl": 0.10}
    dirs = [0] * len(df)
    dirs[0] = 1                      # one LONG, opened on bar 1, runs to the end
    ms = int(df["Date"].iloc[0].value // 1_000_000)
    hour = 3_600_000
    # three settlements inside the trade, one before it, one after the end
    funding = [{"settle_ms": ms - hour, "rate": 0.5},
               {"settle_ms": ms + 5 * hour, "rate": 0.01},
               {"settle_ms": ms + 9 * hour, "rate": 0.02},
               {"settle_ms": ms + 13 * hour, "rate": 0.03},
               {"settle_ms": ms + 500 * hour, "rate": 0.5}]
    base = at.backtest_strategy("_fund_t", df, 10.0, fee=0.0, slippage=0.0,
                                sizing="flat", dirs=dirs)
    paid = at.backtest_strategy("_fund_t", df, 10.0, fee=0.0, slippage=0.0,
                                sizing="flat", dirs=dirs, funding=funding)
    at.STRATEGY_SPECS.pop("_fund_t", None)
    notional = 10.0 * at.LEVERAGE
    # a long pays a positive rate: 0.01 + 0.02 + 0.03 of notional
    assert paid["log"][0]["funding $"] == pytest.approx(-0.06 * notional)
    assert paid["profit"] == pytest.approx(base["profit"] - 0.06 * notional)
    # ...and the settlements outside the window are NOT charged
    assert paid["profit"] != pytest.approx(base["profit"] - 1.06 * notional)


def test_funding_pays_a_short_when_the_rate_is_positive():
    df = _flat_bars()
    at.STRATEGY_SPECS["_fund_s"] = {"interval": "Min60", "bar_seconds": 3600,
                                    "tp": 0.10, "sl": 0.10}
    dirs = [0] * len(df)
    dirs[0] = -1
    ms = int(df["Date"].iloc[0].value // 1_000_000)
    funding = [{"settle_ms": ms + 5 * 3_600_000, "rate": 0.01}]
    r = at.backtest_strategy("_fund_s", df, 10.0, fee=0.0, slippage=0.0,
                             sizing="flat", dirs=dirs, funding=funding)
    at.STRATEGY_SPECS.pop("_fund_s", None)
    assert r["log"][0]["funding $"] == pytest.approx(0.01 * 10.0 * at.LEVERAGE)


def test_funding_window_survives_second_resolution_timestamps():
    """MEXC frames arrive as datetime64[s]. Converting them with a nanosecond
    divisor read 1,754 instead of 1,754,406,000,000, so every trade's funding
    window spanned the whole history and PROVE's year read -$2,230."""
    import numpy as np

    df = _flat_bars()
    df["Date"] = df["Date"].values.astype("datetime64[s]")
    at.STRATEGY_SPECS["_fund_u"] = {"interval": "Min60", "bar_seconds": 3600,
                                    "tp": 0.10, "sl": 0.10}
    dirs = [0] * len(df)
    dirs[0] = 1
    ms = int(np.datetime64(df["Date"].iloc[0], "ms").astype("int64"))
    funding = [{"settle_ms": ms - 10_000 * 3_600_000, "rate": 0.9},
               {"settle_ms": ms + 5 * 3_600_000, "rate": 0.01}]
    r = at.backtest_strategy("_fund_u", df, 10.0, fee=0.0, slippage=0.0,
                             sizing="flat", dirs=dirs, funding=funding)
    at.STRATEGY_SPECS.pop("_fund_u", None)
    assert r["log"][0]["funding $"] == pytest.approx(-0.01 * 10.0 * at.LEVERAGE)


# ============ one timeframe per coin =========================================
# The operator's rule: "if i enable a different timeframe for a certain coin
# make sure i wont be enable other timeframe". MEXC nets same-symbol positions
# into one, so two strategies on one coin at different bar sizes are two bots
# resizing each other's trade, and either stop closes part of a position it does
# not own.
LIVE_BOTH = {"mom15_4h_w": ["real"], "trend50_30m_pi": ["real"]}


def test_two_LIVE_timeframes_on_one_coin_is_a_conflict():
    s = {"strategies": ["mom15_4h_w", "trend50_30m_pi"],
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]},
         "strategy_books": LIVE_BOTH}
    c = at.timeframe_conflicts(s)
    assert len(c) == 1
    assert c[0]["coin"] == "PI_USDT"
    assert c[0]["timeframes"] == ["Hour4", "Min30"]


def test_two_PAPER_timeframes_on_one_coin_are_allowed():
    """Operator, 2026-08-19: "i should be able to enable demo for both 30m and
    1hr timeframe for pi ... its only restricted on live trade". The netting
    that makes this dangerous is an EXCHANGE behaviour; the paper book has no
    MEXC position for the two to collide over."""
    s = {"strategies": ["mom15_4h_w", "trend50_30m_pi"],
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]},
         "strategy_books": {"mom15_4h_w": ["paper"],
                            "trend50_30m_pi": ["paper"]}}
    assert at.timeframe_conflicts(s) == []


def test_one_live_and_one_paper_timeframe_is_not_a_conflict():
    """Only the live pair can net. A papered second timeframe is a comparison,
    not a second bot on the same position."""
    s = {"strategies": ["mom15_4h_w", "trend50_30m_pi"],
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]},
         "strategy_books": {"mom15_4h_w": ["paper"],
                            "trend50_30m_pi": ["real"]}}
    assert at.timeframe_conflicts(s) == []


def test_a_strategy_on_BOTH_books_still_conflicts_live():
    s = {"strategies": ["mom15_4h_w", "trend50_30m_pi"],
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]},
         "strategy_books": {"mom15_4h_w": ["real", "paper"],
                            "trend50_30m_pi": ["real", "paper"]}}
    assert len(at.timeframe_conflicts(s)) == 1


def test_one_timeframe_per_coin_is_fine():
    s = {"strategies": ["trend50_30m_pi"],
         "strategy_coins": {"trend50_30m_pi": ["PI_USDT"]},
         "strategy_books": {"trend50_30m_pi": ["real"]}}
    assert at.timeframe_conflicts(s) == []


def test_same_timeframe_two_strategies_is_not_a_conflict():
    """Two 4h strategies on one coin still share one position, but that is the
    ladder/order question, not the timeframe rule the operator stated."""
    s = {"strategies": ["mom15_4h_w", "trend50_4h"],
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_4h": ["PI_USDT"]},
         "strategy_books": {"mom15_4h_w": ["real"],
                            "trend50_4h": ["real"]}}
    assert at.timeframe_conflicts(s) == []


def test_different_coins_on_different_timeframes_are_fine():
    s = {"strategies": ["mom15_4h_w", "trend50_30m_pi"],
         "strategy_coins": {"mom15_4h_w": ["XAUT_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]}}
    assert at.timeframe_conflicts(s) == []


def test_the_runner_refuses_a_cycle_while_a_coin_is_double_booked(monkeypatch):
    """Reporting the conflict is not enough — it must not trade."""
    s = {"strategies": ["mom15_4h_w", "trend50_30m_pi"], "enabled": True,
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]},
         "strategy_books": {"mom15_4h_w": ["real"],
                            "trend50_30m_pi": ["real"]}}
    monkeypatch.setattr(at, "load_settings", lambda: s)
    monkeypatch.setattr(at, "load_state", lambda: {})
    touched = []
    monkeypatch.setattr(at, "adopt_orphans",
                        lambda *a, **k: touched.append("adopt"))
    monkeypatch.setattr(at, "process_symbol",
                        lambda *a, **k: touched.append("process"))
    monkeypatch.setattr(at, "append_ledger", lambda e: touched.append(e["action"]))
    at.run_cycle(fx=object())
    assert "process" not in touched, "must not trade a double-booked coin"
    assert "adopt" not in touched
    assert "blocked" in touched, "and must say so in the ledger"


def test_the_new_pi_key_carries_its_own_barriers():
    """#3CRXP8 is 30m TP 2.5 / SL 2.0. The standing `trend50` key is 4h TP 4.5 /
    SL 1.5 — ticking that would run a different strategy on a different bar."""
    a = at.STRATEGY_SPECS["trend50_30m_pi"]
    b = at.STRATEGY_SPECS["trend50"]
    assert (a["interval"], a["tp"], a["sl"]) == ("Min30", 0.025, 0.020)
    assert (b["interval"], b["tp"], b["sl"]) != (a["interval"], a["tp"], a["sl"])
    assert at.signal_for("trend50_30m_pi", [1]*60, [1]*60, list(range(60))) != 0


def test_an_explicitly_empty_coin_list_means_none_not_all():
    """`per.get(key) or coins` treated [] as falsy and fell back to the GLOBAL
    coin list, so unticking a strategy's last coin silently promoted it to
    trading every coin in the config. Found live: mom15_1h_g sat at [] and was
    claiming all five contracts."""
    s = {"coins": ["A_USDT", "B_USDT", "C_USDT"],
         "strategy_coins": {"k": []}}
    assert at.coins_for("k", s) == [], "empty must mean none"


def test_a_missing_key_still_falls_back_to_the_global_list():
    """Old settings files predate per-strategy lists and must keep working."""
    s = {"coins": ["A_USDT", "B_USDT"], "strategy_coins": {}}
    assert at.coins_for("k", s) == ["A_USDT", "B_USDT"]


def test_unticking_a_coin_does_not_promote_a_strategy_to_all_coins():
    s = {"coins": ["PI_USDT", "XAUT_USDT"],
         "strategies": ["mom15_4h_w", "trend50_30m_pi"],
         "strategy_coins": {"mom15_4h_w": ["PI_USDT"],
                            "trend50_30m_pi": ["PI_USDT"]}}
    s["strategy_coins"]["mom15_4h_w"].remove("PI_USDT")
    assert at.coins_for("mom15_4h_w", s) == []
    assert at.timeframe_conflicts(s) == [], \
        "moving PI to 30m must leave no conflict, not create four"


# ==========================================================================
# The four defects found on 2026-08-19 by auditing the live account.
# Each test names what it cost, so nobody "simplifies" the fix away later.
# ==========================================================================
def _scratch_state(tmp_path, monkeypatch):
    monkeypatch.setattr(at, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(at, "STATE_LOCK_PATH", tmp_path / "state.lock")
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)


def test_a_stale_cycle_cannot_resurrect_a_closed_position(tmp_path,
                                                          monkeypatch):
    """The XAUT incident. 2026-08-18 00:20:48 the operator closed a real short
    from the app; a runner cycle that had already started then saved its own
    copy, which still held the position, and the runner "stopped out" that
    phantom 28 more times at -0.96 apiece through 2026-08-19 07:44. MEXC's
    all-time XAUT figure is -1.01 USDT; the ledger's was -32.39."""
    _scratch_state(tmp_path, monkeypatch)
    at.save_state({"PI_USDT": {"step": 3, "position": {"entry": 0.08707}}})
    runner, ui = at.load_state(), at.load_state()

    ui["PI_USDT"]["position"] = None              # exchange-confirmed close
    at.save_state(ui, keys=["PI_USDT"])

    runner["PI_USDT"]["step"] = 4                 # stale cycle finishes
    at.save_state(runner, keys=["PI_USDT"])

    assert at.load_state()["PI_USDT"]["position"] is None, \
        "the closed position came back — the race is open again"


def test_a_normal_write_is_not_blocked(tmp_path, monkeypatch):
    """The guard must only fire on a genuine conflict, or the runner can never
    record anything."""
    _scratch_state(tmp_path, monkeypatch)
    at.save_state({"PI_USDT": {"step": 1}})
    s = at.load_state()
    s["PI_USDT"]["step"] = 9
    at.save_state(s, keys=["PI_USDT"])
    assert at.load_state()["PI_USDT"]["step"] == 9


def test_a_save_never_touches_a_slot_it_did_not_name(tmp_path, monkeypatch):
    """`close_one` writes one coin. A whole-file write is what let one writer
    undo another."""
    _scratch_state(tmp_path, monkeypatch)
    at.save_state({"PI_USDT": {"step": 1}, "APEX_USDT": {"step": 6}})
    s = at.load_state()
    s["APEX_USDT"] = {"step": 0}                  # stale in this copy
    s["PI_USDT"] = {"step": 2}
    at.save_state(s, keys=["PI_USDT"])
    after = at.load_state()
    assert after["APEX_USDT"]["step"] == 6, "an undeclared slot was written"
    assert after["PI_USDT"]["step"] == 2


def test_every_state_writer_declares_its_slots():
    """A bare save_state(state) is the bug. Every caller must name its keys."""
    import inspect
    import re
    src = inspect.getsource(at)
    bare = re.findall(r"save_state\(state\)", src)
    assert bare == [], f"{len(bare)} whole-file state writes remain"


def test_the_paper_poll_does_not_hammer_the_venue():
    """It was 5 seconds, which bought nothing — the paper exit check replays
    one-minute candle RANGES, so the poll cannot beat the data's resolution.
    What it did buy, measured 2026-08-19: 77 scans in one minute, 166 code-510
    refusals, 668 paper exit checks with no price at all, a 106 MB log."""
    assert at.DRY_EXIT_POLL_SECONDS >= 60


def test_a_failed_size_leaves_the_candle_unseen():
    """2026-08-18 19:00: a rate-limited contract read raised inside sizing,
    ALICE's entry died, and the candle had already been ticked off — so the
    signal was never retried."""
    import inspect
    src = inspect.getsource(at.process_symbol)
    assert "_prev_seen = st[\"last_ts\"].get(spec[\"interval\"], 0)" in src
    assert src.count('st["last_ts"][spec["interval"]] = _prev_seen') == 2, \
        "both the sizing and the order path must hand the candle back"
    assert "size_failed" in src and "order_failed" in src


def test_the_suite_can_never_write_to_the_operators_live_book():
    """The canary for the 2026-08-19 finding: a test drove `process_symbol`
    through its exit path with LEDGER_PATH still pointing at
    ~/.tradingagents/auto_trade_ledger.jsonl, so every run of the suite wrote a
    real-looking `XAUT_USDT exit SL -0.96 dry_run false` row. 86 accumulated,
    which is why the app read XAUT at -32.39 all-time against MEXC's -1.01 —
    and the daily loss limit reads those rows, so running the tests could have
    halted live trading."""
    import pathlib
    home = pathlib.Path.home() / ".tradingagents"
    for name in ("STATE_PATH", "LEDGER_PATH", "SETTINGS_PATH", "LOG_PATH",
                 "PID_PATH", "KILL_PATH", "STATE_LOCK_PATH"):
        p = pathlib.Path(str(getattr(at, name)))
        assert home not in p.parents, f"{name} still points at the live book: {p}"

    at.append_ledger({"symbol": "CANARY_USDT", "action": "exit",
                      "pnl_est": -1.0, "dry_run": False})
    assert at.LEDGER_PATH.exists()
    assert "CANARY_USDT" in at.LEDGER_PATH.read_text()


def test_nothing_is_defined_after_the_runner_entry_point():
    """The runner starts with `python -m tradingagents.auto_trader run`, so the
    module body executes top to bottom and STOPS at the __main__ guard — never
    defining anything below it. A plain `import` runs the whole file, so the
    API and every test still see those names and nothing looks wrong.

    On 2026-08-22 save_settings and timeframe_locks sat below the guard and
    every LIVE cycle raised `name 'timeframe_locks' is not defined`: 1,176
    failures across five hours, four coins a cycle, while the paper book kept
    printing healthy scan lines beside them.
    """
    import ast
    import pathlib

    for mod in ("tradingagents/auto_trader.py", "tradingagents/db_jobs.py",
                "tradingagents/daily_grid.py", "tradingagents/market_sweep.py",
                "tradingagents/rows_index.py"):
        p = pathlib.Path(mod)
        if not p.exists():
            continue
        tree = ast.parse(p.read_text())
        guard = next((n.lineno for n in tree.body
                      if isinstance(n, ast.If)
                      and ast.unparse(n.test).startswith("__name__")), None)
        if guard is None:
            continue
        after = [f"{type(n).__name__} at line {n.lineno}"
                 for n in tree.body if n.lineno > guard]
        assert not after, (
            f"{mod}: these are invisible when the module runs as __main__:\n  "
            + "\n  ".join(after))


def test_the_runner_can_resolve_the_live_lock_as_main():
    """The specific name that broke, checked the way the RUNNER loads it."""
    import runpy
    import sys

    argv = sys.argv[:]
    sys.argv = ["auto_trader", "__never_runs__"]
    try:
        # run_name is deliberately not "__main__": we want the module body
        # WITHOUT starting the trading loop, then assert the tail defined.
        ns = runpy.run_module("tradingagents.auto_trader", run_name="probe")
    finally:
        sys.argv = argv
    for name in ("timeframe_locks", "save_settings", "process_symbol"):
        assert name in ns, f"{name} is missing from the module namespace"


def test_the_runner_writes_its_own_log_however_it_was_started():
    """The Runner feed reads auto_trade.log and api.py uses that file's mtime
    as the heartbeat. start_runner() redirects the child's stdout into it, but
    launchd sends the identical command to supervisor.log — so a runner the
    supervisor restarted wrote nothing there, the feed froze on the previous
    process's last line, and a healthy runner read as dead."""
    import ast
    import pathlib

    src = pathlib.Path("tradingagents/auto_trader.py").read_text()
    tree = ast.parse(src)
    guard = next(n for n in tree.body
                 if isinstance(n, ast.If)
                 and ast.unparse(n.test).startswith("__name__"))
    body = ast.unparse(guard)
    assert "FileHandler" in body and "LOG_PATH" in body, (
        "the entry point must attach a FileHandler on LOG_PATH")
    assert "StreamHandler" not in body, (
        "a StreamHandler as well would double every line on the UI path, "
        "which redirects stdout into the same file")
