"""The account forecast, and the four cost/deployment defects fixed beside it.

Operator, `Sep 23, 2026`, after the same 80 rows read **97.3%** in Backtest
v2, **72.0%** on the practice book and **57.1%** live: *"okay start fixing the
bugs now and apply the recommendation you said i want forecast to be 10/10"*.

What these tests hold (docs/RCA.md RCA-2026-09-23-B..F):

* the replay walks EVERY deployed row together through the runner's gates —
  one coin at a time (`max_slices`), an opposite side refused, the cost gate
  fed by the venue's own book readings and refusing an UNKNOWN book, entry at
  the next bar's open, exits by the minute, both prices in one minute a loss,
  Martingale doubling when the book has it on and a flat twin beside it;
* a backtest charges the BOOK's slippage wherever a trade is simulated;
* the fade15 thresholds are fractions, not percentages;
* a delisted coin is disarmed, not left deployed;
* the paper book pays the exchange fee ONCE, and the fee helper believes the
  venue's fills over a spec that under-states.
"""
from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

import pytest

import tradingagents.auto_trader as at
from tradingagents import portfolio_replay as pr, stores

ROOT = Path(__file__).resolve().parents[1]

KEY_A = "stoch14_15m_sl12tp12"     # TP 1.2% / SL 1.2%, 15m
KEY_B = "willr14_15m_sl12tp12"     # its twin: same bars, same prices
SYM = "AAA_USDT"
T0 = 1_790_000_100_000             # ms; 1,790,000,100 s is a multiple of 900, a quarter-hour edge


def _minutes(n: int, px: float = 100.0):
    """n flat one-minute bars from T0 — the canvas the tests paint on."""
    t = [T0 + i * 60_000 for i in range(n)]
    return {"t": t, "o": [px] * n, "h": [px] * n, "l": [px] * n,
            "c": [px] * n, "v": [1.0] * n}


def _store(tmp_path: Path, bars: dict, *, fee=0.0008, slippage=0.0002):
    home = tmp_path / "v2"
    (home / "candles").mkdir(parents=True)
    (home / "costs").mkdir(parents=True)
    (home / "candles" / f"{SYM}-1m.json").write_text(json.dumps(bars))
    (home / "costs" / f"{SYM}.json").write_text(json.dumps(
        {"symbol": SYM, "fee": fee, "slippage": slippage, "liq": None,
         "funding": []}))
    return stores.Store(name="v2", home=home, candles=home / "candles",
                        rows_db=home / "rows.db", parquet=home / "parquet",
                        fine_tf="1m",
                        download_kind="download_v2", backtest_kind="backtest_v2")


def _settings(**over):
    s = {"strategy_coins": {KEY_A: [SYM], KEY_B: [SYM]}, "margin": 5,
         "partial_tp_demo": True, "partial_max_slices": 4,
         "martingale_demo": False}
    s.update(over)
    return s


@pytest.fixture
def signal_on_bar_two(monkeypatch):
    """Both rows fire LONG on the third 15m bar and nowhere else."""
    def fake_dirs(key, high, low, close, opens=None, volume=None, ts=None,
                  funding=None):
        d = [0] * len(close)
        if len(d) > 3:
            d[2] = 1
        return d
    monkeypatch.setattr(at, "_dirs_for_backtest", fake_dirs)
    return fake_dirs


def _readings(cost: float, at_ms: int = T0 + 45 * 60_000):
    """The venue's book, read once, at the close of bar 2."""
    return {SYM: ([at_ms], [cost])}


# ----------------------------------------------------------- the replay
def test_the_entry_is_the_next_bars_open_and_the_exit_is_the_first_minute_touched(
        tmp_path, signal_on_bar_two):
    bars = _minutes(120)
    # bar 3 (minutes 45-59) opens at 100; minute 52 touches the win price
    bars["h"][52] = 101.3
    store = _store(tmp_path, bars)
    r = pr.replay(_settings(), store=store, readings=_readings(0.002))
    assert r["trades"] == 2, r["refused"]
    t = r["log"][0]
    assert t["entry_ms"] == T0 + 45 * 60_000, "the bar closes at the next open"
    assert t["entry"] == 100.0
    assert t["why"] == "TP" and t["exit_ms"] == T0 + 52 * 60_000
    assert t["unclear"] == 0
    # (move - cost) * margin * leverage, cost = the book's reading
    assert t["pnl"] == pytest.approx((0.012 - 0.002) * 5 * at.LEVERAGE, abs=1e-6)
    assert t["cost_source"] == "record"


