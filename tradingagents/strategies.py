"""Strategy registry for MEXC perpetuals.

Six strategies, all long-only. They differ in **exposure structure**, not in
entry signals, and that is deliberate: across 51,192 tested signal combinations
on SPX500, permutation tests showed entry signals carried no information —
shuffled signals scored p=0.467 and randomly-timed entries did as well or
better. Walk-forward selection of the "best" signal lost money while holding
made money. So the honest levers are how much exposure to carry and when to
give it up, not what to predict.

Every strategy is scored against buy & hold on the same bars, same leverage,
same fees. A strategy that cannot beat holding is reported as not beating it.
"""

from __future__ import annotations

import dataclasses

from tradingagents import futures_backtest as fbt


@dataclasses.dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    kind: str                 # "bracket" or "position"
    summary: str              # one line, shown in the picker
    rationale: str            # why this is defensible rather than mined
    params: dict              # defaults, editable in the UI
    risk: str                 # the honest failure mode


def _sma(values, n):
    out, run = [None] * len(values), 0.0
    for i, v in enumerate(values):
        run += v
        if i >= n:
            run -= values[i - n]
        out[i] = run / n if i >= n - 1 else None
    return out


def _stdev(values, n):
    out = [None] * len(values)
    for i in range(len(values)):
        if i < n - 1:
            continue
        w = values[i - n + 1:i + 1]
        m = sum(w) / n
        out[i] = (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return out


# ------------------------------------------------------------------ registry
REGISTRY: dict[str, Strategy] = {
    "barrier_harvest": Strategy(
        key="barrier_harvest",
        name="Barrier harvest (validated)",
        kind="bracket",
        summary="Always long. Limit-sell each +2% pop, rebuy next bar. Stop -10%.",
        rationale=(
            "The only configuration that survived adversarial review. The limit "
            "take-profit sells an intrabar spike and rebuys at the next open, "
            "often lower — harvesting chop inside an uptrend. 98% of the "
            "surrounding TP/SL grid also beat holding, so it is a plateau "
            "rather than a lone spike."),
        params={"take_profit_pct": 2.0, "stop_loss_pct": 10.0},
        risk=("The edge is ~3 of 14.7 unlevered points; the rest is drift. It "
              "dies past ~25bp of slippage, so the exit must fill as a limit."),
    ),
    "buy_hold": Strategy(
        key="buy_hold",
        name="Buy and hold",
        kind="position",
        summary="Enter once, never exit. The benchmark every other strategy must beat.",
        rationale=(
            "Not a placeholder — it beat every signal strategy tested, including "
            "walk-forward selection of the best performer. One trade, no fees "
            "beyond the round trip, no timing risk."),
        params={},
        risk=("Full exposure to every drawdown. On this instrument the worst "
              "1-week fall in 188 days was -7.1%; at leverage that is amplified."),
    ),
    "trend_filter": Strategy(
        key="trend_filter",
        name="Trend filter",
        kind="position",
        summary="Long only while price is above its moving average, flat below.",
        rationale=(
            "Gives up drift in exchange for sitting out sustained declines. "
            "Structural, not predictive: it makes no forecast, it just refuses "
            "to hold what is already falling."),
        params={"ma_bars": 200},
        risk=("Whipsaws in a choppy market: each cross costs fees and can sell "
              "the low. In the SPX500 sample this UNDERPERFORMED holding."),
    ),
    "session_long": Strategy(
        key="session_long",
        name="Cash-session long",
        kind="position",
        summary="Hold only while the US cash market is open (13:30-20:00 UTC).",
        rationale=(
            "A perpetual trades 24/7 but the index it tracks does not. Off-hours "
            "pricing is a dealer's mark, not real discovery, so this avoids "
            "carrying risk through hours with no underlying liquidity."),
        params={"open_hour_utc": 13, "close_hour_utc": 20},
        risk=("Roughly a third of the exposure, so roughly a third of the drift. "
              "Also misses overnight gaps in both directions."),
    ),
    "ladder_dca": Strategy(
        key="ladder_dca",
        name="Ladder in (DCA)",
        kind="position",
        summary="Scale exposure in over N steps instead of entering all at once.",
        rationale=(
            "Removes entry timing entirely — the single decision most likely to "
            "be wrong. Averages the fill across the ladder period, which lowers "
            "the worst-case entry without needing a forecast."),
        params={"steps": 8, "bars_between": 288},
        risk=("In a rising market a ladder underperforms buying immediately, "
              "because the un-deployed portion earns nothing."),
    ),
    "vol_target": Strategy(
        key="vol_target",
        name="Volatility target",
        kind="position",
        summary="Size exposure inversely to recent volatility, capped at 100%.",
        rationale=(
            "Holds risk roughly constant instead of holding size constant. Cuts "
            "exposure automatically when the instrument gets violent, which is "
            "when leveraged accounts get liquidated."),
        params={"lookback_bars": 288, "target_vol_pct": 0.05},
        risk=("Reacts to volatility that has already happened. In a calm, "
              "steadily rising market it will lever up right before a shock."),
    ),
}

ORDER = ["barrier_harvest", "buy_hold", "trend_filter", "session_long",
         "ladder_dca", "vol_target"]


# ------------------------------------------------------------------ positions
def positions_for(key: str, candles, params: dict) -> list:
    """Per-bar target exposure (0..1) for the position-style strategies."""
    C = candles["Close"].tolist()
    n = len(C)
    if key == "buy_hold":
        return [1.0] * n
    if key == "trend_filter":
        ma = _sma(C, int(params.get("ma_bars", 200)))
        return [0.0 if (ma[i] is None) else (1.0 if C[i] > ma[i] else 0.0)
                for i in range(n)]
    if key == "session_long":
        lo = int(params.get("open_hour_utc", 13))
        hi = int(params.get("close_hour_utc", 20))
        hours = [d.hour for d in candles["Date"]]
        return [1.0 if lo <= h < hi else 0.0 for h in hours]
    if key == "ladder_dca":
        steps = max(1, int(params.get("steps", 8)))
        gap = max(1, int(params.get("bars_between", 288)))
        out = []
        for i in range(n):
            filled = min(steps, i // gap + 1)
            out.append(filled / steps)
        return out
    if key == "vol_target":
        look = max(2, int(params.get("lookback_bars", 288)))
        target = float(params.get("target_vol_pct", 0.05)) / 100.0
        rets = [0.0] + [(C[i] / C[i - 1] - 1) for i in range(1, n)]
        sd = _stdev(rets, look)
        out = []
        for i in range(n):
            if sd[i] is None or sd[i] <= 0:
                out.append(0.0)
            else:
                out.append(max(0.0, min(1.0, target / sd[i])))
        return out
    raise ValueError(f"{key} is not a position-style strategy")


def exposure_series(key: str, candles, params: dict | None = None) -> list:
    """Per-bar exposure for ANY strategy, including the bracket one.

    Funding is charged on exposure, so a bracket strategy needs an exposure
    series too — it is 1.0 whenever a position is open and 0.0 in the gap
    between an exit and the next entry.
    """
    strat = REGISTRY[key]
    p = {**strat.params, **(params or {})}
    if strat.kind != "bracket":
        return positions_for(key, candles, p)
    r = fbt.run(candles, take_profit_pct=float(p["take_profit_pct"]),
                stop_loss_pct=float(p["stop_loss_pct"]),
                margin=1.0, leverage=1.0)
    times = list(candles["Date"])
    out = [0.0] * len(times)
    for t in r.trades:
        inside = False
        for i, ts in enumerate(times):
            if ts == t.entry_at:
                inside = True
            if inside:
                out[i] = 1.0
            if ts >= t.exit_at:
                break
    return out


def backtest(key: str, candles, *, margin: float, leverage: float,
             params: dict | None = None,
             fee_per_side: float = fbt.DEFAULT_FEE,
             funding: list | None = None) -> tuple:
    """Run one strategy by key.

    Returns ``(result, funding_pnl)``. ``funding`` is the settlement list from
    ``mexc_futures.funding_history``; when supplied, the long side's funding is
    computed on the strategy's own exposure — a perpetual charges (or pays)
    while a position is open, so a strategy that holds less is exposed less.
    Raises KeyError on an unknown strategy.
    """
    strat = REGISTRY[key]
    p = {**strat.params, **(params or {})}
    if strat.kind == "bracket":
        res = fbt.run(candles, take_profit_pct=float(p["take_profit_pct"]),
                      stop_loss_pct=float(p["stop_loss_pct"]),
                      margin=margin, leverage=leverage,
                      fee_per_side=fee_per_side)
    else:
        res = fbt.run_positions(candles, positions_for(key, candles, p),
                                margin=margin, leverage=leverage,
                                fee_per_side=fee_per_side, label=strat.name)
    fund = 0.0
    if funding:
        fund = fbt.funding_pnl(candles, exposure_series(key, candles, p),
                               funding, notional=res.notional)
    return res, fund


def compare(candles, *, margin: float, leverage: float,
            overrides: dict | None = None,
            fee_per_side: float = fbt.DEFAULT_FEE,
            funding: list | None = None) -> list:
    """Every strategy on the same bars, best PnL first.

    Returns rows carrying the honest comparison: PnL, return on margin, trade
    count, win rate, mark-to-market drawdown, liquidation flag, and whether the
    strategy beat simply holding.
    """
    rows = []
    for key in ORDER:
        strat = REGISTRY[key]
        try:
            r, fund = backtest(key, candles, margin=margin, leverage=leverage,
                               params=(overrides or {}).get(key),
                               fee_per_side=fee_per_side, funding=funding)
        except Exception as exc:                          # noqa: BLE001
            rows.append({"key": key, "name": strat.name, "error": str(exc)})
            continue
        # Buy & hold is the benchmark, so its funding must be included in the
        # bar every strategy is measured against — otherwise a strategy that
        # holds less looks better purely by dodging a cost (or an income).
        bh_fund = 0.0
        if funding:
            bh_fund = fbt.funding_pnl(candles, [1.0] * len(candles), funding,
                                      notional=r.notional)
        total = r.pnl + fund
        bh_total = r.buy_hold_pnl + bh_fund
        eps = max(abs(r.notional), 1.0) * 1e-9
        rows.append({
            "key": key, "name": strat.name, "summary": strat.summary,
            "kind": strat.kind, "pnl": r.pnl, "return_pct": r.return_pct,
            "funding_pnl": fund, "total_pnl": total,
            "total_return_pct": (total / margin * 100) if margin else 0.0,
            "trades": len(r.trades), "win_rate": r.win_rate,
            "max_drawdown": r.max_drawdown, "worst_equity": r.worst_equity,
            "liquidated": r.liquidated, "buy_hold_pnl": r.buy_hold_pnl,
            "buy_hold_total": bh_total,
            "beats_buy_hold": total > bh_total + eps, "result": r,
            "risk": strat.risk,
        })
    ok = [r for r in rows if "error" not in r]
    bad = [r for r in rows if "error" in r]
    ok.sort(key=lambda d: -d["total_pnl"])
    return ok + bad
