"""The Runner feed may not print a fossil as "last bars".

`Sep 13, 2026 4:01pm`, the operator's own feed, on a runner that had been up
38 hours and whose candle feed was perfectly current:

    scan GPNSTOCK_USDT[real]: 0 of 3 slot(s) open · flat ...
        last_bars=Min15@Sep 05, 2026 9:00am Min30@Sep 13, 2026 3:30pm
    scan KITE_USDT[real]:     0 of 1 slot(s) open · flat ...
        last_bars=Min60@Sep 05, 2026 8:00am

An eight-day-old bar beside a live one reads as a dead data feed, and that is
what it was taken for. Nothing was stale. `last_bars` is a UNION of every
slot's `last_ts`, and a slot's `last_ts` OUTLIVES the strategy that wrote it:

* On `Sep 05, 2026` partial TP/SL moved the real book onto per-strategy slots
  (`SYM#live#KEY`). The BASE slot (`SYM`) is still visited — a position opened
  before the switch must keep being managed by the code that opened it — but
  with `entries=False`, and every `last_ts` write lives in the entry loop. So
  the base slot's stamps froze on the day of the switch.
* On KITE, ROLSTOCK and DVNSTOCK the base slot is the ONLY real slot and
  nothing is armed on the real book at all, so the fossil was the whole line.

Both halves are label failures, not trading failures: no order, no position
and no barrier was ever decided by this value. But the feed is where the
operator looks to answer "why has this coin not traded", and for eight days it
answered with a date.

The rule: a timeframe may speak for a coin only when something on THIS book is
watching it — an armed strategy, or an open position whose strategy was
disarmed while it was holding. And a book with nothing armed says so, because
"none yet" claims a feed that has not delivered, which is a different fault.
"""
from __future__ import annotations

import json
import logging

import pytest

from tradingagents import auto_trader as at
from tradingagents.positions_view import fmt_when

COIN = "GPNSTOCK_USDT"
OTHER = "NGAS_USDT"                 # keeps the real book running
M30 = "stoch14_30m_sl2tp2"          # armed real, writes Min30
M15 = "macddiv_15m_sl15tp15"        # paper only — its Min15 must not speak
FOSSIL = 1788_000_000               # the base slot's frozen stamp
LIVE = 1789_700_000


@pytest.fixture
def runner(tmp_path, monkeypatch):
    for name in ("SETTINGS_PATH", "STATE_PATH", "LEDGER_PATH",
                 "PID_PATH", "KILL_PATH"):
        monkeypatch.setattr(at, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.setattr(at, "STATE_DIR", tmp_path)
    monkeypatch.setattr(at, "STATE_LOCK_PATH", tmp_path / "state.lock")
    # the cycle must do nothing but produce its scan line
    monkeypatch.setattr(at, "process_symbol", lambda *a, **k: None)
    monkeypatch.setattr(at, "reconcile_unconfigured", lambda *a, **k: None)
    monkeypatch.setattr(at, "tripped_strategies", lambda *a, **k: [])
    return tmp_path


def _settings(books, *, coins=None):
    """`books` maps strategy -> books; `coins` overrides which coin each is on."""
    coins = coins or {}
    return {"strategies": list(books), "coins": [COIN], "margin": 1.0,
            "enabled": True, "strategy_books": books,
            "strategy_coins": {k: coins.get(k, [COIN]) for k in books}}


def _scan_lines(caplog, book):
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith(f"scan {COIN}[{book}]")]


def _run(caplog, settings, state):
    at.SETTINGS_PATH.write_text(json.dumps(settings), encoding="utf-8")
    at.save_state(state)
    with caplog.at_level(logging.INFO, logger=at.logger.name):
        at.run_cycle(fx=object())