def test_both_prices_in_one_minute_is_the_loss_and_is_counted(tmp_path,
                                                              signal_on_bar_two):
    bars = _minutes(120)
    bars["h"][50], bars["l"][50] = 101.3, 98.7
    r = pr.replay(_settings(), store=_store(tmp_path, bars),
                  readings=_readings(0.002))
    assert r["trades"] == 2 and r["losses"] == 2
    assert r["unclear"] == 2
    assert all(t["why"] == "SL" and t["unclear"] == 1 for t in r["log"])


def test_one_coin_holds_at_most_max_slices_rows(tmp_path, signal_on_bar_two):
    bars = _minutes(120)
    bars["h"][52] = 101.3
    store = _store(tmp_path, bars)
    one = pr.replay(_settings(partial_max_slices=1), store=store,
                    readings=_readings(0.002))
    assert one["trades"] == 1 and one["refused"] == {"coin_busy": 1}
    both = pr.replay(_settings(partial_max_slices=4), store=store,
                     readings=_readings(0.002))
    assert both["trades"] == 2 and both["refused"] == {}


def test_an_opposite_side_on_a_held_coin_is_refused(tmp_path, monkeypatch):
    def dirs(key, *a, **k):
        d = [0] * len(a[2])
        d[2] = 1 if key == KEY_A else -1
        return d
    monkeypatch.setattr(at, "_dirs_for_backtest", dirs)
    bars = _minutes(120)
    bars["h"][52] = 101.3
    r = pr.replay(_settings(), store=_store(tmp_path, bars),
                  readings=_readings(0.002))
    assert r["trades"] == 1
    assert r["refused"] == {"opposite_side": 1}


def test_the_cost_gate_reads_the_venues_book_and_refuses_half_the_target(
        tmp_path, signal_on_bar_two):
    bars = _minutes(120)
    bars["h"][52] = 101.3
    store = _store(tmp_path, bars)
    # 0.6% round trip against a 1.2% target is exactly the 50% line
    wide = pr.replay(_settings(), store=store, readings=_readings(0.006))
    assert wide["trades"] == 0 and wide["refused"] == {"cost_gate": 2}
    tight = pr.replay(_settings(), store=store, readings=_readings(0.0059))
    assert tight["trades"] == 2


def test_an_unknown_book_is_refused_never_guessed(tmp_path, signal_on_bar_two):
    """Rule 12's shape: the runner refuses a book it cannot read. A reading
    older than the gate's own cache does not count, and the saved snapshot is
    never charged in its place — that snapshot (0.16%-0.22%) is how 508
    'wins' were booked over Sep 04-15, 2026 on books reading 0.6%-2.8%."""
    bars = _minutes(120)
    bars["h"][52] = 101.3
    store = _store(tmp_path, bars)
    none = pr.replay(_settings(), store=store, readings={})
    assert none["trades"] == 0 and none["refused"] == {"book_unknown": 2}
    stale = pr.replay(_settings(), store=store,
                      readings=_readings(0.002, at_ms=T0 + 45 * 60_000
                                         - pr.READING_TOL_MS - 1))
    assert stale["trades"] == 0 and stale["refused"] == {"book_unknown": 2}
    assert pr.READING_TOL_MS == at._GATE_TTL * 1000, \
        "a reading counts only as long as the runner's own gate would use it"
    assert not any(t["cost_source"] == "saved" for t in none["log"])


def test_martingale_doubles_after_a_loss_when_the_book_has_it_on_and_the_flat_twin_does_not(
        tmp_path, monkeypatch):
    def dirs(key, *a, **k):
        d = [0] * len(a[2])
        d[2] = 1          # bar 2 -> loses
        d[6] = 1          # bar 6 -> wins
        return d
    monkeypatch.setattr(at, "_dirs_for_backtest", dirs)
    bars = _minutes(200)
    bars["l"][50] = 98.7                    # first trade stops out
    bars["h"][110] = 101.3                  # second trade wins
    store = _store(tmp_path, bars)
    rd = {SYM: ([T0 + 45 * 60_000, T0 + 105 * 60_000], [0.002, 0.002])}
    on = pr.replay(_settings(martingale_demo=True, partial_max_slices=1,
                             strategy_coins={KEY_A: [SYM]}),
                   store=store, readings=rd)
    assert on["sizing"] == "martingale"
    assert [t["margin"] for t in on["log"]] == [5, 10]
    flat = pr.replay(_settings(martingale_demo=True, partial_max_slices=1,
                               strategy_coins={KEY_A: [SYM]}),
                     store=store, readings=rd, sizing="flat")
    assert flat["sizing"] == "flat"
    assert [t["margin"] for t in flat["log"]] == [5, 5]


