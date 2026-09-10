"""One trade, one id — on demo and on live. And the screen refreshes itself.

Operator, Sep 10, 2026, after a live stop-loss on PSXSTOCK at 8:04pm:

  *"i want the ui realtime when i lose it should show the winrate lose or what
  ever currently i need to refresh it also the trade id in demo and live
  should be the same so i know it has equivalent trade when i find it"*

Both halves were real. Measured on their own book that evening:

* the live PSXSTOCK short and its demo twin entered on the SAME 15m bar
  (`entry_ts` 1789042500 = Sep 10, 2026 8:15pm), same strategy, same side —
  and carried the ids `ZFGQ2QUZ` and `H3J9B9NN`, because the book was part of
  the hash. One signal, two names, no way to pair them.
* `StrategiesGrid` loaded its rows ONCE (its 4-second timer polls the backtest
  job, not the rows), and `TradeHistory` / `PnlPanel` re-fetched only after a
  FAILURE. So the −$0.25 loss sat in the ledger while the screen showed the
  record from before it, until a reload.
"""
import json
import pathlib

import pytest

from tradingagents import auto_trader as at

REPO = pathlib.Path(__file__).resolve().parents[1]
TRADE = REPO / "webapp" / "src" / "components" / "trade"
LIVE_TS = 1_789_042_500          # Sep 10, 2026 8:15pm — a real 15m bar
KEY = "willr14_15m_sl1tp12"


@pytest.fixture(autouse=True)
def spec(monkeypatch):
    """The operator's own strategy, so the bar size is the real one."""
    monkeypatch.setitem(at.STRATEGY_SPECS, KEY,
                        {"interval": "Min15", "bar_seconds": 900,
                         "tp": 1.2, "sl": 1.0})


# --------------------------------------------------------------- the id
def test_the_same_trade_has_one_id_on_both_books():
    live = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1, False)
    demo = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1, True)
    assert live == demo, "a demo trade and its live twin must share a name"
    assert len(live) == 8 and live.isupper()
    # and it is not the OLD id either — the rule changed on purpose
    assert live not in ("ZFGQ2QUZ", "H3J9B9NN")


def test_two_different_trades_still_have_different_ids():
    base = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1)
    assert base != at.trade_code("PDDSTOCK_USDT", KEY, LIVE_TS, -1), "coin"
    assert base != at.trade_code("PSXSTOCK_USDT", "stoch14_15m_sl1tp12",
                                 LIVE_TS, -1), "strategy"
    assert base != at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, 1), "side"
    assert base != at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS + 900, -1), "bar"


def test_a_few_seconds_apart_inside_one_bar_is_one_trade():
    """The two books are entered in the same cycle but not the same instant.
    The bar is what they share, so the seconds are floored away."""
    a = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS + 3, -1, False)
    b = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS + 61, -1, True)
    assert a == b == at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1)


def test_the_book_is_still_accepted_and_simply_ignored():
    """Every caller passes `dry`; changing the signature would have been a
    bigger blast radius than the fix."""
    import inspect

    assert "dry" in inspect.signature(at.trade_code).parameters
    src = inspect.getsource(at.trade_code)
    assert '"paper" if dry else "live"' not in src, "the book is out of the hash"
    assert "seed" in src and "dry" not in src.split("seed = ")[1].split("\n)")[0]


# ------------------------------------------------------------ the history
def _ledger(tmp_path, rows):
    p = tmp_path / "ledger.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _pair_rows():
    """One signal, acted on twice: live and demo, entered and exited."""
    out = []
    for dry in (False, True):
        out.append({"ts": LIVE_TS + 2, "action": "enter", "symbol": "PSXSTOCK_USDT",
                    "strategy": KEY, "side": "SHORT", "dry_run": dry,
                    "entry_ts": LIVE_TS, "trade_id": "OLD1" + ("D" if dry else "L") + "234"})
        out.append({"ts": LIVE_TS + 3000, "action": "exit", "symbol": "PSXSTOCK_USDT",
                    "strategy": KEY, "side": "SHORT", "dry_run": dry, "why": "SL",
                    "pnl_est": -0.25, "trade_id": "OLD1" + ("D" if dry else "L") + "234"})
    return out


def test_restamp_makes_the_two_books_match_in_history(tmp_path, monkeypatch):
    p = _ledger(tmp_path, _pair_rows())
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    got = at.backfill_ledger_ids(p, restamp=True)
    assert got["written"] and got["entered"] == 2
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    ids = {(r["action"], r["dry_run"]): r["trade_id"] for r in rows}
    want = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1)
    assert set(ids.values()) == {want}, ids
    # the exit keeps its own entry's id — the FIFO pairing is untouched
    assert ids[("enter", True)] == ids[("exit", True)]


