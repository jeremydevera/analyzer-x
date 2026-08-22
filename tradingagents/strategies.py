"""Strategy registry for MEXC perpetuals.

Seven strategies, all long-only. Six differ in **exposure structure**, not in
entry signals, and that is deliberate: across 51,192 tested signal combinations
on SPX500, permutation tests showed entry signals carried no information —
shuffled signals scored p=0.467 and randomly-timed entries did as well or
better. Walk-forward selection of the "best" signal lost money while holding
made money. So the honest levers are how much exposure to carry and when to
give it up, not what to predict. The exception is trend50, added after the
Aug'25-Aug'26 multi-timeframe study found a genuine momentum edge on 4-hour
BTC bars — see its rationale/risk for what was measured and what was not.

Every strategy is scored against buy & hold on the same bars, same leverage,
same fees. A strategy that cannot beat holding is reported as not beating it.
"""

from __future__ import annotations

import dataclasses
import logging

from tradingagents import futures_backtest as fbt

logger = logging.getLogger(__name__)


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
    "trend50": Strategy(
        key="trend50",
        name="Trend 50 (4-hour momentum)",
        kind="position",
        summary="Long only while price is above its 50-bar average, flat below. Built for 4-hour bars.",
        rationale=(
            "The best-performing signal of the 13-month multi-timeframe study "
            "(Aug 2025 - Aug 2026): on BTC 4-hour bars the two-sided form made "
            "+$446 per $10 base with 11 of 13 months green, and the momentum "
            "family held up across barriers and ladders (a plateau, not a lone "
            "spike). BTC trends at multi-day scale even though it mean-reverts "
            "at hours and cascades at minutes."),
        params={"ma_bars": 50},
        risk=("Measured TWO-SIDED (long and short); this bot form is long-only, "
              "so it forfeits the short side's profit and sat out most of a "
              "-20% bear stretch in the study. Whipsaws around the average cost "
              "a spread each cross - run it on Hour4 bars, never minutes. "
              "Backtest, not a guarantee: paper-trade before arming."),
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

ORDER = ["barrier_harvest", "buy_hold", "trend_filter", "trend50",
         "session_long", "ladder_dca", "vol_target"]


# ------------------------------------------------------------------ positions
def positions_for(key: str, candles, params: dict) -> list:
    """Per-bar target exposure (0..1) for the position-style strategies."""
    C = candles["Close"].tolist()
    n = len(C)
    if key == "buy_hold":
        return [1.0] * n
    if key in ("trend_filter", "trend50"):
        ma = _sma(C, int(params.get("ma_bars", 200 if key == "trend_filter" else 50)))
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


def exposure_series(key: str, candles, params: dict | None = None,
                    limits: dict | None = None) -> list:
    """Per-bar exposure for ANY strategy, including the bracket one.

    Funding is charged on exposure, so a bracket strategy needs an exposure
    series too — it is 1.0 whenever a position is open and 0.0 in the gap
    between an exit and the next entry.
    """
    strat = REGISTRY[key]
    p = {**strat.params, **(params or {})}
    if strat.kind != "bracket":
        return positions_for(key, candles, p)
    # The limits must apply here too. This re-runs the simulation to find WHEN a
    # position was held, and running it unlimited reported exposure for periods the
    # real run never traded — crediting $41.06 of funding to a backtest that took
    # zero trades.
    lim = limits or {}
    r = fbt.run(candles, take_profit_pct=float(p["take_profit_pct"]),
                stop_loss_pct=float(p["stop_loss_pct"]),
                margin=1.0, leverage=1.0,
                max_losses=int(lim.get("max_losses") or 0),
                daily_loss_limit=(float(lim["daily_loss_limit"]) / max(
                    float(lim.get("notional") or 1.0), 1e-9)
                    if lim.get("daily_loss_limit") and lim.get("notional")
                    else 0.0))
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
             funding: list | None = None,
             limits: dict | None = None) -> tuple:
    """Run one strategy by key.

    Returns ``(result, funding_pnl)``. ``funding`` is the settlement list from
    ``mexc_futures.funding_history``; when supplied, the long side's funding is
    computed on the strategy's own exposure — a perpetual charges (or pays)
    while a position is open, so a strategy that holds less is exposed less.
    Raises KeyError on an unknown strategy.
    """
    strat = REGISTRY[key]
    p = {**strat.params, **(params or {})}
    lim = limits or {}
    if strat.kind == "bracket":
        res = fbt.run(candles, take_profit_pct=float(p["take_profit_pct"]),
                      stop_loss_pct=float(p["stop_loss_pct"]),
                      margin=margin, leverage=leverage,
                      fee_per_side=fee_per_side,
                      max_notional=lim.get("max_notional"),
                      max_losses=int(lim.get("max_losses") or 0),
                      daily_loss_limit=float(lim.get("daily_loss_limit") or 0.0),
                      min_equity=float(lim.get("min_equity") or 0.0),
                      starting_equity=lim.get("starting_equity"))
    else:
        res = fbt.run_positions(candles, positions_for(key, candles, p),
                                margin=margin, leverage=leverage,
                                fee_per_side=fee_per_side, label=strat.name,
                                max_notional=lim.get("max_notional"),
                                daily_loss_limit=float(
                                    lim.get("daily_loss_limit") or 0.0),
                                min_equity=float(lim.get("min_equity") or 0.0),
                                starting_equity=lim.get("starting_equity"))
    fund = 0.0
    if funding:
        exposure = exposure_series(key, candles, p,
                                   {**lim, "notional": res.notional})
        if res.liquidated and res.trades:
            # No account, no position, no funding. exposure_series re-runs the
            # simulation UNLEVERED to find when a position was held, and an
            # unlevered run is never liquidated — so it happily reported exposure
            # for the whole window. At 200x that credited 166 days of funding to
            # an account wiped out on day 23, turning a -$10 total into +$195.83.
            end = res.trades[-1].exit_at
            exposure = [e if t <= end else 0.0
                        for e, t in zip(exposure, candles["Date"], strict=False)]
        fund = fbt.funding_pnl(candles, exposure, funding,
                               notional=res.notional)
        if not res.trades:
            fund = 0.0
        fund = _cap_funding_at_margin(res, fund)
    return res, fund