def test_every_deployed_row_is_accounted_for(tmp_path, signal_on_bar_two):
    """Kit item F: no row disappears. A row that never traded says why."""
    bars = _minutes(120)
    bars["h"][52] = 101.3
    s = _settings(strategy_coins={KEY_A: [SYM], KEY_B: [SYM],
                                  "ote_1h_sl3tp1": ["NOPE_USDT"]})
    r = pr.replay(s, store=_store(tmp_path, bars), readings=_readings(0.002))
    assert r["rows_deployed"] == 3
    assert r["rows_traded"] == 2
    assert r["rows_refused"] == {"ote_1h_sl3tp1|NOPE_USDT":
                                 "no 1-minute candles in the v2 store"}
    for row in r["rows"]:
        for col in ("tp", "sl", "trades", "wins", "losses", "pnl", "worst_run",
                    "win_rate", "signals", "cost_refused"):
            assert col in row, col


def test_the_window_and_the_deploy_date_cut_the_signals(tmp_path, monkeypatch,
                                                         signal_on_bar_two):
    bars = _minutes(120)
    bars["h"][52] = 101.3
    store = _store(tmp_path, bars)
    late = pr.replay(_settings(), store=store, readings=_readings(0.002),
                     since_ms=T0 + 46 * 60_000)
    assert late["trades"] == 0 and late["signals"] == 0
    monkeypatch.setattr(pr.local_history, "deployed_at",
                        lambda: {f"{KEY_A}|{SYM}": {"at": (T0 + 46 * 60_000) // 1000,
                                                    "from": None}})
    dep = pr.replay(_settings(), store=store, readings=_readings(0.002),
                    from_deployed=True)
    assert dep["trades"] == 1, "KEY_B has no deploy date and keeps its signal"
    assert dep["log"][0]["key"] == KEY_B


# ------------------------------------------------ the record it is read against
def test_book_readings_come_from_the_recorder_the_refusals_and_the_fills(tmp_path):
    rec = tmp_path / "book_readings.jsonl"
    rec.write_text(json.dumps({"ts": 1_790_000_000, "symbol": SYM,
                               "round_trip": 0.0031}) + "\n")
    rows = [
        {"ts": 1_790_000_100, "symbol": SYM, "action": "gate_blocked", "dry_run": True,
         "why": "round-trip cost 2.490% vs take-profit 0.40% = 623% of the target"},
        {"ts": 1_790_000_200, "symbol": SYM, "action": "enter", "dry_run": True,
         "trade_id": "T1", "margin": 5.0, "leverage": 20, "opened_at": 1_790_000_201},
        # a LONG from 100 to 101.2 booking +$1.00 on $100 BEFORE the fix: the
        # realised 0.2% carries the doubled fee, which is taken back out
        {"ts": pr.DEMO_FEE_TWICE_UNTIL_S - 10, "symbol": SYM, "action": "exit",
         "dry_run": True, "trade_id": "T1", "why": "TP", "side": "LONG",
         "entry": 100.0, "exit": 101.2, "pnl_est": 1.00},
        {"ts": 1_790_000_300, "symbol": SYM, "action": "gate_blocked", "dry_run": False,
         "why": "round-trip cost 9.000% vs take-profit 0.40% = 623% of the target"},
    ]
    rd = pr.book_readings(rows, dry=True, readings_path=rec)
    ts, cs = rd[SYM]
    assert ts == [1_790_000_000_000, 1_790_000_100_000, 1_790_000_201_000]
    assert cs[0] == pytest.approx(0.0031)
    assert cs[1] == pytest.approx(0.0249)
    assert cs[2] == pytest.approx(0.012 - 1.00 / 100.0 - 2 * at.FEE_FALLBACK)
    assert 0.09 not in cs, "the live book's readings are the live book's"


