"""Multi-coin bracket auto-trader driven by the Auto Trade tab.

Reads the operator's saved settings (strategies, coins, base margin, enabled)
and, once per poll, checks each coin's last CLOSED 4-hour candle for a signal.
A signal opens a market position sized ladder-step × base margin at 20x and
rests the backtested bracket on MEXC's servers (TP +4.5% / SL −1.5%) so the
exit survives this process dying.

Safety model — same as spx_bot, deliberately:

1. The Auto Trade checkbox is the live switch (operator's directive) —
   ticking the Dry-run checkbox or exporting ``AUTO_TRADE_DRY=yes`` forces
   simulation instead. Dry runs
   simulate fills against the candles and write the same ledger, so the
   operator can watch it trade for a while before arming it.
2. A kill file (``~/.tradingagents/auto_trade.KILL``) halts entries instantly.
3. The runner is stopped by PID from its pid file, never by process name.

The ladder is the backtest's DEEP martingale expressed as multiples of the
base margin: 1,1,2,2,4,4,8 — step advances on a loss, resets on a win, and is
capped at the last rung (the backtest's "reset on cap" was never hit in 13
months, so capping is the conservative reading).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pandas as _pd

from tradingagents import portable

logger = logging.getLogger(__name__)

STATE_DIR = Path(os.path.expanduser("~/.tradingagents"))
SETTINGS_PATH = STATE_DIR / "auto_trade.json"
STATE_PATH = STATE_DIR / "auto_trade_state.json"
LEDGER_PATH = STATE_DIR / "auto_trade_ledger.jsonl"
PID_PATH = STATE_DIR / "auto_trade.pid"
LOG_PATH = STATE_DIR / "auto_trade.log"
KILL_PATH = STATE_DIR / "auto_trade.KILL"
# "the operator wants it running". A supervisor watches this file: while it
# exists the runner is restarted whenever it dies, and a deliberate STOP
# removes it, so nothing fights the operator's own decision.
WANT_PATH = STATE_DIR / "auto_trade.WANT"
# held for the process's whole life: the single-instance lock
LOCK_PATH = STATE_DIR / "auto_trade.lock"
_RUN_LOCK = None

BAR_SECONDS = 4 * 3600       # the default (coarsest) strategy timeframe
LEVERAGE = 20
LADDER = (1, 1, 2, 2, 4, 4, 8)   # DEEP ladder as multiples of base margin
POLL_SECONDS = 300           # heartbeat between candle closes
ENTRY_LAG_SECONDS = 3        # wake this soon after a candle boundary
# How often to tick-check simulated positions. This was 5 seconds, which
# bought NOTHING: the paper exit check replays one-minute candle RANGES since
# the trade opened, so any barrier touched between two polls is still caught to
# the minute -- the poll rate cannot improve on the data's own resolution.
# What it did buy was a rate limit. Measured 2026-08-19 on the live account: 77
# scans in a single minute, 166 `code=510 Requests are too frequent` refusals,
# 668 paper exit checks that could not read a price at all (so the position
# stayed open, so the fast poll stayed on), a 106 MB log, and -- because a
# refused reply came back EMPTY rather than as an error -- one cancelled ALICE
# entry on 2026-08-18 19:00. It also rewrote the shared state file every 5
# seconds, which is what let a runner cycle overwrite the UI's CLOSE of XAUT
# and re-book the same stop 28 times for -0.96 apiece.
DRY_EXIT_POLL_SECONDS = 60   # tick-check simulated positions this often
# Candles only change when a bar closes, so re-downloading them on every fast
# wake is pure rate-limit burn — and MEXC answers a hammered client with
# TRUNCATED history, which is how wrong numbers got published earlier today.
# Cached until the bar that produced them is superseded.
_BAR_CACHE: dict = {}
MOM6_THRESHOLD = 0.006       # 4h BTC threshold from the study

# Every strategy carries its own timeframe and bracket — the signal defines
# the rhythm, not the runner. Brackets are the barriers each signal was
# measured with over the same 13 BTC months ($10 base, 20x, DEEP ladder):
#   ict_fvg  4h  +$367.22 (12/13 green)   mom6 4h +$513.98   trend50 4h +$446.33
#   sweep_1h 1h  +$220.16 (9/13 green) — the fastest signal that made money
#   sweep_rt 1m  −$374.81 (5/13 green) — the realtime signal the operator
#                asked for, shipped WITH its measured loss so the choice is
#                informed rather than hidden.
STRATEGY_SPECS = {
    "ict_fvg": {"interval": "Hour4", "bar_seconds": 14400,
                "tp": 0.045, "sl": 0.015},
    "mom6": {"interval": "Hour4", "bar_seconds": 14400,
             "tp": 0.045, "sl": 0.015},
    "trend50": {"interval": "Hour4", "bar_seconds": 14400,
                "tp": 0.045, "sl": 0.015},
    "sweep_1h": {"interval": "Min60", "bar_seconds": 3600,
                 "tp": 0.018, "sl": 0.006},
    "sweep_rt": {"interval": "Min1", "bar_seconds": 60,
                 "tp": 0.018, "sl": 0.006},
    # S&P 500 playbook's best-balanced row: mom15 4h 0.50%/1.50% DEEP —
    # +$116.54 over 13 months, 10/13 green, worst month −$4.08. Index
    # threshold is 0.2% (S&P moves less than BTC per 4h bar).
    "mom15_sp": {"interval": "Hour4", "bar_seconds": 14400,
                 "tp": 0.015, "sl": 0.005, "threshold": 0.002},
    # From the 941-coin sweep (2026-08-12). Thin-book caveat applies: the
    # backtests fill at candle prices with no slippage.
    "mom15_1h": {"interval": "Min60", "bar_seconds": 3600,
                 "tp": 0.018, "sl": 0.006, "threshold": 0.003},
    "fade15_1h": {"interval": "Min60", "bar_seconds": 3600,
                  "tp": 0.018, "sl": 0.006, "threshold": 0.003},
    "fade15_15m": {"interval": "Min15", "bar_seconds": 900,
                   "tp": 0.009, "sl": 0.003, "threshold": 0.003},
    "fade15_1m": {"interval": "Min1", "bar_seconds": 60,
                  "tp": 0.0036, "sl": 0.0012, "threshold": 0.003},
    # Survivors of the 941-coin sweep + split-half holdout + stability re-run
    # (2026-08-12). Same 1h barriers the sweep measured them with.
    "rsi14_1h": {"interval": "Min60", "bar_seconds": 3600,
                 "tp": 0.018, "sl": 0.006},
    # Row #3M3CRXP8 from the 2026-08-19 15m/30m year sweep, deployed on PI at the
    # operator's request. Its barriers are its own: the standing `trend50` key
    # is 4h with TP 4.5 / SL 1.5, and ticking that would have run a DIFFERENT
    # strategy on a different bar (CLAUDE.md rule 21). Not a survivor -- 9/13
    # months green (69.2%, a third of a month under the 70% bar) and a $69.07
    # worst dip against an $80.47 wallet at $5 base.
    "trend50_30m_pi": {"interval": "Min30", "bar_seconds": 1800,
                       "tp": 0.025, "sl": 0.020},
    # --- 1-hour GOLD contracts. XAUT and PAXG are tokenized gold and carry
    # the venue's cheapest taker fee (0.01%/0.04% vs 0.04% on most alts), so
    # a 2.0-2.4% target survives costs that kill the same target on an alt:
    # round-trip cost is 1-4% of the take-profit here. Distinct names because
    # mom15_1h already exists on 1.8%/0.6% barriers and these use their own.
    "mom15_1h_g": {"interval": "Min60", "bar_seconds": 3600,
                   "tp": 0.024, "sl": 0.008, "threshold": 0.003},
    "mom6_1h_g": {"interval": "Min60", "bar_seconds": 3600,
                  "tp": 0.020, "sl": 0.005, "threshold": 0.0015},
    # The ONLY 1-hour config in the 55,062-combination sweep that survived at
    # BOTH sizings on a real year: flat +$36.85 (11/15 green, halves +13.85 /
    # +23.81) AND martingale +$148.65 (14/15 green). Gold's 0.01% fee makes
    # the cost just 1% of the target. Same barriers as the mom15 version it
    # replaces on XAUT — only the signal differs.
    # XAUT, 2026-08-19. Row #CZ7THVJW, the balanced winner of an 11,460-combination
    # sweep over ALICE and XAUT (2 coins x 2 timeframes x 7 signals x 3
    # thresholds x 10 stops x 11 targets x 2 sizings). Replaces SL 0.80 / TP
    # 2.40, and replaces mom15_1h_g on this coin entirely. Measured on 9,999
    # hourly bars (416 days) the moment before deploying: +$94.54, 203 trades,
    # 53.20% win, worst dip $15.80, worst losing streak -$15.80 over 5 trades,
    # green in all 14 months, no liquidations, stop reachable (1.50% inside
    # XAUT's 4.96% liquidation move at 20x).
    "mom6_1h_gx": {"interval": "Min60", "bar_seconds": 3600,
                   "tp": 0.020, "sl": 0.015, "threshold": 0.002},
    # PROVE, 2026-08-17. Winner of a 3,432-combination search over PROVE's own
    # 1-hour year (376 days), with MEXC's 4.50% liquidation modelled so no row
    # could win on a stop the venue would never let fire. Flat-staked it is the
    # ONLY signal on PROVE 1h that survives: +$171.77 over 375 days, 38.8% win
    # over 765 trades, both halves positive (+98 / +70), 10/13 months green,
    # worst trade -$2.10. It replaces trend50_4h, which on the same terms made
    # +$89.57 at 29.5%. The trade-off is the dip: $57 against trend50's $28.
    # PROVE, added 2026-08-19 on the operator's instruction: row #8ZFUXG8F, the
    # single most profitable row of the 130,294-combination August sweep
    # (2026-08-01 to 08-19): +$226.82 at a 12.50% win rate over 48 trades. They
    # labelled it "Best 8.57 for August" -- 8.57 is their figure from the
    # artifact's BALANCED column; the numbers below are the ones I measured.
    #
    # THIS IS A LOTTERY-TICKET SHAPE AND THE OPERATOR WAS TOLD SO BEFORE IT WAS
    # WRITTEN. A 0.30% stop with an 8.00% target on 1-hour PROVE candles, over
    # 9,095 bars (380 days) with fees, slippage, funding and MEXC's 4.50%
    # liquidation charged:
    #   martingale  +$123.75 over 1,515 trades -- 90 wins, 1,425 losses (5.94%)
    #               worst losing run  -$274.24 over 82 CONSECUTIVE losses
    #               worst dip $661.47 against a $192 wallet -- 3.4x the account
    #               7/13 months green, 0 liquidations, biggest stake $40
    #   flat        +$51.88, worst run -$36.16, dip $97.45, 8/13 months green
    # The flat version is the survivable one; the operator chose martingale
    # anyway when shown both (AskUserQuestion, 2026-08-19). Ships with NO book
    # ticked, because PROVE already runs mom6_1h_pv live on the same 1-hour bar
    # and one coin holds ONE position per book -- arming both would have them
    # racing for the same slot, which is the 2026-08-12 class of failure.
    # THRESHOLD 0.20, not 0.30. row_code checked: 0.20 gives #8ZFUXG8F, 0.30
    # gives #5P3SYZDY (+$172.01, 45 trades) and 0.50 gives #AVEP6U3N. Three rows
    # identical in coin, bar, signal, barriers and sizing, separated only by the
    # threshold -- which is exactly why the ID is hashed from all seven fields.
    "fade15_1h_pv2": {"interval": "Min60", "bar_seconds": 3600,
                      "tp": 0.080, "sl": 0.003, "threshold": 0.002},
    "mom6_1h_pv": {"interval": "Min60", "bar_seconds": 3600,
                   "tp": 0.040, "sl": 0.025, "threshold": 0.003},
    # --- From the August win-rate board, 2026-08-24.
    # #NEQMY7RS — PROVE 1h mom6, TP 4.0 / SL 4.0. The SAME signal and target as
    # mom6_1h_pv above but a WIDER stop, and it was the highest August win rate
    # at 1h: 19W/3L over 22 trades, 86.4%, +$57.92. DEMO ONLY. The operator kept
    # mom6_1h_pv live: PROVE has 62 days of candles, so its "3 months", "6
    # months" and "full history" windows are the same 62 days printed three
    # times, which is not the evidence a live swap needs.
    # Runs FLAT, like the row it copies. Deployed under the account's
    # martingale default it hashed to 7R4JEPGJ — a DIFFERENT combination that
    # had never been tested, which is the 2026-08-17 deploy exactly. A demo
    # whose sizing differs from the row it is rehearsing is not a rehearsal.
    "mom6_1h_pv4": {"interval": "Min60", "bar_seconds": 3600,
                    "tp": 0.040, "sl": 0.040, "threshold": 0.005},
    # #F2S7J87Z — NOM 4h mom6, TP 5.0 / SL 4.0. Green in EVERY nested window
    # (1m +$56.28, 3m +$121.93, 6m +$159.55, full year +$113.26 over 361
    # trades) and edge_check ok at 4% of the target. Runs FLAT: laddered its
    # worst losing run is -$188.60 over 10 trades against a $210.68 wallet,
    # flat the same run is -$41.00 for the same full-year profit.
    "mom6_4h_nom": {"interval": "Hour4", "bar_seconds": 14400,
                    "tp": 0.050, "sl": 0.040, "threshold": 0.008},
    "fvg_1h": {"interval": "Min60", "bar_seconds": 3600,
               "tp": 0.018, "sl": 0.006},
    # --- Wide 1-hour barriers (1.00%/4.00%). From the 55,062-combination
    # all-market sweep of 2026-08-14. APEX/sweep30 is one of only TWO configs
    # in the whole search that survived FLAT-staked on a real year (+$55.72,
    # 10/12 months green, both halves positive) — i.e. the signal works, not
    # just the ladder. ALICE/fvg is the most consistent martingale survivor
    # (+$443.63, 13/15 green) whose flat version is also clearly positive
    # (+$80.23), so its edge is real even though its flat months miss the 70%
    # bar. Both cost 6% of target on a measured book.
    # APEX. Changed 2026-08-19 from SL 1.00 / TP 4.00, which had gone cold:
    # -$4.80 in July and -$22.62 in August on a year that read +$111.52. Same
    # signal, same bar; only the barriers move.
    #
    # Row **#VB4SNUHQ** (laddered) / #CR6SEXJL (flat), from
    # backtest_report.row_code. NOTE for anyone recomputing one of these: the
    # seed takes the SHORT coin name ("APEX"), because that is what a grid row
    # stores in `coin` -- row_code("APEX_USDT", ...) returns a different code
    # that appears on no page. The previous barriers are #PKLLZM9D
    # (laddered) / #G4HC92TM (flat).
    #
    # Measured on 7,809 hourly bars (325 days) the moment before deploying:
    # +$128.08, 243 trades, 56.79% win, worst dip $20.24, 11/12 months green,
    # no liquidations, stop reachable (3.00% inside APEX's 4.00% liquidation
    # move at 20x). Re-measured 2026-08-19 17:00 on 7,825 bars: +$83.73
    # laddered / +$27.48 flat, 244 trades, 56.6% win, dip $24.02 -- same
    # signal, thinner book. Round-trip cost is now 0.278% (slippage 0.099%
    # per side, measured), which is 9.3% of the 3% target, up from 6%.
    "sweep30_1h_w": {"interval": "Min60", "bar_seconds": 3600,
                     "tp": 0.030, "sl": 0.030},
    "fvg_1h_w": {"interval": "Min60", "bar_seconds": 3600,
                 "tp": 0.040, "sl": 0.010},
    # --- 4-hour winners: the only configs that came through the full
    # gauntlet with 13/13 green months (941-coin sweep → measured book cost
    # → split-half holdout → real per-coin fee). 4h beats every faster bar
    # because the 4.5% target absorbs the same fee a 0.9% target cannot.
    "mom15_4h": {"interval": "Hour4", "bar_seconds": 14400,
                 "tp": 0.045, "sl": 0.015, "threshold": 0.006},
    # Wider barriers on the same signal. A 630-combination grid over PI's full
    # 18-month history (2026-08-13) ranked this #1 of 105 configs: +$1,283 vs
    # +$884 for the 4.5%/1.5% version, 19/19 months green on both, profitable
    # in BOTH halves at BOTH sizings, and 233 fewer trades so less fee drag.
    "mom15_4h_w": {"interval": "Hour4", "bar_seconds": 14400,
                   "tp": 0.080, "sl": 0.020, "threshold": 0.006},
    "mom15_4h_b": {"interval": "Hour4", "bar_seconds": 14400,
                   "tp": 0.036, "sl": 0.012, "threshold": 0.006},
    "fvg_4h": {"interval": "Hour4", "bar_seconds": 14400,
               "tp": 0.045, "sl": 0.015},
    "fvg_4h_b": {"interval": "Hour4", "bar_seconds": 14400,
                 "tp": 0.036, "sl": 0.012},
    "trend50_4h": {"interval": "Hour4", "bar_seconds": 14400,
                   "tp": 0.045, "sl": 0.015},
    "sweep30_4h": {"interval": "Hour4", "bar_seconds": 14400,
                   "tp": 0.045, "sl": 0.015},
}

# Order matters: when several ticked strategies fire at once, the first one
# here wins. FVG first — it is the config the tab was built for.
# A human name for a row, shown beside its id in both UIs.
#
# NO NUMBERS IN HERE. `app._strategy_label` records why: barriers typed into a
# label drift from the spec the runner trades — the APEX tile advertised
# "TP 4.0%" against a real 3.0% for weeks. Barriers are derived from
# STRATEGY_SPECS at render time; this map is for PROVENANCE, which is the part
# a spec cannot express: where the row came from and why it was picked.
STRATEGY_LABELS = {
    "mom6_1h_pv4": "Best winrate for Aug",
    "mom6_4h_nom": "Best winrate for Aug",
}


def label_for(key: str, settings: dict | None = None) -> str:
    """The row's human name — from the CONFIG first, then this file's default.

    It started as a dict in this module only, which meant the operator could
    not change a label without editing code. `settings["strategy_labels"]`
    overrides it, exactly like strategy_margins and strategy_books, so the name
    is data. The map above is only the shipped default for the rows that came
    with one.
    """
    if settings:
        got = (settings.get("strategy_labels") or {}).get(key)
        if got is not None:
            return str(got)
    return STRATEGY_LABELS.get(key, "")

STRATEGY_ORDER = ("mom15_4h", "mom15_4h_b", "fvg_4h", "fvg_4h_b",
                  "trend50_4h", "sweep30_4h", "mom15_1h_g", "mom6_1h_g",
                  "mom15_4h_w", "sweep30_1h_w", "fvg_1h_w", "mom6_1h_gx",
                  "mom6_1h_pv", "mom6_1h_pv4", "mom6_4h_nom",
                  "trend50_30m_pi", "fade15_1h_pv2",
                  "ict_fvg", "fvg_1h", "rsi14_1h", "mom15_sp", "mom6",
                  "trend50", "sweep_1h", "sweep_rt", "mom15_1h", "fade15_1h",
                  "fade15_15m", "fade15_1m")


# ------------------------------------------------------------------ signals
# Each takes plain OHLC lists of CLOSED bars and answers the direction the
# LAST bar signals: +1 long, −1 short, 0 nothing. These are line-for-line the
# rules the 13-month backtest measured (see the BTC playbook artifact).

def sig_ict_fvg(high: list, low: list, close: list) -> int:
    """Fair value gap, 50% fill entry, 60-bar expiry."""
    bull = bear = None
    out = 0
    n = len(close)
    for i in range(2, n):
        if low[i] > high[i - 2]:
            bull = (low[i], high[i - 2], i)
        if high[i] < low[i - 2]:
            bear = (low[i - 2], high[i], i)
        cur = 0
        if bull and i - bull[2] < 60 and close[i] <= (bull[0] + bull[1]) / 2:
            cur = 1
            bull = None
        if bear and i - bear[2] < 60 and cur == 0 and \
                close[i] >= (bear[0] + bear[1]) / 2:
            cur = -1
            bear = None
        if i == n - 1:
            out = cur
    return out


def sig_mom6(close: list, threshold: float = MOM6_THRESHOLD) -> int:
    if len(close) < 7:
        return 0
    r = close[-1] / close[-7] - 1
    return 1 if r > threshold else (-1 if r < -threshold else 0)


def sig_mom15(close: list, threshold: float) -> int:
    if len(close) < 16:
        return 0
    r = close[-1] / close[-16] - 1
    return 1 if r > threshold else (-1 if r < -threshold else 0)


def sig_trend50(close: list) -> int:
    if len(close) < 50:
        return 0
    ma = sum(close[-50:]) / 50
    return 1 if close[-1] > ma else -1


def sig_sweep(high: list, low: list, close: list, n: int = 30) -> int:
    """Liquidity sweep: the bar pierces the prior n-bar extreme and closes
    back inside — stops were grabbed, fade the reclaim."""
    if len(close) < n + 1:
        return 0
    prior_low = min(low[-n - 1:-1])
    prior_high = max(high[-n - 1:-1])
    if low[-1] < prior_low and close[-1] > prior_low:
        return 1
    if high[-1] > prior_high and close[-1] < prior_high:
        return -1
    return 0


def sig_rsi14(close: list) -> int:
    """Wilder RSI(14): long under 30, short over 70."""
    n = 14
    if len(close) < n + 2:
        return 0
    g = lo = 0.0
    for i in range(1, len(close)):
        ch = close[i] - close[i - 1]
        if i <= n:
            if ch > 0:
                g += ch
            else:
                lo -= ch
            if i == n:
                g /= n
                lo /= n
            continue
        g = (g * (n - 1) + max(ch, 0)) / n
        lo = (lo * (n - 1) + max(-ch, 0)) / n
    r = 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)
    return 1 if r < 30 else (-1 if r > 70 else 0)


def signal_for(key: str, high: list, low: list, close: list,
               opens: list | None = None, volume: list | None = None,
               ts: list | None = None) -> int:
    # The expansion rules (signals_ext, signals_ext2) were BACKTEST-ONLY until
    # 2026-08-19: this function never dispatched to them, so a deployed
    # fib618/sr_break/supertrend strategy would have silently emitted 0
    # forever. The grid and the runner must speak the same rules.
    from tradingagents.signals_conf import CONF_SIGNALS
    from tradingagents.signals_ext import EXTRA_SIGNALS
    from tradingagents.signals_ext2 import EXTRA_SIGNALS2

    # Same order as the backtest path. A rule the grid can pick and the runner
    # cannot emit is a strategy that trades zero times once deployed.
    for _name in sorted(CONF_SIGNALS, key=len, reverse=True):
        if key == _name or key.startswith(_name + "_"):
            dirs = CONF_SIGNALS[_name](opens or [], high, low, close,
                                       volume or [], ts or [])
            return dirs[-1] if dirs else 0
    for _name in sorted(EXTRA_SIGNALS2, key=len, reverse=True):
        if key == _name or key.startswith(_name + "_"):
            dirs = EXTRA_SIGNALS2[_name](opens or [], high, low, close,
                                         volume or [], ts or [])
            return dirs[-1] if dirs else 0
    for _name in sorted(EXTRA_SIGNALS, key=len, reverse=True):
        if key == _name or key.startswith(_name + "_"):
            dirs = EXTRA_SIGNALS[_name](high, low, close)
            return dirs[-1] if dirs else 0
    if key.startswith("fvg_") or key == "ict_fvg":
        return sig_ict_fvg(high, low, close)
    if key == "rsi14_1h":
        return sig_rsi14(close)
    if key.startswith("trend50"):
        return sig_trend50(close)
    if key.startswith("sweep30"):
        return sig_sweep(high, low, close)
    if key.startswith("mom6"):
        return sig_mom6(close, STRATEGY_SPECS[key].get(
            "threshold", MOM6_THRESHOLD))
    if key == "trend50":
        return sig_trend50(close)
    if key in ("sweep_1h", "sweep_rt"):
        return sig_sweep(high, low, close)
    if key == "mom15_sp" or key.startswith("mom15_"):
        return sig_mom15(close, STRATEGY_SPECS[key]["threshold"])
    if key.startswith("fade15_"):
        return -sig_mom15(close, STRATEGY_SPECS[key]["threshold"])
    return 0


# ------------------------------------------------------------- persistence
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_settings() -> dict:
    return _read_json(SETTINGS_PATH)


def timeframe_conflicts(settings: dict) -> list[dict]:
    """Coins trading REAL money on more than one timeframe at once.

    The operator's rule: "if i enable a different timeframe for a certain coin
    make sure i wont be enable other timeframe". Two strategies on one coin at
    different bar sizes are two bots fighting over a single MEXC position -- the
    venue nets same-symbol positions into one, so the second entry silently
    resizes the first, and whichever stop fires closes part of a trade it does
    not own. Same class as the 2026-08-12 wrong-position lookup, arrived at
    from the settings side instead.

    LIVE ONLY, on the operator's instruction (2026-08-19): "i should be able to
    enable demo for both 30m and 1hr timeframe for pi ... its only restricted
    on live trade". The netting is an EXCHANGE behaviour, so it is real money
    that cannot be double-booked; the paper book has no MEXC position for two
    strategies to collide over. Note the paper book still keeps ONE simulated
    position per coin, so two papered timeframes take turns rather than running
    side by side -- see `state_key`.
    """
    seen: dict[str, list[tuple[str, str]]] = {}
    for key in settings.get("strategies", []):
        spec = STRATEGY_SPECS.get(key)
        if spec is None:
            continue
        if False not in books_for(key, settings):   # paper-only: no netting
            continue
        for coin in coins_for(key, settings):
            seen.setdefault(coin, []).append((key, spec["interval"]))
    out = []
    for coin, pairs in sorted(seen.items()):
        tfs = {iv for _, iv in pairs}
        if len(tfs) > 1:
            out.append({"coin": coin, "timeframes": sorted(tfs),
                        "strategies": sorted(k for k, _ in pairs)})
    return out


def coins_for(key: str, settings: dict) -> list[str]:
    """The contracts a strategy trades. Per-strategy lists came later, so a
    settings file with only the old global ``coins`` list still works.

    An EXPLICITLY EMPTY list means none, not all. `per.get(key) or coins` treated
    `[]` as falsy and fell through to the global list, so a strategy whose last
    coin was unticked silently began trading every coin in the config -- the
    opposite of what unticking means. Found 2026-08-19: `mom15_1h_g` sat at `[]`
    and was claiming all five contracts, and removing PI from `mom15_4h_w` to
    honour one-timeframe-per-coin promoted THAT strategy to all five too. Only a
    MISSING key falls back now.
    """
    per = settings.get("strategy_coins") or {}
    if key in per:
        return list(per[key] or [])
    return list(settings.get("coins", []))


def sizing_for(settings: dict, key: str | None = None) -> str:
    """"flat" or "martingale", PER STRATEGY, falling back to the global choice.

    Defaults to martingale so an existing config keeps behaving exactly as it
    did before this setting existed.

    Flat is how a signal is MEASURED; the ladder is a sizing choice made
    afterwards, with its own funding requirement. An audit showed six live
    strategies whose "13/13 green months" was produced by the ladder rather
    than the signal, so the runner has to be able to actually RUN the flat
    version that the backtest scores.

    PER STRATEGY because sizing is not one decision for the whole account. On
    2026-08-24 NOM/mom6 measured +$114.57 flat and +$113.26 laddered over the
    same year — the same money — but its worst losing run was −$41.00 flat and
    −$188.60 laddered, against a $210.68 wallet. Flat was obviously right for
    that row and obviously wrong to force on the others, and with only a global
    switch the operator's choice could not be expressed at all.
    """
    if key:
        per = (settings.get("strategy_sizing") or {}).get(key)
        if per:
            return "flat" if str(per).lower() == "flat" else "martingale"
    v = str(settings.get("sizing") or "martingale").lower()
    return "flat" if v == "flat" else "martingale"


def staked_margin(key: str, settings: dict, step: int) -> float:
    """The margin for the next trade, honouring the sizing setting."""
    base = margin_for(key, settings)
    return (base if sizing_for(settings, key) == "flat"
            else ladder_margin(base, step))


def margin_for(key: str, settings: dict) -> float:
    """A strategy's base margin — its own figure when set, else the global."""
    per = settings.get("strategy_margins") or {}
    v = per.get(key)
    return float(v) if v else float(settings.get("margin", 10.0))


