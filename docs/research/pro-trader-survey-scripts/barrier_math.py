"""Arithmetic behind the survey's cost/edge tables (no market data, no trading code).

1. Driftless random walk: P(hit TP before SL) = SL / (TP + SL).
2. Break-even win rate after a round-trip cost c: (SL + c) / (TP + SL).
3. Required lift over random = c / (TP + SL).
4. Wald's identity: E[gross P&L per trade] = drift * E[holding time];
   for small drift E[T] ~= TP * SL / sigma^2, so gross ~= Sharpe_in_trade * TP * SL / sigma_annual.
5. Trades needed to detect a win-rate lift, single test vs many variants.
6. Expected best win rate among N variants by luck alone.
7. Monte Carlo check of (1) and (4) on a minute-step random walk.
"""
import math

import numpy as np
from statistics import NormalDist

N01 = NormalDist()
C = 0.0023  # measured round-trip cost (fee + spread), fraction of notional


def table_barriers():
    print("== 1-3: barriers that pay 2:1 after fees (TP = 2*SL + 3c) ==")
    print(f"{'SL%':>5} {'TP%':>6} {'p0 random':>10} {'break-even':>11} {'lift needed':>12}")
    for sl in (0.003, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03):
        tp = 2 * sl + 3 * C
        p0 = sl / (tp + sl)
        be = (sl + C) / (tp + sl)
        print(f"{sl*100:5.2f} {tp*100:6.2f} {p0*100:9.1f}% {be*100:10.1f}% {100*(be-p0):10.1f}pp")
    print("-- wider payoff (TP = 3*SL and 4*SL, then net ratio) --")
    for sl in (0.01, 0.015, 0.02):
        for k in (3, 4):
            tp = k * sl
            p0 = sl / (tp + sl)
            be = (sl + C) / (tp + sl)
            net = (tp - C) / (sl + C)
            print(f"SL {sl*100:.1f}% TP {tp*100:.1f}% net payoff {net:.2f}:1  p0 {p0*100:.1f}%  "
                  f"break-even {be*100:.1f}%  lift {100*(be-p0):.1f}pp")


def table_edge():
    print("\n== 4: gross edge per trade = S * TP * SL / sigma_annual (Wald) ==")
    print("S = annualised Sharpe of the signal WHILE in the trade")
    for sl in (0.01, 0.015, 0.02):
        tp = 2 * sl + 3 * C
        print(f"-- SL {sl*100:.1f}%  TP {tp*100:.2f}% --")
        for sig in (0.10, 0.20, 0.35, 0.50, 0.75, 1.00, 1.50):
            et_days = tp * sl / (sig * sig / 365.0)
            row = [f"vol {sig*100:4.0f}%  hold~{et_days:6.1f}d"]
            for s in (0.5, 1.0, 2.0, 3.0):
                g = s * tp * sl / sig
                row.append(f"S={s:.1f}: {g*100:5.2f}%")
            # Sharpe needed just to pay the cost
            s_need = C * sig / (tp * sl)
            row.append(f"S needed {s_need:5.2f}")
            print("  ".join(row))


def table_trades():
    print("\n== 5: trades needed (one-sided, 80% power), win-rate lift over p0~0.30 ==")
    p = 0.30
    zb = N01.inv_cdf(0.80)
    for lift in (0.024, 0.034, 0.044, 0.062, 0.105):
        row = [f"lift {lift*100:4.1f}pp"]
        for n_var in (1, 100, 10_000, 1_000_000):
            alpha = 0.05 / n_var
            za = N01.inv_cdf(1 - alpha)
            n = (za + zb) ** 2 * p * (1 - p) / lift ** 2
            row.append(f"N={n_var:>9,}: {n:7,.0f}")
        print("  ".join(row))


def table_luck():
    print("\n== 6: best win rate among N variants by luck (true p = 0.30) ==")
    gamma = 0.5772156649
    for n_var in (100, 10_000, 1_000_000, 3_800_000):
        emax = (1 - gamma) * N01.inv_cdf(1 - 1 / n_var) + gamma * N01.inv_cdf(1 - 1 / (n_var * math.e))
        row = [f"N={n_var:>9,} (E[max z]={emax:4.2f})"]
        for trades in (20, 30, 50, 100, 300):
            sd = math.sqrt(0.3 * 0.7 / trades)
            row.append(f"n={trades}: {min(1.0, 0.30 + emax*sd)*100:5.1f}%")
        print("  ".join(row))


def monte_carlo(seed=7, trades=20_000):
    print("\n== 7: Monte Carlo on minute steps (checks 1 and 4) ==")
    rng = np.random.default_rng(seed)
    sig_a = 0.60                      # 60% annual vol
    sig_m = sig_a / math.sqrt(365 * 1440)
    sl, tp = 0.02, 2 * 0.02 + 3 * C
    for s_in in (0.0, 2.0):
        mu_m = s_in * sig_a / (365 * 1440)   # drift per minute for in-trade Sharpe s_in
        wins = 0
        total_ret = 0.0
        total_min = 0
        batch = 2000
        done = 0
        while done < trades:
            pos = np.zeros(batch)
            alive = np.ones(batch, dtype=bool)
            res = np.zeros(batch)
            t = np.zeros(batch, dtype=np.int64)
            step = 0
            while alive.any() and step < 400_000:
                k = int(alive.sum())
                pos[alive] += mu_m + sig_m * rng.standard_normal(k)
                t[alive] += 1
                hit_tp = alive & (pos >= tp)
                hit_sl = alive & (pos <= -sl)
                res[hit_tp] = tp
                res[hit_sl] = -sl
                alive &= ~(hit_tp | hit_sl)
                step += 1
            wins += int((res > 0).sum())
            total_ret += float(res.sum())
            total_min += int(t.sum())
            done += batch
        p_hat = wins / done
        print(f"in-trade Sharpe {s_in}: win rate {p_hat*100:5.2f}% (formula p0 {sl/(tp+sl)*100:5.2f}% at S=0); "
              f"mean gross {total_ret/done*100:6.3f}%; mean hold {total_min/done/1440:5.2f} d "
              f"(formula {tp*sl/(sig_a**2/365):5.2f} d); Wald drift*hold {mu_m*total_min/done*100:6.3f}%")


if __name__ == "__main__":
    table_barriers()
    table_edge()
    table_trades()
    table_luck()
    monte_carlo()
