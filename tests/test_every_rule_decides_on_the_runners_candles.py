"""Every strategy rule decides on the live trader's candles exactly what the
backtest decided at the same bar (Oct 21, 2026).

The live trader reads 300 candles (299 closed) before it decides a signal;
the backtest walks a frame of hundreds or thousands of bars. A rule whose
indicator REMEMBERS further back than the trader can see — a recursive EMA or
Wilder ATR of 200 bars — reads a different number live than in the backtest,
and trades a signal no backtest measured. Measured on 24 real Gate frames the
same day: 124 of 130 rules agreed on every bar, six did not (cf_emarsi x3 on
the 200-bar EMA, cf_eqhl and cf_obretest on the 200-bar ATR, cx_4h built on
them) — 62 switched-on strategies in the rooms used two of them.

The operator: "adjust the ones that needs to be adjusted according to your
intuition". This holds the CLASS: every rule in the registry, on real candles,
so a rule added later with a long memory fails here the day it lands.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

import tradingagents.auto_trader as at
from tradingagents import backtest_report as br

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gate_candles_oct21.json.gz"
TAIL = 299              # the trader's closed candles (auto_trader: 300 fetched, the forming one dropped)
LAST = 60               # decision bars compared per frame: the newest ones


def _frames() -> dict:
    with gzip.open(FIXTURE, "rt", encoding="utf-8") as fh:
        return json.load(fh)["frames"]


FRAMES = _frames()


def _dirs(key, f, a=0, b=None):
    b = len(f["c"]) if b is None else b
    return at._dirs_for_backtest(key, f["h"][a:b], f["l"][a:b], f["c"][a:b], opens=f["o"][a:b],
                                 volume=f["v"][a:b], ts=f["t"][a:b])


@pytest.mark.parametrize("name", sorted(FRAMES))
def test_every_rule_decides_the_same_on_299_candles(name):
    f = FRAMES[name]
    tf = name.rsplit("-", 1)[1]
    iv, bs, _cap = br.TFS[tf]
    n = len(f["c"])
    differ = []
    for sig in br.SIGNALS:
        key = f"{sig}_bt_{tf}"
        at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bs, "tp": .02, "sl": .01,
                                  "threshold": .003}
        try:
            dk = "rsi14_1h" if sig == "rsi14" else key
            full = _dirs(dk, f)
            for end in range(n - LAST + 1, n + 1):
                live = int(_dirs(dk, f, end - TAIL, end)[-1])
                if live != int(full[end - 1]):
                    differ.append(f"{sig} bar {end - 1}: live {live}, backtest {int(full[end - 1])}")
        finally:
            at.STRATEGY_SPECS.pop(key, None)
    assert not differ, f"{name}: {len(differ)} decisions differ — {differ[:8]}"