STATE_LOCK_PATH = STATE_DIR / "auto_trade_state.lock"


def load_state() -> dict:
    """The shared book. Carries a per-slot revision so a writer can tell
    whether someone else has changed a slot since this copy was read."""
    state = _read_json(STATE_PATH)
    state.setdefault("_rev", {})
    return state


def save_state(state: dict, keys: list | None = None) -> None:
    """Write the book back WITHOUT clobbering another process's work.

    Two programs share this file: the runner (every cycle) and the app (the
    CLOSE button, panic-close). The old version wrote the whole dict from
    whatever the caller happened to hold, so the last writer won outright.

    What that cost, measured on the live account: at 00:20:48 on 2026-08-18 the
    operator closed a real XAUT short from the app. `close_one` sent the order,
    MEXC confirmed flat, and the exit reached the ledger -- then a runner cycle
    that had started earlier saved ITS copy, which still held the position. The
    runner then "stopped out" that phantom 28 more times, at -0.96 apiece,
    through 07:44 on 2026-08-19: -$30.72 of losses the exchange never saw
    (MEXC's own all-time XAUT figure is -$1.01, the ledger's was -$32.39), and
    the daily loss limit reads exactly those rows.

    So: take a lock, re-read the file, and merge per slot. ``keys`` names the
    slots this caller actually decided about; anything else on disk is left
    alone. A slot whose on-disk revision has moved past the one this copy was
    read at belongs to the other writer -- it is DROPPED here and re-read next
    cycle, because a fresher exchange-confirmed close always beats a stale
    in-memory position.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    mine_rev = state.get("_rev") or {}
    if keys is None:
        keys = [k for k in state if k != "_rev"]
    with STATE_LOCK_PATH.open("a+", encoding="utf-8") as lock:
        portable.lock_exclusive(lock)
        try:
            disk = _read_json(STATE_PATH)
            disk_rev = dict(disk.get("_rev") or {})
            for k in keys:
                if k not in state:
                    continue
                if disk_rev.get(k, 0) > mine_rev.get(k, 0):
                    logger.warning(
                        "state slot %s was changed by another process while "
                        "this cycle ran (rev %s > %s) — keeping THEIR version "
                        "and re-reading next cycle.",
                        k, disk_rev.get(k, 0), mine_rev.get(k, 0))
                    continue
                disk[k] = state[k]
                disk_rev[k] = disk_rev.get(k, 0) + 1
            disk["_rev"] = disk_rev
            _write_json(STATE_PATH, disk)
            # Leave the caller's copy in step with what is now on disk, so a
            # second save in the same cycle is not treated as stale.
            state["_rev"] = dict(disk_rev)
        finally:
            portable.unlock(lock)


def append_ledger(entry: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": int(time.time()), **entry}
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# Trade IDs. The exit row used to carry no identity and no opening time, so
# the history table could not name a trade or say when it started — the
# operator asked for both on 2026-08-22 ("put ids for each trade and date
# opened ... you will add this in the database").
#
# The id is HASHED from the facts that cannot change once the trade opens:
# contract, strategy, the entry candle's timestamp, side and which book it is
# on. Not a counter — a counter renumbers the same trade whenever the file is
# rewritten or a row is dropped, which is the "#05146 / #02054" confusion the
# backtest row codes already had to fix. Hashing also means the BACKFILL of
# old rows computes exactly the id the live path would have written.
_TRADE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"      # no 0/O/1/I


def trade_code(symbol: str, strategy: str, entry_ts, side, dry: bool) -> str:
    """A stable 8-character id for one trade, e.g. ``K4M7QP2X``."""
    import hashlib

    seed = "|".join([str(symbol), str(strategy or ""), str(int(entry_ts or 0)),
                     "L" if (side or 0) > 0 else "S",
                     "paper" if dry else "live"])
    n = int.from_bytes(hashlib.blake2s(seed.encode(), digest_size=5).digest(),
                       "big")
    out = ""
    for _ in range(8):
        out = _TRADE_ALPHABET[n % 32] + out
        n //= 32
    return out


def backfill_ledger_ids(path=None, *, dry_run: bool = False) -> dict:
    """Give every past enter/exit row a trade id and an opened timestamp.

    Pairs each exit with its own entry FIFO within (symbol, strategy, book),
    which is exactly how the runner holds one position per slot, so the
    pairing is not a guess. Rows already carrying an id are left untouched,
    so this is safe to run twice.

    Rewrites the file under the same lock the writers use, through a temp file
    and a rename, keeping a timestamped ``.bak`` — a half-written ledger would
    take every PnL figure in the app with it.
    """
    p = Path(path) if path else LEDGER_PATH
    if not p.exists():
        return {"rows": 0, "entered": 0, "exited": 0, "written": False}
    lines = p.read_text(encoding="utf-8").splitlines()
    rows: list = []
    for ln in lines:
        try:
            rows.append(json.loads(ln))
        except ValueError:
            rows.append(ln)                  # keep unparseable lines verbatim
    open_by: dict = {}
    n_enter = n_exit = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        act = r.get("action")
        if act not in ("enter", "exit"):
            continue
        slot = (r.get("symbol"), r.get("strategy"), bool(r.get("dry_run")))
        if act == "enter":
            if not r.get("trade_id"):
                r["trade_id"] = trade_code(
                    r.get("symbol"), r.get("strategy"),
                    r.get("entry_ts") or r.get("ts"),
                    1 if str(r.get("side", "")).upper() == "LONG" else -1,
                    bool(r.get("dry_run")))
                n_enter += 1
            r.setdefault("opened_at", r.get("ts"))
            open_by.setdefault(slot, []).append(r)
        else:
            q = open_by.get(slot) or []
            src = q.pop(0) if q else None
            if src is not None:
                if not r.get("trade_id"):
                    r["trade_id"] = src["trade_id"]
                    n_exit += 1
                r.setdefault("opened_at", src.get("opened_at"))
                if r.get("held_s") is None and r.get("ts") and src.get("ts"):
                    r["held_s"] = int(r["ts"]) - int(src["ts"])
            elif not r.get("trade_id"):
                # An exit with no surviving entry row (the ledger predates the
                # entry, or it was a reconciliation). Give it an id of its own
                # rather than leaving a blank cell nobody can quote.
                r["trade_id"] = trade_code(
                    r.get("symbol"), r.get("strategy"), r.get("ts"),
                    1 if str(r.get("side", "")).upper() == "LONG" else -1,
                    bool(r.get("dry_run")))
                n_exit += 1
    if dry_run:
        return {"rows": len(rows), "entered": n_enter, "exited": n_exit,
                "written": False}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "ledger.lock").open("a+") as lock:
        portable.lock_exclusive(lock)
        try:
            # Re-read under the lock: the runner may have appended while the
            # pairing above was computed. Those tail rows are carried over
            # untouched, and the next run will id them.
            fresh = p.read_text(encoding="utf-8").splitlines()
            tail = fresh[len(lines):]
            bak = p.with_suffix(f".bak-{int(time.time())}")
            bak.write_text("\n".join(fresh) + ("\n" if fresh else ""),
                           encoding="utf-8")
            tmp = p.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write((json.dumps(r) if isinstance(r, dict) else r)
                             + "\n")
                for ln in tail:
                    fh.write(ln + "\n")
            tmp.replace(p)
        finally:
            portable.unlock(lock)
    return {"rows": len(rows), "entered": n_enter, "exited": n_exit,
            "written": True, "backup": str(bak)}


def log_tail(n: int = 200) -> list[str]:
    """Last ``n`` lines of the runner's own log (scan lines and warnings)."""
    try:
        return LOG_PATH.read_text(encoding="utf-8").strip().splitlines()[-n:]
    except OSError:
        return []


