"""One walk per combination instead of six.

``run_grid`` needs six numbers per (signal, threshold, SL, TP): flat and
martingale, each over the full history and both halves. It used to get them
by running :func:`auto_trader.backtest_strategy` six times, and the walk —
find the entry, scan bars to the exit — is identical in all six. What differs
is bookkeeping:

* **Sizing never moves an entry or an exit.** Barriers hang off the entry
  price and liquidation is a distance, not a dollar amount, so the trade list
  is the same for flat and for the ladder. The ladder's rung sequence depends
  only on win/lose, and a trade's SIGN is the same at any margin — so
  martingale is the flat trade list with each trade scaled by its rung.
* **The first half is a prefix of the full run.** Same entries, same rungs,
  same exits — except a trade still open at the boundary, which the half-run
  marks to market at the boundary bar. That trade is by construction the
  half-run's LAST trade, so re-marking it changes nothing downstream.
* **The second half is NOT a suffix** — it starts flat at the boundary, so it
  can take entries the full run was in a position for. It needs its own walk.

So: two walks (full, second half) and six cheap derivations, in place of six
walks. The derivations must reproduce ``backtest_strategy`` to the cent —
``tests/test_fast_grid.py`` pins that row-for-row against the engine itself.

Multi-exit ``slices`` rows are rare and keep the old engine path.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence

WHY_TP, WHY_SL, WHY_LIQ, WHY_END = 0, 1, 2, 3


def walk(dirs_idx: Sequence[int], dirs, opens, high, low, close, *,
         tp: float, sl: float, liq: float | None,
         start: int = 0, end: int | None = None,
         f_ms=None, f_cum=None, bar_ms=None) -> list[tuple]:
    """The engine's bar walk, once, sizing-free.

    Returns one tuple per trade:
    ``(sig_bar, entry_bar, exit_bar, side, out, why, fund_frac)`` where
    ``out`` is the exit's fraction of notional (±tp/±sl/−liq/mark) and
    ``fund_frac`` is the funding paid per unit of notional (sign applied).
    ``start``/``end`` bound the walk in GLOBAL bar indices, exactly like
    running the engine over ``df.iloc[start:end]`` with ``dirs[start:end]``.
    """
    n = len(close) if end is None else int(end)
    out: list[tuple] = []
    sp = bisect.bisect_left(dirs_idx, start)
    nsig = len(dirs_idx)
    i = start
    while i < n - 1:
        while sp < nsig and dirs_idx[sp] < i:
            sp += 1
        if sp >= nsig:
            break
        i = int(dirs_idx[sp])
        if i >= n - 1:
            break
        s = dirs[i]
        if s == 0:            # cannot happen (dirs_idx is nonzero), kept 1:1
            i += 1
            continue
        entry = opens[i + 1]
        tp_px = entry * (1 + s * tp)
        sl_px = entry * (1 - s * sl)
        liq_px = None if liq is None else entry * (1 - s * liq)
        j = i + 1
        res_out = None
        why = WHY_END
        while j < n:
            hit_liq = liq_px is not None and (
                low[j] <= liq_px if s == 1 else high[j] >= liq_px)
            hit_sl = (low[j] <= sl_px if s == 1 else high[j] >= sl_px)
            if hit_liq and (liq is None or liq <= sl or not hit_sl):
                res_out, why = -liq, WHY_LIQ
                break
            if hit_sl:
                res_out, why = -sl, WHY_SL
                break
            if (high[j] >= tp_px if s == 1 else low[j] <= tp_px):
                res_out, why = tp, WHY_TP
                break
            j += 1
        if res_out is None:
            res_out = s * (close[n - 1] / entry - 1)
            why, j = WHY_END, n - 1
        fund_frac = 0.0
        if f_ms:
            a = bisect.bisect_right(f_ms, int(bar_ms[i + 1]))
            b = bisect.bisect_right(f_ms, int(bar_ms[j]))
            fund_frac = -s * (f_cum[b] - f_cum[a])
        out.append((i, i + 1, j, s, res_out, why, fund_frac))
        i = j + 1
    return out


def derive(trades: list[tuple], *, base: float, lev: int, fee: float,
           sizing: str, ladder, mo_idx, mo_labels) -> dict:
    """Fold a trade list into exactly what ``backtest_strategy`` returns
    (the keys ``run_grid`` reads), at one sizing."""
    monthly: dict[str, float] = {}
    trades_n = wins = n_liq = 0
    profit = worst = equity = peak = max_dd = fund_total = 0.0
    step = 0
    # The worst unbroken run of losses, and how many trades it took. On a
    # ladder this is what empties an account — the single worst trade is not.
    run_sum = worst_run = 0.0
    run_len = worst_run_len = 0
    for (_sig, _entry, exit_bar, _s, res_out, why, fund_frac) in trades:
        margin = base if sizing == "flat" else ladder(base, step)
        notional = margin * lev
        pnl = (res_out - 2 * fee) * notional
        fund = fund_frac * notional
        pnl += fund
        if why == WHY_LIQ:
            pnl = -margin
        trades_n += 1
        wins += pnl > 0
        profit += pnl
        worst = min(worst, pnl)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        m = mo_labels[mo_idx[exit_bar]]
        monthly[m] = monthly.get(m, 0.0) + pnl
        n_liq += why == WHY_LIQ
        fund_total += fund
        if pnl > 0:
            run_sum, run_len = 0.0, 0
        else:
            run_sum += pnl
            run_len += 1
            if run_sum < worst_run:
                worst_run, worst_run_len = run_sum, run_len
        step = 0 if pnl > 0 else step + 1
    monthly = {m: round(v, 2) for m, v in sorted(monthly.items())}
    return {"trades": trades_n, "wins": wins, "losses": trades_n - wins,
            "profit": round(profit, 2), "worst_trade": round(worst, 2),
            "max_dd": round(max_dd, 2), "monthly": monthly,
            "months_green": sum(1 for v in monthly.values() if v > 0),
            "months_total": len(monthly),
            "liqs": n_liq, "funding_total": round(fund_total, 4),
            "worst_streak": round(worst_run, 2),
            "worst_streak_len": worst_run_len}


def end_state(trades: list[tuple], *, base: float, lev: int, fee: float,
              sizing: str, ladder, mo_idx, mo_labels, opens, bar_ms,
              last_ms: int, stamp=None) -> dict:
    """The engine's RESUME STATE at the last bar, from a walk's trade list —
    exactly what ``backtest_strategy(..., resume=prev)`` writes to
    ``result["state"]`` when it is asked to carry an open trade.

    This is the memory a GitHub machine never had. The cloud sweep measures
    with ``walk``/``derive`` (fast) and could therefore never continue a coin
    from its last bar: every UPDATE re-measured the whole window (operator,
    2026-09-09: "if the last backtest was sep1 and i click update it should
    run on github to update the gap which is sept 2 onwards"). With this,
    the full run ships a resume state per combination, and the next run
    continues it with the engine over the new bars only.

    Two things differ from ``derive`` on purpose, and both follow the engine:

    * a trade still open at the last bar (``WHY_END``) is NOT counted — the
      engine, given a resume dict, hands it to the next run as ``open``
      instead of marking it to market (auto_trader.py, "Hand it to the next
      refresh instead of pretending it closed"). ``derive`` marks it, which is
      right for a REPORT of a closed window and wrong for a state to continue.
    * the sums are UNROUNDED: the engine resumes from its raw floats and
      rounds only what it prints. Rounding here would drift a cent per run.

    ``last_ms`` is the frame's last bar, as the engine records it. ``stamp``
    formats the open trade's ``opened`` field the way the engine does; when
    None, the one date formatter is used.
    """
    monthly: dict[str, float] = {}
    trades_n = wins = n_liq = 0
    profit = worst = equity = peak = max_dd = fund_total = 0.0
    step = 0
    # the losing streak, which the engine's own resume state does NOT carry
    # (auto_trader._state has no run_sum/run_len), so a continued run would
    # understate a run of losses that straddles the boundary. Carried here;
    # resume_state.fold_streak continues it over the next run's trades.
    run_sum = worst_run = 0.0
    run_len = worst_run_len = 0
    open_pos = None
    # Did the last COUNTED trade exit on the frame's last bar? The engine
    # resumes its signal search after an exit at j from j+1, so a signal
    # sitting on that bar is unavailable — but a signal on a last bar with
    # NO exit on it enters on the first NEW bar, which the next run must take
    # (continue_combo starts one bar early unless this is set). Measured:
    # 65 trades continued vs 66 in one run, before this (2026-09-09).
    exit_at_last = False
    open_pos = None
    last_i = len(trades) - 1
    last_bar = len(bar_ms) - 1
    for k, (_sig, entry_bar, exit_bar, s, res_out, why, fund_frac) in enumerate(trades):
        margin = base if sizing == "flat" else ladder(base, step)
        if k == last_i and why == WHY_END:
            # still open at the last bar: carried, not counted
            ems = int(bar_ms[entry_bar])
            if stamp is not None:
                opened = stamp(entry_bar)
            else:
                from tradingagents.positions_view import fmt_when

                opened = fmt_when(ems / 1000.0)
            open_pos = {"side": int(s), "entry": float(opens[entry_bar]),
                        "margin": float(margin), "opened": opened,
                        "entry_ms": ems}
            break
        notional = margin * lev
        pnl = (res_out - 2 * fee) * notional
        fund = fund_frac * notional
        pnl += fund
        if why == WHY_LIQ:
            pnl = -margin
        trades_n += 1
        wins += pnl > 0
        profit += pnl
        worst = min(worst, pnl)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        m = mo_labels[mo_idx[exit_bar]]
        monthly[m] = monthly.get(m, 0.0) + pnl
        n_liq += why == WHY_LIQ
        fund_total += fund
        if pnl > 0:
            run_sum, run_len = 0.0, 0
        else:
            run_sum += pnl
            run_len += 1
            if run_sum < worst_run:
                worst_run, worst_run_len = run_sum, run_len
        step = 0 if pnl > 0 else step + 1
        exit_at_last = int(exit_bar) == last_bar
    return {"trades": trades_n, "wins": wins, "profit": profit,
            "worst": worst, "equity": equity, "peak": peak,
            "max_dd": max_dd, "step": step,
            # the engine stores the ROUNDED month map in its state (it rounds
            # `monthly` for the report first, then copies it) — match that
            "monthly": {m: round(v, 2) for m, v in sorted(monthly.items())},
            "liqs": n_liq, "funding_total": fund_total, "open": open_pos,
            "last_ms": int(last_ms),
            # ours, ignored by the engine's resume, read by fold_streak
            "streak_sum": run_sum, "streak_len": run_len,
            "worst_streak": worst_run, "worst_streak_len": worst_run_len,
            # ours, read by continue_combo (see above)
            "exit_at_last": exit_at_last}


def combo_six(dirs_idx, dirs, opens, high, low, close, *, tp, sl, liq,
              sizings=None,
              half, base, lev, fee, ladder, mo_idx, mo_labels,
              f_ms=None, f_cum=None, bar_ms=None,
              with_trades: bool = False) -> dict:
    """Everything ``run_grid`` needs for one (dirs, SL, TP): the six results,
    from two walks. ``with_trades=True`` also returns the full walk's trade
    list under ``"trades"`` so a caller can derive a resume state
    (``end_state``) without walking again."""
    kw = {"f_ms": f_ms, "f_cum": f_cum, "bar_ms": bar_ms}
    full = walk(dirs_idx, dirs, opens, high, low, close,
                tp=tp, sl=sl, liq=liq, **kw)
    # first half: prefix of the full walk, boundary trade re-marked
    h1: list[tuple] = []
    for t in full:
        sig_bar, entry_bar, exit_bar, s, res_out, why, fund_frac = t
        if sig_bar >= half - 1:
            break
        if exit_bar < half:
            h1.append(t)
            continue
        entry = opens[entry_bar]
        m_out = s * (close[half - 1] / entry - 1)
        m_fund = 0.0
        if f_ms:
            a = bisect.bisect_right(f_ms, int(bar_ms[entry_bar]))
            b = bisect.bisect_right(f_ms, int(bar_ms[half - 1]))
            m_fund = -s * (f_cum[b] - f_cum[a])
        h1.append((sig_bar, entry_bar, half - 1, s, m_out, WHY_END, m_fund))
        break
    # second half: its own walk — it starts flat, so it can take entries the
    # full run was in a position for
    h2 = walk(dirs_idx, dirs, opens, high, low, close,
              tp=tp, sl=sl, liq=liq, start=half, **kw)
    out = {}
    from tradingagents import backtest_report as br

    # WHICHEVER SIZINGS THE CALLER ASKED FOR, defaulting to the grid's own
    # registry — which the operator cut to ("flat",) on Sep 11, 2026, halving
    # this function's work. `sizings=` exists so the engine-parity tests can
    # still prove the ladder maths matches `backtest_strategy`: the capability
    # is correct and proven, it is simply not in the grid any more, and
    # deleting a proven path is a different decision from not measuring it.
    for sz in (sizings or br.SIZINGS):
        d = {"base": base, "lev": lev, "fee": fee, "sizing": sz, "ladder": ladder,
                 "mo_idx": mo_idx, "mo_labels": mo_labels}
        out[sz] = {"full": derive(full, **d), "h1": derive(h1, **d),
                   "h2": derive(h2, **d)}
    if with_trades:
        out["trades"] = full
    return out