def test_an_old_demo_exit_has_the_doubled_fee_taken_back_out():
    rows = [
        {"ts": 1_790_000_200, "symbol": SYM, "action": "enter", "dry_run": True,
         "trade_id": "T1", "margin": 5.0, "leverage": 20, "opened_at": 1_790_000_201},
        {"ts": pr.DEMO_FEE_TWICE_UNTIL_S - 10, "symbol": SYM, "action": "exit",
         "dry_run": True, "trade_id": "T1", "why": "TP", "side": "LONG",
         "entry": 100.0, "exit": 101.2, "pnl_est": 1.00},
    ]
    rd = pr.book_readings(rows, dry=True, readings_path=Path("nowhere"))
    assert rd[SYM][1][0] == pytest.approx(0.012 - 0.01 - 2 * at.FEE_FALLBACK)
    act = pr.demo_actual(rows, dry=True, base=10.0)
    assert act["trades"] == 1 and act["pnl"] == 1.0
    assert act["pnl_fee_once"] == pytest.approx(1.0 + 2 * at.FEE_FALLBACK * 100, abs=0.01)
    assert act["pnl_at_base"] == pytest.approx(act["pnl_fee_once"] * 2, abs=0.01)


def test_the_gate_records_every_fresh_book_read_once_a_second(tmp_path, monkeypatch):
    p = tmp_path / "book_readings.jsonl"
    monkeypatch.setattr(at, "BOOK_READINGS_PATH", p)
    monkeypatch.setattr(at, "_LAST_READING", {})
    monkeypatch.setattr(at.time, "time", lambda: 1_790_000_000.4)
    at._record_book_reading(SYM, 0.0031, {"spread": 0.001, "slippage": 0.0005})
    at._record_book_reading(SYM, 0.0032, {"spread": 0.001, "slippage": 0.0005})
    at._record_book_reading("BBB_USDT", 0.01, {})
    lines = [json.loads(x) for x in p.read_text().splitlines()]
    assert [(r["symbol"], r["round_trip"]) for r in lines] == [
        (SYM, 0.0031), ("BBB_USDT", 0.01)]
    # and edge_check calls it right after it computes the round trip
    src = inspect.getsource(at.edge_check)
    assert "_record_book_reading(symbol, round_trip, m)" in src
    # never raises: a path that cannot be written is not a trading error
    monkeypatch.setattr(at, "BOOK_READINGS_PATH", tmp_path / "no" / "such" / "dir.jsonl")
    at._record_book_reading("CCC_USDT", 0.01, {})


def test_the_forecast_is_served_on_backtest_v2_with_its_ids():
    src = (ROOT / "tradingagents" / "api.py").read_text(encoding="utf-8")
    assert '@app.get("/api/v2/portfolio")' in src
    i = src.index('@app.get("/api/v2/portfolio")')
    frag = src[i:i + 2500]
    assert "pr.forecast(dry=dry)" in frag
    assert 'r["id"] = row_id_for(r["key"], r["coin"], settings)' in frag
    ts = (ROOT / "webapp" / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    assert "`${P}/portfolio?book=${book}" in ts
    page = (ROOT / "webapp" / "src" / "app" / "(admin)" / "backtest-v2" / "page.tsx"
            ).read_text(encoding="utf-8")
    assert "<PortfolioForecast />" in page
    panel = (ROOT / "webapp" / "src" / "components" / "backtest" /
             "PortfolioForecast.tsx").read_text(encoding="utf-8")
    # the mandatory columns, every row (CLAUDE.md items 1-8)
    for col in ('head("TP")', 'head("SL")', '"profit $", "pnl"', '"worst run $"',
                '"wins", "wins"', '"losses", "losses"', 'head("id")'):
        assert col in panel, col
    assert "TOTAL PROFIT" in panel
    assert "book_unknown" in panel, "every refusal has words"
    assert ".toLocale" not in panel.replace(".toLocaleString()", "")


# ------------------------------------------- RCA-A: the backtest charges the book
def test_every_simulated_trade_charges_the_books_slippage():
    """One trade, one cost, wherever it is simulated. The engine's flat
    0.03%/side under-charged the operator's coins by ~0.13% a trade against
    the practice book (Sep 23, 2026): 0.220% charged, 0.350% paid."""
    ms = (ROOT / "tradingagents" / "market_sweep.py").read_text(encoding="utf-8")
    tree = ast.parse(ms)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "backtest_strategy"]
    assert len(calls) >= 6, "the engine is called from run_pair, restate, trades_for, window_rows"
    for c in calls:
        kws = {k.arg for k in c.keywords}
        assert "slippage" in kws, f"line {c.lineno}: the engine call has no slippage= — it would charge the flat default"
    assert 'save_costs(symbol, fee=fee, liq=liq, funding=fund, slippage=slip)' in ms
    assert '"slippage": slippage,' in ms, "the cost file keeps the book's slippage"
    shard = (ROOT / ".github" / "scripts" / "sweep_shard.py").read_text(encoding="utf-8")
    assert "0.0003, ladder" not in shard, "the cloud shard no longer hard-codes the flat slippage"
    assert shard.count("slippage=slip") >= 2 and "fee=fee + slip" in shard
    rs = (ROOT / "tradingagents" / "resume_state.py").read_text(encoding="utf-8")
    assert "slippage: float | None = None" in rs and '"slippage": float(slippage)' in rs


