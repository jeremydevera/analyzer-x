"""THE backtesting-trading-strategies SKILL ON EVERY COIN x EVERY TIMEFRAME (Nov 05, 2026;
tradingagents/skill_bt.py). Each claimed coin's 15m, 30m, 1h, 4h and 1d candles from the exchange,
the skill's eight strategies x three settings x two stops chosen on the older 70% and judged on the
newest 30%, every trade paying the coin's fee both ways and its usual gap. One line per coin-timeframe.

SKILL_SET=ta runs the technical-analysis and backtesting-frameworks skills' own strategies instead
(tradingagents/skill_ta.py), the same way, into skillta-*.jsonl; ta_all keeps EVERY one of their 42
settings x stops of each coin-timeframe, not the best 3, into skilltaall-*.jsonl.

SKILL_SET=daily is what the skill rooms follow (skilldaily-*.jsonl): all 42 technical-analysis
settings x stops, then ONLY the backtesting skill's strategies PINNED for that coin-timeframe
(research/v4/bt_pinned.json: Backtest v4's ids never move), every trade paying its funding. Since Nov
11, 2026 a stop or target is settled MINUTE BY MINUTE over the last `skill_bt.MINUTE_DAYS` days
(`skill_bt.Fine`, read once a coin, the same read a follower makes), the close deciding only the
candles the minutes do not cover; each line says how many steps went each way (`exits`).
"""
# ruff: noqa: E402
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault("MODE", "full")

import sweep_shard as ss  # noqa: E402

import tradingagents.auto_trader as at  # noqa: E402
from tradingagents import backtest_report as br, skill_bt as sb, skill_ta as sta  # noqa: E402
from tradingagents.dataflows import exchange as fx  # noqa: E402
from tradingagents.skill_frames import BARS, frame  # noqa: E402,F401  (the candle frame lives there)

SET = os.environ.get("SKILL_SET", "bt") or "bt"
if SET not in ("bt", "ta", "ta_all", "daily"):
    raise SystemExit(f"SKILL_SET must be bt, ta, ta_all or daily, not {SET!r}")
PREFIX = {"bt": "skill", "ta": "skillta", "ta_all": "skilltaall", "daily": "skilldaily"}[SET]
PINNED_FILE = os.path.join(ROOT, "research", "v4", "bt_pinned.json")
KEEP = None if SET == "ta_all" else sb.PER_PAIR
GRID, TARGETS = (None, None) if SET in ("bt", "daily") else (sta.GRID, sta.TARGETS)
OUT = os.path.join("out", f"{PREFIX}-{ss.SHARD}.jsonl")
REPORT_OUT = os.path.join("out", f"{PREFIX}-report-{ss.SHARD}.json")
COIN_RETRIES = 2


def costs(sym: str) -> tuple[float, float]:
    """The coin's fee a side and its usual gap a side (the searches' own reads)."""
    fee = at.taker_fee(sym, fx=fx)
    book = fx.book_cost(sym, ss.BASE_MARGIN * at.LEVERAGE)
    slip = br.charged_slippage([float(book.get("slippage") or 0.0) or 0.0003])
    return float(fee), float(slip)


def line(coin: str, tf: str, res: dict, fee: float, slip: float) -> dict:
    picks = []
    for c in res["picks"]:
        picks.append({"label": sb.label(c), "strategy": c["strategy"], "params": c["params"],
                      "stop": c["stop"], "target": c.get("target"), "older": c["older"], "newer": c["newer"],
                      "older_lost": c["older_lost"],
                      "trades": [[t["entry_ms"], t["exit_ms"], t["side"], t["why"], t["pnl"]]
                                 for t in c["trades"]]})
    return {"coin": coin, "tf": tf, "fee": fee, "slip": slip, "bars": res["bars"],
            "combos": res["combos"], "split_ms": res["split_ms"], "start_ms": res["start_ms"],
            "end_ms": res["end_ms"], "bar": res["bar"], "picks": picks}


def pinned_pairs() -> dict:
    """The backtesting skill's pinned picks by 'COIN|tf' (the daily set); a missing file is an
    error, never a day measured without them."""
    with open(PINNED_FILE, encoding="utf-8") as fh:
        return json.load(fh)["pairs"]


def funding_of(sym: str, first_ms: int) -> sb.Funding:
    """The coin's funding settlements since its first 1d candle, read ONCE a coin. A read that raises
    fails the coin (redone alone): never a coin measured with its funding silently missing."""
    return sb.Funding(fx.funding_history(sym, since_ms=int(first_ms)))


def _save(report):
    tmp = REPORT_OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(report, fh)
    os.replace(tmp, REPORT_OUT)


def main() -> int:
    os.makedirs("out", exist_ok=True)
    t0 = time.time()
    coins = ss.eligible()
    ss.report.board = len(coins)
    report, failed, queue, done, n = [], {}, [], 0, 0
    pinned = pinned_pairs() if SET == "daily" else {}
    with open(OUT, "w", encoding="utf-8") as out:
        stream = ss.coin_stream(coins, t0)
        while True:
            sym = next(stream, None)
            if sym is None:
                if not queue:
                    break
                sym = queue.pop(0)
            coin = sym.replace("_USDT", "")
            try:
                fee, slip = costs(sym)
                frames, funding, fine = {}, None, None
                if SET == "daily":
                    frames["1d"] = frame(sym, "1d")
                    funding = funding_of(sym, sb._ms(frames["1d"].index)[0] if len(frames["1d"]) else (time.time() - 730 * 86400) * 1000)
                    # the minutes, ONCE a coin: a read that raises fails the coin (redone alone) - never a
                    # coin measured on candles because its minutes were missing, while its room reads them
                    today_ms = int(time.time() * 1000) // 86_400_000 * 86_400_000
                    fine = sb.read_fine(sym, sb.fine_from_ms(today_ms))
                for tf in BARS:
                    t1 = time.time()
                    entry = {"coin": coin, "tf": tf}
                    try:
                        df = frames[tf] if tf in frames else frame(sym, tf)
                        if len(df) < 2:          # CLAUDE.md: no bar floor but the physical one
                            entry["skipped"] = f"{len(df)} candles"
                        elif SET == "daily":
                            out.write(json.dumps(sb.daily_line(coin, tf, df, pinned.get(f"{coin}|{tf}"), fee=fee,
                                                               slip=slip, funding=funding,
                                                               bar_ms=br.TFS[tf][1] * 1000, fine=fine),
                                                 separators=(",", ":")) + "\n")
                            n += 1
                        else:
                            out.write(json.dumps(line(coin, tf, sb.pair(df, fee=fee, slip=slip, grid=GRID, targets=TARGETS, k=KEEP), fee, slip),
                                                 separators=(",", ":")) + "\n")
                            n += 1
                    except Exception as exc:                       # noqa: BLE001
                        entry["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                        ss.log(f"{coin} {tf}: FAILED {entry['error']}")
                    entry["seconds"] = round(time.time() - t1, 1)
                    report.append(entry)
                out.flush()
                done += 1
            except Exception as exc:                               # noqa: BLE001
                failed[sym] = failed.get(sym, 0) + 1
                ss.log(f"{sym}: FAILED ({type(exc).__name__}: {exc}) try {failed[sym]}")
                if failed[sym] <= COIN_RETRIES:
                    queue.append(sym)
                else:
                    report.append({"coin": coin, "tf": "*", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            _save(report)
            ss.report("testing", done, len(coins), rows=n, note=f"{coin} done")
    _save(report)
    ss.log(f"skill run ({SET}) done: {done} coin(s), {n} coin-timeframe(s) in {(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
