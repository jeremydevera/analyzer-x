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


def combo_six(dirs_idx, dirs, opens, high, low, close, *, tp, sl, liq,
              half, base, lev, fee, ladder, mo_idx, mo_labels,
              f_ms=None, f_cum=None, bar_ms=None) -> dict:
    """Everything ``run_grid`` needs for one (dirs, SL, TP): the six results,
    from two walks."""
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
    for sz in ("flat", "martingale"):
        d = {"base": base, "lev": lev, "fee": fee, "sizing": sz, "ladder": ladder,
                 "mo_idx": mo_idx, "mo_labels": mo_labels}
        out[sz] = {"full": derive(full, **d), "h1": derive(h1, **d),
                   "h2": derive(h2, **d)}
    return out