def pnl_today(now: float | None = None, dry: bool | None = None) -> dict:
    """Realized bot PnL since local midnight, from the ledger's exit rows.

    ``dry=True`` counts only simulated (paper) trades, ``dry=False`` only real
    ones, ``None`` counts both. Paper and real money must never be added
    together in anything the operator reads.
    """
    now = time.time() if now is None else now
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            0, 0, 0, 0, 0, -1))
    total = 0.0
    wins = losses = 0
    # Read by TIME, not by row count: gate_blocked / chase_skip / error rows
    # share this file, so a fixed tail silently hid a whole day's exits once
    # the log got busy — and the loss limit then read 0.00 on a losing day.
    for e in ledger_since(midnight):
        if e.get("action") != "exit" or e.get("ts", 0) < midnight:
            continue
        if dry is not None and bool(e.get("dry_run")) is not dry:
            continue
        p = float(e.get("pnl_est") or 0.0)
        total += p
        if p > 0:
            wins += 1
        else:
            losses += 1
    return {"total": round(total, 2), "wins": wins, "losses": losses,
            "trades": wins + losses}


def ledger_since(ts: float) -> list[dict]:
    """Every ledger row at or after ``ts`` — no row-count cap.

    Risk controls must never be blinded by log volume.
    """
    out = []
    try:
        with LEDGER_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("ts", 0) >= ts:
                    out.append(e)
    except OSError:
        return []
    return out


def ledger_tail(n: int = 20) -> list[dict]:
    try:
        lines = LEDGER_PATH.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(out))


# --------------------------------------------------- liquidity / edge gate
TAKER_FEE = 0.0002          # BTC's rate — a FLOOR, never assume it globally
# Contracts charge different taker fees and some misreport: MCDSTOCK_USDT's
# contract_spec says takerFeeRate 0 while MEXC actually charged 0.0008/side on
# a real fill. When the spec is missing or zero, assume the worst observed.
FEE_FALLBACK = 0.0008
# Charged on PAPER fills only. A real order's price already contains its
# slippage; a simulated one is filled at the exact barrier, so without this
# the demo reports better results than the backtest that justified it.
PAPER_SLIPPAGE = 0.0003
# How far SHY of a resting barrier a real fill may land and still be named
# after it. A fill THROUGH the barrier always counts (a stop slips past by
# any amount — ALICE's 0.1396 stop filled at 0.1407); shy fills happen on
# the TP side, measured at 0.15% (TP 0.1386 filled 0.1384). Twice the worst
# observed. Anything shy of both barriers by more reads as a manual close.
EXIT_LABEL_TOLERANCE = 0.003


# How far price may drift from the signal bar's close before the entry is
# abandoned, as a FRACTION OF THE STOP DISTANCE (not a flat %) — a 4h
# strategy with a 1.5% stop tolerates more drift than a 15m one with 0.3%.
#
# Calibrated against measured MEXC data (2026-08-12), not guessed:
#   * On a perpetual there is NO gap between a bar's close and the next bar's
#     open — measured 0.000% across 2,198 4h bars on all six live coins. So
#     the backtest's entry price IS the signal close, and every bit of live
#     drift is deviation from what was tested.
#   * Price movement in the first MINUTE after a 4h close: median 0.060%,
#     90th 0.140%, 99th 0.385%. The runner fires ~3s in, so a healthy cycle
#     drifts a small fraction of that (~0.01-0.03%).
#   * 0.10 of the stop = 0.150% on the 4h strategies: roughly 5-15x a healthy
#     cycle's drift, so it effectively never blocks normal operation, while
#     catching a runner that woke late (missed poll, rate limit, restart) —
#     which is exactly when chasing does damage.
MAX_CHASE_FRACTION_OF_STOP = 0.10

# A signal is only worth acting on while it is FRESH. The backtest enters at
# the next bar's open — seconds after the close. A newly enabled book has no
# record of recent candles, so it would happily act on one that closed hours
# ago: on 2026-08-13 the live book entered PROVE on a signal 5h41m old, purely
# because it had just been switched on. The chase guard did not catch it
# because PRICE had barely moved; staleness is a separate dimension.
MAX_SIGNAL_AGE_FRACTION = 0.5      # of one bar


def chase_ok(side: int, signal_close: float, live_px: float,
             sl_pct: float) -> tuple[bool, float, float]:
    """Has price run too far past the signal to still be the tested trade?

    Returns (ok, drift_fraction_of_price, limit_fraction_of_price). Drift is
    measured in the direction that HURTS: a long that has already risen has
    less room to its stop and further to its target.
    """
    if signal_close <= 0 or live_px <= 0:
        return False, 0.0, 0.0
    drift = (live_px / signal_close - 1) * side      # + = moved against entry
    limit = sl_pct * MAX_CHASE_FRACTION_OF_STOP
    return drift <= limit, drift, limit


def taker_fee(symbol: str, *, fx=None) -> float:
    """This contract's real taker fee per side, never a global guess."""
    if fx is None:
        from tradingagents.dataflows import mexc_futures as fx  # noqa: PLC0415
    try:
        rate = float(fx.contract_spec(symbol).get("takerFeeRate") or 0)
    except Exception:
        rate = 0.0
    return rate if rate > 0 else FEE_FALLBACK
# A strategy is only worth running if its take-profit dwarfs the round-trip
# cost of touching the market. 2026-08-12: fade15_1m ran on BDX with TP 0.36%
# against a 1.56% spread — arithmetically impossible, and it cost real money.
COST_RATIO_BLOCK = 0.50     # cost ≥ 50% of TP  → refuse
COST_RATIO_WARN = 0.20      # cost ≥ 20% of TP  → allow, loudly


def edge_check(key: str, symbol: str, margin: float = 10.0, *, fx=None) -> dict:
    """Can this strategy's edge survive this contract's real trading cost?

    Measures the live order book at the size the strategy would actually
    trade (its deepest ladder rung, which is where thin books hurt most) and
    compares the round-trip cost to the take-profit being aimed at.

    verdict: "ok" | "warn" | "block" | "unknown"
    """
    if fx is None:
        from tradingagents.dataflows import mexc_futures as fx  # noqa: PLC0415
    spec = STRATEGY_SPECS.get(key)
    if spec is None:
        return {"verdict": "unknown", "reason": f"unknown strategy {key}"}
    deepest = margin * LADDER[-1] * LEVERAGE
    try:
        m = fx.book_cost(symbol, deepest)
    except Exception as exc:
        return {"verdict": "unknown", "reason": str(exc), "symbol": symbol,
                "strategy": key}
    tp = spec["tp"]
    round_trip = 2 * (m["slippage"] + taker_fee(symbol, fx=fx))
    ratio = round_trip / tp if tp else float("inf")
    verdict = ("block" if ratio >= COST_RATIO_BLOCK
               else "warn" if ratio >= COST_RATIO_WARN else "ok")
    if m["book_exhausted"]:
        verdict = "block"
    return {"verdict": verdict, "strategy": key, "symbol": symbol,
            "tp": tp, "spread": m["spread"], "slippage": m["slippage"],
            "round_trip_cost": round_trip, "cost_ratio": ratio,
            "notional_tested": deepest, "book_exhausted": m["book_exhausted"],
            "reason": (
                f"round-trip cost {round_trip:.3%} vs take-profit {tp:.2%} "
                f"= {ratio:.0%} of the target"
                + (" · book cannot even fill the deepest ladder rung"
                   if m["book_exhausted"] else ""))}


_GATE_CACHE: dict = {}
_GATE_TTL = 300           # re-measure a pair's book every 5 minutes
_GATE_LOGGED: dict = {}
_GATE_LOG_EVERY = 3600    # one loud line per pair per hour, not per candle


def _edge_gate_cached(key: str, symbol: str, margin: float, *, fx) -> dict:
    hit = _GATE_CACHE.get((key, symbol))
    now = time.time()
    if hit and now - hit[0] < _GATE_TTL:
        return hit[1]
    r = edge_check(key, symbol, margin, fx=fx)
    _GATE_CACHE[(key, symbol)] = (now, r)
    return r


def _gate_should_log(symbol: str, key: str, dry: bool = False) -> bool:
    """Rate-limit the gate warning PER BOOK. Both books run the gate now, and
    a shared key let whichever ran first swallow the other's warning."""
    now = time.time()
    last = _GATE_LOGGED.get((key, symbol, dry), 0)
    if now - last < _GATE_LOG_EVERY:
        return False
    _GATE_LOGGED[(key, symbol, dry)] = now
    return True


def blocked_pairs(settings: dict, *, fx=None) -> list[dict]:
    """Every enabled strategy/coin pair whose edge cannot cover its cost."""
    out = []
    for key in settings.get("strategies", []):
        for symbol in coins_for(key, settings):
            r = edge_check(key, symbol, margin_for(key, settings), fx=fx)
            if r["verdict"] == "block":
                out.append(r)
    return out


# ----------------------------------------------------------------- backtest
def _dirs_for_backtest(key: str, high: list, low: list,
                       close: list, opens: list | None = None,
                       volume: list | None = None,
                       ts: list | None = None) -> list[int]:
    """Per-bar signal directions over a whole history — the same rules the
    live ``sig_*`` functions apply to the last bar, evaluated at every bar.

    ``opens``, ``volume`` and ``ts`` (epoch ms per bar) feed the second
    expansion's session/volume rules; a rule whose stream is missing abstains
    (all zeros) rather than guessing.
    """
    n = len(close)
    out = [0] * n
    # The expansion rules live in their own modules and are matched FIRST, by
    # the longest name, so `sr_break_x` cannot be swallowed by a shorter key.
    # The second registry (volume/session rules, 2026-08-19) outranks the
    # first only in lookup order; names never collide across the two.
    from tradingagents.signals_conf import CONF_SIGNALS
    from tradingagents.signals_ext import EXTRA_SIGNALS
    from tradingagents.signals_ext2 import EXTRA_SIGNALS2

    # The confluence set (2026-08-26) is checked FIRST and by the longest name,
    # so `cf_mom_l1_1h` cannot be swallowed by `cf_mom`.
    for _name in sorted(CONF_SIGNALS, key=len, reverse=True):
        if key == _name or key.startswith(_name + "_"):
            return CONF_SIGNALS[_name](opens or [], high, low, close,
                                       volume or [], ts or [])
    for _name in sorted(EXTRA_SIGNALS2, key=len, reverse=True):
        if key == _name or key.startswith(_name + "_"):
            return EXTRA_SIGNALS2[_name](opens or [], high, low, close,
                                         volume or [], ts or [])
    for _name in sorted(EXTRA_SIGNALS, key=len, reverse=True):
        if key == _name or key.startswith(_name + "_"):
            return EXTRA_SIGNALS[_name](high, low, close)
    if key == "rsi14_1h":
        g = lo = 0.0
        for i in range(1, n):
            ch = close[i] - close[i - 1]
            if i <= 14:
                if ch > 0:
                    g += ch
                else:
                    lo -= ch
                if i == 14:
                    g /= 14
                    lo /= 14
                continue
            g = (g * 13 + max(ch, 0)) / 14
            lo = (lo * 13 + max(-ch, 0)) / 14
            r = 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)
            out[i] = 1 if r < 30 else (-1 if r > 70 else 0)
    elif key.startswith("fvg_") or key == "ict_fvg":
        bull = bear = None
        for i in range(2, n):
            if low[i] > high[i - 2]:
                bull = (low[i], high[i - 2], i)
            if high[i] < low[i - 2]:
                bear = (low[i - 2], high[i], i)
            if bull and i - bull[2] < 60 and close[i] <= (bull[0] + bull[1]) / 2:
                out[i] = 1
                bull = None
            if bear and i - bear[2] < 60 and out[i] == 0 and \
                    close[i] >= (bear[0] + bear[1]) / 2:
                out[i] = -1
                bear = None
    elif key.startswith("mom6"):
        for i in range(6, n):
            r = close[i] / close[i - 6] - 1
            _th = STRATEGY_SPECS.get(key, {}).get("threshold",
                                                   MOM6_THRESHOLD)
            out[i] = 1 if r > _th else (-1 if r < -_th else 0)
    elif key.startswith("trend50"):
        # The average INCLUDES the current bar, matching sig_trend50 and the
        # published playbook. An earlier version averaged the previous 50
        # excluding it — a different rule, so the backtest was not measuring
        # what traded. Pinned by test_backtest_dirs_match_the_live_signal.
        run_sum = sum(close[:50])
        for i in range(49, n):
            if i > 49:
                run_sum += close[i] - close[i - 50]
            out[i] = 1 if close[i] > run_sum / 50 else -1
    elif key in ("sweep_1h", "sweep_rt") or key.startswith("sweep30"):
        for i in range(30, n):
            pl = min(low[i - 30:i])
            ph = max(high[i - 30:i])
            if low[i] < pl and close[i] > pl:
                out[i] = 1
            elif high[i] > ph and close[i] < ph:
                out[i] = -1
    elif key == "mom15_sp" or key.startswith(("mom15_", "fade15_")):
        th = STRATEGY_SPECS[key]["threshold"]
        sign = -1 if key.startswith("fade15_") else 1
        for i in range(15, n):
            r = close[i] / close[i - 15] - 1
            out[i] = sign if r > th else -sign if r < -th else 0
    return out


