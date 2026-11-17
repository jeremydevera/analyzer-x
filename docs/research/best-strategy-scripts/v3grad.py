import pickle, numpy as np, math
import os; SP=os.environ.get("SCRATCH","./")  # folder for the intermediate files
P=pickle.load(open(SP+"v3pool.pkl","rb")); M=pickle.load(open(SP+"v3coinmeta.pkl","rb"))
def cl(a):
    n=len(a); pnl=a[:,3]; day=(a[:,0]//86400000).astype(np.int64); dd=day-day.min()
    m=pnl.mean(); sd=np.bincount(dd,weights=pnl); nd=np.bincount(dd).astype(float)
    se=math.sqrt(((sd-m*nd)**2).sum())/n
    return n,m,(m/se if se>0 else 0)
# 1) the cost gradient: trend family, no extra filter, every setting, both years, both windows, crypto only
rows=[]  # (slip, a)
for y in ("2025","2026"):
    for (ck,w),parts in P[y]["R"].items():
        if not ck.startswith("v3_trend|") or not ck.endswith("|none"): continue
        for ci,a,_ in parts:
            m=M[y][ci]
            if m and m['kind']=='crypto' and m['slip'] is not None:
                rows.append((m['slip'],a))
slips=np.array([r[0] for r in rows]); 
edges=[0,0.0003,0.0005,0.0008,0.0012,0.002,0.004,1]
print("TREND (no extra filter) by the coin's usual one-side gap, $ per trade at $5 risk, both years pooled")
for lo,hi in zip(edges[:-1],edges[1:]):
    sel=[r[1] for r in rows if lo<r[0]<=hi]
    if not sel: continue
    a=np.concatenate(sel); n,m,t=cl(a)
    print("  gap %.2f-%.2f%%  trades %7d  mean %+.3f  t %.1f  win %.0f%%"%(lo*100,hi*100 if hi<1 else 99,n,m,t,100*(a[:,3]>0).mean()))
# 2) walk-forward inside the cheap bucket: choose combo on 2025 (whole year), judge on 2026 (whole year)
cheap=lambda m:m and m['slip'] is not None and m['slip']<=0.0005 and m['kind']=='crypto'
combos=sorted({k[0] for k in P["2026"]["R"]})
sc={}
for ck in combos:
    a25=[p[1] for w in ("older","unseen") for p in P["2025"]["R"].get((ck,w),[]) if cheap(M["2025"][p[0]])]
    a26=[p[1] for w in ("older","unseen") for p in P["2026"]["R"].get((ck,w),[]) if cheap(M["2026"][p[0]])]
    if not a25 or not a26: continue
    a25=np.concatenate(a25);a26=np.concatenate(a26)
    if len(a25)<300 or len(a26)<300: continue
    sc[ck]=(cl(a25),cl(a26))
rank=sorted(sc,key=lambda k:-sc[k][0][2])
print("\nWALK-FORWARD in cheap crypto: chosen on 2025's whole year, judged on 2026's whole year")
print(" combos with 300+ trades each year:",len(sc))
for k in rank[:8]:
    a,b=sc[k]; print("  %-30s 2025 n%6d %+.3f t%.1f | 2026 n%6d %+.3f t%.1f"%(k,a[0],a[1],a[2],b[0],b[1],b[2]))
top3=rank[:3]; 
print(" mean of 2026 result over ALL combos: %+.3f ; over the top 3 chosen on 2025: %+.3f"%(np.mean([sc[k][1][1] for k in sc]),np.mean([sc[k][1][1] for k in top3])))
print(" combos positive in 2025:",sum(1 for k in sc if sc[k][0][1]>0)," of those positive in 2026:",sum(1 for k in sc if sc[k][0][1]>0 and sc[k][1][1]>0))
print(" combos negative in 2025:",sum(1 for k in sc if sc[k][0][1]<=0)," of those positive in 2026:",sum(1 for k in sc if sc[k][0][1]<=0 and sc[k][1][1]>0))
