"""Bracket-order backtester for MEXC perpetuals.

The same simulation the SPX500 study used, packaged so any symbol and any
take-profit / stop-loss pair can be checked before real money is committed —
the parameters that worked on one instrument are not transferable, so the UI
needs a way to re-measure them.

Conventions, chosen to be pessimistic rather than flattering:

* a position is entered at the NEXT bar's open after the strategy is eligible,
  never at the signal bar's close (that would be look-ahead)
* take-profit and stop-loss are checked against each later bar's high and low
* when one bar touches BOTH levels the STOP is assumed to fill first
* fees are charged on both sides of every trade
* drawdown is measured MARK-TO-MARKET, including open-position loss, because
  that is what a venue liquidates on — realised-only drawdown flatters a
  strategy that holds through a deep dip
* LIQUIDATION ENDS THE SIMULATION. Under isolated margin the venue force-closes
  the position and the loss is capped at the margin: you cannot lose more than
  you posted, and with nothing left you cannot place another trade. Earlier this
  was only a flag on the result, so a 200x run reported a single stop-loss of
  -$200.80 against a $10 margin — twenty times the whole account — and then
  booked twelve more trades on money that no longer existed, finishing +$239.30
  when the truth was -$10 on day one.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

DEFAULT_FEE = 0.0002          # MEXC futures taker, per side


@dataclasses.dataclass(frozen=True)
class Trade:
    """One completed (or still-open) round trip."""
    n: int
    entry_at: datetime
    exit_at: datetime
    entry_px: float
    exit_px: float
    reason: str               # "take-profit" | "stop-loss" | "open at end"
    net_return: float         # fraction, after fees
    pnl: float                # currency, on the notional
    bars_held: int


@dataclasses.dataclass(frozen=True)
class Result:
    """Everything the UI needs to show, plus the honest benchmark."""
    trades: list
    margin: float
    leverage: float
    notional: float
    pnl: float
    return_pct: float             # on margin
    win_rate: float
    n_tp: int
    n_sl: int
    n_open: int
    max_drawdown: float           # currency, mark-to-market
    worst_equity: float           # lowest the account ever marked
    liquidated: bool
    halted_reason: str            # "" unless a breaker stopped the run early
    buy_hold_pnl: float           # same margin and leverage, no barriers
    bars: int
    span_days: float
    equity_curve: list            # [(datetime, equity)] after each trade

    @property
    def beats_buy_hold(self) -> bool:
        """True only if the strategy beat holding by more than rounding noise.

        A tie must not read as a win: buy & hold measured against itself differs
        by ~1e-15 of floating point, and reporting that as "beaten" would be a
        lie in the one place the UI most needs to be trusted.
        """
        eps = max(abs(self.notional), 1.0) * 1e-9
        return self.pnl > self.buy_hold_pnl + eps


def run(candles, *, take_profit_pct: float, stop_loss_pct: float,
        margin: float = 100.0, leverage: float = 1.0,
        fee_per_side: float = DEFAULT_FEE,
        max_hold_bars: int | None = None,
        max_notional: float | None = None,
        max_losses: int = 0,
        daily_loss_limit: float = 0.0,
        min_equity: float = 0.0,
        starting_equity: float | None = None) -> Result:
    """Backtest always-long-with-barriers over an OHLCV frame.

    ``candles`` needs Date/Open/High/Low/Close columns (the shape both the spot
    and futures kline helpers return). Positions never overlap: the next entry
    is the bar after an exit, which is how the live bot behaves.
    """
    if take_profit_pct <= 0 or stop_loss_pct <= 0:
        raise ValueError("take_profit_pct and stop_loss_pct must be positive")
    if len(candles) < 3:
        raise ValueError("need at least 3 candles to simulate an entry and exit")

    Op = candles["Open"].tolist()
    H = candles["High"].tolist()
    L = candles["Low"].tolist()
    C = candles["Close"].tolist()
    T = list(candles["Date"])
    n_bars = len(Op)
    # The live runner sizes with min(margin * leverage, max_notional). Ignoring the
    # cap made the simulation trade a different position from the bot: at $10
    # margin, 200x and a $400 cap it used $2,000 — five times the size, so every
    # figure it produced was five times too large.
    notional = margin * leverage
    if max_notional and max_notional > 0:
        notional = min(notional, float(max_notional))
    tp_f, sl_f = take_profit_pct / 100.0, stop_loss_pct / 100.0

    trades: list = []
    realised = 0.0
    peak = 0.0
    max_dd = 0.0
    worst_equity = margin
    liquidated = False
    losses = 0
    halted = ""
    day = None
    day_start_realised = 0.0
    i = 0
    while i < n_bars - 2 and not liquidated and not halted:
        # The same breakers the bot enforces, in the same order. Without them the
        # simulation kept trading through conditions that stop the real runner.
        entry_day = T[i + 1].strftime("%Y-%m-%d")
        if entry_day != day:
            day, day_start_realised = entry_day, realised
        if max_losses and losses >= max_losses:
            halted = f"loss limit: {losses} losing trades"
            break
        # The bot's floor is on the WALLET balance, not on the position's margin.
        # Comparing margin + realised halted a $10-margin run instantly against a
        # $20 floor, even with $163 in the wallet — the check fired on the wrong
        # quantity. With no wallet figure supplied the check is skipped rather
        # than guessed at.
        if min_equity and starting_equity is not None and \
                starting_equity + realised < min_equity:
            halted = (f"wallet {starting_equity + realised:.2f} below floor "
                      f"{min_equity:.2f}")
            break
        if daily_loss_limit and \
                realised - day_start_realised <= -abs(daily_loss_limit):
            # The bot stands down for the rest of the day, then resumes.
            j = i + 1
            while j < n_bars - 2 and T[j].strftime("%Y-%m-%d") == day:
                j += 1
            i = j
            continue
        entry_px = Op[i + 1]
        if entry_px <= 0:
            i += 1
            continue
        tp_px = entry_px * (1 + tp_f)
        sl_px = entry_px * (1 - sl_f)
        cap = n_bars if max_hold_bars is None else min(n_bars, i + 1 + max_hold_bars)
        exit_i, exit_px, reason = -1, 0.0, ""
        j = i + 1
        while j < cap:
            # mark the open position at this bar's worst and best
            open_worst = (L[j] / entry_px - 1) * notional
            equity = margin + realised + open_worst
            if equity < worst_equity:
                worst_equity = equity
            if equity <= 0:
                # Force-closed. The loss is exactly what was left, so the account
                # ends at zero rather than at a fictional negative, and the price
                # is the one at which that happened — not the bar's low.
                liq_px = entry_px * (1 + (-margin - realised) / notional)
                liq_pnl = -(margin + realised)
                realised += liq_pnl
                worst_equity = 0.0
                trades.append(Trade(
                    n=len(trades) + 1, entry_at=T[i + 1], exit_at=T[j],
                    entry_px=entry_px, exit_px=liq_px, reason="liquidated",
                    net_return=liq_pnl / notional if notional else 0.0,
                    pnl=liq_pnl, bars_held=j - (i + 1)))
                liquidated = True
                exit_i = j
                break
            if realised + open_worst - peak < max_dd:
                max_dd = realised + open_worst - peak
            open_best = (H[j] / entry_px - 1) * notional
            if realised + open_best > peak:
                peak = realised + open_best
            if L[j] <= sl_px:
                exit_i, exit_px, reason = j, sl_px, "stop-loss"
                break
            if H[j] >= tp_px:
                exit_i, exit_px, reason = j, tp_px, "take-profit"
                break
            j += 1
        if liquidated:
            break
        if exit_i < 0:
            exit_i = cap - 1
            if exit_i <= i:
                break
            exit_px, reason = C[exit_i], "open at end"
        net = (exit_px / entry_px - 1) - 2 * fee_per_side
        pnl = net * notional
        realised += pnl
        if pnl < 0:
            losses += 1
        trades.append(Trade(
            n=len(trades) + 1, entry_at=T[i + 1], exit_at=T[exit_i],
            entry_px=entry_px, exit_px=exit_px, reason=reason,
            net_return=net, pnl=pnl, bars_held=exit_i - (i + 1)))
        i = exit_i + 1

    wins = sum(1 for t in trades if t.pnl > 0)
    # The benchmark is a real leveraged long facing the same path, so it can be
    # liquidated too. Without this it was the raw price change times notional:
    # +$228.92 against a $10 margin at 200x, a number no account could hold.
    bh_net = (C[-1] / Op[1] - 1) - 2 * fee_per_side if n_bars > 1 else 0.0
    bh_pnl = bh_net * notional
    if n_bars > 1 and Op[1] > 0 and notional > 0:
        for low in L[1:]:
            if margin + (low / Op[1] - 1) * notional <= 0:
                bh_pnl = -margin
                break
    span = ((T[-1] - T[0]).total_seconds() / 86400) if n_bars > 1 else 0.0
    curve, running = [], margin
    for t in trades:
        running += t.pnl
        curve.append((t.exit_at, running))

    return Result(
        trades=trades, margin=margin, leverage=leverage, notional=notional,
        pnl=realised, return_pct=(realised / margin * 100) if margin else 0.0,
        win_rate=(wins / len(trades) * 100) if trades else 0.0,
        n_tp=sum(1 for t in trades if t.reason == "take-profit"),
        n_sl=sum(1 for t in trades if t.reason == "stop-loss"),
        n_open=sum(1 for t in trades if t.reason == "open at end"),
        max_drawdown=max_dd, worst_equity=worst_equity,
        liquidated=liquidated, halted_reason=halted,
        buy_hold_pnl=bh_pnl, bars=n_bars, span_days=span,
        equity_curve=curve)


def sweep(candles, tp_grid, sl_grid, *, margin: float = 100.0,
          leverage: float = 1.0, fee_per_side: float = DEFAULT_FEE) -> list:
    """Every (take-profit, stop-loss) pair, best PnL first.

    A single cell proves nothing: what matters is whether the neighbourhood is a
    plateau (robust) or a lone spike (overfit), which a caller can see from the
    spread of this list.
    """
    out = []
    for tp in tp_grid:
        for sl in sl_grid:
            try:
                r = run(candles, take_profit_pct=tp, stop_loss_pct=sl,
                        margin=margin, leverage=leverage,
                        fee_per_side=fee_per_side)
            except ValueError:
                continue
            out.append({"tp": tp, "sl": sl, "pnl": r.pnl,
                        "return_pct": r.return_pct, "trades": len(r.trades),
                        "win_rate": r.win_rate, "max_drawdown": r.max_drawdown,
                        "liquidated": r.liquidated,
                        "beats_buy_hold": r.beats_buy_hold})
    out.sort(key=lambda d: -d["pnl"])
    return out


def run_positions(candles, positions, *, margin: float = 100.0,
                  leverage: float = 1.0, fee_per_side: float = DEFAULT_FEE,
                  label: str = "", max_notional: float | None = None,
                  daily_loss_limit: float = 0.0, min_equity: float = 0.0,
                  starting_equity: float | None = None) -> Result:
    """Backtest a per-bar target exposure instead of TP/SL brackets.

    ``positions[i]`` is the fraction of full notional to hold going into bar
    i+1 (0 = flat, 1 = fully long). Fees are charged on the CHANGE in exposure,
    so a strategy that trades constantly pays for it. This is the engine for
    exposure-shaping strategies — trend filters, session windows, volatility
    targeting — where there is no discrete take-profit to hit.
    """
    Op = candles["Open"].tolist()
    C = candles["Close"].tolist()
    T = list(candles["Date"])
    n = min(len(Op), len(positions))
    if n < 3:
        raise ValueError("need at least 3 candles")
    # Same sizing rule as run() and as the live runner.
    notional = margin * leverage
    if max_notional and max_notional > 0:
        notional = min(notional, float(max_notional))

    realised = 0.0
    peak = 0.0
    max_dd = 0.0
    worst = margin
    liquidated = False
    halted = ""
    day = None
    day_start_realised = 0.0
    prev_pos = 0.0
    trades: list = []
    open_at = None
    open_px = None
    for i in range(n - 2):
        # The same breakers run() enforces. Without them the compare table ranked
        # bracket strategies that stopped on the operator's limits against exposure
        # strategies that ignored them — different rules in one league table.
        entry_day = T[i + 1].strftime("%Y-%m-%d")
        if entry_day != day:
            day, day_start_realised = entry_day, realised
        if min_equity and starting_equity is not None and \
                starting_equity + realised < min_equity:
            halted = (f"wallet {starting_equity + realised:.2f} below floor "
                      f"{min_equity:.2f}")
            break
        if daily_loss_limit and \
                realised - day_start_realised <= -abs(daily_loss_limit):
            pos = 0.0                       # stand down for the rest of the day
        else:
            pos = float(positions[i])
        ret = Op[i + 2] / Op[i + 1] - 1
        realised += pos * ret * notional
        turn = abs(pos - prev_pos)
        realised -= turn * fee_per_side * notional
        # a change in exposure is recorded as a trade boundary
        if turn > 1e-9:
            if prev_pos > 0 and open_at is not None:
                net = (Op[i + 1] / open_px - 1) - 2 * fee_per_side
                trades.append(Trade(
                    n=len(trades) + 1, entry_at=open_at, exit_at=T[i + 1],
                    entry_px=open_px, exit_px=Op[i + 1],
                    reason="exposure change", net_return=net,
                    pnl=net * notional * prev_pos, bars_held=0))
            if pos > 0:
                open_at, open_px = T[i + 1], Op[i + 1]
            else:
                open_at = open_px = None
        prev_pos = pos
        if realised > peak:
            peak = realised
        if realised - peak < max_dd:
            max_dd = realised - peak
        if margin + realised < worst:
            worst = margin + realised
        if margin + realised <= 0:
            # Force-closed: cap the loss at the margin and stop. See run().
            realised = -float(margin)
            worst = 0.0
            liquidated = True
            if open_at is not None:
                trades.append(Trade(
                    n=len(trades) + 1, entry_at=open_at, exit_at=T[i + 1],
                    entry_px=open_px, exit_px=Op[i + 1], reason="liquidated",
                    net_return=-1.0, pnl=-(margin), bars_held=0))
            break
    if prev_pos > 0 and not liquidated:
        # A position still open at the end must still pay to get out, or a
        # buy-and-hold strategy shows one fee less than the benchmark it is
        # measured against and appears to beat itself.
        #
        # Skipped after a liquidation: the venue has already closed the position
        # and the loss is capped at the margin, so charging an exit fee on top
        # pushed the result to -$10.40 against a $10 margin — reintroducing the
        # very "lost more than you posted" bug this rule exists to prevent.
        realised -= prev_pos * fee_per_side * notional
    if prev_pos > 0 and open_at is not None and not liquidated:
        net = (C[n - 1] / open_px - 1) - 2 * fee_per_side
        trades.append(Trade(
            n=len(trades) + 1, entry_at=open_at, exit_at=T[n - 1],
            entry_px=open_px, exit_px=C[n - 1], reason="open at end",
            net_return=net, pnl=net * notional * prev_pos, bars_held=0))

    wins = sum(1 for t in trades if t.pnl > 0)
    # The benchmark must be measured the SAME way as the strategies it is
    # compared against: this engine sums per-bar returns, so summing them for a
    # fully-invested position is the only apples-to-apples buy & hold. Using a
    # single open-to-close return here made buy & hold appear to lose to itself,
    # because summed arithmetic returns differ from one compounded return.
    bh_net = sum(Op[i + 2] / Op[i + 1] - 1 for i in range(n - 2)) - 2 * fee_per_side
    bh_pnl = bh_net * notional
    if n > 1 and Op[1] > 0 and notional > 0:
        # Same rule as run(): a leveraged benchmark can be liquidated.
        for px_low in C[1:n]:
            if margin + (px_low / Op[1] - 1) * notional <= 0:
                bh_pnl = -margin
                break
    span = (T[-1] - T[0]).total_seconds() / 86400
    curve, running = [], margin
    for t in trades:
        running += t.pnl
        curve.append((t.exit_at, running))
    return Result(
        trades=trades, margin=margin, leverage=leverage, notional=notional,
        pnl=realised, return_pct=(realised / margin * 100) if margin else 0.0,
        win_rate=(wins / len(trades) * 100) if trades else 0.0,
        n_tp=0, n_sl=0, n_open=sum(1 for t in trades if t.reason == "open at end"),
        max_drawdown=max_dd, worst_equity=worst, liquidated=liquidated,
        halted_reason=halted,
        buy_hold_pnl=bh_pnl, bars=n, span_days=span,
        equity_curve=curve)


def funding_pnl(candles, positions, funding, *, notional: float) -> float:
    """A long position's funding PnL over the window, in currency.

    ``funding`` is the list from ``mexc_futures.funding_history``. MEXC's sign
    convention is that a POSITIVE rate means longs pay, so the long side earns
    ``-rate`` each settlement, scaled by how much exposure was held then.
    Settlements outside the candle window are ignored.
    """
    if not funding or notional == 0:
        return 0.0
    times = [int(d.timestamp() * 1000) for d in candles["Date"]]
    if not times:
        return 0.0
    lo, hi = times[0], times[-1]
    total = 0.0
    j = 0
    for f in funding:
        t = f["settle_ms"]
        if t < lo or t > hi:
            continue
        while j + 1 < len(times) and times[j + 1] <= t:
            j += 1
        exposure = float(positions[j]) if j < len(positions) else 0.0
        total += -f["rate"] * notional * exposure
    return total