# ------------------------------------------------------------- the incident
def test_a_frozen_base_slot_does_not_speak_for_the_coin(runner, caplog):
    """GPNSTOCK exactly: a base slot stuck on Sep 05 beside a live Min30."""
    state = {
        COIN: {"step": 0, "position": None,
               "last_ts": {"Min15": FOSSIL, "Min30": FOSSIL}},
        f"{COIN}#live#{M30}": {"step": 0, "position": None,
                               "last_ts": {"Min30": LIVE}},
    }
    _run(caplog, _settings({M30: ["real"], M15: ["paper"]}), state)
    line = _scan_lines(caplog, "real")[0]
    assert "Min30@" in line
    assert "Min15@" not in line, (
        "Min15 is armed on PAPER only — its stamp must not appear on the real "
        f"book's line: {line}")
    assert fmt_when(FOSSIL) not in line, \
        f"the Sep 05 fossil is still being printed as a last bar: {line}"
    assert fmt_when(LIVE) in line


def test_a_book_with_nothing_armed_says_so(runner, caplog):
    """KITE, ROLSTOCK and DVNSTOCK: the fossil was the WHOLE line, on a book
    holding no armed strategy at all."""
    state = {COIN: {"step": 0, "position": None,
                    "last_ts": {"Min60": FOSSIL}}}
    _run(caplog, _settings({M15: ["paper"], M30: ["real"]},
                           coins={M30: [OTHER]}), state)
    line = _scan_lines(caplog, "real")[0]
    assert "nothing armed on this book" in line, line
    assert fmt_when(FOSSIL) not in line


def test_none_yet_still_means_a_feed_that_has_not_delivered(runner, caplog):
    """The two empty states are different and must read differently: armed
    here, but no bar recorded yet."""
    state = {f"{COIN}#live#{M30}": {"step": 0, "position": None,
                                    "last_ts": {}}}
    _run(caplog, _settings({M30: ["real"]}), state)
    line = _scan_lines(caplog, "real")[0]
    assert "none yet" in line, line
    assert "nothing armed" not in line


# ----------------------------------------------------------- no regression
def test_an_armed_timeframe_still_prints(runner, caplog):
    state = {f"{COIN}#live#{M30}": {"step": 0, "position": None,
                                    "last_ts": {"Min30": LIVE}}}
    _run(caplog, _settings({M30: ["real"]}), state)
    assert fmt_when(LIVE) in _scan_lines(caplog, "real")[0]


def test_an_open_position_speaks_even_if_its_strategy_was_disarmed(runner, caplog):
    """A position held by a strategy the operator has since unticked is still
    real money on a real barrier. Its bar is news, not a fossil."""
    gone = M30
    pos = {"side": 1, "vol": 1, "entry": 100.0, "tp": 102.0, "sl": 98.0,
           "margin": 1.0, "strategy": gone, "entry_ts": LIVE,
           "opened_at": LIVE, "dry": False, "bracket": True}
    state = {f"{COIN}#live#{gone}": {"step": 0, "position": pos,
                                     "last_ts": {"Min30": LIVE}}}
    # armed on paper only, yet holding a REAL position. Another strategy
    # keeps the real book running, on a different coin.
    _run(caplog, _settings({gone: ["paper"], M15: ["real"]},
                           coins={M15: [OTHER]}), state)
    line = _scan_lines(caplog, "real")[0]
    assert fmt_when(LIVE) in line, line
    assert "nothing armed on this book" not in line


def test_the_paper_book_keeps_its_own_bars(runner, caplog):
    """The union across per-strategy paper slots is the reason this line
    exists — one line per coin must not claim only one strategy's bar."""
    state = {
        at.state_key(COIN, True, M30): {"step": 0, "position": None,
                                        "last_ts": {"Min30": LIVE}},
        at.state_key(COIN, True, M15): {"step": 0, "position": None,
                                        "last_ts": {"Min15": LIVE - 900}},
    }
    _run(caplog, _settings({M30: ["paper"], M15: ["paper"]}), state)
    line = _scan_lines(caplog, "paper")[0]
    assert "Min30@" in line and "Min15@" in line, line