# ---------------------------------------------- RCA-B: fade15's thresholds
def test_no_spec_threshold_is_a_percentage_wearing_a_fractions_clothes():
    """`fade15_1h_sl3tp06` carried `threshold: 0.5` — a 50% one-hour move,
    which has never happened, so the row measured 0 signals ever and was
    deployed on 6 coins at a 100% win rate over 0 trades. 0.005 fires 940
    times over the same bars."""
    for key, spec in at.STRATEGY_SPECS.items():
        th = spec.get("threshold")
        if th is None:
            continue
        assert float(th) < 0.05, f"{key}: threshold {th} is a percentage, not a fraction"
    assert at.STRATEGY_SPECS["fade15_1h_sl3tp06"]["threshold"] == 0.005
    assert at.STRATEGY_SPECS["fade15_4h_sl3tp1"]["threshold"] == 0.004


# ------------------------------------------- RCA-C: a delisted coin is disarmed
def test_a_delisted_coin_is_disarmed_from_every_row_and_written_down(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr(at, "save_settings", lambda s: saved.update(s))
    monkeypatch.setattr(at, "load_settings", lambda: {
        "strategy_coins": {KEY_A: ["ROLSTOCK_USDT", SYM], KEY_B: ["ROLSTOCK_USDT"]},
        "strategy_books": {at.book_slot(KEY_A, "ROLSTOCK_USDT"): "demo",
                           at.book_slot(KEY_A, SYM): "demo"}})
    recorded = []
    monkeypatch.setattr(pr.local_history, "record_deployment",
                        lambda *a, **k: recorded.append((a, k)))
    out = at.disarm_coins({"ROLSTOCK_USDT"}, why="delisted")
    assert out["removed"] == {"ROLSTOCK_USDT": [KEY_A, KEY_B]}
    assert out["rows"] == 2
    assert saved["strategy_coins"] == {KEY_A: [SYM], KEY_B: []}
    assert at.book_slot(KEY_A, "ROLSTOCK_USDT") not in saved["strategy_books"]
    assert at.book_slot(KEY_A, SYM) in saved["strategy_books"]
    assert len(recorded) == 2
    sm = (ROOT / "tradingagents" / "storage_months.py").read_text(encoding="utf-8")
    assert "_at.disarm_coins(" in sm, "the delisted cleanup disarms what it forgets"


# ------------------------------------------- RCA-D/E: the fee, once, and real
def test_the_paper_book_charges_the_gates_round_trip_and_nothing_on_top():
    class Fx:
        def contract_spec(self, symbol):
            return {"takerFeeRate": 0}
    gate_rt = 2 * (0.0005 + at.taker_fee(SYM, fx=Fx())) + 0.0001
    assert at.paper_round_trip({"rt_cost": gate_rt}, SYM, fx=Fx()) == gate_rt
    src = inspect.getsource(at._process_slot)
    i = src.index("cost = (paper_round_trip(pos, symbol, fx=fx) if pos_dry")
    frag = src[i:i + 220]
    assert 'pnl = (move - cost) * pos["margin"] * LEVERAGE' in frag
    assert "taker_fee" not in frag


def test_the_fee_helper_believes_the_venues_fills_over_a_low_spec():
    class Fx:
        def __init__(self, rate):
            self.rate = rate
        def contract_spec(self, symbol):
            return {"takerFeeRate": self.rate}
    assert at.taker_fee(SYM, fx=Fx(0.0004)) == at.FEE_FALLBACK
    assert at.taker_fee(SYM, fx=Fx(0)) == at.FEE_FALLBACK
    assert at.taker_fee(SYM, fx=Fx(0.0012)) == 0.0012
    assert at.FEE_FALLBACK == 0.0008, "0.080% a side on 44 of 48 real fills"


def test_the_rca_entries_exist():
    rca = (ROOT / "docs" / "RCA.md").read_text(encoding="utf-8")
    for letter in "BCDEF":
        assert re.search(rf"^## RCA-2026-09-23-{letter} ", rca, re.M), letter


# --------------------------------------- RCA-G: the entry spread, once
def test_the_paper_book_charges_the_entry_spread_once():
    """A paper buy is filled at the ASK, so the entry's half-spread is in the
    fill; the round trip charged at exit holds both sides' slippage. Measured
    0.022% a trade adverse on 92 matched fills (Sep 15-22, 2026). A position
    carrying `book_slippage` pays the round trip less that one side; one
    without it (opened before Sep 23, 2026) pays as before."""
    class Fx:
        def contract_spec(self, symbol):
            return {"takerFeeRate": 0}
    fee = at.taker_fee(SYM, fx=Fx())
    rt = 2 * (0.0005 + fee) + 0.0001
    assert at.paper_round_trip({"rt_cost": rt, "book_slippage": 0.0005}, SYM,
                               fx=Fx()) == pytest.approx(rt - 0.0005)
    assert at.paper_round_trip({"rt_cost": rt}, SYM, fx=Fx()) == rt
    # never below zero, whatever the book said
    assert at.paper_round_trip({"rt_cost": 0.001, "book_slippage": 0.01}, SYM,
                               fx=Fx()) == 0.0
    # and the position is given the figure at entry, from the gate it read
    src = inspect.getsource(at._process_slot)
    assert '"book_slippage": float(gate.get("slippage") or 0.0),' in src


def test_a_fill_is_a_book_reading_only_before_the_recorder_existed():
    rows = [
        {"ts": 1_790_000_200, "symbol": SYM, "action": "enter", "dry_run": True,
         "trade_id": "T1", "margin": 5.0, "leverage": 20, "opened_at": 1_790_000_201},
        {"ts": pr.DEMO_FEE_TWICE_UNTIL_S + 5, "symbol": SYM, "action": "exit",
         "dry_run": True, "trade_id": "T1", "why": "TP", "side": "LONG",
         "entry": 100.0, "exit": 101.2, "pnl_est": 1.00},
    ]
    rd = pr.book_readings(rows, dry=True, readings_path=Path("nowhere"))
    assert SYM not in rd, "after the fix a fill's realised cost is net of the entry spread and is not the gate's number"


# ---------------------------------------------------- twins are named
def test_a_row_that_can_only_copy_another_is_named_its_twin(tmp_path,
                                                             signal_on_bar_two):
    """KEY_A and KEY_B fire on the same bars with the same prices: the second
    is a twin, and the screen says so instead of counting two opinions."""
    bars = _minutes(120)
    bars["h"][52] = 101.3
    r = pr.replay(_settings(), store=_store(tmp_path, bars),
                  readings=_readings(0.002))
    assert r["twins"] == {f"{KEY_B}|{SYM}": f"{KEY_A}|{SYM}"}
    by = {row["row"]: row for row in r["rows"]}
    assert by[f"{KEY_B}|{SYM}"]["twin_of"] == f"{KEY_A}|{SYM}"
    assert by[f"{KEY_A}|{SYM}"]["twin_of"] is None
    panel = (ROOT / "webapp" / "src" / "components" / "backtest" /
             "PortfolioForecast.tsx").read_text(encoding="utf-8")
    assert "twin of #" in panel
    src = (ROOT / "tradingagents" / "api.py").read_text(encoding="utf-8")
    assert 'r["twin_id"] = ids.get(r["twin_of"], "")' in src
