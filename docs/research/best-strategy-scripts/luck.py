import sqlite3, os, math, json, time
import numpy as np
t0 = time.time()
p = os.path.expanduser('~/.tradingagents/v4/rows.db')
c = sqlite3.connect('file:' + p + '?mode=ro', uri=True)
c.row_factory = sqlite3.Row
# one pass over every trade: per strategy, count / sum / sum of squares, older (opened before the split) and newer, and the real-priced ones
q = """
select t.sid,
  sum(t.en < s.split_s) as no, sum(case when t.en < s.split_s then t.pnl else 0 end) as so, sum(case when t.en < s.split_s then t.pnl*t.pnl else 0 end) as qo,
  sum(t.en >= s.split_s) as nn, sum(case when t.en >= s.split_s then t.pnl else 0 end) as sn, sum(case when t.en >= s.split_s then t.pnl*t.pnl else 0 end) as qn,
  sum(t.real=2) as nr, sum(case when t.real=2 then t.pnl else 0 end) as sr, sum(case when t.real=2 then t.pnl*t.pnl else 0 end) as qr,
  count(*) as na, sum(t.pnl) as sa, sum(t.pnl*t.pnl) as qa
from trade t join strat s on s.sid = t.sid
where s.coin not in ('TWUMC','WUXIBIO')
group by t.sid
"""
agg = {r['sid']: tuple(r)[1:] for r in c.execute(q)}
print("aggregated", len(agg), "strategies in", round(time.time() - t0), "s")
def tstat(n, s, qq):
    if n < 2: return float('nan')
    m = s / n
    var = (qq - n * m * m) / (n - 1)
    if var <= 0: return float('nan')
    return m / math.sqrt(var / n)
S = {r['sid']: dict(r) for r in c.execute("select * from strat where coin not in ('TWUMC','WUXIBIO')")}
rows = []
for sid, a in agg.items():
    no, so, qo, nn, sn, qn, nr, sr, qr, na, sa, qa = a
    rows.append((sid, no, tstat(no, so, qo), nn, tstat(nn, sn, qn), nr, tstat(nr, sr, qr), na, tstat(na, sa, qa), sn / nn if nn else float('nan')))
R = {r[0]: r for r in rows}
# check the split counts agree with the stored older/newer counts on a sample
bad = 0
for sid in list(R)[:2000]:
    if R[sid][1] != S[sid]['older_trades'] or R[sid][3] != S[sid]['newer_trades']: bad += 1
print("split count mismatches in 2000:", bad)
cand = [r for r in rows if r[1] >= 20 and r[3] >= 20]
print("20+ each half:", len(cand))
K1 = [r for r in cand if r[2] >= 2.0]
print("older t>=2:", len(K1), " of those newer>0:", sum(1 for r in K1 if r[4] > 0), " newer t>=2:", sum(1 for r in K1 if r[4] >= 2),
      " expected newer t>=2 with no persistence ~", round(len(K1) * 0.023))
K3 = [r for r in cand if r[2] >= 3.0]
print("older t>=3:", len(K3), " newer>0:", sum(1 for r in K3 if r[4] > 0), " newer t>=2:", sum(1 for r in K3 if r[4] >= 2))
# the 74
b3 = ("older_trades>=20 and newer_trades>=20 and older_profit>0 and newer_profit>0 and real_trades>=20 "
      "and real_profit>0 and months_n>=3 and green=months_n")
mine = [dict(r) for r in c.execute(f"select * from strat where coin not in ('TWUMC','WUXIBIO') and {b3}")]
N = len(cand)
def pz(z):  # one-sided normal p
    return 0.5 * math.erfc(z / math.sqrt(2))
need_strict = None
# z needed for p < 0.05 / N
lo, hi = 0.0, 10.0
for _ in range(60):
    mid = (lo + hi) / 2
    if pz(mid) > 0.05 / N: lo = mid
    else: hi = mid
need_strict = hi
print("candidates", N, "-> z needed after counting every one tried:", round(need_strict, 2))
out = []
for m in mine:
    r = R[m['sid']]
    out.append(dict(id=m['id'], coin=m['coin'], tf=m['tf'], label=m['label'], trades=r[7], t_all=r[8], newer_t=r[4], newer_n=r[3], older_t=r[2], real_n=r[5], real_t=r[6],
                    profit=m['profit'], real_profit=m['real_profit'], win=m['win_rate']))
out.sort(key=lambda d: -d['t_all'])
print("whole-history t >= strict bar:", sum(1 for d in out if d['t_all'] >= need_strict), "of", len(out))
print("whole-history t >= 3:", sum(1 for d in out if d['t_all'] >= 3), " >= 2:", sum(1 for d in out if d['t_all'] >= 2))
print("real-priced t >= 2:", sum(1 for d in out if d['real_t'] >= 2), " newer-half t >= 2:", sum(1 for d in out if d['newer_t'] >= 2))
for d in out[:12]:
    print(f"#{d['id']} {d['coin']} {d['tf']} {d['label'][:60]} | trades {d['trades']} t_all {d['t_all']:.2f} older_t {d['older_t']:.2f} newer_t {d['newer_t']:.2f} ({d['newer_n']}) real_t {d['real_t']:.2f} ({d['real_n']}) profit {d['profit']:+.2f} real {d['real_profit']:+.2f}")
json.dump(dict(need=need_strict, N=N, out=out), open(os.path.join(os.path.dirname(__file__), 'luck.json'), 'w'))
print("done", round(time.time() - t0), "s")