def backtest_strategy(key: str, df, base_margin: float = 10.0,
                      fee: float = 0.0002,
                      slippage: float = 0.0003,
                      sizing: str = "martingale",
                      dirs: list | None = None,
                      tp: float | None = None,
                      sl: float | None = None,
                      leverage: int | None = None,
                      liq_move_pct: float | None = None,
                      funding: list | None = None,
                      keep_log: bool = True,
                      resume: dict | None = None,
                      start_at: int = 0,
                      slices: list | None = None,
                      sig_idx=None) -> dict:
    """Run one strategy's exact live rules over a candle history.

    Same engine as the 13-month studies: signal at bar close, enter next bar
    open, worst-case fills (SL before TP inside one bar), DEEP ladder, 20x,
    taker fee both sides — PLUS a slippage cost per side (default 0.03%),
    because live market orders never fill at the printed candle price. The
    operator asked the backtest to match live, not flatter it.

    ``funding`` charges the third cost a perpetual has: the settlement paid (or
    received) every few hours for HOLDING the position. Pass MEXC's published
    history -- ``mexc_futures.funding_history(symbol)``, a list of
    ``{"settle_ms", "rate"}`` -- and every settlement inside a trade's own
    window is applied at its real rate, so a 6-hour trade pays one cycle and a
    5-day trade pays thirty. Sign is MEXC's: a positive rate means longs pay.
    Omitting it overstates profit by however long the strategy holds -- measured
    2026-08-19, that was 0.2% on PI and 17.2% on PROVE.

    ``slices`` is [(weight, tp, sl), ...] with the weights summing to 1: ONE
    position with several exits, each owning its share of the volume. That is
    what two strategies on one coin become on MEXC, because the venue NETS
    same-side positions into a single record -- verified against the API on
    2026-08-19, where ``stoporder/place`` accepts ``volType=1`` with a specified
    vol and even separate takeProfitVol/stopLossVol. Three things this has to
    get right, and why each matters:

    * **Liquidation is on the POSITION, not the slice.** The slices share one
      margin, so when price reaches the liquidation distance every slice still
      open dies at once and the loss caps at the margin. Letting a slice
      "survive" a liquidation that already took the account is how a backtest
      invents money the venue would never have paid.
    * **Funding stops per slice.** The early exit stops paying settlements; the
      runner keeps paying. One window for the whole trade overstates the cost
      of taking profit early.
    * **One exit row.** The trade books a single net PnL, so the ladder rung,
      the daily loss limit and the W/L columns keep meaning what they say.
      Per-slice detail goes in the log under "slices".
    """
    if slices is not None:
        if not slices:
            raise ValueError("slices=[] is not a plan; pass None for one exit")
        _w = [float(x[0]) for x in slices]
        if any(w <= 0 for w in _w):
            raise ValueError(f"slice weights must be positive: {_w}")
        if abs(sum(_w) - 1.0) > 1e-6:
            raise ValueError(f"slice weights must sum to 1, got {sum(_w)}")
        for _sw, _stp, _ssl in slices:
            if float(_stp) <= 0 or float(_ssl) <= 0:
                raise ValueError("every slice needs a positive tp and sl")
        if resume is not None:
            # A carried-open trade would have to remember which slices are
            # still live and how much each has left. Refusing beats a number
            # nobody can reproduce.
            raise ValueError("slices with resume= is not supported yet")
    spec = STRATEGY_SPECS[key]
    # Barriers may be overridden to sweep TP/SL without touching the live
    # spec. Assigning into STRATEGY_SPECS would edit what the UI renders and
    # what the runner brackets with — a sweep must never do that to draw a
    # table.
    tp = spec["tp"] if tp is None else float(tp)
    sl = spec["sl"] if sl is None else float(sl)
    lev = LEVERAGE if leverage is None else int(leverage)
    # Liquidation is modelled ONLY when the caller supplies the venue's real
    # figure (mexc_futures.liquidation_move_pct, which reads MEXC's published
    # maintenanceMarginRate). Guessing 100/leverage overstates the survivable
    # move — the reason that helper exists — and an invented boundary is worse
    # than none, so `None` means "do not model it" rather than "assume".
    liq = None if liq_move_pct is None else abs(float(liq_move_pct)) / 100.0
    fee = fee + slippage
    # Funding settlements as two sorted arrays, so each trade can bisect the
    # window it actually spanned instead of scanning the whole history.
    _f_ms: list[int] = []
    _f_rate: list[float] = []
    if funding:
        for f in sorted(funding, key=lambda d: d["settle_ms"]):
            _f_ms.append(int(f["settle_ms"]))
            _f_rate.append(float(f["rate"]))
    # A market-wide sweep runs thousands of combinations per coin and reads
    # only the totals, yet every trade allocated a 16-key dict. Counting what
    # the log was being scanned for (liquidations, funding) and skipping the
    # dicts is the difference between a 12-hour sweep and a 4-hour one.
    n_liq = 0
    fund_total = 0.0
    # The worst unbroken run of losses — what actually empties a laddered
    # account. The page computed it in JS; storing it needs it here.
    run_sum = 0.0
    run_len = 0
    worst_run = 0.0
    worst_run_len = 0
    _f_cum = [0.0]
    for _r in _f_rate:
        _f_cum.append(_f_cum[-1] + _r)
    # Bar timestamps in EPOCH MILLISECONDS, converted through datetime64[ms]
    # rather than by dividing a raw int64. MEXC's frames come back as
    # datetime64[s], so `astype("int64") // 1_000_000` read 1,754 instead of
    # 1,754,406,000,000 -- every funding window then spanned the whole history
    # and PROVE's year came out at -$2,230 instead of +$153.
    _bar_ms = (df["Date"].to_numpy().astype("datetime64[ms]")
               .astype("int64")) if _f_ms else None
    high = [float(x) for x in df["High"]]
    low = [float(x) for x in df["Low"]]
    close = [float(x) for x in df["Close"]]
    opens = [float(x) for x in df["Open"]]
    # The per-bar signal depends only on the signal rule and the candles, not
    # on TP/SL or sizing — a sweep re-testing one coin at 3 barriers x 2
    # sizings recomputed the identical array 6 times. Callers may pass it in.
    if dirs is None:
        _vols = ([float(x) for x in df["Volume"]]
                 if "Volume" in df.columns else None)
        _ts = list(df["Date"].to_numpy().astype("datetime64[ms]")
                   .astype("int64"))
        dirs = _dirs_for_backtest(key, high, low, close,
                                  opens=opens, volume=_vols, ts=_ts)
    # Formatting a timestamp for EVERY bar cost 80% of this function on a
    # 525,000-bar 1-minute history — and only two stamps per TRADE are ever
    # read (the entry bar and the exit bar). Format them on demand instead.
    _dates = df["Date"].to_numpy()
    _stamp_cache: dict[int, str] = {}

    def stamp(k: int) -> str:
        v = _stamp_cache.get(k)
        if v is None:
            v = _pd.Timestamp(_dates[k]).strftime("%Y-%m-%d %H:%M")
            _stamp_cache[k] = v
        return v
    # One strftime per TRADE just to label its month was 14% of this function.
    # Bars map to months vectorised, once, and the label is looked up by index.
    _mo_codes = _dates.astype("datetime64[M]")
    _mo_names: dict = {}

    def _month_of(k: int) -> str:
        v = _mo_codes[k]
        name = _mo_names.get(v)
        if name is None:
            name = str(v)[:7]
            _mo_names[v] = name
        return name
    monthly: dict[str, float] = {}
    n = len(close)
    trades = wins = 0
    profit = worst_trade = 0.0
    equity = peak = max_dd = 0.0
    step = 0
    i = max(0, int(start_at))
    # A refresh must not re-test the year it already tested. `resume` carries
    # the tail state of an earlier run -- ladder rung, running totals, the
    # month-by-month map, the losing streak, and any position still open at the
    # boundary -- so this call continues that same backtest over new bars only.
    # Where the signals actually are, instead of walking every bar to find
    # them. The same `dirs` array is reused across ~200 barrier/sizing
    # combinations, and each one used to step through all 19,000 bars in Python
    # purely to skip the ~95% that hold nothing.
    if sig_idx is None:
        try:
            import numpy as _np

            _sig = _np.flatnonzero(_np.asarray(dirs, dtype=_np.int8))
        except Exception:
            _sig = [k for k, v in enumerate(dirs) if v]
    else:
        _sig = sig_idx
    _sp = 0
    _nsig = len(_sig)
    _open = None
    if resume:
        trades = int(resume.get("trades", 0))
        wins = int(resume.get("wins", 0))
        profit = float(resume.get("profit", 0.0))
        worst_trade = float(resume.get("worst", 0.0))
        equity = float(resume.get("equity", 0.0))
        peak = float(resume.get("peak", 0.0))
        max_dd = float(resume.get("max_dd", 0.0))
        step = int(resume.get("step", 0))
        monthly.update({k2: float(v2)
                        for k2, v2 in (resume.get("monthly") or {}).items()})
        n_liq = int(resume.get("liqs", 0))
        fund_total = float(resume.get("funding_total", 0.0))
        _open = resume.get("open") or None
    log: list[dict] = []
    while i < n - 1:
        if _open is None:
            while _sp < _nsig and _sig[_sp] < i:
                _sp += 1
            if _sp >= _nsig:
                break
            i = int(_sig[_sp])
            if i >= n - 1:
                break
        if _open is not None:
            # carried across the boundary: same side, entry, rung and barriers
            s = int(_open["side"])
            margin = float(_open["margin"])
            entry = float(_open["entry"])
            notional = margin * lev
            tp_px = entry * (1 + s * tp)
            sl_px = entry * (1 - s * sl)
            _entry_bar = i
        else:
            s = dirs[i]
            if s == 0:
                i += 1
                continue
            margin = (base_margin if sizing == "flat"
                      else ladder_margin(base_margin, step))
            entry = opens[i + 1]
            notional = margin * lev
            tp_px = entry * (1 + s * tp)
            sl_px = entry * (1 - s * sl)
            _entry_bar = i + 1
        # The venue closes the position at the liquidation price whatever the
        # stop says. Past a certain leverage that price sits INSIDE the stop,
        # so the stop can never fire and the loss is the whole margin.
        liq_px = None if liq is None else entry * (1 - s * liq)
        _sl_det: list | None = None
        if slices is not None:
            # One walk, every slice. Each slice carries its own barriers and
            # closes independently; the shared liquidation closes them all.
            _live = [{"w": float(w), "tp": float(stp), "sl": float(ssl),
                      "tp_px": entry * (1 + s * float(stp)),
                      "sl_px": entry * (1 - s * float(ssl)),
                      "out": None, "why": None, "bar": None}
                     for w, stp, ssl in slices]
            j = _entry_bar
            _liq_all = False
            while j < n and any(x["out"] is None for x in _live):
                hit_liq = liq_px is not None and (
                    low[j] <= liq_px if s == 1 else high[j] >= liq_px)
                # The nearest barrier of ANY open slice decides whether the
                # liquidation got there first. A slice whose stop is inside the
                # liquidation distance is filled by the stop; one whose stop is
                # beyond it never fires at all, and the venue takes the margin.
                _open_sl = [x["sl"] for x in _live if x["out"] is None]
                if hit_liq and (liq is None or not _open_sl
                                or liq <= min(_open_sl)):
                    for x in _live:
                        if x["out"] is None:
                            x["out"], x["why"], x["bar"] = -liq, "LIQ", j
                    _liq_all = True
                    break
                for x in _live:
                    if x["out"] is not None:
                        continue
                    if (low[j] <= x["sl_px"] if s == 1
                            else high[j] >= x["sl_px"]):
                        x["out"], x["why"], x["bar"] = -x["sl"], "SL", j
                    elif (high[j] >= x["tp_px"] if s == 1
                            else low[j] <= x["tp_px"]):
                        x["out"], x["why"], x["bar"] = x["tp"], "TP", j
                if all(x["out"] is not None for x in _live):
                    break
                j += 1
            # Anything still open at the last bar is marked to market, exactly
            # as the single-exit path does with why="END".
            for x in _live:
                if x["out"] is None:
                    x["out"] = s * (close[-1] / entry - 1)
                    x["why"], x["bar"] = "END", n - 1
            j = max(x["bar"] for x in _live)
            _whys = {x["why"] for x in _live}
            why = ("LIQ" if _liq_all else
                   _whys.pop() if len(_whys) == 1 else
                   "/".join(sorted(_whys)))
            pnl = 0.0
            fund = 0.0
            for x in _live:
                _pn = (x["out"] - 2 * fee) * notional * x["w"]
                _fn = 0.0
                if _f_ms:
                    import bisect as _bis

                    _a = _bis.bisect_right(_f_ms, int(_bar_ms[_entry_bar]))
                    _b = _bis.bisect_right(_f_ms, int(_bar_ms[x["bar"]]))
                    _fn = -s * (_f_cum[_b] - _f_cum[_a]) * notional * x["w"]
                    _pn += _fn
                x["pnl"] = _pn
                x["fund"] = _fn
                pnl += _pn
                fund += _fn
            if _liq_all:
                # Shared margin: the venue takes it once, not once per slice.
                pnl = -margin
            out = pnl / notional if notional else 0.0
            _sl_det = [{"weight": round(x["w"], 4),
                        "tp %": round(x["tp"] * 100, 4),
                        "sl %": round(x["sl"] * 100, 4),
                        "why": x["why"], "exit time": stamp(x["bar"]),
                        "exit": round(entry * (1 + s * x["out"]), 6)
                                if x["why"] != "END" else round(close[-1], 6),
                        "funding $": round(x["fund"], 4),
                        "pnl $": round(x["pnl"], 4)} for x in _live]
            _skip_single = True
        else:
            _skip_single = False
        out, j, why = (out, j, why) if _skip_single else (None, _entry_bar, None)
        while j < n and not _skip_single:
            hit_liq = liq_px is not None and (
                low[j] <= liq_px if s == 1 else high[j] >= liq_px)
            hit_sl = (low[j] <= sl_px if s == 1 else high[j] >= sl_px)
            # Worst case inside one bar: liquidation is checked FIRST, and it
            # only wins when it is nearer than the stop.
            if hit_liq and (liq is None or liq <= sl or not hit_sl):
                out, why = -liq, "LIQ"
                break
            if hit_sl:
                out, why = -sl, "SL"
                break
            if (high[j] >= tp_px if s == 1 else low[j] <= tp_px):
                out, why = tp, "TP"
                break
            j += 1
        if out is None and not _skip_single:
            if resume is not None or _open is not None:
                # Hand it to the next refresh instead of pretending it closed.
                _ems = (int(_bar_ms[_entry_bar]) if _bar_ms is not None
                        else int(_pd.Timestamp(_dates[_entry_bar]).value
                                 // 1_000_000))
                _open = {"side": s, "entry": entry, "margin": margin,
                         "opened": stamp(_entry_bar),
                         # the funding window has to start where the trade
                         # started, not where this refresh's frame starts
                         "entry_ms": int((_open or {}).get("entry_ms", _ems))}
                break
            out, why = s * (close[-1] / entry - 1), "END"
            j = n - 1
        if not _skip_single:
            pnl = (out - 2 * fee) * notional
        # Holding cost: every settlement between the entry fill and the exit.
        # A long pays when the rate is positive, a short receives it.
        if not _skip_single:
            fund = 0.0
        if _f_ms and not _skip_single:
            import bisect as _bis

            _from = (int(_open["entry_ms"]) if _open is not None
                     and _open.get("entry_ms") is not None
                     else int(_bar_ms[_entry_bar]))
            _a = _bis.bisect_right(_f_ms, _from)
            _b = _bis.bisect_right(_f_ms, int(_bar_ms[j]))
            fund = -s * (_f_cum[_b] - _f_cum[_a]) * notional
            pnl += fund
        if why == "LIQ" and not _skip_single:
            # A liquidation cannot cost more than the margin that was staked.
            pnl = -margin
        trades += 1
        wins += pnl > 0
        profit += pnl
        worst_trade = min(worst_trade, pnl)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        month = _month_of(j)
        monthly[month] = monthly.get(month, 0.0) + pnl
        n_liq += why == "LIQ"
        fund_total += fund
        if pnl > 0:
            run_sum, run_len = 0.0, 0
        else:
            run_sum += pnl
            run_len += 1
            if run_sum < worst_run:
                worst_run, worst_run_len = run_sum, run_len
        if not keep_log:
            step = 0 if pnl > 0 else step + 1
            _open = None          # or a carried trade re-enters at its old
            i = j + 1             # entry price on every following bar
            continue
        log.append({"entry time": stamp(i + 1), "exit time": stamp(j),
                    "side": "LONG" if s > 0 else "SHORT", "step": step + 1,
                    "margin $": margin, "leverage": f"{lev}x",
                    "notional $": round(notional, 2),
                    "entry": round(entry, 6),
                    "TP px": round(tp_px, 6), "SL px": round(sl_px, 6),
                    "exit": round(entry * (1 + s * out), 6)
                            if why != "END" else round(close[-1], 6),
                    "why": why, "WIN/LOSE": "WIN" if pnl > 0 else "LOSE",
                    "funding $": round(fund, 4),
                    "pnl $": round(pnl, 2), "running total $": round(equity, 2),
                    **({"slices": _sl_det} if _sl_det else {})})
        step = 0 if pnl > 0 else step + 1
        _open = None
        i = j + 1
    days = (df["Date"].iloc[-1] - df["Date"].iloc[0]).days if n else 0
    monthly = {m: round(v, 2) for m, v in sorted(monthly.items())}
    green = sum(1 for v in monthly.values() if v > 0)
    _state = {"trades": trades, "wins": wins, "profit": profit,
              "worst": worst_trade, "equity": equity, "peak": peak,
              "max_dd": max_dd, "step": step, "monthly": dict(monthly),
              "liqs": n_liq, "funding_total": fund_total, "open": _open,
              "last_ms": (int(_bar_ms[-1]) if _bar_ms is not None and n
                          else (int(df["Date"].to_numpy()
                                    .astype("datetime64[ms]")
                                    .astype("int64")[-1]) if n else 0))}
    return {"liqs": n_liq, "funding_total": round(fund_total, 4),
            "worst_streak": round(worst_run, 2),
            "worst_streak_len": worst_run_len,
            "state": _state,
            "trades": trades, "wins": wins, "losses": trades - wins,
            "profit": round(profit, 2), "worst_trade": round(worst_trade, 2),
            "max_dd": round(max_dd, 2), "bars": n, "days": days, "log": log,
            "monthly": monthly, "months_green": green,
            "months_total": len(monthly),
            "worst_month": round(min(monthly.values()), 2) if monthly else 0.0}


def daily_pnl(dry: bool | None = None) -> dict:
    """Realized PnL per LOCAL calendar day, from the ledger's exit rows.

    Keyed "YYYY-MM-DD". Local days, not UTC — the operator reads a calendar in
    their own timezone, and a trade closed at 8am local belongs to that day.
    Each day carries wins/losses/trades so a green day that was 1W/4L reads
    differently from 3W/0L.
    """
    out: dict[str, dict] = {}
    for e in ledger_since(0):
        if e.get("action") != "exit":
            continue
        if dry is not None and bool(e.get("dry_run")) is not dry:
            continue
        key = time.strftime("%Y-%m-%d", time.localtime(float(e.get("ts") or 0)))
        d = out.setdefault(key, {"pnl": 0.0, "wins": 0, "losses": 0,
                                 "trades": 0, "coins": set()})
        p = float(e.get("pnl_est") or 0.0)
        d["pnl"] += p
        d["trades"] += 1
        d["wins" if p > 0 else "losses"] += 1
        if e.get("symbol"):
            d["coins"].add(e["symbol"].replace("_USDT", ""))
    for d in out.values():
        d["pnl"] = round(d["pnl"], 2)
        d["coins"] = sorted(d["coins"])
    return out


def coin_stats(dry: bool | None = None) -> dict:
    """Lifetime realized results per CONTRACT, from the ledger's exit rows.

    Same shape as :func:`strategy_stats`, keyed by symbol. The operator asked
    for this directly: a per-strategy record hides that one coin inside a
    strategy is carrying the others, or bleeding while they win.
    """
    out: dict[str, dict] = {}
    for e in ledger_since(0):
        if e.get("action") != "exit":
            continue
        if dry is not None and bool(e.get("dry_run")) is not dry:
            continue
        key = e.get("symbol") or "(unknown)"
        s = out.setdefault(key, {"pnl": 0.0, "wins": 0, "losses": 0,
                                 "strategies": set(), "last_ts": 0})
        p = float(e.get("pnl_est") or 0.0)
        s["pnl"] += p
        if p > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
        if e.get("strategy"):
            s["strategies"].add(e["strategy"])
        s["last_ts"] = max(s["last_ts"], float(e.get("ts") or 0))
    for s in out.values():
        n = s["wins"] + s["losses"]
        s["trades"] = n
        s["winrate"] = round(100 * s["wins"] / n, 1) if n else 0.0
        s["pnl"] = round(s["pnl"], 2)
        s["strategies"] = ", ".join(sorted(s["strategies"])) or "—"
    return out


def strategy_stats(dry: bool | None = None) -> dict:
    """Lifetime realized results per strategy, from the ledger's exit rows.

    ``dry`` selects the book — real and paper must never be blended into one
    "record" the operator judges a strategy by. Reads the WHOLE ledger: a
    fixed tail blanked the record out once skip/error rows piled up.
    Older exit rows carried no strategy name; those land under "(unknown)".
    """
    out: dict[str, dict] = {}
    for e in ledger_since(0):
        if e.get("action") != "exit":
            continue
        if dry is not None and bool(e.get("dry_run")) is not dry:
            continue
        key = e.get("strategy") or "(unknown)"
        s = out.setdefault(key, {"pnl": 0.0, "wins": 0, "losses": 0})
        p = float(e.get("pnl_est") or 0.0)
        s["pnl"] += p
        if p > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
    for s in out.values():
        n = s["wins"] + s["losses"]
        s["trades"] = n
        s["winrate"] = round(100 * s["wins"] / n, 1) if n else 0.0
        s["pnl"] = round(s["pnl"], 2)
    return out


def pnl_today_by_strategy(now: float | None = None,
                          dry: bool | None = None) -> dict:
    """Realized PnL since local midnight, grouped by strategy.

    ``dry`` selects the book. Paper losses must never pause real trading,
    and real losses must never be masked by a winning demo.
    """
    now = time.time() if now is None else now
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday,
                            0, 0, 0, 0, 0, -1))
    out: dict[str, float] = {}
    for e in ledger_since(midnight):
        if e.get("action") != "exit" or e.get("ts", 0) < midnight:
            continue
        if dry is not None and bool(e.get("dry_run")) is not dry:
            continue
        key = e.get("strategy") or "(unknown)"
        out[key] = round(out.get(key, 0.0) + float(e.get("pnl_est") or 0.0), 2)
    return out


