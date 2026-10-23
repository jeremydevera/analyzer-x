"""ONE COIN THE V3 WAY, for real — Part 1's check that the engine runs on
Gate's own data before any GitHub run (Backtest v3 plan, Task 6).

    .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1h bb20 fixed:0.02:0.01
    .venv/Scripts/python -m tradingagents.v3_smoke BTC_USDT 1d trend50 trail:3:50 --days 365

Prints how much of the window the recorded order books cover first (COVERAGE
FIRST), then trades, wins, losses and profit at $1 risk a trade, the orders
that never filled and what entering them at the market would have made, and
every count the engine keeps. Reads only: no order, no store, no screen.
"""
from __future__ import annotations

import argparse
import time

LEAD_BARS = 300       # the lookback every stored rule reads before it can signal
# a copy of auto_trader.PAPER_SLIPPAGE: ONE figure for every coin, paid a side
# where no book was recorded. The engine has no default gap (walk's flat_slip
# is required); Part 2 passes each coin's own (CLAUDE.md rule 10)
FLAT_SLIP = 0.0003


def exit_spec(text: str) -> dict:
    """fixed:TP:SL · trail:ATR[:MA] · snap:ATR:BARS (fractions, multiples, counts)."""
    kind, *parts = text.split(":")
    if kind == "fixed" and len(parts) == 2:
        return {"kind": "fixed", "tp": float(parts[0]), "sl": float(parts[1])}
    if kind == "trail" and parts:
        return {"kind": "trail", "atr_mult": float(parts[0]),
                "ma_n": int(parts[1]) if len(parts) > 1 else None}
    if kind == "snap" and len(parts) == 2:
        return {"kind": "snap", "mean_n": 20, "stop_atr": float(parts[0]),
                "max_bars": int(parts[1])}
    raise ValueError(f"exit {text!r}: use fixed:TP:SL, trail:ATR[:MA] or snap:ATR:BARS")


def run(sym: str, tf: str, signal: str, spec: dict, *, days: int = 120,
        th: float | None = None, fx=None) -> dict:
    """One stored signal on one coin over its last `days`, the v3 way."""
    import tradingagents.auto_trader as at
    from tradingagents import backtest_report as br, cost_store, v3_engine
    from tradingagents.positions_view import fmt_when

    if fx is None:
        from tradingagents.dataflows import exchange as fx
    iv, bar_s, _cap = br.TFS[tf]
    df = fx.klines(sym, iv, int(days * 86400 / bar_s) + LEAD_BARS)
    t_all = df["Date"].to_numpy().astype("datetime64[ms]").astype("int64")
    final = t_all + bar_s * 1000 <= int(time.time() * 1000)   # the forming candle is not final
    df, t = df[final], [int(x) for x in t_all[final]]
    bars = {"t": t, "o": [float(x) for x in df["Open"]], "h": [float(x) for x in df["High"]],
            "l": [float(x) for x in df["Low"]], "c": [float(x) for x in df["Close"]]}
    vol = [float(x) for x in df["Volume"]] if "Volume" in df.columns else None
    lead = min(LEAD_BARS, len(t) - 1)
    from_s, end_s = t[lead] // 1000, t[-1] // 1000 + bar_s
    ft, fh, fl, _n5 = br.fine_bars(sym, from_s, end_s, fx=fx)
    fine = (ft.tolist(), fh.tolist(), fl.tolist()) if len(ft) else None
    book = cost_store.engine_book(sym, from_s, end_s)
    fund = fx.funding_history(sym, since_ms=(from_s - 86400) * 1000)
    c = fx.contract_spec(sym)
    key = f"{signal}_v3_{tf}"
    at.STRATEGY_SPECS[key] = {"interval": iv, "bar_seconds": bar_s, "tp": .02, "sl": .01,
                              "threshold": .003 if th is None else th}
    try:
        dk = "rsi14_1h" if signal == "rsi14" else key
        dirs = at._dirs_for_backtest(dk, bars["h"], bars["l"], bars["c"], opens=bars["o"],
                                     volume=vol, ts=t, funding=fund)
    finally:
        at.STRATEGY_SPECS.pop(key, None)
    got = v3_engine.walk(
        bars, dirs, spec, bar_s=bar_s,
        contract={"contract_size": float(c.get("contractSize") or 0.0),
                  "min_vol": int(c.get("minVol") or 1),
                  "mmr": float(c.get("maintenanceMarginRate") or 0.0),
                  "max_lev": int(c.get("maxLeverage") or 1),
                  "min_lev": int(c.get("minLeverage") or 1)},
        fees={"maker": at.maker_fee_floor(), "taker": at.fee_floor()},
        fine=fine, book=book, flat_slip=FLAT_SLIP, funding=fund, start=lead)
    trades = got["trades"]
    twins = [m["market"] for m in got["missed"] if "pnl" in m["market"]]
    return {"sym": sym, "tf": tf, "signal": signal, "exit": spec,
            "start": fmt_when(from_s), "end": fmt_when(end_s),
            "coverage": cost_store.coverage(book, from_s, end_s),
            "trades": len(trades), "wins": sum(1 for x in trades if x["pnl"] > 0),
            "losses": sum(1 for x in trades if x["pnl"] <= 0),
            "profit": round(sum(x["pnl"] for x in trades), 2),
            "missed": len(got["missed"]), "missed_entered": len(twins),
            "missed_pnl": round(sum(x["pnl"] for x in twins), 2),
            "counts": got["counts"]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m tradingagents.v3_smoke",
                                description="One stored signal on one coin, the v3 way.")
    p.add_argument("sym")
    p.add_argument("tf", choices=("15m", "30m", "1h", "4h", "1d"))
    p.add_argument("signal")
    p.add_argument("exit", help="fixed:TP:SL, trail:ATR[:MA] or snap:ATR:BARS")
    p.add_argument("--days", type=int, default=120)
    p.add_argument("--th", type=float, default=None)
    a = p.parse_args(argv)
    t0 = time.time()
    got = run(a.sym, a.tf, a.signal, exit_spec(a.exit), days=a.days, th=a.th)
    print(f"{got['sym']} {got['tf']} {got['signal']} {a.exit}: {got['start']} to {got['end']}")
    print(f"order books cover {100 * got['coverage']:.1f}% of the minutes "
          "(the rest pay a typical cost)")
    print(f"{got['trades']} trades, {got['wins']} won, {got['losses']} lost, "
          f"{got['profit']:+.2f} at $1 risk a trade")
    print(f"orders that never filled: {got['missed']}; the {got['missed_entered']} the "
          f"runner would have entered at the market would have made {got['missed_pnl']:+.2f}")
    print("counts:", got["counts"], f"({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