def _cap_funding_at_margin(result, fund: float) -> float:
    """A funding bill cannot exceed what is in the account.

    Funding is settled against the margin balance, so on a contract where longs
    PAY, the payments themselves liquidate the account once they exhaust it. This
    engine applies funding as a lump sum after the price simulation, so nothing
    stopped the combined figure from going past the margin — a 3x run reported a
    total worse than the money posted, which no exchange can produce.

    This is a CAP, not a full model. Properly, funding belongs inside the equity
    path: an account being drained by funding is liquidated EARLIER than the price
    alone would do it, and the trades after that point should not exist either. So
    treat a capped result as an upper bound on what you would have kept, not as a
    faithful replay. It is flagged in the log so the difference is visible.
    """
    floor = -result.margin - result.pnl
    if fund < floor:
        logger.warning(
            "funding of %.4f would take the account past its %.2f margin; capped "
            "at %.4f. Funding alone would have liquidated this position earlier "
            "than the price did, so the trade list is optimistic.",
            fund, result.margin, floor)
        return floor
    return fund


def compare(candles, *, margin: float, leverage: float,
            overrides: dict | None = None,
            fee_per_side: float = fbt.DEFAULT_FEE,
            funding: list | None = None,
            limits: dict | None = None) -> list:
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
                               fee_per_side=fee_per_side, funding=funding,
                               limits=limits)
        except Exception as exc:                          # noqa: BLE001
            rows.append({"key": key, "name": strat.name, "error": str(exc)})
            continue
        # ONE comparison implementation. This function carried its own copy, so the
        # fix that stops paying the benchmark funding after a liquidation landed in
        # hold_comparison() and not here. Two copies of a rule is two rules.
        cmp_ = hold_comparison(r, fund, candles, funding)
        cmp_["hold_funding"]
        total = cmp_["total"]
        bh_total = cmp_["hold_total"]
        rows.append({
            "key": key, "name": strat.name, "summary": strat.summary,
            "kind": strat.kind, "pnl": r.pnl, "return_pct": r.return_pct,
            "funding_pnl": fund, "total_pnl": total,
            "total_return_pct": (total / margin * 100) if margin else 0.0,
            "trades": len(r.trades), "win_rate": r.win_rate,
            "max_drawdown": r.max_drawdown, "worst_equity": r.worst_equity,
            "liquidated": r.liquidated, "buy_hold_pnl": r.buy_hold_pnl,
            "buy_hold_total": bh_total,
            "beats_buy_hold": cmp_["beats_hold"], "result": r,
            "halted_reason": r.halted_reason,
            "risk": strat.risk,
        })
    ok = [r for r in rows if "error" not in r]
    bad = [r for r in rows if "error" in r]
    ok.sort(key=lambda d: -d["total_pnl"])
    return ok + bad