def tripped_strategies(settings: dict | None = None,
                       dry: bool = False) -> set:
    """Strategies whose realized PnL today is at or past THEIR loss limit.

    A tripped strategy is paused for the rest of the day; the others keep
    trading — the operator's ask: don't punish the ones that are working.
    """
    if settings is None:
        settings = load_settings()
    limits = settings.get("strategy_loss_limits") or {}
    active = {k: float(v) for k, v in limits.items() if v and float(v) > 0}
    if not active:
        return set()
    by = pnl_today_by_strategy(dry=dry)
    return {k for k, lim in active.items() if by.get(k, 0.0) <= -lim}


def panic_stop(*, fx=None, close_positions: bool = True) -> dict:
    """Stop everything NOW: halt entries, kill the runner, and (by default)
    close every real position at market.

    A kill switch that only blocks new entries is not a kill switch — the
    money already on the table is the part that hurts.
    """
    if fx is None:
        from tradingagents.dataflows import mexc_futures as fx  # noqa: PLC0415
    report = {"halted": False, "runner_stopped": False,
              "closed": [], "failed": []}
    KILL_PATH.parent.mkdir(parents=True, exist_ok=True)
    KILL_PATH.write_text("panic stop")
    report["halted"] = True
    report["runner_stopped"] = stop_runner()
    if close_positions:
        try:
            positions = fx.open_positions()
        except Exception as exc:
            report["failed"].append(f"could not read positions: {exc}")
            positions = []
        for p in positions:
            sym = p.get("symbol")
            side = 1 if int(p.get("positionType") or 0) == 1 else -1
            vol = int(p.get("holdVol") or 0)
            if not sym or vol <= 0:
                continue
            try:
                _force_close(sym, {"side": side, "vol": vol,
                                   "position_id": int(p.get("positionId") or 0)},
                             fx=fx)
                report["closed"].append(sym)
            except Exception as exc:
                report["failed"].append(f"{sym}: {exc}")
    # Clear ONLY what was actually closed, and book its real loss. Clearing a
    # position whose close FAILED would forget live money that nothing retries.
    failed_syms = {f.split(":")[0] for f in report["failed"]}
    state = load_state()
    cleared: list = []
    for key, st in list(state.items()):
        if not isinstance(st, dict) or key.endswith("#paper"):
            continue
        pos = st.get("position")
        if not pos:
            continue
        if key in failed_syms or key not in report["closed"]:
            logger.error("PANIC: %s was NOT confirmed closed — keeping it in "
                         "the book so it stays tracked and retried.", key)
            continue
        realised = None
        try:
            for h in fx.position_history(key, 10):
                if int(h.get("positionId") or 0) == int(
                        pos.get("position_id") or -1):
                    realised = float(h.get("realised") or 0.0)
                    break
        except Exception:
            realised = None
        # Written as an "exit" row: every PnL reader and every loss limit
        # filters on action == "exit", so a panic_stop-only row was invisible
        # to all of them and a real loss read as a $0.00 day.
        _pop = pos.get("opened_at") or pos.get("entry_ts")
        append_ledger({"symbol": key, "action": "exit", "why": "PANIC_CLOSE",
                       "strategy": pos.get("strategy"),
                       # side/entry belong on the EXIT row too: the trade
                       # history reads exit rows only, so without them the
                       # LONG/SHORT column was empty for every closed trade.
                       # Same reasoning for the id and the opening time.
                       "trade_id": pos.get("trade_id"), "opened_at": _pop,
                       "held_s": (int(time.time()) - int(_pop)) if _pop
                                 else None,
                       "side": "LONG" if pos.get("side", 0) > 0 else "SHORT",
                       "entry": pos.get("entry"),
                       "pnl_est": None if realised is None else round(realised, 2),
                       "dry_run": False})
        st["position"] = None
        cleared.append(key)
    save_state(state, keys=cleared)
    append_ledger({"action": "panic_stop", "closed": report["closed"],
                   "failed": report["failed"]})
    logger.error("PANIC STOP: entries halted, runner stopped, closed %s%s",
                 report["closed"] or "nothing",
                 f", FAILED {report['failed']}" if report["failed"] else "")
    return report


def close_one(symbol: str, *, fx=None) -> dict:
    """Close ONE real position at market, from the UI table.

    Not a panic stop: entries stay open, the runner keeps running, every other
    position is untouched. Only this contract is flattened.

    The exchange is the source of truth, so this re-reads ``open_positions``
    AFTER submitting and only reports success when the size is actually gone.
    A venue can accept a close and still leave the position on the book — a
    partial fill, a 2078 refusal near liquidation, a 510 swallowing the second
    leg — and reporting that as closed would clear the local book and leave
    real money open with nothing tracking or retrying it.
    """
    if fx is None:
        from tradingagents.dataflows import mexc_futures as fx  # noqa: PLC0415
    rep = {"symbol": symbol, "closed": False, "realised": None, "error": None}
    try:
        live = [p for p in fx.open_positions() if p.get("symbol") == symbol]
    except Exception as exc:
        rep["error"] = f"could not read positions: {exc}"
        logger.error("close_one %s: %s", symbol, rep["error"])
        return rep
    if not live:
        rep["error"] = f"no open position on {symbol}"
        return rep
    p = live[0]
    side = 1 if int(p.get("positionType") or 0) == 1 else -1
    vol = int(p.get("holdVol") or 0)
    pos_id = int(p.get("positionId") or 0)
    if vol <= 0:
        rep["error"] = f"no open position on {symbol} (zero volume)"
        return rep
    try:
        _force_close(symbol, {"side": side, "vol": vol,
                              "position_id": pos_id}, fx=fx)
    except Exception as exc:
        rep["error"] = str(exc)
        logger.error("close_one %s FAILED: %s", symbol, exc)
        append_ledger({"symbol": symbol, "action": "close_failed",
                       "why": "MANUAL_UI", "error": str(exc),
                       "dry_run": False})
        return rep
    # ---- the exchange, not the request, decides whether this is closed
    try:
        still = [q for q in fx.open_positions()
                 if q.get("symbol") == symbol
                 and int(q.get("holdVol") or 0) > 0]
    except Exception as exc:
        rep["error"] = (f"close was sent but the position could not be "
                        f"re-read ({exc}) — treat it as still open")
        logger.error("close_one %s: %s", symbol, rep["error"])
        return rep
    if still:
        rep["error"] = (f"{symbol} is still open after the close "
                        f"({still[0].get('holdVol')} left) — keeping it in "
                        f"the book so it stays tracked")
        logger.error("close_one %s: %s", symbol, rep["error"])
        return rep
    rep["closed"] = True
    try:
        for h in fx.position_history(symbol, 10):
            if int(h.get("positionId") or 0) == pos_id:
                rep["realised"] = round(float(h.get("realised") or 0.0), 2)
                break
    except Exception:
        rep["realised"] = None
    # Written as an "exit" row: every PnL reader and the loss limit filter on
    # action == "exit", so any other action name makes a real loss read as a
    # $0.00 day.
    state = load_state()
    st = state.get(symbol)
    pos = st.get("position") if isinstance(st, dict) else None
    _mop = (pos or {}).get("opened_at") or (pos or {}).get("entry_ts")
    append_ledger({"symbol": symbol, "action": "exit", "why": "MANUAL_UI",
                   "strategy": (pos or {}).get("strategy"),
                   "trade_id": (pos or {}).get("trade_id"),
                   "opened_at": _mop,
                   "held_s": (int(time.time()) - int(_mop)) if _mop else None,
                   "side": ("LONG" if (pos or {}).get("side", 0) > 0
                            else "SHORT") if pos else None,
                   "entry": (pos or {}).get("entry"),
                   "pnl_est": rep["realised"], "dry_run": False})
    if isinstance(st, dict):
        st["position"] = None
        # ONE slot. The close is exchange-confirmed, so this revision bump is
        # what makes a runner cycle still holding the old position back down.
        save_state(state, keys=[symbol])
    logger.warning("close_one: %s closed from the UI, realised %s",
                   symbol, rep["realised"])
    return rep


def loss_limit_hit(settings: dict | None = None) -> bool:
    """True when today's realized bot PnL has fallen to −loss_limit or worse.

    Realized only — open positions are already capped by their exchange-side
    stops, so the limit guards the day's cumulative bleed, not one trade.
    """
    if settings is None:
        settings = load_settings()
    limit = float(settings.get("loss_limit") or 0)
    if limit <= 0:
        return False
    # REAL money only. A demo drawdown is not a reason to halt live trading,
    # and this breaker exists to protect the account, not the simulation.
    return pnl_today(dry=False)["total"] <= -limit


# ------------------------------------------------------------------ arming
def state_key(symbol: str, dry: bool) -> str:
    """Book key. Live and paper are separate books on the same coin, so a
    simulated trade can never be mistaken for — or interfere with — a real
    one, and each keeps its own martingale ladder step."""
    return f"{symbol}#paper" if dry else symbol


def _env_dry() -> bool:
    return os.getenv("AUTO_TRADE_DRY", "").strip().lower() in ("yes", "true", "1")


def books_for(key: str, settings: dict | None = None) -> list[bool]:
    """Which books THIS strategy trades, as ``dry`` flags.

    ``settings["strategy_books"]`` maps a strategy key to any of "real" and
    "paper", so one strategy can be papered while another trades real money.
    A strategy with no entry falls back to the old global switches — an
    existing settings file has no map, and it must keep behaving exactly as
    it did rather than silently trading nothing (or everything, live).

    AUTO_TRADE_DRY keeps its long-standing meaning: it ADDS the paper book,
    it does not take the live one away.
    """
    if settings is None:
        settings = load_settings()
    per = (settings.get("strategy_books") or {}).get(key)
    if per is None:
        books = []
        if settings.get("enabled"):
            books.append(False)                  # live
        if settings.get("dry_run") or _env_dry():
            books.append(True)                   # paper
        return books
    books = []
    if "real" in per:
        books.append(False)
    if "paper" in per or _env_dry():
        books.append(True)
    return books


def active_modes(settings: dict | None = None) -> list[bool]:
    """Which books to run this cycle, as ``dry`` flags — the union over every
    ARMED strategy. A strategy that is not armed contributes nothing whatever
    its book says.
    """
    if settings is None:
        settings = load_settings()
    if not settings.get("strategy_books"):
        # No per-strategy assignment: the two global switches, unchanged.
        modes = []
        if settings.get("enabled"):
            modes.append(False)
        if settings.get("dry_run") or _env_dry():
            modes.append(True)
        return modes
    modes = []
    for key in settings.get("strategies", []):
        for dry in books_for(key, settings):
            if dry not in modes:
                modes.append(dry)
    return sorted(modes)


def dry_mode(settings: dict | None = None) -> bool:
    """True = simulate fills, no orders. The operator's Auto Trade checkbox
    IS the live switch (their explicit directive: \"if i check auto trade,
    do auto trade, period\"); ticking the separate Dry-run checkbox — or
    exporting AUTO_TRADE_DRY=yes — forces simulation."""
    if os.getenv("AUTO_TRADE_DRY", "").strip().lower() in ("yes", "true", "1"):
        return True
    if settings is None:
        settings = load_settings()
    return bool(settings.get("dry_run", False))


def halted() -> bool:
    return KILL_PATH.exists()


# ------------------------------------------------------------ trade logic
def ladder_margin(base: float, step: int) -> float:
    return base * LADDER[min(step, len(LADDER) - 1)]


def _closed_bars(df, bar_seconds: int):
    """Drop the in-progress candle: a signal on a bar still forming is a
    different (unbacktested) strategy.

    Compare Timestamps directly. The previous version did
    ``df["Date"].astype("int64") // 10**9``, which assumed nanosecond dtype —
    but pandas 3 returns ``datetime64[s]`` from ``to_datetime(unit="s")``, so
    the integer division collapsed every 2026 timestamp to 1 and the filter
    silently kept EVERY bar. The bot then signalled on the forming candle and
    traded a rule no backtest ever measured (live orders on 2026-08-11 went in
    21 minutes before their 1h bar closed). Never reintroduce dtype-dependent
    integer math here.
    """
    import pandas as pd  # noqa: PLC0415
    cutoff = pd.Timestamp(time.time() - bar_seconds, unit="s")
    return df[df["Date"] <= cutoff]


def _bracket(side: int, entry: float, tp: float, sl: float) -> tuple[float, float]:
    """(take-profit price, stop price) for a fill at ``entry``."""
    if side > 0:
        return entry * (1 + tp), entry * (1 - sl)
    return entry * (1 - tp), entry * (1 + sl)


def _exchange_exit_label(pos: dict, close_px: float) -> str:
    """Name an exchange-side close by where its real fill price landed.

    A resting bracket fills intrabar, so the position is gone from the venue
    before the candle check ever sees the cross — which ledgered every real
    bracket fill as MANUAL/EXCHANGE (10 of 10 real exits as of 2026-08-20,
    none of them closed by hand; ALICE filled at exactly its 0.1321 stop and
    was still called manual). A fill at or beyond a barrier, give or take
    slippage, is that barrier firing; only a fill clear of both is manual.
    """
    tol = EXIT_LABEL_TOLERANCE
    if pos["side"] > 0:
        if close_px <= pos["sl"] * (1 + tol):
            return "SL"
        if close_px >= pos["tp"] * (1 - tol):
            return "TP"
    else:
        if close_px >= pos["sl"] * (1 - tol):
            return "SL"
        if close_px <= pos["tp"] * (1 + tol):
            return "TP"
    return "MANUAL/EXCHANGE"


def _dry_fill(pos: dict, high: list, low: list) -> str | None:
    """Walk bars since entry; SL first when both barriers sit in one bar —
    the same worst-case rule the backtest used."""
    for hi, lo in zip(high, low, strict=False):
        if pos["side"] > 0:
            if lo <= pos["sl"]:
                return "SL"
            if hi >= pos["tp"]:
                return "TP"
        else:
            if hi >= pos["sl"]:
                return "SL"
            if lo <= pos["tp"]:
                return "TP"
    return None


def _snap_prices(symbol: str, tp_px: float, sl_px: float, *, fx):
    """Round bracket prices to the contract's price precision — MEXC answers
    code 2015 to a price with more decimals than the contract allows."""
    try:
        scale = int(fx.contract_spec(symbol).get("priceScale") or 6)
    except Exception:
        scale = 6
    return round(tp_px, scale), round(sl_px, scale)