def test_without_restamp_an_existing_id_is_left_alone(tmp_path, monkeypatch):
    p = _ledger(tmp_path, _pair_rows())
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    at.backfill_ledger_ids(p)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert {r["trade_id"] for r in rows} == {"OLD1L234", "OLD1D234"}


def test_a_row_with_no_id_is_still_filled_in(tmp_path, monkeypatch):
    rows = _pair_rows()
    for r in rows:
        r.pop("trade_id")
    p = _ledger(tmp_path, rows)
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    at.backfill_ledger_ids(p)
    got = [json.loads(x)["trade_id"] for x in p.read_text(encoding="utf-8").splitlines()]
    assert len(set(got)) == 1 and all(got)


# --------------------------------------------------------- the open trades
def test_an_open_pair_is_restamped_to_one_id(tmp_path, monkeypatch):
    """The pair the operator is actually watching is OPEN, and its id lives in
    the shared book, not the ledger."""
    state = {
        "PSXSTOCK_USDT": {"position": {"strategy": KEY, "entry_ts": LIVE_TS,
                                       "side": -1, "dry": False,
                                       "trade_id": "ZFGQ2QUZ"}},
        "PSXSTOCK_USDT#paper#" + KEY: {"position": {"strategy": KEY,
                                                    "entry_ts": LIVE_TS,
                                                    "side": -1, "dry": True,
                                                    "trade_id": "H3J9B9NN"}},
        "NOTHING_USDT": {"position": None},
        "_rev": {},
    }
    saved = {}
    monkeypatch.setattr(at, "load_state", lambda: state)
    monkeypatch.setattr(at, "save_state",
                        lambda s, keys=None: saved.update({"keys": list(keys or [])}))
    got = at.restamp_open_trade_ids()
    want = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1)
    assert state["PSXSTOCK_USDT"]["position"]["trade_id"] == want
    assert state["PSXSTOCK_USDT#paper#" + KEY]["position"]["trade_id"] == want
    assert len(got["changed"]) == 2 and got["changed"][0]["was"] == "ZFGQ2QUZ"
    assert set(saved["keys"]) == {"PSXSTOCK_USDT", "PSXSTOCK_USDT#paper#" + KEY}, \
        "only the slots that changed are written, so the runner is not clobbered"


def test_restamping_twice_changes_nothing(tmp_path, monkeypatch):
    want = at.trade_code("PSXSTOCK_USDT", KEY, LIVE_TS, -1)
    state = {"PSXSTOCK_USDT": {"position": {"strategy": KEY, "entry_ts": LIVE_TS,
                                            "side": -1, "trade_id": want}},
             "_rev": {}}
    monkeypatch.setattr(at, "load_state", lambda: state)
    monkeypatch.setattr(at, "save_state",
                        lambda s, keys=None: pytest.fail("nothing to write"))
    got = at.restamp_open_trade_ids()
    assert got["changed"] == [] and got["unchanged"] == 1


# ------------------------------------------------------------- the screen
def test_the_panels_that_show_money_refresh_themselves():
    """Each of these showed a number that MOVES and did not move it."""
    for name, why in (("StrategiesGrid.tsx", "LIVE $ and LIVE W/L"),
                      ("TradeHistory.tsx", "a trade that just closed"),
                      ("PnlPanel.tsx", "today's profit"),
                      ("PositionsPanel.tsx", "an open position's unrealized")):
        src = (TRADE / name).read_text(encoding="utf-8")
        assert "useLiveRefresh(" in src, f"{name} does not refresh: {why}"
        assert 'from "@/lib/live"' in src, name
    grid = (TRADE / "StrategiesGrid.tsx").read_text(encoding="utf-8")
    assert "useLiveRefresh(load, 5_000" in grid, \
        "the ROWS must refresh, not only the backtest-job poll beside them"
    assert "useEffect(() => { load(); }, [load]);" not in grid, \
        "the load-once effect is what froze the W/L"


def test_a_background_tab_is_caught_up_the_moment_it_is_looked_at():
    """A hidden tab's timers are throttled to about one a minute, so an
    interval alone leaves the operator staring at stale numbers on return —
    which is what "i need to refresh it" describes."""
    src = (REPO / "webapp" / "src" / "lib" / "live.ts").read_text(encoding="utf-8")
    assert 'addEventListener("visibilitychange"' in src
    assert 'addEventListener("focus"' in src
    assert "document.hidden" in src, "and a hidden tab must not keep polling"
    assert "removeEventListener" in src, "both listeners come off on unmount"
    # the callback is held in a ref: a fresh closure each render must not
    # restart the timer, or a panel that re-renders often never ticks
    assert "useRef(load)" in src and "fn.current = load" in src