# ------------------------------------------------------------- timeframes
# One authoritative timeframe. The UI used to carry three separate interval
# pickers — one for the chart, one for the backtest, and none for the bot — so a
# person could study 1-minute bars, backtest on 5-minute bars, and run a bot that
# used neither.
TIMEFRAMES = ("Min1", "Min5", "Min15", "Min30", "Min60", "Hour4", "Day1")

TIMEFRAME_SECONDS = {"Min1": 60, "Min5": 300, "Min15": 900, "Min30": 1800,
                     "Min60": 3600, "Hour4": 14400, "Day1": 86400}

TIMEFRAME_LABELS = {"Min1": "1 minute", "Min5": "5 minutes",
                    "Min15": "15 minutes", "Min30": "30 minutes",
                    "Min60": "1 hour", "Hour4": "4 hours", "Day1": "1 day"}


def poll_seconds_for(timeframe: str) -> int:
    """How often a bot on this timeframe needs to look.

    Half a bar, floored at 30s and capped at 5 minutes. Polling faster than the
    bar it trades gains nothing — the decision cannot change until the bar does —
    and polling slower than half a bar risks missing one entirely.
    """
    bar = TIMEFRAME_SECONDS.get(timeframe, 300)
    return max(30, min(300, bar // 2))


def timeframe_fit(timeframe: str, strategy: str) -> tuple:
    """Is this strategy sensible on this timeframe? Returns (verdict, why).

    Verdict is "good", "workable" or "avoid". The judgements are measured on this
    project's own SPX500 data, not opinion:

    * A bracket strategy is nearly timeframe-independent, because its exits are
      price levels rather than bar events. It only needs bars fine enough to
      notice a level being crossed.
    * An exposure strategy rebalances once per bar, so its trading cost scales
      inversely with bar size. Measured on the real 1-minute file, an on/off
      exposure rule turned over 2,279x the notional in 31 days — 148 orders a day.
      At the current zero fee that is still $10.22/month of spread on a $345
      position (107%/yr of margin), and at a normal 2bp fee it is $157/month
      against an account of $163.
    """
    strat = REGISTRY.get(strategy)
    if strat is None:
        return "avoid", f"{strategy!r} is not a known strategy"
    bar = TIMEFRAME_SECONDS.get(timeframe, 300)
    if strategy == "buy_hold":
        return "good", (
            "One entry and one exit for the whole period, so the timeframe "
            "changes nothing about cost. It is the benchmark every other "
            "strategy here has to beat.")
    if strategy == "ladder_dca":
        steps = REGISTRY[strategy].params.get("steps", 8)
        span = TIMEFRAME_SECONDS.get(timeframe, 300) * \
            REGISTRY[strategy].params.get("bars_between", 288) * steps / 86400
        return ("good" if span <= 60 else "workable"), (
            f"Turnover is bounded at {steps} partial entries however fine the "
            f"bars are, so cost is not the issue. What the timeframe changes is "
            f"how LONG the ladder takes: {span:.1f} days at this setting. Adjust "
            f"'bars between' if that is not the ramp you want.")
    if strat.kind == "bracket":
        if bar < 300:
            return "workable", (
                "The barriers are price levels, so the timeframe barely matters. "
                "1-minute bars only make the backtest's fills more optimistic, "
                "because a smaller bar is more likely to touch a level it could "
                "not actually have filled at.")
        return "good", (
            f"Barriers are price levels, so {TIMEFRAME_LABELS.get(timeframe, timeframe)} "
            f"bars are ample. This is the pairing the +2%/-10% grid was measured on.")
    # The three genuine per-bar rebalancers — trend_filter, session_long and
    # vol_target — are the only ones whose turnover grows as bars shrink.
    if bar < 900:
        return "avoid", (
            f"This rebalances once per bar. On {TIMEFRAME_LABELS.get(timeframe, timeframe)} "
            f"bars that measured 148 orders a day and 2,279x turnover in 31 days "
            f"— $10.22/month of spread at today's zero fee, and $157/month once "
            f"fees return, against a $163 account.")
    if bar < 3600:
        return "workable", (
            "Rebalancing this often is affordable but not free. Watch the "
            "turnover figure in the backtest before trusting it.")
    return "good", (
        f"One rebalance per {TIMEFRAME_LABELS.get(timeframe, timeframe)} keeps "
        f"trading cost to a few dollars a month at this size.")


def strategies_for(timeframe: str) -> list:
    """Every strategy, annotated for this timeframe, best fit first."""
    order = {"good": 0, "workable": 1, "avoid": 2}
    rows = []
    for key in ORDER:
        verdict, why = timeframe_fit(timeframe, key)
        rows.append({"key": key, "name": REGISTRY[key].name, "verdict": verdict,
                     "why": why, "kind": REGISTRY[key].kind})
    rows.sort(key=lambda r: (order[r["verdict"]], ORDER.index(r["key"])))
    return rows


# ------------------------------------------------------- entry gates
# A strategy's per-bar exposure can be used two different ways.
#
#   AS AN EXPOSURE TARGET (what the backtest measures): rebalance the position
#   toward the target every bar. That is what makes trend_filter and friends
#   ruinous on fine bars — measured at 148 orders a day on 1-minute data.
#
#   AS AN ENTRY GATE (what this function serves): only ask "would this strategy
#   want to be long right now?" and, if so, take ONE bracketed trade managed by a
#   take-profit and a stop. Turnover is then bounded by the barriers rather than
#   by the bar count, so the fee problem disappears.
#
# These are NOT the same strategy. A gate has no exposure sizing and does not
# scale out, so the backtested figures for the exposure form do not transfer.
# Anything showing a gate result must say so.
def wants_long(strategy: str, candles, params: dict | None = None) -> bool:
    """Would this strategy want exposure on the latest bar?

    ``candles`` needs Date/Open/High/Low/Close and enough history for the
    strategy's lookback. Returns False rather than raising when there is not
    enough data — refusing to trade on an unknown signal is the safe direction.
    """
    strat = REGISTRY.get(strategy)
    if strat is None:
        return False
    if strat.kind == "bracket":
        return True                      # always-long: it never declines
    p = {**strat.params, **(params or {})}
    try:
        exposure = positions_for(strategy, candles, p)
    except (ValueError, KeyError, IndexError, ZeroDivisionError):
        return False
    if not exposure:
        return False
    return float(exposure[-1]) > 0.0


def gate_reason(strategy: str, candles, params: dict | None = None) -> str:
    """One line on why the gate is open or shut, for the log and the UI."""
    strat = REGISTRY.get(strategy)
    if strat is None:
        return f"{strategy!r} is not a known strategy"
    if strat.kind == "bracket":
        return "always-long: never declines an entry"
    on = wants_long(strategy, candles, params)
    if strategy in ("trend_filter", "trend50"):
        return ("price is above its moving average" if on
                else "price is below its moving average")
    if strategy == "session_long":
        return ("the US cash session is open" if on
                else "the US cash session is shut")
    if strategy == "vol_target":
        return ("recent volatility permits exposure" if on
                else "recent volatility is too high for any exposure")
    if strategy == "ladder_dca":
        return "the ladder has started" if on else "the ladder has not started"
    return "wants exposure" if on else "wants no exposure"


def hold_comparison(result, strategy_funding: float, candles,
                    funding: list | None) -> dict:
    """Strategy total vs buy-and-hold total, both on the same terms.

    The benchmark must be charged (or paid) funding too. Showing a strategy's PnL
    WITH funding against a buy-and-hold figure WITHOUT it credits the strategy
    with income the benchmark also earned — and on SPX500_USDT, where funding pays
    longs ~21.6%/yr, that error flatters any strategy that sits flat part of the
    time, which is most of them.
    """
    hold_funding = 0.0
    if funding:
        hold_exposure = [1.0] * len(candles)
        if result.liquidated and result.trades:
            # Buy and hold at this leverage is a real long facing the same move,
            # so it stops earning funding at the same point. Paying the benchmark
            # for 143 days it could not have survived would understate the
            # strategy instead of overstating it — wrong either way.
            end = result.trades[-1].exit_at
            hold_exposure = [1.0 if t <= end else 0.0 for t in candles["Date"]]
        hold_funding = fbt.funding_pnl(candles, hold_exposure, funding,
                                       notional=result.notional)
        # The benchmark's balance is finite too.
        floor = -result.margin - result.buy_hold_pnl
        hold_funding = max(hold_funding, floor)
    total = result.pnl + strategy_funding
    hold_total = result.buy_hold_pnl + hold_funding
    eps = max(abs(result.notional), 1.0) * 1e-9
    return {"total": total, "hold_total": hold_total,
            "strategy_funding": strategy_funding, "hold_funding": hold_funding,
            "beats_hold": total > hold_total + eps,
            "edge": total - hold_total}