def _force_close(symbol: str, pos: dict, *, fx) -> bool:
    """Close a live position NOW: market order, falling back to a resting
    limit when the venue refuses a market close near liquidation (2078)."""
    close_side = fx.SIDE_CLOSE_LONG if pos["side"] > 0 else fx.SIDE_CLOSE_SHORT
    try:
        fx.submit(symbol, close_side, pos["vol"], leverage=LEVERAGE,
                  dry_run=False)
        return True
    except Exception as exc:
        if "2078" not in str(exc):
            raise
    # 2078 means the venue refuses a fill BEYOND the liquidation price, so the
    # limit must sit just INSIDE it — above liq when closing a long, below liq
    # when closing a short. Anchor on the exchange's own liquidatePrice; using
    # last-price ± a tick puts a short's buy-limit UNDER a rising market, where
    # it can never fill. (Both branches of the first version of this ternary
    # were identical — the escape path guaranteed the liquidation it existed
    # to prevent. Tested both directions now.)
    # last_price now RAISES rather than returning a fake 0.0, so this escape
    # hatch must survive without it: the liquidation price is the real anchor
    # and last-price is only the fallback.
    try:
        px = float(fx.last_price(symbol))
    except Exception as exc:
        logger.warning("%s: no last price for the 2078 limit close (%s) — "
                       "anchoring on the liquidation price alone.",
                       symbol, exc)
        px = 0.0
    scale = int(fx.contract_spec(symbol).get("priceScale") or 6)
    tick = 10 ** -scale
    liq = 0.0
    try:
        for p in fx.open_positions(symbol):
            if int(p.get("positionId") or 0) == int(pos.get("position_id") or -1):
                liq = float(p.get("liquidatePrice") or 0)
                break
    except Exception:
        liq = 0.0
    if not liq and not px:
        raise RuntimeError(
            f"cannot price a limit close for {symbol}: the venue gave neither "
            f"a liquidation price nor a last price")
    if pos["side"] > 0:                       # long → SELL to close
        anchor = (max(liq + tick, px - tick) if liq and px
                  else (liq + tick if liq else px - tick))
    else:                                     # short → BUY to close
        anchor = (min(liq - tick, px + tick) if liq and px
                  else (liq - tick if liq else px + tick))
    limit = round(anchor, scale)
    fx.submit(symbol, close_side, pos["vol"], leverage=LEVERAGE,
              order_type=fx.TYPE_LIMIT, price=limit, dry_run=False)
    logger.warning("%s: market close refused near liquidation (2078) — limit "
                   "close resting at %.6g (last %.6g, liq %.6g).",
                   symbol, limit, px, liq)
    return True


def _rest_bracket(symbol: str, pos: dict, *, fx) -> bool:
    """Rest the TP/SL on MEXC for a tracked position. Marks pos["bracket"].

    Failure is logged CRITICAL and left retryable — the position stays
    tracked and the next cycle tries again, instead of orphaning it.
    """
    try:
        fx.place_position_stop(symbol, pos.get("position_id", 0), pos["vol"],
                               stop_loss_price=pos["sl"],
                               take_profit_price=pos["tp"], dry_run=False)
        # A 200 OK is NOT protection. mexc_futures documents that two of three
        # historical TP/SL records finished errorCode 8912 / vol 0 — accepted
        # by the API, inert on the book. Read it back before believing it.
        try:
            ok = bool(fx.verify_position_stop(
                symbol, int(pos.get("position_id") or 0)).get("protected"))
        except Exception as exc:
            logger.error("%s: bracket placed but VERIFY FAILED (%s) — "
                         "treating as unprotected.", symbol, exc)
            ok = False
        pos["bracket"] = ok
        if not ok:
            logger.error(
                "CRITICAL: %s accepted the TP/SL but the exchange does not "
                "show it resting — position is UNPROTECTED. Retrying next "
                "cycle.", symbol)
            append_ledger({"symbol": symbol, "action": "bracket_unverified",
                           "why": "placed but not resting on the exchange"})
            return False
        logger.info(
            "BRACKET verified resting on MEXC for %s position %s: TP %.6g / "
            "SL %.6g — exits fire on the exchange even if this process dies",
            symbol, pos.get("position_id"), pos["tp"], pos["sl"])
        return True
    except Exception as exc:
        pos["bracket"] = False
        if "5003" in str(exc):
            # The market is already past the stop price — a bracket can never
            # rest there. The strategy's answer is: be out. Close now.
            logger.error(
                "%s: stop price already breached (5003) — closing the "
                "position immediately instead of holding it naked.", symbol)
            try:
                _force_close(symbol, pos, fx=fx)
                append_ledger({"symbol": symbol, "action": "forced_close",
                               "why": "stop unplaceable (5003)"})
            except Exception as exc2:
                logger.error("CRITICAL: %s forced close ALSO failed (%s) — "
                             "position naked, retrying next cycle.",
                             symbol, exc2)
                append_ledger({"symbol": symbol, "action": "close_failed",
                               "why": str(exc2)})
            return False
        logger.error(
            "CRITICAL: %s position is OPEN but UNPROTECTED — the exchange "
            "rejected the TP/SL (%s). Retrying next cycle.", symbol, exc)
        append_ledger({"symbol": symbol, "action": "bracket_failed",
                       "why": str(exc)})
        return False


