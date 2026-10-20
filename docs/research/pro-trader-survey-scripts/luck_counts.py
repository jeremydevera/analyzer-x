"""How many 'winners' pure luck produces among N variants (true win rate 0.30)."""
from math import comb

def tail(n, k, p):
    return sum(comb(n, j) * p**j * (1 - p)**(n - j) for j in range(k, n + 1))

p = 0.30
print("P(win rate >= threshold | n trades, true p=0.30) and expected count among N=3.8M and N=10,000 independent variants")
for n in (20, 30, 50, 100, 300):
    for thr in (0.50, 0.65, 0.80):
        k = -(-int(thr * n * 1000) // 1000)  # ceil
        k = max(k, int(thr * n) if thr * n == int(thr * n) else int(thr * n) + 1)
        pr = tail(n, k, p)
        print(f"n={n:3d} win>={thr:.0%} (>= {k} wins): P={pr:.2e}  expected false winners: N=3.8M -> {pr*3.8e6:,.1f}   N=10k -> {pr*1e4:,.2f}")
# two-arm gate test size
from statistics import NormalDist
N = NormalDist()
za, zb = N.inv_cdf(0.95), N.inv_cdf(0.80)
for d in (0.01, 0.02, 0.03):
    n = 2 * (za + zb) ** 2 * p * (1 - p) / d ** 2
    print(f"gate vs no-gate, detect +{d*100:.0f}pp win rate (one test, 80% power): {n:,.0f} trades per arm")
# cost/target ratio for the 2:1-after-fee barrier set
C = 0.0023
for sl in (0.003, 0.005, 0.01, 0.015, 0.02):
    tp = 2 * sl + 3 * C
    print(f"SL {sl*100:.1f}% TP {tp*100:.2f}%: cost/target {C/tp*100:.1f}%  required lift {C/(tp+sl)*100:.1f}pp")