def process_symbol(symbol: str, settings: dict, state: dict, *, fx,
                   dry: bool, tripped: frozenset = frozenset()) -> None:
    """One decision cycle for one coin. Mutates ``state`` in place.

    Each enabled strategy is evaluated on ITS OWN timeframe — FVG on 4h
    candles, the realtime sweep on 1m — with candles fetched once per
    timeframe. The exit check runs on the finest enabled timeframe so a
    simulated fill is caught as early as the data allows.
    """
    # NOTE: tripped strategies are excluded from ENTRIES only, further down —
    # they must stay in this list so an open position's exit keeps being
    # tracked after its strategy trips.
    # A strategy the operator has ASSIGNED to a book must never appear in the
    # other one — that is the line between a simulation and a real order.
    # Strategies with no assignment are left to the caller's `dry`, which is
    # how every existing caller and the legacy global switches already work.
    _books = settings.get("strategy_books") or {}
    strategies = [k for k in STRATEGY_ORDER
                  if k in settings.get("strategies", [])
                  and symbol in coins_for(k, settings)
                  and (k not in _books or dry in books_for(k, settings))]
    # …but the book filter governs ENTRIES ONLY. A position already open in
    # THIS book still holds real money and still needs its exit tracked, even
    # once its strategy has been moved to demo, unticked, or renamed. Moving
    # XAUT to demo-only on 2026-08-17 left an open real short unmanaged: the
    # exchange stopped it out at 01:22 and the bot never booked the -0.85,
    # showing a phantom position for over a day. Same rule as tripped
    # strategies, one filter later.
    _held = (state.get(state_key(symbol, dry)) or {}).get("position")
    if _held and not strategies:
        _own = _held.get("strategy")
        _rescue = _own if _own in STRATEGY_SPECS else next(
            (k for k in STRATEGY_ORDER if symbol in coins_for(k, settings)),
            None)
        if _rescue:
            strategies = [_rescue]
            # EXITS ONLY. Adding it to `tripped` is what makes that true —
            # the entry gate further down skips tripped strategies while the
            # exit path above it still runs. Without this the rescue placed a
            # NEW real order on a demo-only strategy: on 2026-08-18 it exited
            # XAUT's stopped-out short and opened a fresh real long one second
            # later, on a strategy the operator had set to demo.
            tripped = frozenset(tripped) | {_rescue}
            logger.warning(
                "%s: no strategy armed in this book but a position is open — "
                "tracking its EXIT only under %s; no entries.",
                symbol, _rescue)
    if not strategies:
        return
    float(settings.get("margin", 10.0))

    # One fetch per distinct timeframe, shared by the strategies on it.
    frames: dict[str, object] = {}
    for key in strategies:
        spec = STRATEGY_SPECS[key]
        if spec["interval"] in frames:
            continue
        # Serve from cache while the same bar is still the newest closed one.
        bar_s = spec["bar_seconds"]
        this_bar = int(time.time()) // bar_s
        hit = _BAR_CACHE.get((symbol, spec["interval"]))
        if hit and hit[0] == this_bar:
            frames[spec["interval"]] = hit[1]
            continue
        df = _closed_bars(fx.klines(symbol, spec["interval"], 300), bar_s)
        if not df.empty:
            _BAR_CACHE[(symbol, spec["interval"])] = (this_bar, df)
            frames[spec["interval"]] = df
    if not frames:
        return

    st = state.setdefault(state_key(symbol, dry),
                          {"step": 0, "last_ts": {}, "position": None})
    if not isinstance(st.get("last_ts"), dict):   # pre-multi-TF state files
        st["last_ts"] = {}

    # ---- exits first, on the finest available timeframe
    pos = st.get("position")
    # A position opened live stays managed live even if Dry-run is ticked
    # afterwards, and vice versa. The checkbox governs NEW entries only.
    pos_dry = bool(pos.get("dry", dry)) if pos else dry
    if pos and not pos_dry and not pos.get("bracket", True):
        _rest_bracket(symbol, pos, fx=fx)   # retry a rejected TP/SL
    if pos:
        seconds_of = {s["interval"]: s["bar_seconds"]
                      for s in STRATEGY_SPECS.values()}
        df = frames[min(frames, key=lambda k: seconds_of[k])]
        bars_since = [(float(h), float(lo)) for h, lo, t in zip(
            df["High"], df["Low"], (int(d.timestamp()) for d in df["Date"]), strict=False)
            if t > pos["entry_ts"]]
        outcome = _dry_fill(pos, [h for h, _ in bars_since],
                            [lo for _, lo in bars_since])
        if not outcome and pos_dry:
            # A real bracket rests AT THE EXCHANGE and fills the instant any
            # trade prints through the barrier — on a wick, intrabar, at 3am.
            # The demo owns no order, so it can only look. Looking at the last
            # PRICE misses every wick that stabs the barrier and comes back;
            # measured against a real bracket that cost a median 0 but a 90th
            # percentile of 60 minutes and a worst case of 206 minutes of lag,
            # because the miss was only caught when the 4-hour bar closed.
            # One-minute RANGES close that gap to ~1 minute.
            try:
                fine = _closed_bars(fx.klines(symbol, "Min1", 300), 60)
                wick = [(float(h), float(lo)) for h, lo, t in zip(
                    fine["High"], fine["Low"],
                    (int(d.timestamp()) for d in fine["Date"]), strict=False)
                    if t > pos["entry_ts"]]
                outcome = _dry_fill(pos, [h for h, _ in wick],
                                    [lo for _, lo in wick])
            except Exception as exc:
                logger.warning("%s: could not read 1-minute ranges for the "
                               "paper bracket (%s) — falling back to the "
                               "last-price check.", symbol, exc)
        if not outcome and pos_dry:
            # Real-time exit for simulated positions: closed bars lag, so
            # also test the live tick against the bracket. SL checked first,
            # mirroring the worst-case bar rule.
            try:
                px = float(fx.last_price(symbol))
            except Exception as exc:
                # Unreadable price = no exit decision this cycle. Booking one
                # anyway is how the paper book invented take-profits.
                logger.warning("%s: no live price for the paper exit check "
                               "(%s) — leaving the position open.",
                               symbol, exc)
                px = None
            if px is not None and px > 0:
                if pos["side"] > 0:
                    outcome = ("SL" if px <= pos["sl"]
                               else "TP" if px >= pos["tp"] else None)
                else:
                    outcome = ("SL" if px >= pos["sl"]
                               else "TP" if px <= pos["tp"] else None)
        live_gone = False
        if not pos_dry:
            live_gone = not any(
                p.get("symbol") == symbol for p in fx.open_positions(symbol))
        if outcome and not pos_dry and not live_gone:
            # THE EXCHANGE IS THE SOURCE OF TRUTH. A barrier cross on our
            # candles means nothing while MEXC still reports the position
            # open — a bracket verified at entry can be cancelled or expire
            # later, and the first fix only self-closed when the bracket had
            # NEVER verified. An independent audit reproduced the remaining
            # hole: exchange open, book flushed, no close sent, ladder
            # advanced, re-entry on the same coin. That is the BDX loop.
            # So: close it ourselves, whatever the bracket flag claims.
            try:
                close_side = (fx.SIDE_CLOSE_LONG if pos["side"] > 0
                              else fx.SIDE_CLOSE_SHORT)
                fx.submit(symbol, close_side, pos["vol"], leverage=LEVERAGE,
                          dry_run=False)
                logger.warning(
                    "%s: barrier crossed while the exchange still shows the "
                    "position OPEN — closed at market ourselves rather than "
                    "assuming the bracket fired.", symbol)
            except Exception as exc:
                logger.error(
                    "CRITICAL: %s barrier crossed, no bracket, and the "
                    "market close FAILED (%s) — position still open, "
                    "retrying next cycle.", symbol, exc)
                append_ledger({"symbol": symbol, "action": "close_failed",
                               "why": str(exc)})
                outcome = None          # keep tracking; do NOT flush the book
        if outcome and not pos_dry and not live_gone:
            # The close above either succeeded or set outcome=None. If we get
            # here with a live position the venue still reports open, do not
            # book an exit — re-check next cycle instead of inventing one.
            try:
                still = any(p.get("symbol") == symbol
                            for p in fx.open_positions(symbol))
            except Exception:
                still = True                      # cannot verify → assume open
            if still:
                logger.error(
                    "CRITICAL: %s still OPEN on the exchange after the close "
                    "attempt — refusing to clear the book. Retrying.", symbol)
                append_ledger({"symbol": symbol, "action": "close_unconfirmed",
                               "why": "exchange still reports the position"})
                outcome = None
        if outcome or live_gone:
            why = outcome or "CLOSED"
            if why == "TP":
                exit_px = pos["tp"]
            elif why == "SL":
                exit_px = pos["sl"]
            else:
                # Unknown exit: NEVER assume the profitable one. Mark to the
                # live price, else assume the stop. Falling through to tp
                # booked liquidations as wins and reset the ladder.
                try:
                    exit_px = float(fx.last_price(symbol))
                except Exception:
                    exit_px = pos["sl"]
                if not exit_px:
                    exit_px = pos["sl"]
            move = (exit_px / pos["entry"] - 1) * pos["side"]
            # Charge the round-trip cost. Reporting a gross figure made every
            # displayed PnL optimistic and fed the loss limits a number the
            # account never saw.
            try:
                cost = 2 * taker_fee(symbol, fx=fx)
            except Exception:
                cost = 2 * FEE_FALLBACK
            if pos_dry:
                # A PAPER fill lands on the exact TP/SL price, which no real
                # order gets. Charge the same slippage the backtest charges,
                # or the demo flatters itself against the very numbers it is
                # supposed to be validating.
                cost += 2 * PAPER_SLIPPAGE
            pnl = (move - cost) * pos["margin"] * LEVERAGE
            if live_gone and not outcome:
                # Gone from the exchange without our barriers being crossed —
                # usually a manual close. Record MEXC's REAL realized PnL,
                # not our bracket-price estimate.
                try:
                    hist = fx.position_history(symbol, 10)
                    match = next(
                        (h for h in hist
                         if int(h.get("positionId") or 0) ==
                         int(pos.get("position_id") or -1)), None)
                    if match is not None:
                        real = match.get("realised")
                        if real is not None:
                            pnl = float(real)      # 0.0 is a real answer
                        why = "MANUAL/EXCHANGE"
                        if match.get("closeAvgPrice"):
                            exit_px = float(match["closeAvgPrice"])
                            # A bracket fills intrabar, so the position is
                            # gone before the candle check sees the cross —
                            # without this every stop/TP fill was ledgered
                            # as a manual close. Let the fill price say
                            # which barrier fired.
                            why = _exchange_exit_label(pos, exit_px)
                except Exception as exc:
                    logger.warning("could not fetch real PnL for %s manual "
                                   "close, using estimate: %s", symbol, exc)
            if pnl > 0:
                st["step"] = 0
            elif pnl < 0:
                st["step"] += 1
            else:
                # Exactly flat: neither a win nor a loss. Do not touch the
                # ladder, and say so rather than pretending it was a loss.
                logger.warning("%s exit priced at exactly 0.00 — ladder left "
                               "at step %s; verify against the exchange.",
                               symbol, st["step"])
            st["position"] = None
            logger.info(
                "EXIT %s %s %s at %.6g → pnl %+.2f USDT (%s) · ladder step "
                "now %d [%s]", symbol,
                "LONG" if pos["side"] > 0 else "SHORT", why, exit_px, pnl,
                "WIN" if pnl > 0 else "LOSE", st["step"],
                "dry run" if dry else "LIVE")
            _op = pos.get("opened_at") or pos.get("entry_ts")
            append_ledger({"symbol": symbol, "action": "exit", "why": why,
                           "strategy": pos.get("strategy"),
                           # id and opening time travel WITH the position, so
                           # a closed trade keeps the identity it opened with
                           "trade_id": pos.get("trade_id") or trade_code(
                               symbol, pos.get("strategy"),
                               pos.get("entry_ts"), pos.get("side"), pos_dry),
                           "opened_at": _op,
                           "held_s": (int(time.time()) - int(_op)) if _op
                                     else None,
                           "side": "LONG" if pos.get("side", 0) > 0 else "SHORT",
                           "entry": pos.get("entry"), "exit": exit_px,
                           "pnl_est": round(pnl, 2), "step_next": st["step"],
                           "dry_run": pos_dry})
            try:
                from tradingagents import notifications as _nt

                _nt.record(
                    "trade_close",
                    f"{'PAPER' if pos_dry else 'LIVE'} "
                    f"{symbol.replace('_USDT', '')} closed {why} "
                    f"{round(pnl, 2):+.2f} USDT",
                    detail=(f"{pos.get('strategy')} · "
                            f"{'LONG' if pos.get('side', 0) > 0 else 'SHORT'} "
                            f"{pos.get('entry')} -> {exit_px}"),
                    # a loss is not an ERROR, so ok tracks the money not the run
                    ok=bool(pnl >= 0),
                    meta={"symbol": symbol, "strategy": pos.get("strategy"),
                          "dry": bool(pos_dry), "why": why,
                          "pnl": round(pnl, 2), "exit": exit_px})
            except Exception:
                pass

    # ---- entries: each strategy acts once per closed candle of its own TF
    if st.get("position") or halted():
        for tf, df in frames.items():
            st["last_ts"][tf] = max(st["last_ts"].get(tf, 0),
                                    int(df["Date"].iloc[-1].timestamp()))
        return
    _live_locks = timeframe_locks(settings) if not dry else {}
    for key in strategies:
        if key in tripped:                 # paused for the day — no entries
            continue
        # ONE LIVE STRATEGY PER COIN, enforced where the order is placed.
        # The rule was checked only when SETTINGS WERE SAVED, so a config that
        # was already double-booked kept trading both: on 2026-08-22 PROVE ran
        # fade15_1h_pv2 and mom6_1h_pv live together, MEXC netted them into one
        # position, and either stop could close part of a trade it did not own.
        # A save-time check cannot protect a state that already exists.
        # Demo is untouched — `_live_locks` is empty when dry.
        _lock = _live_locks.get(key)
        if _lock and symbol in (coins_for(key, settings) or []):
            logger.warning(
                "REFUSED live entry %s · %s: %s is already traded live by %s. "
                "One live strategy per coin — disarm one of them to trade the "
                "other.", symbol, key, _lock["coin"].replace("_USDT", ""),
                _lock["held_by"])
            append_ledger({"symbol": symbol, "action": "refused",
                           "strategy": key, "why": "coin already live",
                           "held_by": _lock["held_by"], "dry_run": dry})
            continue
        # The liquidity gate: never open a trade whose take-profit is
        # smaller than the cost of getting in and out. Checked live, per
        # pair, because books change. (The BDX lesson, enforced in code.)
        # The demo runs the SAME gates as live. Its whole job is to predict
        # what live would do; a demo that takes trades live refuses is not a
        # rehearsal, it is a different strategy that happens to look better.
        # (These two were `if not dry:` — so the paper book skipped the
        # liquidity gate and the chase guard entirely, and would have shown a
        # tidy profit on a BDX-class contract live would never have touched.)
        if True:
            gate = _edge_gate_cached(key, symbol, margin_for(key, settings),
                                     fx=fx)
            if gate["verdict"] == "block":
                if _gate_should_log(symbol, key, dry):
                    logger.error(
                        "LIQUIDITY GATE: refusing %s on %s — %s. No order "
                        "placed. Pick a deeper-book contract or a strategy "
                        "with a wider target.", key, symbol, gate["reason"])
                    append_ledger({"symbol": symbol, "action": "gate_blocked",
                                   "strategy": key, "why": gate["reason"],
                                   "dry_run": dry})
                continue
        spec = STRATEGY_SPECS[key]
        df = frames.get(spec["interval"])
        if df is None:
            continue
        last_ts = int(df["Date"].iloc[-1].timestamp())
        if st["last_ts"].get(spec["interval"], 0) >= last_ts:
            continue                       # this candle already considered
        # How long ago did this candle CLOSE? (its timestamp is its open)
        age = time.time() - (last_ts + spec["bar_seconds"])
        max_age = spec["bar_seconds"] * MAX_SIGNAL_AGE_FRACTION
        if age > max_age:
            st["last_ts"][spec["interval"]] = last_ts   # do not revisit it
            logger.warning(
                "STALE SIGNAL: %s on %s closed %.0f min ago (limit %.0f min) "
                "— skipping. Acting on an old candle is not the trade the "
                "backtest measured; waiting for the next close.",
                key, symbol, age / 60, max_age / 60)
            append_ledger({"symbol": symbol, "action": "stale_skip",
                           "strategy": key, "age_min": round(age / 60),
                           "dry_run": dry})
            continue
        high = [float(x) for x in df["High"]]
        low = [float(x) for x in df["Low"]]
        close = [float(x) for x in df["Close"]]
        side = signal_for(
            key, high, low, close,
            opens=[float(x) for x in df["Open"]],
            volume=([float(x) for x in df["Volume"]]
                    if "Volume" in df.columns else None),
            ts=list(df["Date"].to_numpy().astype("datetime64[ms]")
                    .astype("int64")))
        if side == 0:
            # Mark the bar SEEN even with no signal. Without this the same
            # quiet candle was re-evaluated every few seconds until it aged
            # past the staleness limit, and every quiet hour then emitted a
            # `stale_skip` at exactly HH:30 — 282 of 341 of them carried
            # "age 30 min". The feed read as if the bot were missing most of
            # its checks when it had examined every one and found no trade.
            st["last_ts"][spec["interval"]] = last_ts
            continue
        # The mark is TENTATIVE from here on. A signal fired, so the candle must
        # not be re-evaluated once the order is away — but if the attempt dies on
        # a venue read, the trade never happened and the signal has to survive to
        # the next cycle. Before this the mark was final: on 2026-08-18 19:00 a
        # rate-limited contract detail read raised inside sizing, ALICE's entry
        # was thrown away, and the candle was already ticked off as considered.
        _prev_seen = st["last_ts"].get(spec["interval"], 0)
        st["last_ts"][spec["interval"]] = last_ts
        margin = staked_margin(key, settings, st["step"])
        notional = margin * LEVERAGE
        entry = close[-1]
        # The backtest enters at the next bar's open. Live, that is only true
        # if we act immediately — a late poll, a rate limit or a restart can
        # leave the signal stale, and buying after the move has already
        # happened is not the trade that was measured.
        if True:
            try:
                live_px = float(fx.last_price(symbol))
            except Exception as exc:
                # No price = no entry. A chase guard that switches itself off
                # whenever the venue hiccups is not a guard.
                logger.warning(
                    "SKIP %s %s: cannot read the live price (%s), so the "
                    "chase guard cannot run — refusing to enter blind.",
                    key, symbol, exc)
                append_ledger({"symbol": symbol, "action": "no_price_skip",
                               "strategy": key, "why": str(exc),
                               "dry_run": dry})
                continue
            if live_px:
                ok, drift, limit = chase_ok(side, entry, live_px, spec["sl"])
                if not ok:
                    logger.warning(
                        "CHASE GUARD: skipping %s %s — price moved %+.3f%% "
                        "against the entry since the signal bar closed "
                        "(limit %.3f%% = %.0f%% of the %.2f%% stop). The "
                        "trade is no longer the one that was backtested.",
                        key, symbol, drift * 100, limit * 100,
                        MAX_CHASE_FRACTION_OF_STOP * 100, spec["sl"] * 100)
                    append_ledger({"symbol": symbol, "action": "chase_skip",
                                   "strategy": key, "drift": round(drift, 5),
                                   "limit": round(limit, 5), "dry_run": dry})
                    return
                entry = live_px          # size and bracket off the real price
        try:
            vol = fx.contracts_for(symbol, notional, price=entry)
        except Exception as exc:
            # No size = no order. Give the candle back so the next cycle
            # re-reads it, rather than losing a signal to a venue hiccup.
            st["last_ts"][spec["interval"]] = _prev_seen
            logger.warning(
                "SIZE FAILED %s %s: %s — no order sent, and the %s candle is "
                "left UNSEEN so the next cycle retries this signal.",
                key, symbol, exc, spec["interval"])
            append_ledger({"symbol": symbol, "action": "size_failed",
                           "strategy": key, "why": str(exc),
                           "retry": True, "dry_run": dry})
            return
        if vol < 1:
            append_ledger({"symbol": symbol, "action": "skip",
                           "why": f"{notional:.2f} USDT notional is below one "
                                  f"contract", "strategy": key, "dry_run": dry})
            return
        # A deep ladder rung can exceed the venue's per-order volume cap —
        # MEXC answers code 2051 and the trade never happens. Cap and say so:
        # a smaller trade beats a rejected one.
        try:
            max_vol = int(float(fx.contract_spec(symbol).get("maxVol") or 0))
        except Exception:
            max_vol = 0
        if max_vol and vol > max_vol:
            # Recompute margin/notional from the size that ACTUALLY goes to
            # market. Recording the full ladder margin against a capped order
            # inflated every downstream figure for that trade — including the
            # numbers the daily loss limit reads.
            scale = max_vol / vol
            logger.warning(
                "%s: ladder wants %d contracts but the venue caps a single "
                "order at %d — sizing down. Notional %.0f → %.0f USDT, "
                "margin %.2f → %.2f.",
                symbol, vol, max_vol, notional, notional * scale,
                margin, margin * scale)
            vol = max_vol
            notional *= scale
            margin *= scale
        tp_px, sl_px = _bracket(side, entry, spec["tp"], spec["sl"])
        order_side = fx.SIDE_OPEN_LONG if side > 0 else fx.SIDE_OPEN_SHORT
        logger.info(
            "ENTER %s %s · %s · vol %d (%.0f USDT notional, %.0f margin, "
            "step %d) · entry ~%.6g · TP %.6g · SL %.6g [%s]", symbol,
            "LONG" if side > 0 else "SHORT", key, vol, notional, margin,
            st["step"] + 1, entry, tp_px, sl_px,
            "dry run" if dry else "LIVE ORDER")
        try:
            fx.submit(symbol, order_side, vol, leverage=LEVERAGE, dry_run=dry)
        except Exception as exc:
            # The order was REFUSED, so there is nothing open and nothing to
            # bracket: the candle goes back. This is the last point where a
            # retry is safe — past here the position exists, and re-reading
            # the same signal would open a second one.
            st["last_ts"][spec["interval"]] = _prev_seen
            logger.error(
                "ORDER REFUSED %s %s: %s — nothing opened, the %s candle is "
                "left UNSEEN so the next cycle retries this signal.",
                key, symbol, exc, spec["interval"])
            append_ledger({"symbol": symbol, "action": "order_failed",
                           "strategy": key, "why": str(exc), "vol": vol,
                           "retry": True, "dry_run": dry})
            return
        position_id = 0
        if not dry:
            # Find the filled position, then bracket at the REAL fill price,
            # snapped to the contract's price precision — MEXC rejects a stop
            # with too many decimals (code 2015), and a rejected stop once
            # left two live positions unprotected.
            # Match by SIDE and take the newest — open_positions()[0] once
            # returned a stale opposite-side position while the 1m strategy
            # was churning, which bracketed the wrong trade and orphaned the
            # right one.
            want_type = 1 if side > 0 else 2
            for _ in range(10):
                cands = [p for p in fx.open_positions(symbol)
                         if int(p.get("positionType") or 0) == want_type]
                if cands:
                    newest = max(cands,
                                 key=lambda p: p.get("updateTime") or 0)
                    position_id = int(newest.get("positionId") or 0)
                    entry = float(newest.get("holdAvgPrice") or entry)
                    tp_px, sl_px = _bracket(side, entry, spec["tp"], spec["sl"])
                    break
                time.sleep(1)
            tp_px, sl_px = _snap_prices(symbol, tp_px, sl_px, fx=fx)
        # Record the position BEFORE bracketing: if the stop is rejected the
        # runner must still know it holds the position, or it can never exit
        # it — and would enter again on the next candle.
        # "dry" is a property of THE POSITION, fixed at entry — never re-read
        # from settings later. Flipping the Dry-run checkbox while a real
        # position is open must not make the runner fabricate its exit, and a
        # paper position must never be mistaken for money at risk.
        _opened_at = int(time.time())
        # The trade's identity, minted ONCE here and carried to its exit row,
        # so the history table can name a trade and say when it opened.
        _tid = trade_code(symbol, key, last_ts, side, bool(dry))
        st["position"] = {"side": side, "vol": vol, "entry": entry,
                          "tp": tp_px, "sl": sl_px, "margin": margin,
                          "strategy": key, "entry_ts": last_ts,
                          "position_id": position_id, "dry": bool(dry),
                          # entry_ts is the CANDLE's time; opened_at is when
                          # the order actually went out — the operator asked
                          # to see both.
                          "opened_at": _opened_at, "trade_id": _tid,
                          "bracket": bool(dry)}
        if not dry:
            _rest_bracket(symbol, st["position"], fx=fx)
        append_ledger({"symbol": symbol, "action": "enter", "strategy": key,
                       "trade_id": _tid, "opened_at": _opened_at,
                       "side": "LONG" if side > 0 else "SHORT", "vol": vol,
                       "entry": entry, "tp": round(tp_px, 6),
                       "sl": round(sl_px, 6), "margin": margin,
                       "leverage": LEVERAGE, "step": st["step"],
                       "dry_run": dry})
        # The bell. Wrapped because this is the live money path: a feed write
        # failing must never be able to interrupt an order or a bracket.
        try:
            from tradingagents import notifications as _nt

            _nt.record(
                "trade_open",
                f"{'PAPER' if dry else 'LIVE'} {'LONG' if side > 0 else 'SHORT'} "
                f"{symbol.replace('_USDT', '')}",
                detail=(f"{key} · entry {entry} · {margin} USDT at {LEVERAGE}x "
                        f"· TP {round(tp_px, 6)} / SL {round(sl_px, 6)}"),
                ok=True,
                meta={"symbol": symbol, "strategy": key, "dry": bool(dry),
                      "side": "LONG" if side > 0 else "SHORT",
                      "entry": entry, "margin": margin, "step": st["step"]})
        except Exception:
            pass
        return


def adopt_orphans(settings: dict, state: dict, *, fx, dry: bool) -> None:
    """Adopt any exchange position on a bot coin that the book isn't
    tracking: record it, bracket it with its strategy's barriers.

    This automates the manual rescue of 2026-08-12 — an orphaned BDX long
    sat unprotected until closed by hand. Never again silently.
    """
    if dry:
        return
    for key in settings.get("strategies", []):
        spec = STRATEGY_SPECS.get(key)
        if spec is None:          # a retired name must not kill the sweep
            logger.warning("orphan sweep: unknown strategy %r in settings — "
                           "skipping it, continuing with the rest.", key)
            continue
        for symbol in coins_for(key, settings):
            st = state.setdefault(state_key(symbol, False),
                                  {"step": 0, "last_ts": {},
                                   "position": None})
            held = st.get("position")
            if held and not held.get("dry"):
                continue
            if held and held.get("dry"):
                # A paper trade parked in the live slot would block rescue on
                # this coin forever. The live book is for real money only.
                logger.warning("%s: a simulated position was occupying the "
                               "live book — clearing it so rescue can run.",
                               symbol)
                st["position"] = None
            try:
                live = fx.open_positions(symbol)
            except Exception:
                continue
            for p in live:
                side = 1 if int(p.get("positionType") or 0) == 1 else -1
                entry = float(p.get("holdAvgPrice") or 0)
                vol = int(p.get("holdVol") or 0)
                if not entry or not vol:
                    continue
                tp_px, sl_px = _bracket(side, entry, spec["tp"], spec["sl"])
                tp_px, sl_px = _snap_prices(symbol, tp_px, sl_px, fx=fx)
                # Derive margin from the position's ACTUAL size. Recording the
                # configured base margin understated every figure for an
                # adopted trade by up to 8x.
                real_margin = margin_for(key, settings)
                try:
                    csize = float(fx.contract_spec(symbol).get("contractSize") or 0)
                    if csize > 0 and entry > 0:
                        real_margin = round(vol * csize * entry / LEVERAGE, 6)
                except Exception:
                    pass
                st["position"] = {
                    "side": side, "vol": vol, "entry": entry,
                    "tp": tp_px, "sl": sl_px,
                    "margin": real_margin,
                    "strategy": key, "entry_ts": int(time.time()),
                    "opened_at": int(time.time()),
                    "position_id": int(p.get("positionId") or 0),
                    # An adopted position is REAL by definition. Without this
                    # the mode fell back to the current checkbox, and ticking
                    # Dry run let the simulator "close" real money.
                    "dry": False, "bracket": False}
                logger.error(
                    "ORPHAN ADOPTED: %s %s (vol %s, entry %.6g) was open on "
                    "MEXC with no book entry — now tracked under %s and "
                    "being bracketed.", symbol,
                    "LONG" if side > 0 else "SHORT", vol, entry, key)
                append_ledger({"symbol": symbol, "action": "orphan_adopted",
                               "strategy": key, "vol": vol, "entry": entry})
                _rest_bracket(symbol, st["position"], fx=fx)
                break


def reconcile_unconfigured(settings: dict, state: dict, *, fx) -> None:
    """Settle book positions whose coin is no longer in the settings.

    ``process_symbol`` only visits configured coins, so removing a strategy or
    a coin used to STRAND its open position in the book forever — the UI kept
    showing money at risk that the exchange had already closed, and its real
    PnL never reached the ledger. Found live on 2026-08-12: CHEEMS, ONG and
    MCDSTOCK all sat stale after the strategy list was replaced.
    """
    configured = {c for k in settings.get("strategies", [])
                  for c in coins_for(k, settings)}
    for key, st in list(state.items()):
        if not isinstance(st, dict):
            continue
        if key.endswith("#paper"):
            # Paper books have no exchange position; a de-configured paper
            # trade would otherwise sit in the UI forever.
            sym = key[:-len("#paper")]
            if st.get("position") and sym not in configured:
                st["position"] = None
                logger.info("cleared a stranded PAPER position on %s "
                            "(coin no longer configured).", sym)
            continue
        symbol = key
        pos = st.get("position")
        if not pos or symbol in configured or pos.get("dry"):
            continue
        try:
            still_open = any(p.get("symbol") == symbol
                             for p in fx.open_positions(symbol))
        except Exception:
            continue                      # cannot verify → leave it alone
        if still_open:
            # Still live on a coin we no longer scan: it would otherwise sit
            # with nobody retrying its bracket. Make it safe here.
            if not pos.get("bracket", True):
                logger.error(
                    "CRITICAL: %s is OPEN and UNPROTECTED on a coin no "
                    "longer configured — bracketing it now.", symbol)
                _rest_bracket(symbol, pos, fx=fx)
            continue
        realised = None
        try:
            for h in fx.position_history(symbol, 10):
                if int(h.get("positionId") or 0) == int(
                        pos.get("position_id") or -1):
                    realised = float(h.get("realised") or 0.0)
                    break
        except Exception:
            realised = None
        st["position"] = None
        logger.warning(
            "RECONCILED %s: the book held a position on a coin no longer "
            "configured, and the exchange has closed it. Realised %s.",
            symbol, "unknown" if realised is None else f"{realised:+.2f} USDT")
        _rop = pos.get("opened_at") or pos.get("entry_ts")
        append_ledger({"symbol": symbol, "action": "exit", "why": "RECONCILED",
                       "strategy": pos.get("strategy"),
                       "trade_id": pos.get("trade_id"), "opened_at": _rop,
                       "held_s": (int(time.time()) - int(_rop)) if _rop
                                 else None,
                       "side": "LONG" if pos.get("side", 0) > 0 else "SHORT",
                       "entry": pos.get("entry"),
                       "pnl_est": None if realised is None else round(realised, 2),
                       "dry_run": False})


def run_cycle(*, fx=None) -> None:
    if fx is None:
        from tradingagents.dataflows import mexc_futures as fx  # noqa: PLC0415
    settings = load_settings()
    if not active_modes(settings):
        return
    # One timeframe per coin. Two strategies on the same coin at different bar
    # sizes net into ONE MEXC position, so the second entry resizes the first
    # and either stop closes part of a trade it does not own. Refuse the cycle
    # rather than trade a position neither strategy thinks it owns.
    conflicts = timeframe_conflicts(settings)
    if conflicts:
        for c in conflicts:
            logger.error(
                "REFUSING TO TRADE %s: enabled on %s at once (%s). One "
                "timeframe per coin -- untick all but one.", c["coin"],
                " and ".join(c["timeframes"]), ", ".join(c["strategies"]))
            append_ledger({"symbol": c["coin"], "action": "blocked",
                           "why": "coin enabled on multiple timeframes",
                           "strategies": c["strategies"],
                           "timeframes": c["timeframes"]})
        return
    state = load_state()
    try:
        # Orphan rescue is a LIVE concern. Gate it on whether the live book is
        # running, NOT on dry_mode() — dry_mode ignores `enabled`, so with both
        # switches ticked this silently skipped every rescue.
        # Rescue live orphans whenever the LIVE book is running — which is now
        # "any armed strategy trades real", not the old global `enabled`.
        adopt_orphans(settings, state, fx=fx,
                      dry=False not in active_modes(settings))
    except Exception as exc:
        logger.warning("orphan sweep failed: %s", exc)
    try:
        reconcile_unconfigured(settings, state, fx=fx)
    except Exception as exc:
        logger.warning("reconcile sweep failed: %s", exc)
    tripped_by_book = {d: frozenset(tripped_strategies(settings, dry=d))
                       for d in active_modes(settings)}
    tripped = frozenset().union(*tripped_by_book.values()) \
        if tripped_by_book else frozenset()
    today = time.strftime("%Y-%m-%d")
    logged = state.setdefault("_tripped_logged", {})
    for key in sorted(tripped):
        if logged.get(key) != today:
            logged[key] = today
            pnl = pnl_today_by_strategy().get(key, 0.0)
            limit = (settings.get("strategy_loss_limits") or {}).get(key)
            logger.error(
                "STRATEGY LOSS LIMIT HIT: %s is %+.2f USDT today "
                "(limit -%s) — PAUSED until midnight. Other strategies "
                "keep running; its open position keeps its bracket.",
                key, pnl, limit)
            append_ledger({"action": "strategy_paused", "strategy": key,
                           "pnl_today": pnl, "limit": limit})
    symbols: list[str] = []
    for key in settings.get("strategies", []):
        for c in coins_for(key, settings):
            if c not in symbols:
                symbols.append(c)
    modes = active_modes(settings)
    # Only the slots this cycle visited get written back. Anything else on
    # disk belongs to another writer — the app's CLOSE button — and is left
    # exactly as found.
    touched: list = ["_tripped_logged"]
    for dry in modes:
      for symbol in symbols:
        try:
            touched.append(state_key(symbol, dry))
            process_symbol(symbol, settings, state, fx=fx, dry=dry,
                           tripped=tripped_by_book.get(dry, frozenset()))
            st = state.get(state_key(symbol, dry), {})
            pos = st.get("position")
            seen = st.get("last_ts") or {}
            if not isinstance(seen, dict):     # pre-multi-TF state files
                seen = {"Hour4": seen}
            def _bar_stamp(ts: float) -> str:
                # The scan log is shown in the Runner feed, so it uses THE
                # format like everything else. This was a third hand-rolled
                # copy — unpadded day, uppercase PM — and it is what the
                # operator was looking at when they asked for the format a
                # third time on 2026-08-22.
                from tradingagents.positions_view import fmt_when

                return fmt_when(ts)

            bars_txt = " ".join(
                f"{tf}@{_bar_stamp(ts)}"
                for tf, ts in sorted(seen.items())) or "none yet"
            logger.info(
                "scan %s: step=%s position=%s last_bars=%s", symbol,
                st.get("step", 0),
                (f"{'LONG' if pos['side'] > 0 else 'SHORT'} {pos['strategy']} "
                 f"entry {pos['entry']} tp {pos['tp']:.2f} sl {pos['sl']:.2f}"
                 if pos else "flat — no signal or waiting for a new candle"),
                bars_txt)
        except Exception as exc:  # one sick coin must not stop the others
            msg = str(exc)
            if any(t in msg.lower() for t in ("429", "too many", "rate limit",
                                              "510", "request frequency")):
                logger.warning(
                    "RATE LIMITED by MEXC while scanning %s — skipping this "
                    "cycle; the next poll retries automatically. Persistent "
                    "rate limits mean too many coins/timeframes are enabled.",
                    symbol)
                append_ledger({"symbol": symbol, "action": "rate_limited",
                               "why": msg})
            else:
                logger.warning("auto-trader cycle failed for %s: %s",
                               symbol, exc)
                append_ledger({"symbol": symbol, "action": "error",
                               "why": msg})
    save_state(state, keys=touched)


# --------------------------------------------------------- process control
def wants_runner() -> bool:
    """Whether the operator has asked for the runner to be up."""
    return WANT_PATH.exists()


def runner_pid() -> int | None:
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if portable.pid_alive(pid) else None


def start_runner() -> int:
    """Spawn the loop as a detached process. Returns the PID."""
    existing = runner_pid()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # record the INTENT before spawning: a supervisor keeps it up from here
    WANT_PATH.write_text("run", encoding="utf-8")
    if existing:
        return existing
    with LOG_PATH.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "tradingagents.auto_trader", "run"],
            stdout=log, stderr=log, **portable.DETACHED,
            cwd=str(Path(__file__).resolve().parent.parent))
    PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def stop_runner() -> bool:
    """Terminate by recorded PID — never by process name.

    Clears the want-flag FIRST, so a supervisor does not restart what the
    operator just stopped.
    """
    WANT_PATH.unlink(missing_ok=True)
    pid = runner_pid()
    if not pid:
        PID_PATH.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    PID_PATH.unlink(missing_ok=True)
    return True


def next_sleep_seconds(now: float | None = None) -> float:
    """Sleep so the next wake lands seconds after the FINEST enabled
    timeframe's candle closes.

    Entries can only appear on a fresh candle, so waking at the boundary (plus
    a small lag for the exchange to publish it) is what makes the entry price
    the real-time one the backtest assumed — a fixed 5-minute poll entered up
    to 5 minutes late. With the 1m realtime sweep enabled this wakes every
    minute. Between boundaries the heartbeat still runs so a disable is
    noticed, and a simulated open position is tick-checked fast.
    """
    now = time.time() if now is None else now
    enabled = load_settings().get("strategies", [])
    bar = min((STRATEGY_SPECS[k]["bar_seconds"] for k in enabled
               if k in STRATEGY_SPECS), default=4 * 3600)
    to_boundary = bar - (now % bar) + ENTRY_LAG_SECONDS
    # ONLY a paper position justifies the fast poll: a live position's exit
    # is handled by the exchange-side bracket, so polling fast for it just
    # burns the rate limit that protects the candle data.
    has_dry_position = any(
        isinstance(v, dict) and (v.get("position") or {}).get("dry")
        for k, v in load_state().items() if k.endswith("#paper"))
    cap = DRY_EXIT_POLL_SECONDS if has_dry_position else POLL_SECONDS
    return max(1.0, min(float(cap), to_boundary))


def disk_free_mb() -> int:
    """Free space where the state, ledger and log live."""
    return portable.disk_free_mb(STATE_DIR if STATE_DIR.exists() else Path.home())


MIN_FREE_MB = 500


def run_forever() -> None:
    from tradingagents.dataflows import mexc_credentials as cred
    cred.load_into_env()
    # Finish the cycle in flight before dying. Ledger rows are written during
    # a cycle and state is saved at the end; being killed between the two
    # replayed the exit next start and double-counted the day's loss.
    _stopping = {"flag": False}

    def _graceful(signum, frame):
        _stopping["flag"] = True
        logger.warning("stop requested — finishing this cycle, then exiting.")
    try:
        signal.signal(signal.SIGTERM, _graceful)
        signal.signal(signal.SIGINT, _graceful)
    except (ValueError, OSError):
        pass
    other = runner_pid()
    if other and other != os.getpid():
        # Two runners double every trade. Refuse loudly instead.
        print(f"another auto-trader is already running (pid {other}) — "
              f"stop it first:  kill {other}", file=sys.stderr)
        raise SystemExit(1)
    # The pid check alone LOST A RACE on 2026-08-22: launchd started a second
    # runner beside a healthy one and both lived for seconds while the newcomer
    # was still importing. An exclusive lock cannot race — whoever holds it is
    # the runner, and the loser exits before it can trade.
    global _RUN_LOCK
    try:
        # held for the life of the process ON PURPOSE: closing it releases
        # the flock, which is the only thing stopping a second runner
        _RUN_LOCK = open(LOCK_PATH, "w")   # noqa: SIM115
        portable.lock_exclusive(_RUN_LOCK, blocking=False)
    except OSError:
        print("another auto-trader holds the run lock — exiting so trades are "
              "never doubled", file=sys.stderr)
        raise SystemExit(1) from None
    # A full disk killed the runner mid-write on 2026-08-22 (fatal OSError at
    # 05:33); two positions then closed at the exchange with nobody recording
    # the exits for three hours. Refuse to start, loudly, instead.
    free = disk_free_mb()
    if free < MIN_FREE_MB:
        logger.error("REFUSING TO START: only %s MB free where the state and "
                     "ledger live (need %s MB). A write failing mid-cycle is "
                     "how the runner died on 2026-08-22 — free space first.",
                     f"{free:,}", f"{MIN_FREE_MB:,}")
        print(f"disk almost full: {free} MB free, need {MIN_FREE_MB} MB",
              file=sys.stderr)
        raise SystemExit(2)
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    modes = active_modes()
    names = [("LIVE — real orders" if not d else "PAPER — simulated")
             for d in modes] or ["nothing enabled"]
    logger.info("auto-trader loop starting (%s)", " + ".join(names))
    append_ledger({"action": "runner_start", "books": names})
    try:
        while True:
            settings = load_settings()
            if not active_modes(settings):
                append_ledger({"action": "runner_stop", "why": "disabled"})
                break
            run_cycle()
            if _stopping["flag"]:
                append_ledger({"action": "runner_stop", "why": "signal"})
                break
            if loss_limit_hit():
                day = pnl_today()
                limit = settings.get("loss_limit")
                KILL_PATH.write_text(
                    f"account daily loss limit hit: realised "
                    f"{day['total']:+.2f} USDT reached the limit of "
                    f"-{abs(float(limit)):.2f} USDT")
                logger.error(
                    "DAILY LOSS LIMIT HIT: realized %+.2f USDT ≤ -%s — "
                    "auto trade STOPPED. Open positions keep their "
                    "exchange-side TP/SL. Re-enable by ticking Auto Trade "
                    "and saving (that clears the kill file).",
                    day["total"], limit)
                append_ledger({"action": "loss_limit_stop",
                               "pnl_today": day["total"], "limit": limit})
                break
            slept = 0.0
            target = next_sleep_seconds()
            while slept < target and not _stopping["flag"]:
                time.sleep(min(1.0, target - slept))
                slept += 1.0
    finally:
        if runner_pid() == os.getpid():
            PID_PATH.unlink(missing_ok=True)




def save_settings(payload: dict) -> list[dict]:
    """Write auto_trade.json atomically and record what changed, locally.

    The deploy history write must never stop the save itself. Returns the
    recorded changes so callers can show what happened.
    """
    prev = load_settings()
    _write_json(SETTINGS_PATH, payload)
    changes: list[dict] = []
    try:
        from tradingagents import local_history as _lh

        for c in _lh.deploy_diff(prev, payload):
            if _lh.record_deployment(c):
                changes.append(c)
    except Exception:
        pass
    return changes


def timeframe_locks(settings: dict | None = None) -> dict:
    """Which strategies may not go LIVE, because their coin is already taken.

    ONE LIVE STRATEGY PER COIN. Not one per timeframe — per coin, full stop.
    MEXC nets every order on a contract into a single position, so a second
    live entry resizes the first and either stop closes part of a trade it does
    not own. The bar size is irrelevant to that; the contract is what nets.

    This check used to compare intervals (`claim[c][1] != interval`), so it
    only caught clashes across DIFFERENT timeframes. On 2026-08-22 PROVE was
    running `fade15_1h_pv2` and `mom6_1h_pv` live at the SAME 1h, and the guard
    waved it through.

    DEMO is never locked. The operator's words: "for demo it can have multiple
    strategies so i can see if its working" — a simulated book has no MEXC
    position to fight over, and comparing strategies side by side on one coin
    is the point of paper trading.

    The FIRST live row in STRATEGY_ORDER wins a coin, so freeing it is an
    explicit disarm rather than a silent reassignment. Two passes, because the
    rule is symmetric: claiming and locking in one sweep only ever locked rows
    below the holder.

    Returns {locked_key: {"coin": ..., "held_by": ...}}.
    """
    if settings is None:
        settings = load_settings()
    books = settings.get("strategy_books") or {}
    coins = settings.get("strategy_coins") or {}

    claim: dict[str, str] = {}            # coin -> the key holding it live
    for key in STRATEGY_ORDER:
        if "real" not in (books.get(key) or []):
            continue                      # demo claims nothing and locks nobody
        mine = coins.get(key) or []
        if any(c in claim for c in mine):
            continue                      # already double-booked: claims nothing
        for c in mine:
            claim.setdefault(c, key)

    locked: dict[str, dict] = {}
    for key in STRATEGY_ORDER:
        hit = next((c for c in (coins.get(key) or [])
                    if c in claim and claim[c] != key), None)
        if hit:
            locked[key] = {"coin": hit, "held_by": claim[hit]}
    return locked


# ---------------------------------------------------------------------------
# THE ENTRY POINT MUST BE THE LAST THING IN THIS FILE.
#
# It used to sit at line 2999 with save_settings and timeframe_locks defined
# BELOW it. `import tradingagents.auto_trader` runs the whole file, so the API
# and every test saw those two functions and everything looked fine. The runner
# starts with `python -m tradingagents.auto_trader run`: the module body
# executes top to bottom, reaches this guard, and enters the trading loop —
# so nothing below it is ever defined.
#
# On 2026-08-22 that made every LIVE cycle raise
# `name 'timeframe_locks' is not defined` from 13:34:23 onward: 1,176 failures
# over five hours, four coins a cycle. The paper book kept running, because the
# lock is only consulted when the book is real, so the screen still filled with
# healthy-looking scan lines. No money was lost — no live entry could be placed
# — but no live entry could be placed.
#
# Anything appended after this block is invisible to the runner and visible to
# everything else, which is the worst kind of bug: it passes every test.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Log to THE FILE, not to stdout.
    #
    # `start_runner()` spawns the child with stdout/stderr redirected into
    # auto_trade.log, so a runner started from the UI button filled the Runner
    # feed. launchd starts the very same command with its output going to
    # supervisor.log — so a runner it restarted (a crash, a reboot) wrote
    # nothing to auto_trade.log at all: the feed sat frozen on the last line
    # the previous process wrote, and api.py uses that file's mtime as the
    # runner's heartbeat, so a perfectly healthy runner read as dead.
    #
    # Owning the handler here makes it true however the process was started.
    # No StreamHandler, or the UI path would write every line twice.
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    # THE date format on every line too. basicConfig's default asctime is
    # "2026-08-22 19:27:03,488" — the compact stamp the operator banned,
    # printed on every row of the Runner feed they read.
    from tradingagents.positions_view import WhenFormatter

    _h = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _h.setFormatter(WhenFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[_h])
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        run_cycle()
    else:
        run_forever()
